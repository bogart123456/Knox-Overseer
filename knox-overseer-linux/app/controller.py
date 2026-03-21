from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Optional

from .config import ServerConfig


@dataclass
class ServerState:
    running: bool = False
    pid: Optional[int] = None


class LinuxServerController:
    """Cross-platform server process controller for Project Zomboid dedicated servers."""

    def __init__(self, config: ServerConfig):
        self.config = config
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._log_queue: "Queue[str]" = Queue()
        self._stop_reader = threading.Event()

    @property
    def state(self) -> ServerState:
        running = self._process is not None and self._process.poll() is None
        pid = self._process.pid if self._process else None
        return ServerState(running=running, pid=pid)

    def build_command(self) -> list[str]:
        command = self.config.start_command.strip()
        if not command:
            raise ValueError("Start command cannot be empty")
        return shlex.split(command, posix=(sys.platform != "win32"))

    def start(self) -> None:
        if self.state.running:
            raise RuntimeError("Server is already running")

        server_dir = self.config.normalized_server_dir()
        if not os.path.isdir(server_dir):
            raise FileNotFoundError(f"Server directory not found: {server_dir}")

        command = self.build_command()
        self._stop_reader.clear()
        popen_kwargs = {
            "cwd": server_dir,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.PIPE,
            "text": True,
            "bufsize": 1,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["preexec_fn"] = os.setsid

        self._process = subprocess.Popen(
            command,
            **popen_kwargs,
        )

        self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self._reader_thread.start()
        self._log_queue.put(f"[info] started pid={self._process.pid}")

    def _read_output(self) -> None:
        if not self._process or not self._process.stdout:
            return

        for line in iter(self._process.stdout.readline, ""):
            if self._stop_reader.is_set():
                break
            stripped = line.rstrip()
            if stripped:
                self._log_queue.put(stripped)

        code = self._process.poll() if self._process else None
        if code is not None:
            self._log_queue.put(f"[info] process exited with code {code}")

    def poll_log_line(self, timeout: float = 0.05) -> Optional[str]:
        try:
            return self._log_queue.get(timeout=timeout)
        except Empty:
            return None

    def send_console_command(self, command: str) -> None:
        text = (command or "").strip()
        if not text:
            return

        fifo_path = self.config.normalized_fifo()
        if fifo_path and os.path.exists(fifo_path):
            with open(fifo_path, "w", encoding="utf-8") as fifo:
                fifo.write(text + "\n")
        elif self._process and self._process.stdin:
            self._process.stdin.write(text + "\n")
            self._process.stdin.flush()
        else:
            if fifo_path:
                raise FileNotFoundError(f"Control FIFO not found: {fifo_path}")
            raise RuntimeError("No control FIFO configured and no process stdin available")
        self._log_queue.put(f"[cmd] {text}")

    def stop_graceful(self, wait_seconds: int = 20) -> None:
        if not self.state.running:
            return

        # Safe stop sequence per wiki guidance: save then quit through FIFO.
        try:
            self.send_console_command("save")
            time.sleep(2)
            self.send_console_command("quit")
        except Exception as exc:
            self._log_queue.put(f"[warn] graceful stop unavailable: {exc}")
            self.stop_force()
            return

        started = time.time()
        while self.state.running and (time.time() - started) < wait_seconds:
            time.sleep(0.25)

        if self.state.running:
            self._log_queue.put("[warn] graceful stop timed out; forcing stop")
            self.stop_force()

    def stop_force(self) -> None:
        if not self.state.running:
            return

        assert self._process is not None
        if sys.platform == "win32":
            try:
                self._process.send_signal(signal.CTRL_BREAK_EVENT)
            except Exception as exc:
                self._log_queue.put(f"[warn] CTRL_BREAK failed: {exc}")
                try:
                    self._process.terminate()
                except Exception as term_exc:
                    self._log_queue.put(f"[warn] terminate failed: {term_exc}")
        else:
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception as exc:
                self._log_queue.put(f"[warn] SIGTERM failed: {exc}")

        started = time.time()
        while self.state.running and (time.time() - started) < 8:
            time.sleep(0.2)

        if self.state.running:
            if sys.platform == "win32":
                try:
                    self._process.kill()
                except Exception as exc:
                    self._log_queue.put(f"[error] kill failed: {exc}")
            else:
                try:
                    os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
                except Exception as exc:
                    self._log_queue.put(f"[error] SIGKILL failed: {exc}")

        self._stop_reader.set()
        self._process = None
