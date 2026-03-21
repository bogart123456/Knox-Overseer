from __future__ import annotations

from dataclasses import dataclass
import os
import platform


@dataclass
class ServerConfig:
    server_dir: str = "/opt/pzserver"
    start_command: str = "bash start-server.sh -servername servertest"
    control_fifo: str = "/opt/pzserver/zomboid.control"

    def normalized_server_dir(self) -> str:
        return os.path.abspath(os.path.expanduser(self.server_dir.strip()))

    def normalized_fifo(self) -> str:
        fifo = self.control_fifo.strip()
        if not fifo:
            return ""
        return os.path.abspath(os.path.expanduser(fifo))


def default_config_for_platform(system_name: str | None = None) -> ServerConfig:
    system = (system_name or platform.system()).lower()
    if system == "windows":
        return ServerConfig(
            server_dir=r"C:\Program Files (x86)\Steam\steamapps\common\Project Zomboid Dedicated Server",
            start_command="StartServer64.bat",
            control_fifo="",
        )
    return ServerConfig(
        server_dir="/opt/pzserver",
        start_command="bash start-server.sh -servername servertest",
        control_fifo="/opt/pzserver/zomboid.control",
    )
