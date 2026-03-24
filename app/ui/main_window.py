from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QTabWidget, QMessageBox, QApplication, QProgressBar
)
from PySide6.QtCore import Qt, QTimer, Signal, QSettings, QLockFile
import subprocess
import os
import sys
import ctypes
import shutil
import threading
import shlex
import socket
import struct
import tempfile
import time
import traceback
import zipfile
import configparser
import urllib.parse
import requests
from datetime import datetime, timedelta
from .stats_tab import StatsTab
from .mods_tab import ModsTab
from .console_tab import ConsoleTab
from .settings_tab import SettingsTab
from .backup_tab import BackupTab
from .discord_tab import DiscordTab
from .ini_tab import IniTab
from .sandbox_tab import SandboxVarsTab
from .settings_store import get_app_settings

class MainWindow(QMainWindow):
    output_signal = Signal(str)
    rcon_response = Signal(str, str)
    mod_updates_detected = Signal(object)
    backup_status_signal = Signal(str)
    discord_send_status_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self._ui_settings = get_app_settings()
        self.server_process = None
        self._server_started_at = None
        self._session_started_at = None
        self._last_restart_at = None
        self._current_log_path = None
        self._restart_schedule = None
        self._sent_restart_alerts = set()
        self._scheduled_restart_triggered = False
        self._pending_restart = False
        self._restart_requested = False
        self._last_auto_restart_enabled = None
        self._mod_baseline = {}
        self._mod_update_pending_restart_at = None
        self._mod_check_in_progress = False
        self._connected_players = 0
        self._server_starting = False
        self._server_stopping = False
        self._startup_timed_out = False
        self._server_ready = False
        self._stop_requested_by_user = False
        self._crash_recovery_pending = False
        self._crash_recovery_remaining = 0
        self._crash_recovery_timer = QTimer(self)
        self._crash_recovery_timer.setInterval(1000)
        self._crash_recovery_timer.timeout.connect(self._tick_crash_recovery_countdown)
        self._crash_handled_for_current_process = False
        self._backup_worker_running = False
        self._discord_repeat_sending = False
        self._server_lock = None
        self._server_lock_mutex = None
        self._startup_tasks = []
        self._startup_total_steps = 0
        self._startup_completed_steps = 0
        self._startup_preloading = False
        self._active_ini_path = ""
        self._loaded_for_ini = {
            "mods": None,
            "logs": None,
            "ini": None,
            "sandbox": None,
        }
        self._kernel32 = self._init_kernel32_api()
        self.output_signal.connect(self.append_to_terminal)
        self.setWindowTitle("Knox Overseer")
        self.setGeometry(100, 100, 1200, 800)
        self.setup_ui()
        self.connect_signals()
        self._restore_ui_state()

    def setup_ui(self):
        central_widget = QWidget()
        self._central_widget = central_widget
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)

        # Server info grid
        server_info_layout = QGridLayout()
        self.label_server_name = QLabel("Server: -")
        self.label_uptime = QLabel("Uptime: -")
        self.label_status = QLabel("Status: Stopped")
        self.label_last_restart = QLabel("Last Restart: -")
        server_info_layout.addWidget(self.label_server_name, 0, 0)
        server_info_layout.addWidget(self.label_uptime, 0, 1)
        server_info_layout.addWidget(self.label_status, 1, 0)
        server_info_layout.addWidget(self.label_last_restart, 1, 1)
        main_layout.addLayout(server_info_layout)

        # Server control buttons
        control_layout = QHBoxLayout()
        self.button_start = QPushButton("Start")
        self.button_stop = QPushButton("Stop")
        self.button_restart = QPushButton("Restart")
        control_layout.addWidget(self.button_start)
        control_layout.addWidget(self.button_stop)
        control_layout.addWidget(self.button_restart)
        main_layout.addLayout(control_layout)

        # Main tab widget
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # Create tabs
        self.settings_tab = SettingsTab()
        self.stats_tab = StatsTab()
        self.mods_tab = ModsTab(self.settings_tab)
        self.console_tab = ConsoleTab()
        self.backup_tab = BackupTab()
        self.discord_tab = DiscordTab()
        self.ini_tab = IniTab()
        self.sandbox_tab = SandboxVarsTab()

        # Connect signals
        self.settings_tab.ini_selected.connect(self._on_ini_selected)

        # Add tabs
        self.tab_widget.addTab(self.console_tab, "Console")
        self.tab_widget.addTab(self.stats_tab, "Stats")
        self.tab_widget.addTab(self.mods_tab, "Mods")
        self.tab_widget.addTab(self.ini_tab, "INI")
        self.tab_widget.addTab(self.sandbox_tab, "Sandbox")
        self.tab_widget.addTab(self.backup_tab, "Backup")
        self.tab_widget.addTab(self.discord_tab, "Discord")
        self.tab_widget.addTab(self.settings_tab, "Settings")

        self._setup_loading_overlay()

        # Keep launch responsive by deferring heavier I/O and parsing tasks.
        self._schedule_startup_loads()

    def _setup_loading_overlay(self):
        self._loading_overlay = QWidget(self._central_widget)
        self._loading_overlay.setStyleSheet("background-color: rgba(10, 10, 10, 195);")

        layout = QVBoxLayout(self._loading_overlay)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addStretch(1)

        self._loading_title = QLabel("Preparing Knox Overseer")
        self._loading_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #f0f0f0;")
        self._loading_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._loading_title)

        self._loading_message = QLabel("Loading modules and pages...")
        self._loading_message.setStyleSheet("font-size: 11px; color: #d3d3d3;")
        self._loading_message.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._loading_message)

        self._loading_progress = QProgressBar()
        self._loading_progress.setRange(0, 100)
        self._loading_progress.setValue(0)
        self._loading_progress.setFixedWidth(320)
        self._loading_progress.setTextVisible(True)

        progress_row = QHBoxLayout()
        progress_row.addStretch(1)
        progress_row.addWidget(self._loading_progress)
        progress_row.addStretch(1)
        layout.addLayout(progress_row)
        layout.addStretch(2)

        self._loading_overlay.hide()

    def _show_loading_overlay(self, message: str):
        self._loading_message.setText(message)
        self._loading_overlay.setGeometry(self._central_widget.rect())
        self._loading_overlay.show()
        self._loading_overlay.raise_()

    def _hide_loading_overlay(self):
        self._loading_overlay.hide()

    def connect_signals(self):
        self.button_start.clicked.connect(self.start_server)
        self.button_stop.clicked.connect(lambda: self.stop_server(intentional=True))
        self.button_restart.clicked.connect(self.restart_server)

        # Update status
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(1000)

        # Refresh logs periodically so newly created startup logs appear.
        self.log_refresh_timer = QTimer()
        self.log_refresh_timer.timeout.connect(self.refresh_logs_list)
        self.log_refresh_timer.start(5000)

        # Mod update check cadence: every 5 minutes when enabled.
        self.mod_refresh_timer = QTimer()
        self.mod_refresh_timer.timeout.connect(self.check_mod_updates)
        self.mod_refresh_timer.start(self.settings_tab.get_mod_detection_interval_ms())

        # Allow live update of detection cadence from settings.
        self.settings_tab.mod_detection_rate.currentTextChanged.connect(self.update_mod_detection_interval)

        self.console_tab.input_sent.connect(self.send_to_server)
        self.console_tab.rcon_command.connect(self.send_rcon_command)
        self.console_tab.log_selected.connect(self.load_log_content)
        self.rcon_response.connect(self._on_rcon_response)
        self.mod_updates_detected.connect(self._on_mod_updates_detected)
        self.backup_status_signal.connect(self.backup_tab.set_status)
        self.backup_tab.restore_requested.connect(self._request_restore_backup)
        self.backup_tab.backup_settings_changed.connect(self._apply_builtin_backup_settings)
        self.discord_tab.send_webhook_requested.connect(self._send_discord_webhook)
        self.discord_tab.repeat_settings_changed.connect(self._update_discord_repeat_timer)
        self.discord_send_status_signal.connect(self.discord_tab.set_send_status)
        self.mods_tab.refresh_requested.connect(self._refresh_mods_with_overlay)
        self.settings_tab.sandbox_edit_requested.connect(self._open_sandbox_editor)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        self.discord_repeat_timer = QTimer()
        self.discord_repeat_timer.timeout.connect(self._handle_discord_repeat_push)
        self._update_rcon_state()
        self._update_control_buttons()
        self._update_mod_actions_state()
        self._update_runtime_lock_states()
        self._refresh_discord_preview()
        self._update_discord_repeat_timer()

    def _set_startup_notice(self, text: str):
        self._show_loading_overlay(text)

    def _set_startup_progress(self, completed: int, total: int):
        total = max(1, total)
        self._loading_progress.setRange(0, total)
        self._loading_progress.setValue(max(0, min(completed, total)))
        self._loading_progress.setFormat(f"Step {completed}/{total}")

    def _schedule_startup_loads(self):
        ini_path = self.settings_tab.ini_path.text().strip()
        # Make launch near-instant, then preload heavy pages immediately after show.
        self._on_ini_selected(ini_path, load_visible_tab=False)
        self._startup_tasks = [
            ("Preparing: loading mods...", self._load_mods_if_needed),
            ("Preparing: scanning logs...", self._load_logs_if_needed),
            ("Preparing: loading INI page...", self._load_ini_page_if_needed),
            ("Preparing: loading Sandbox page...", self._load_sandbox_page_if_needed),
            ("Preparing: syncing backup settings...", self._apply_builtin_backup_settings),
        ]
        self._startup_total_steps = len(self._startup_tasks)
        self._startup_completed_steps = 0
        QTimer.singleShot(0, self._start_startup_preload)

    def _start_startup_preload(self):
        if not self._startup_tasks:
            return
        self._startup_preloading = True
        self._set_startup_progress(0, self._startup_total_steps)
        self._set_startup_notice("Preparing modules and pages...")
        QTimer.singleShot(0, self._run_next_startup_task)

    def _run_next_startup_task(self):
        if not self._startup_tasks:
            self._set_startup_progress(self._startup_total_steps, self._startup_total_steps)
            self._loading_progress.setFormat("Ready")
            self._startup_preloading = False
            self._hide_loading_overlay()
            return

        message, task = self._startup_tasks.pop(0)
        self._startup_completed_steps += 1
        self._set_startup_progress(self._startup_completed_steps, self._startup_total_steps)
        self._set_startup_notice(message)
        QApplication.processEvents()
        try:
            task()
        except Exception as exc:
            self.output_signal.emit(
                f"[Startup] Deferred task failed during '{message}': {type(exc).__name__}: {exc!r}"
            )
            self.output_signal.emit(traceback.format_exc().rstrip())
        QTimer.singleShot(0, self._run_next_startup_task)

    def _on_ini_selected(self, ini_path, load_visible_tab=True):
        ini_path = os.path.normpath((ini_path or "").strip()) if ini_path else ""
        previous_ini_path = self._active_ini_path
        self._active_ini_path = ini_path
        ini_changed = ini_path != previous_ini_path

        # Lightweight updates happen immediately.
        self._update_server_name_label(ini_path)
        self.stats_tab.set_ini_path(ini_path)
        self.backup_tab.set_ini_path(ini_path)

        # Invalidate heavy tab data only when INI actually changed.
        if ini_changed:
            self._loaded_for_ini["mods"] = None
            self._loaded_for_ini["logs"] = None
            self._loaded_for_ini["ini"] = None
            self._loaded_for_ini["sandbox"] = None

        # If the currently visible tab depends on INI, load it now.
        if load_visible_tab:
            current = self.tab_widget.currentWidget()
            if current is self.mods_tab:
                self._load_mods_if_needed()
            elif current is self.console_tab:
                self._load_logs_if_needed()
            elif current is self.ini_tab:
                self._load_ini_page_if_needed()
            elif current is self.sandbox_tab:
                self._load_sandbox_page_if_needed()

    def _refresh_mods_with_overlay(self):
        if self.mods_tab.mods_table.rowCount() == 0:
            self._load_mods_if_needed()
            return

        self._show_loading_overlay("Loading mods...")
        self._loading_progress.setRange(0, 0)
        QApplication.processEvents()
        try:
            self.mods_tab.refresh_mods()
        finally:
            self._loading_progress.setRange(0, 100)
            self._loading_progress.setValue(0)
            self._loading_progress.setFormat("%p%")
            self._hide_loading_overlay()

    def _load_mods_if_needed(self):
        if not self._active_ini_path:
            return
        if self._loaded_for_ini["mods"] == self._active_ini_path:
            return
        self.mods_tab.load_mods(self._active_ini_path)
        self._loaded_for_ini["mods"] = self._active_ini_path

    def _load_logs_if_needed(self):
        if not self._active_ini_path:
            return
        if self._loaded_for_ini["logs"] == self._active_ini_path:
            return
        self.refresh_logs_list(self._active_ini_path)
        self._loaded_for_ini["logs"] = self._active_ini_path

    def _load_ini_page_if_needed(self):
        if not self._active_ini_path:
            return
        if self._loaded_for_ini["ini"] == self._active_ini_path:
            return
        self.ini_tab.set_path(self._active_ini_path)
        self._loaded_for_ini["ini"] = self._active_ini_path

    def _load_sandbox_page_if_needed(self):
        if not self._active_ini_path:
            return
        if self._loaded_for_ini["sandbox"] == self._active_ini_path:
            return
        sandbox_path = self.settings_tab.get_sandbox_vars_path(self._active_ini_path)
        self.sandbox_tab.set_path(sandbox_path)
        self._loaded_for_ini["sandbox"] = self._active_ini_path

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_loading_overlay") and self._loading_overlay.isVisible():
            self._loading_overlay.setGeometry(self._central_widget.rect())

    def _set_backup_status(self, text):
        self.backup_status_signal.emit(text)

    def _init_kernel32_api(self):
        if sys.platform != "win32":
            return None

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool
        return kernel32

    def _acquire_server_lock(self):
        if self._server_lock is not None:
            return True

        if self._kernel32 is not None:
            mutex_handle = self._kernel32.CreateMutexW(None, False, "Local\\KnoxOverseerServerMutex")
            if not mutex_handle:
                return False
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                self._kernel32.CloseHandle(mutex_handle)
                return False
            self._server_lock_mutex = mutex_handle

        lock_path = os.path.join(tempfile.gettempdir(), "knox_overseer_server.lock")
        lock = QLockFile(lock_path)
        lock.setStaleLockTime(0)
        if not lock.tryLock(100):
            if self._server_lock_mutex is not None:
                self._kernel32.CloseHandle(self._server_lock_mutex)
                self._server_lock_mutex = None
            return False
        self._server_lock = lock
        return True

    def _release_server_lock(self):
        if self._server_lock is None:
            if self._server_lock_mutex is not None:
                self._kernel32.CloseHandle(self._server_lock_mutex)
                self._server_lock_mutex = None
            return
        self._server_lock.unlock()
        self._server_lock = None
        if self._server_lock_mutex is not None:
            self._kernel32.CloseHandle(self._server_lock_mutex)
            self._server_lock_mutex = None

    def _apply_builtin_backup_settings(self):
        ini_path = self.settings_tab.ini_path.text().strip()
        if not ini_path:
            self._set_backup_status("Select an INI file to apply built-in backup settings.")
            return
        if not os.path.isfile(ini_path):
            self._set_backup_status("INI file was not found; backup settings were not applied.")
            return

        period_minutes = self.backup_tab.get_backup_period_minutes()
        max_backups = self.backup_tab.get_max_backups()
        backup_on_start = "true" if self.backup_tab.is_backup_on_start_enabled() else "false"
        backup_on_version_change = "true" if self.backup_tab.is_backup_on_version_change_enabled() else "false"

        try:
            with open(ini_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()

            lines = self._upsert_ini_line(lines, "BackupsPeriod", str(period_minutes))
            lines = self._upsert_ini_line(lines, "BackupsCount", str(max_backups))
            lines = self._upsert_ini_line(lines, "BackupsOnStart", backup_on_start)
            lines = self._upsert_ini_line(lines, "BackupsOnVersionChange", backup_on_version_change)

            with open(ini_path, "w", encoding="utf-8", errors="replace") as f:
                f.write("\n".join(lines) + "\n")

            backup_dir = os.path.join(os.path.expanduser("~"), "Zomboid", "backups")
            self._set_backup_status(
                f"Built-in backups configured (Count={max_backups}, OnStart={backup_on_start}, OnVersionChange={backup_on_version_change}, Period={period_minutes} min). Output path: {backup_dir}"
            )
        except Exception as exc:
            self._set_backup_status("Failed to apply built-in backup settings. Check console for details.")
            self.output_signal.emit(f"[Backup] Failed applying built-in backup settings: {exc}")

    def _upsert_ini_line(self, lines, key, value):
        key_lower = key.lower()
        updated = False
        out = []
        for raw in lines:
            stripped = raw.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith(";") and "=" in stripped:
                left, _ = stripped.split("=", 1)
                if left.strip().lower() == key_lower:
                    out.append(f"{key}={value}")
                    updated = True
                    continue
            out.append(raw)

        if not updated:
            out.append(f"{key}={value}")
        return out

    def _get_zomboid_root_dir(self):
        ini_path = self.settings_tab.ini_path.text().strip()
        if not ini_path:
            return ""
        server_dir = os.path.dirname(ini_path)
        return os.path.dirname(server_dir)

    def _safe_extract_zip(self, zip_path, extract_dir):
        with zipfile.ZipFile(zip_path, "r") as archive:
            for info in archive.infolist():
                normalized_name = info.filename.replace("\\", "/")
                if normalized_name.startswith("/") or ".." in normalized_name.split("/"):
                    raise ValueError(f"Unsafe path in archive: {info.filename}")

                destination = os.path.abspath(os.path.join(extract_dir, info.filename))
                if not destination.startswith(os.path.abspath(extract_dir)):
                    raise ValueError(f"Blocked path traversal: {info.filename}")

            archive.extractall(extract_dir)

    def _request_restore_backup(self, zip_path):
        if self._is_server_active() or self._server_starting:
            QMessageBox.warning(self, "Restore Blocked", "Stop the server before restoring a backup.")
            return
        if self._backup_worker_running:
            QMessageBox.warning(self, "Restore Blocked", "A backup or restore operation is already in progress.")
            return
        if not os.path.isfile(zip_path):
            QMessageBox.warning(self, "Restore Failed", "Selected backup ZIP file does not exist.")
            self._set_backup_status("Restore failed: ZIP file does not exist.")
            return
        if not zipfile.is_zipfile(zip_path):
            QMessageBox.warning(self, "Restore Failed", "Selected file is not a valid ZIP archive.")
            self._set_backup_status("Restore failed: invalid ZIP archive.")
            return

        result = QMessageBox.question(
            self,
            "Confirm Restore",
            "Restore will apply backup contents into your Zomboid data folder. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result != QMessageBox.Yes:
            return

        self._backup_worker_running = True
        self._set_backup_status("Restore in progress...")
        threading.Thread(target=self._run_restore_worker, args=(zip_path,), daemon=True).start()

    def _resolve_restore_payload_root(self, extract_dir):
        entries = [name for name in os.listdir(extract_dir) if name not in (".", "..")]
        if len(entries) == 1:
            single_dir = os.path.join(extract_dir, entries[0])
            if os.path.isdir(single_dir):
                return single_dir
        return extract_dir

    def _copy_tree_merge(self, src_dir, dst_dir):
        os.makedirs(dst_dir, exist_ok=True)
        for name in os.listdir(src_dir):
            src_path = os.path.join(src_dir, name)
            dst_path = os.path.join(dst_dir, name)
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
            else:
                shutil.copy2(src_path, dst_path)

    def _looks_like_zomboid_root_payload(self, payload_root):
        # Common root-level folders inside Zomboid backups.
        markers = {"saves", "server", "db", "lua", "mods", "logs"}
        try:
            entries = {name.lower() for name in os.listdir(payload_root)}
        except Exception:
            return False
        return len(markers.intersection(entries)) > 0

    def _run_restore_worker(self, zip_path):
        temp_dir = tempfile.mkdtemp(prefix="pz_restore_")
        try:
            zomboid_root = self._get_zomboid_root_dir()
            if not zomboid_root:
                self.output_signal.emit("[BackupRestore] Restore aborted: could not resolve Zomboid root from INI path.")
                self._set_backup_status("Restore failed: could not resolve Zomboid root.")
                return

            self._safe_extract_zip(zip_path, temp_dir)
            payload_root = self._resolve_restore_payload_root(temp_dir)
            if not os.path.isdir(payload_root):
                raise ValueError("Could not determine restore payload directory from the selected ZIP.")

            if not self._looks_like_zomboid_root_payload(payload_root):
                raise ValueError("Selected ZIP does not look like a full Zomboid backup payload.")

            self._copy_tree_merge(payload_root, zomboid_root)
            self.output_signal.emit(
                f"[BackupRestore] Restored backup into Zomboid root: {zomboid_root}"
            )

            self.output_signal.emit(f"[BackupRestore] Restore completed from: {zip_path}")
            self._set_backup_status(f"Restore complete: {os.path.basename(zip_path)}")
        except Exception as exc:
            self.output_signal.emit(f"[BackupRestore] Restore failed: {exc}")
            self._set_backup_status("Restore failed. Check console for details.")
        finally:
            self._backup_worker_running = False
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _update_control_buttons(self):
        is_active = self._is_server_active()
        is_start_blocked = is_active or self._server_starting or self._crash_recovery_pending
        self.button_start.setEnabled(not is_start_blocked)
        self.button_stop.setEnabled((is_active and not self._server_starting and not self._server_stopping) or self._crash_recovery_pending)
        self.button_restart.setEnabled(is_active and not self._server_starting and not self._server_stopping)

    def _update_mod_actions_state(self):
        # Prevent mod list edits while the server process is running.
        self.mods_tab.set_mod_actions_enabled(not self._is_server_active())

    def _update_runtime_lock_states(self):
        is_active = self._is_server_active()
        self.settings_tab.set_runtime_lock(is_active)
        self.backup_tab.set_runtime_lock(is_active)
        self.ini_tab.set_runtime_lock(is_active)
        self.sandbox_tab.set_runtime_lock(is_active)

    def _open_sandbox_editor(self, path: str) -> None:
        """Load the SandboxVars file at *path* and switch to the Sandbox tab."""
        self.sandbox_tab.set_path(path)
        self.tab_widget.setCurrentWidget(self.sandbox_tab)

    def _on_tab_changed(self, index: int) -> None:
        if self._startup_preloading:
            return
        current = self.tab_widget.widget(index)
        if current is self.console_tab:
            self._load_logs_if_needed()
        elif current is self.mods_tab:
            self._load_mods_if_needed()
        elif current is self.ini_tab:
            self._load_ini_page_if_needed()
            self.ini_tab.refresh_if_changed()
        elif current is self.sandbox_tab:
            self._load_sandbox_page_if_needed()
            self.sandbox_tab.refresh_if_changed()

    def _get_logs_dir_from_ini(self, ini_path):
        # INI is typically .../Zomboid/Server/<name>.ini, logs are in .../Zomboid/Logs
        server_dir = os.path.dirname(ini_path)
        zomboid_root = os.path.dirname(server_dir)
        return os.path.join(zomboid_root, "Logs")

    def _update_server_name_label(self, ini_path=None):
        ini_path = (ini_path or self.settings_tab.ini_path.text()).strip()
        if not ini_path:
            self.label_server_name.setText("Server: -")
            return
        server_name = os.path.splitext(os.path.basename(ini_path))[0]
        self.label_server_name.setText(f"Server: {server_name or '-'}")

    def refresh_logs_list(self, ini_path=None):
        ini_path = ini_path or self.settings_tab.ini_path.text().strip()
        selected_item = self.console_tab.log_tree.currentItem()
        selected_path = selected_item.data(0, 256) if selected_item else self._current_log_path

        if not ini_path:
            self.console_tab.set_log_groups([], {})
            self.console_tab.log_content.setPlainText("No INI file selected.")
            return

        logs_dir = self._get_logs_dir_from_ini(ini_path)
        if not os.path.isdir(logs_dir):
            self.console_tab.set_log_groups([], {})
            self.console_tab.log_content.setPlainText(f"Logs directory not found: {logs_dir}")
            return

        current_logs = []
        folder_logs = {}
        for root, _, files in os.walk(logs_dir):
            for name in files:
                if not name.lower().endswith(".txt"):
                    continue
                full_path = os.path.join(root, name)
                try:
                    mtime = os.path.getmtime(full_path)
                except OSError:
                    continue

                rel_path = os.path.relpath(full_path, logs_dir)
                rel_dir = os.path.dirname(rel_path)
                if rel_dir in ('', '.'):
                    current_logs.append((mtime, name, full_path))
                else:
                    folder_name = rel_path.split(os.sep, 1)[0]
                    child_display = rel_path[len(folder_name) + 1:]
                    folder_logs.setdefault(folder_name, []).append((mtime, child_display, full_path))

        current_logs.sort(key=lambda x: x[0], reverse=True)
        current_logs = [(name, full_path) for _, name, full_path in current_logs[:200]]

        grouped = {}
        for folder_name, entries in folder_logs.items():
            entries.sort(key=lambda x: x[0], reverse=True)
            grouped[folder_name] = [(child_display, full_path) for _, child_display, full_path in entries[:200]]

        self.console_tab.set_log_groups(current_logs, grouped)

        # Try to keep the previously selected log visible/selected after refresh.
        restored_item = None
        if selected_path:
            for i in range(self.console_tab.log_tree.topLevelItemCount()):
                top = self.console_tab.log_tree.topLevelItem(i)
                if top is None:
                    continue
                top_path = top.data(0, 256)
                if top_path == selected_path:
                    restored_item = top
                    break
                for j in range(top.childCount()):
                    child = top.child(j)
                    if child.data(0, 256) == selected_path:
                        restored_item = child
                        break
                if restored_item is not None:
                    break

        if current_logs or grouped:
            selected_item = restored_item
            if selected_item is None:
                if current_logs:
                    selected_item = self.console_tab.log_tree.topLevelItem(0)
                else:
                    # No root logs; select first child in first folder.
                    first_parent = self.console_tab.log_tree.topLevelItem(0)
                    if first_parent is not None and first_parent.childCount() > 0:
                        selected_item = first_parent.child(0)

            if selected_item is not None:
                self.console_tab.log_tree.setCurrentItem(selected_item)
                path = selected_item.data(0, 256)
                if path:
                    # Only reload viewer content when selected file changed.
                    if path != self._current_log_path:
                        self.load_log_content(path)
        else:
            self._current_log_path = None
            self.console_tab.log_content.setPlainText("No .txt log files found.")

    def load_log_content(self, log_path):
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                self.console_tab.log_content.setPlainText(f.read())
            self._current_log_path = log_path
        except Exception as e:
            self.console_tab.log_content.setPlainText(f"Failed to load log file:\n{e}")

    def send_to_server(self, text):
        if hasattr(self, 'server_process') and self.server_process and self.server_process.stdin:
            try:
                self.server_process.stdin.write(text + '\n')
                self.server_process.stdin.flush()
            except Exception as e:
                self.output_signal.emit(f"Failed to send input: {e}")

    def send_rcon_command(self, command):
        rcon_port, rcon_password = self._parse_ini_for_rcon(emit_errors=True)
        if not rcon_port or not rcon_password:
            masked = '*' * len(rcon_password) if rcon_password else 'None'
            self.console_tab.rcon_output.append(f"RCONPort or RCONPassword not found in INI. Parsed: Port={rcon_port}, Password={masked}")
            return
        # Run RCON in background thread to avoid blocking GUI
        threading.Thread(target=self._rcon_thread, args=(command, rcon_port, rcon_password), daemon=True).start()

    def _rcon_thread(self, command, rcon_port, rcon_password):
        try:
            response = self.rcon_execute(self.settings_tab.get_rcon_host(), int(rcon_port), rcon_password, command)
            self.rcon_response.emit(command, response)
        except Exception as e:
            self.rcon_response.emit(command, f"Error: {e}")

    def _on_rcon_response(self, command, response):
        self.console_tab.rcon_output.append(f"> {command}\n{response}")

    def _next_restart_datetime(self):
        now = datetime.now()
        t = self.settings_tab.restart_time.time()
        target = now.replace(hour=t.hour(), minute=t.minute(), second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    def _message_for_minutes(self, minutes):
        if minutes == 60:
            return "servermsg Server will restart in 1 hour"
        if minutes == 1:
            return "servermsg Server will restart in 1 minute"
        return f"servermsg Server will restart in {minutes} minutes"

    def _parse_ini_for_rcon(self, emit_errors=False):
        ini_path = self.settings_tab.ini_path.text().strip()
        if not ini_path:
            if emit_errors:
                self.console_tab.rcon_output.append("No INI file selected.")
            return None, None

        config = configparser.ConfigParser(allow_no_value=True)
        try:
            with open(ini_path, 'r', encoding='utf-8', errors='replace') as f:
                config.read_string('[DEFAULT]\n' + f.read())
        except Exception as exc:
            if emit_errors:
                self.console_tab.rcon_output.append(f"Error reading INI: {exc}")
            return None, None

        return config.get('DEFAULT', 'RCONPort', fallback=None), config.get('DEFAULT', 'RCONPassword', fallback=None)

    def _get_player_count(self):
        # Prefer RCON players list for reliable count; fall back to tracked joins.
        rcon_port, rcon_password = self._parse_ini_for_rcon()
        if rcon_port and rcon_password:
            try:
                response = self.rcon_execute(self.settings_tab.get_rcon_host(), int(rcon_port), rcon_password, 'players')
                lines = [line.strip() for line in response.splitlines() if line.strip()]
                # PZ players command commonly returns entries containing " - " for each player row.
                count = sum(1 for line in lines if ' - ' in line)
                return count
            except Exception:
                pass
        return max(0, self._connected_players)

    def _collect_workshop_rows(self):
        rows = []
        seen = set()
        table = self.mods_tab.mods_table
        for row in range(table.rowCount()):
            wid_item = table.item(row, 2)
            name_item = table.item(row, 0)
            if wid_item is None:
                continue
            wid = wid_item.text().strip()
            if not wid or wid in seen:
                continue
            seen.add(wid)
            name = name_item.text().strip() if name_item else wid
            rows.append((wid, name))
        return rows

    def _fetch_mod_versions(self, workshop_rows):
        versions = {}
        names = {}
        details_by_wid = {}
        for wid, name in workshop_rows:
            details = self.mods_tab.fetch_mod_details(wid)
            if details:
                versions[wid] = int(details.get('time_updated', 0))
                names[wid] = details.get('title', name) or name
                details_by_wid[wid] = details
            else:
                versions[wid] = 0
                names[wid] = name
        return versions, names, details_by_wid

    def _on_mod_updates_detected(self, payload):
        changed_wids = payload.get('changed_wids', [])
        details_by_wid = payload.get('details_by_wid', {})
        self.mods_tab.mark_updated_workshop_ids(changed_wids, details_by_wid)
        if changed_wids:
            self._show_loading_overlay("Loading mods...")
            self._loading_progress.setRange(0, 0)
            QApplication.processEvents()
            try:
                self.mods_tab.refresh_mods(workshop_ids=set(changed_wids))
            finally:
                self._loading_progress.setRange(0, 100)
                self._loading_progress.setValue(0)
                self._loading_progress.setFormat("%p%")
                self._hide_loading_overlay()

    def _run_mod_check(self):
        try:
            workshop_rows = self._collect_workshop_rows()
            if not workshop_rows:
                return

            current_versions, current_names, details_by_wid = self._fetch_mod_versions(workshop_rows)

            # First snapshot after server start becomes baseline.
            if not self._mod_baseline:
                self._mod_baseline = dict(current_versions)
                self.output_signal.emit("[ModUpdate] Baseline captured.")
                return

            changed_wids = []
            for wid, new_time in current_versions.items():
                old_time = self._mod_baseline.get(wid, 0)
                if new_time > old_time:
                    changed_wids.append(wid)

            if not changed_wids:
                return

            # Update Mods table on the UI thread so changed entries are visible immediately.
            self.mod_updates_detected.emit({
                'changed_wids': changed_wids,
                'details_by_wid': {wid: details_by_wid.get(wid) for wid in changed_wids}
            })

            player_count = self._get_player_count()
            if player_count <= 0:
                self.output_signal.emit("[ModUpdate] Mod update detected and no players are online. Restarting immediately.")
                self._mod_baseline = dict(current_versions)
                self._request_restart("ModUpdate")
                return

            minutes = self.settings_tab.get_mod_update_alert_minutes()
            self._mod_update_pending_restart_at = datetime.now() + timedelta(minutes=minutes)
            for wid in changed_wids:
                mod_name = current_names.get(wid, wid).replace('"', "'")
                msg = f'servermsg The Mod "{mod_name}" requires an update, Server will restart in {minutes} minutes'
                self._send_server_message(msg)

            self._mod_baseline = dict(current_versions)
        finally:
            self._mod_check_in_progress = False

    def check_mod_updates(self):
        if not self._is_server_active():
            return
        if not self.settings_tab.auto_mod_check.isChecked():
            return
        if self._mod_check_in_progress:
            return
        self._mod_check_in_progress = True
        threading.Thread(target=self._run_mod_check, daemon=True).start()

    def _process_mod_pending_restart(self):
        if self._mod_update_pending_restart_at is None:
            return
        if not self._is_server_active():
            # Do not fire mod-update restarts while server is stopped.
            self._mod_update_pending_restart_at = None
            return
        if datetime.now() < self._mod_update_pending_restart_at:
            return
        self._mod_update_pending_restart_at = None
        self.output_signal.emit("[ModUpdate] Scheduled mod-update restart time reached.")
        self._request_restart("ModUpdate")

    def update_mod_detection_interval(self):
        interval = self.settings_tab.get_mod_detection_interval_ms()
        self.mod_refresh_timer.setInterval(interval)
        self.output_signal.emit(f"[ModUpdate] Detection interval set to {interval // 1000} seconds.")

    def _send_server_message(self, message):
        # Use stdin console command path so messages work even if RCON is unavailable.
        self.send_to_server(message)
        self.output_signal.emit(f"[AutoRestart] {message}")

    def _is_restart_in_progress(self):
        return self._pending_restart or self._restart_requested

    def _request_restart(self, source):
        if self._is_restart_in_progress():
            self.output_signal.emit(f"[{source}] Restart request ignored; another restart is already in progress.")
            return False

        self._restart_requested = True
        self._pending_restart = True
        self.output_signal.emit(f"[{source}] Restart requested. Waiting for full stop before starting again.")
        self.stop_server(intentional=False)
        return True

    def _handle_crash_recovery(self):
        if self.server_process is None:
            return
        if self._is_server_active():
            return
        if self._crash_handled_for_current_process:
            return

        self._crash_handled_for_current_process = True
        exit_code = self.server_process.poll()

        # Clean process exit should never be treated as a crash.
        if exit_code == 0:
            return

        if self._is_restart_in_progress():
            return
        if self._stop_requested_by_user:
            return
        if not self.settings_tab.is_crash_restart_enabled():
            self.output_signal.emit(f"[CrashRecovery] Server exited unexpectedly (code {exit_code}). Crash auto-restart is disabled.")
            return

        if self._crash_recovery_pending:
            return

        delay_sec = self.settings_tab.get_crash_restart_delay_seconds()
        self._crash_recovery_pending = True
        self._crash_recovery_remaining = max(0, int(delay_sec))
        self.output_signal.emit(f"[CrashRecovery] Server crashed (code {exit_code}). Restarting in {delay_sec}s.")
        self._update_control_buttons()
        self._crash_recovery_timer.start()

    def _tick_crash_recovery_countdown(self):
        if not self._crash_recovery_pending:
            self._crash_recovery_timer.stop()
            return

        if self._stop_requested_by_user:
            self._crash_recovery_pending = False
            self._crash_recovery_remaining = 0
            self._crash_recovery_timer.stop()
            self.output_signal.emit("[CrashRecovery] Auto-restart cancelled by user.")
            self._update_control_buttons()
            return

        self._crash_recovery_remaining -= 1
        if self._crash_recovery_remaining <= 0:
            self._crash_recovery_timer.stop()
            self._execute_crash_recovery()
            return

        if self._crash_recovery_remaining <= 5:
            self.output_signal.emit(f"[CrashRecovery] Restarting in {self._crash_recovery_remaining}s. Press Stop to cancel.")

    def _execute_crash_recovery(self):
        self._crash_recovery_pending = False
        self._crash_recovery_remaining = 0
        if self._is_server_active():
            return
        if self._is_restart_in_progress():
            return
        if self._stop_requested_by_user:
            return
        self._request_restart("CrashRecovery")

    def _handle_auto_restart(self):
        # Handle pending restart regardless of whether auto-restart is enabled.
        if self._pending_restart and not self._is_server_active():
            self.output_signal.emit("[Restart] Server fully stopped. Starting again now.")
            self._pending_restart = False
            self._restart_requested = False
            self.start_server()
            return

        enabled = self.settings_tab.auto_restart_check.isChecked()

        # Auto-restart schedule should not run while server is stopped.
        if not self._is_server_active():
            if self._restart_schedule is not None or self._sent_restart_alerts:
                self._restart_schedule = None
                self._sent_restart_alerts.clear()
                self._scheduled_restart_triggered = False
            return

        # Edge handling when toggled off.
        if not enabled:
            if self._last_auto_restart_enabled:
                self._restart_schedule = None
                self._sent_restart_alerts.clear()
                self._scheduled_restart_triggered = False
            self._last_auto_restart_enabled = False
            return

        self._last_auto_restart_enabled = True

        # (Re)initialize schedule if needed.
        if self._restart_schedule is None:
            self._restart_schedule = self._next_restart_datetime()
            self._sent_restart_alerts.clear()
            self._scheduled_restart_triggered = False

        now = datetime.now()
        remaining = (self._restart_schedule - now).total_seconds()
        alert_start = self.settings_tab.get_alert_start_minutes()

        # Minute alerts based on selected start threshold.
        for minute in [60, 30, 15, 10, 5, 1]:
            if minute > alert_start:
                continue
            if remaining <= minute * 60 and minute not in self._sent_restart_alerts:
                self._send_server_message(self._message_for_minutes(minute))
                self._sent_restart_alerts.add(minute)

        # Always end with a 10-second countdown.
        for sec in range(10, 0, -1):
            key = f"sec-{sec}"
            if remaining <= sec and key not in self._sent_restart_alerts:
                self._send_server_message(f"servermsg Server will restart in {sec} seconds")
                self._sent_restart_alerts.add(key)

        # Trigger scheduled restart exactly at or after schedule boundary.
        if remaining <= 0 and not self._scheduled_restart_triggered:
            self._scheduled_restart_triggered = True
            self.output_signal.emit("[AutoRestart] Scheduled restart time reached.")
            self._request_restart("AutoRestart")

            # Prepare next day's schedule.
            self._restart_schedule = self._next_restart_datetime()
            self._sent_restart_alerts.clear()
            self._scheduled_restart_triggered = False

    def _is_server_active(self):
        return self.server_process is not None and self.server_process.poll() is None

    def _update_rcon_state(self):
        self.console_tab.set_rcon_enabled(self._is_server_active())

    def _restore_ui_state(self):
        geometry = self._ui_settings.value("ui/geometry")
        window_state = self._ui_settings.value("ui/windowState")
        tab_index = self._ui_settings.value("ui/selectedTab", 0, type=int)

        if geometry is not None:
            self.restoreGeometry(geometry)
        if window_state is not None:
            self.restoreState(window_state)

        if 0 <= tab_index < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(tab_index)

    def _save_ui_state(self):
        self._ui_settings.setValue("ui/geometry", self.saveGeometry())
        self._ui_settings.setValue("ui/windowState", self.saveState())
        self._ui_settings.setValue("ui/selectedTab", self.tab_widget.currentIndex())

    def _mark_server_ready(self, source="unknown"):
        if self._server_ready:
            return
        self._startup_timed_out = False
        self._server_ready = True
        self._server_starting = False
        self._server_started_at = datetime.now()
        self._last_restart_at = self._server_started_at
        self.label_last_restart.setText(f"Last Restart: {self._last_restart_at.strftime('%Y-%m-%d %H:%M:%S')}")
        self.output_signal.emit(f"Server reported ready ({source}).")

    def _wait_for_server_ready(self):
        # Prefer RCON auth/command success as definitive readiness signal.
        attempts = 0
        while self._is_server_active() and self._server_starting and not self._server_ready:
            attempts += 1
            rcon_port, rcon_password = self._parse_ini_for_rcon()
            if rcon_port and rcon_password:
                try:
                    self.rcon_execute(self.settings_tab.get_rcon_host(), int(rcon_port), rcon_password, 'players')
                    self._mark_server_ready("RCON")
                    return
                except Exception:
                    pass

            # Fallback: if no RCON config, avoid being stuck in Starting forever.
            if attempts >= 180:
                self._server_starting = False
                self._server_ready = False
                self._startup_timed_out = True
                self.output_signal.emit("Server startup timed out waiting for readiness. Process may still be running; check logs/RCON settings.")
                return

            time.sleep(1)

    def _recv_exact(self, sock, size):
        data = b''
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise Exception("Socket closed while receiving data")
            data += chunk
        return data

    def _read_rcon_packet(self, sock):
        size = struct.unpack('<i', self._recv_exact(sock, 4))[0]
        payload = self._recv_exact(sock, size)
        packet_id, packet_type = struct.unpack('<ii', payload[:8])
        body = payload[8:-2].decode('utf-8', errors='replace')
        return packet_id, packet_type, body

    def _build_rcon_packet(self, packet_id, packet_type, text):
        body = text.encode('utf-8') + b'\x00\x00'
        inner = struct.pack('<ii', packet_id, packet_type) + body
        return struct.pack('<i', len(inner)) + inner

    def _normalize_path_list_for_server_dir(self, path_list, server_dir):
        """Resolve relative JVM path-list entries against the selected server directory."""
        if not path_list:
            return path_list

        # Respect the separator style already present in the user-provided value.
        if ';' in path_list and ':' not in path_list:
            separator = ';'
        elif ':' in path_list and ';' not in path_list:
            separator = ':'
        else:
            separator = ';' if sys.platform == "win32" else ':'

        resolved = []
        changed = False
        for part in path_list.split(separator):
            token = part.strip()
            if not token:
                continue

            if token == '.':
                resolved.append(server_dir)
                changed = True
                continue

            if os.path.isabs(token):
                resolved.append(os.path.normpath(token))
                continue

            resolved.append(os.path.normpath(os.path.join(server_dir, token)))
            changed = True

        normalized = separator.join(resolved)
        return normalized if changed else path_list

    def _normalize_java_params_for_server_dir(self, parsed_params, server_dir):
        """Normalize selected JVM arguments so native and classpath entries are CWD-safe."""
        normalized = list(parsed_params)
        i = 0
        while i < len(normalized):
            arg = normalized[i]

            if arg.startswith("-Djava.library.path="):
                raw_value = arg.split("=", 1)[1]
                fixed_value = self._normalize_path_list_for_server_dir(raw_value, server_dir)
                normalized[i] = f"-Djava.library.path={fixed_value}"

            elif arg in ("-cp", "-classpath") and i + 1 < len(normalized):
                normalized[i + 1] = self._normalize_path_list_for_server_dir(normalized[i + 1], server_dir)
                i += 1

            elif arg.startswith("-cp="):
                raw_value = arg.split("=", 1)[1]
                fixed_value = self._normalize_path_list_for_server_dir(raw_value, server_dir)
                normalized[i] = f"-cp={fixed_value}"

            elif arg.startswith("-classpath="):
                raw_value = arg.split("=", 1)[1]
                fixed_value = self._normalize_path_list_for_server_dir(raw_value, server_dir)
                normalized[i] = f"-classpath={fixed_value}"

            i += 1

        return normalized

    def _ensure_steam_symlink_on_linux(self):
        """On Linux, auto-create symlink for Steam if source exists and target missing."""
        if sys.platform != "linux":
            return

        home = os.path.expanduser("~")
        source = "/opt/pzserver/linux64/steamclient.so"
        target_dir = os.path.join(home, ".steam", "sdk64")
        target = os.path.join(target_dir, "steamclient.so")

        # Only proceed if source exists and target doesn't.
        if not os.path.isfile(source):
            return
        if os.path.isfile(target) or os.path.islink(target):
            return

        try:
            os.makedirs(target_dir, exist_ok=True)
            os.symlink(source, target)
            self.output_signal.emit(f"[Steam] Created symlink: {target} → {source}")
        except Exception as exc:
            self.output_signal.emit(f"[Steam] Warning: Could not auto-create symlink: {exc}")

    def _build_server_launch_env(self, server_dir):
        """Return process environment with Linux native library paths primed for Steam."""
        env = os.environ.copy()

        if sys.platform != "linux":
            return env

        home = os.path.expanduser("~")
        candidate_paths = [
            os.path.join(server_dir, "linux64"),
            os.path.join(server_dir, "natives", "linux64"),
            os.path.join(server_dir, "natives"),
            "/opt/pzserver/linux64",
            os.path.join(home, ".steam", "sdk64"),
            os.path.join(home, ".steam", "steamcmd", "linux64"),
            os.path.join(home, "Steam", "steamcmd", "linux64"),
            os.path.join(home, ".local", "share", "Steam", "linux64"),
            os.path.join(home, ".steam", "debian-installation", "linux64"),
        ]

        existing = [p for p in env.get("LD_LIBRARY_PATH", "").split(":") if p]
        merged = []
        seen = set()
        for path in candidate_paths + existing:
            norm = os.path.normpath(path)
            if norm in seen:
                continue
            seen.add(norm)
            merged.append(norm)

        env["LD_LIBRARY_PATH"] = ":".join(merged)
        return env

    def rcon_execute(self, host, port, password, command):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((host, port))
        request_id = 1
        sock.sendall(self._build_rcon_packet(request_id, 3, password))

        # Some servers send response-value packets before auth-response.
        auth_ok = False
        while True:
            packet_id, packet_type, _ = self._read_rcon_packet(sock)
            if packet_type == 2:
                if packet_id == -1:
                    raise Exception("Auth failed")
                auth_ok = True
                break

        if not auth_ok:
            raise Exception("No auth response received")

        sock.sendall(self._build_rcon_packet(request_id, 2, command))
        _, _, body = self._read_rcon_packet(sock)
        sock.close()
        return body

    def start_server(self):
        if self._crash_recovery_pending:
            self.output_signal.emit("Crash-recovery restart countdown is active. Press Stop to cancel before starting manually.")
            self._update_control_buttons()
            return

        if self._server_starting:
            self.output_signal.emit("Server is currently starting; start request ignored.")
            self._update_control_buttons()
            return

        if self._is_server_active():
            self.output_signal.emit("Server is already running; start request ignored.")
            self._update_control_buttons()
            return

        if not self.mods_tab.save_config_silent():
            self.output_signal.emit("Start blocked: failed to save Mods configuration.")
            self._update_control_buttons()
            return

        # Get launch parameters from settings
        params = self.settings_tab.launch_params.text().strip()
        # Get server directory from settings
        server_dir = self.settings_tab.get_server_dir_absolute()
        if not server_dir:
            self.output_signal.emit("No server directory selected.")
            return

        java_candidates = [
            os.path.normpath(os.path.join(server_dir, "jre64", "bin", "java.exe")),
            os.path.normpath(os.path.join(server_dir, "jre64", "bin", "java")),
            os.path.normpath(os.path.join(server_dir, "jre", "bin", "java")),
        ]
        if sys.platform == "win32":
            java_candidates.append(os.path.normpath(os.path.join(server_dir, "jre", "bin", "java.exe")))

        java_exe = next((candidate for candidate in java_candidates if os.path.exists(candidate)), None)
        if not java_exe:
            system_java = shutil.which("java")
            if system_java:
                java_exe = system_java
                self.output_signal.emit(f"Using system Java: {system_java}")
            else:
                self.output_signal.emit("Java executable not found in server directory or PATH.")
                return

        jar_path = os.path.normpath(os.path.join(server_dir, "java", "projectzomboid.jar"))
        if not os.path.exists(jar_path):
            self.output_signal.emit(f"JAR file not found at: {jar_path}")
            self.output_signal.emit("Check that your selected server folder matches the installed Project Zomboid Dedicated Server version.")
            return
        # Construct command as list
        try:
            parsed_params = shlex.split(params, posix=(sys.platform != "win32"))
        except ValueError as e:
            self.output_signal.emit(f"Invalid Java arguments: {e}")
            return

        native_access_flag = "--enable-native-access=ALL-UNNAMED"
        if not any(arg.startswith("--enable-native-access=") for arg in parsed_params):
            parsed_params.insert(0, native_access_flag)
            self.output_signal.emit("Added missing JVM flag: --enable-native-access=ALL-UNNAMED")

        parsed_params = self._normalize_java_params_for_server_dir(parsed_params, server_dir)

        # Ensure Steam symlink exists on Linux before launch.
        self._ensure_steam_symlink_on_linux()

        command_list = [java_exe] + parsed_params
        full_command_str = ' '.join(command_list)  # For logging
        self.output_signal.emit(f"Command: {full_command_str}")
        self.output_signal.emit(f"CWD: {server_dir}")
        launch_env = self._build_server_launch_env(server_dir)
        if sys.platform == "linux":
            self.output_signal.emit(f"LD_LIBRARY_PATH: {launch_env.get('LD_LIBRARY_PATH', '')}")

        if not self._acquire_server_lock():
            self.output_signal.emit("Another Knox Overseer instance already controls the server. Start blocked to prevent duplicate instances.")
            self._update_control_buttons()
            return

        try:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW

            self.server_process = subprocess.Popen(
                command_list,
                cwd=server_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                env=launch_env,
                text=True,
                bufsize=1,
                creationflags=creationflags,
            )
            self.output_signal.emit("Server process started.")
            if self._session_started_at is None:
                # Session uptime starts on the first explicit Start and is preserved
                # across auto/mod/crash restarts until an intentional Stop.
                self._session_started_at = datetime.now()
            self._update_rcon_state()
            self._stop_requested_by_user = False
            self._crash_recovery_pending = False
            self._crash_recovery_remaining = 0
            self._crash_recovery_timer.stop()
            self._crash_handled_for_current_process = False
            self._server_started_at = None
            self._startup_timed_out = False
            self._server_starting = True
            self._server_ready = False
            self._update_control_buttons()
            self._mod_baseline = {}
            self._mod_update_pending_restart_at = None
            self._connected_players = 0
            # Prime baseline shortly after startup.
            QTimer.singleShot(20000, self.check_mod_updates)
            # Startup log files appear after initialization; refresh a few delayed times.
            QTimer.singleShot(5000, self.refresh_logs_list)
            QTimer.singleShot(15000, self.refresh_logs_list)
            QTimer.singleShot(30000, self.refresh_logs_list)
            # Start threads to read output
            threading.Thread(target=self.read_output, args=(self.server_process.stdout, "stdout"), daemon=True).start()
            threading.Thread(target=self.read_output, args=(self.server_process.stderr, "stderr"), daemon=True).start()
            threading.Thread(target=self._wait_for_server_ready, daemon=True).start()
        except Exception as e:
            self.output_signal.emit(f"Failed to start server: {e}")
            self._release_server_lock()
            self._startup_timed_out = False
            self._server_starting = False
            self._server_ready = False
            self._update_control_buttons()

    def read_output(self, pipe, stream_type):
        for line in iter(pipe.readline, ''):
            if line:
                # Emit signal to append to terminal output
                self.output_signal.emit(line.rstrip())
                lower_line = line.lower()
                # Trigger immediate mod-check when a player attempts to join.
                if "join" in lower_line and "attempt" in lower_line:
                    self.check_mod_updates()

                # Best-effort player count tracking from server output.
                if "connected" in lower_line and "player" in lower_line:
                    self._connected_players += 1
                elif "disconnected" in lower_line and "player" in lower_line:
                    self._connected_players = max(0, self._connected_players - 1)

                # Log-based readiness hints for environments where RCON is delayed.
                if (
                    "server is started" in lower_line
                    or "server started" in lower_line
                    or "steam mode enabled" in lower_line
                    or "game server is running" in lower_line
                ):
                    self._mark_server_ready("log")
        pipe.close()

    def append_to_terminal(self, text):
        self.console_tab.terminal_output.append(text)

    def stop_server(self, intentional=True):
        if self._crash_recovery_pending and not self._is_server_active():
            self._stop_requested_by_user = True
            self._crash_recovery_pending = False
            self._crash_recovery_remaining = 0
            self._crash_recovery_timer.stop()
            self.output_signal.emit("[CrashRecovery] Auto-restart countdown cancelled by user.")
            self._update_control_buttons()
            return

        if self._server_starting:
            if intentional:
                QMessageBox.warning(
                    self,
                    "Server Starting",
                    "Server is still initializing. Stopping during startup is blocked to avoid corruption.",
                )
            self.output_signal.emit("Stop blocked: server is still initializing.")
            self._update_control_buttons()
            return

        if intentional:
            confirm = QMessageBox.warning(
                self,
                "Confirm Stop",
                "Are you sure you want to stop the server?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return

            self._stop_requested_by_user = True
            # Only explicit user Stop resets total session uptime.
            self._session_started_at = None
            # Cancel any queued/ongoing restart pipeline for explicit user stop.
            self._pending_restart = False
            self._restart_requested = False
            self._crash_recovery_pending = False
            self._mod_update_pending_restart_at = None
        self._server_starting = False
        self._server_ready = False
        self._server_started_at = None
        if self._is_server_active():
            try:
                # Graceful Project Zomboid shutdown command.
                self.server_process.stdin.write('quit\n')
                self.server_process.stdin.flush()
                self.output_signal.emit("Sent 'quit' command to server.")
                self._server_stopping = True
            except Exception as e:
                self.output_signal.emit(f"Failed to send quit command: {e}")
        else:
            self.output_signal.emit("Server is not running.")
        self._update_rcon_state()
        self._update_control_buttons()

    def restart_server(self):
        confirm = QMessageBox.warning(
            self,
            "Confirm Restart",
            "Are you sure you want to restart the server?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self._request_restart("Manual")

    def _refresh_discord_preview(self):
        context = self.stats_tab.get_discord_template_context()
        self.discord_tab.update_rendered_preview(context)

    def _normalize_webhook_url(self, webhook_text):
        text = (webhook_text or "").strip()
        if not text:
            return ""

        # Accept shorthand "id/token".
        if not (text.startswith("http://") or text.startswith("https://")):
            if "/" in text:
                candidate = f"https://discord.com/api/webhooks/{text.strip('/')}"
            else:
                return ""
        else:
            candidate = text

        try:
            parsed = urllib.parse.urlparse(candidate)
            host = (parsed.netloc or "").lower()
            path = parsed.path or ""
            if host not in (
                "discord.com",
                "www.discord.com",
                "discordapp.com",
                "www.discordapp.com",
                "ptb.discord.com",
                "canary.discord.com",
            ):
                return ""

            # Normalize accidental edit URL usage: /api/webhooks/<id>/<token>/messages/<message_id>
            path = path.rstrip("/")
            if "/messages/" in path:
                path = path.split("/messages/", 1)[0]

            parts = [p for p in path.split("/") if p]
            # Accept both /api/webhooks/<id>/<token> and /api/vX/webhooks/<id>/<token>.
            webhook_idx = -1
            for i, part in enumerate(parts):
                if part == "webhooks":
                    webhook_idx = i
                    break
            if webhook_idx < 0 or len(parts) <= webhook_idx + 2:
                return ""

            webhook_id = parts[webhook_idx + 1]
            webhook_token = parts[webhook_idx + 2]
            if not webhook_id or not webhook_token:
                return ""

            return f"https://discord.com/api/webhooks/{webhook_id}/{webhook_token}"
        except Exception:
            return ""

    def _send_discord_webhook(self, webhook_text, message_id, payload):
        webhook_url = self._normalize_webhook_url(webhook_text)
        if not webhook_url:
            self.discord_send_status_signal.emit("Send status: Invalid webhook. Use Discord webhook URL or id/token")
            return

        clean_message_id = (message_id or "").strip()
        if clean_message_id and not clean_message_id.isdigit():
            # Invalid message id format; send as a new message instead of failing in PATCH mode.
            self.discord_send_status_signal.emit("Send status: Message ID format invalid; sending as new message")
            clean_message_id = ""

        threading.Thread(
            target=self._send_discord_webhook_worker,
            args=(webhook_url, clean_message_id, payload),
            daemon=True,
        ).start()

    def _update_discord_repeat_timer(self):
        should_run = (
            self.discord_tab.is_repeat_enabled()
            and self._is_server_active()
            and self._server_ready
        )

        if not should_run:
            self.discord_repeat_timer.stop()
            return

        interval_ms = max(1, self.discord_tab.get_repeat_interval_seconds()) * 1000
        self.discord_repeat_timer.start(interval_ms)

    def _handle_discord_repeat_push(self):
        if self._discord_repeat_sending:
            return
        if not self.discord_tab.is_repeat_enabled():
            return
        if not self._is_server_active() or not self._server_ready:
            return

        webhook_text = self.discord_tab.webhook_id.text().strip()
        if not webhook_text:
            self.discord_send_status_signal.emit("Send status: Repeat push skipped (webhook field is empty)")
            return

        payload = self.discord_tab.get_rendered_payload()
        if payload is None:
            self.discord_send_status_signal.emit("Send status: Repeat push skipped (rendered JSON invalid)")
            return

        message_id = self.discord_tab.message_id.text().strip()
        self._discord_repeat_sending = True
        self._send_discord_webhook(webhook_text, message_id, payload)

    def _send_discord_webhook_worker(self, webhook_url, message_id, payload):
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "KnoxOverseer/1.0",
        }

        try:
            if message_id:
                url = f"{webhook_url.rstrip('/')}/messages/{urllib.parse.quote(message_id)}"
                method = "PATCH"
                self.discord_send_status_signal.emit("Send status: Sending edit (PATCH)...")
            else:
                joiner = "&" if "?" in webhook_url else "?"
                url = f"{webhook_url}{joiner}wait=true"
                method = "POST"
                self.discord_send_status_signal.emit("Send status: Sending new message (POST)...")

            resp = requests.request(method=method, url=url, headers=headers, json=payload, timeout=20)
            status_code = int(resp.status_code)

            if 200 <= status_code < 300:
                self.discord_send_status_signal.emit(f"Send status: Success ({status_code})")
                return

            # If edit mode fails for any reason, retry by sending a new message.
            if method == "PATCH":
                try:
                    joiner = "&" if "?" in webhook_url else "?"
                    fallback_url = f"{webhook_url}{joiner}wait=true"
                    fallback_resp = requests.post(
                        fallback_url,
                        headers=headers,
                        json=payload,
                        timeout=20,
                    )
                    fallback_status = int(fallback_resp.status_code)

                    if 200 <= fallback_status < 300:
                        self.discord_send_status_signal.emit(
                            f"Send status: Edit failed; sent as new message instead ({fallback_status})"
                        )
                        return

                    self.output_signal.emit(
                        f"[Discord] PATCH fallback POST failed with HTTP {fallback_status}: {fallback_resp.text}"
                    )
                except Exception as fallback_exc:
                    self.output_signal.emit(f"[Discord] PATCH fallback POST failed: {fallback_exc}")

            details = resp.text or ""
            if status_code == 403:
                hint = "Forbidden (403): check webhook URL/token, ensure it is the same webhook for this channel, and if Message ID is set ensure that message was created by this webhook."
                self.discord_send_status_signal.emit(f"Send status: HTTP 403 - {hint}")
                self.output_signal.emit(f"[Discord] {hint} Response: {details}")
            else:
                short = details.replace("\n", " ").strip()
                if len(short) > 180:
                    short = short[:177] + "..."
                self.discord_send_status_signal.emit(f"Send status: HTTP {status_code} - {short}")
                self.output_signal.emit(f"[Discord] Webhook HTTP error {status_code}: {details}")
        except Exception as exc:
            self.discord_send_status_signal.emit("Send status: Failed")
            self.output_signal.emit(f"[Discord] Failed to send webhook: {exc}")
        finally:
            self._discord_repeat_sending = False

    def update_status(self):
        self._handle_crash_recovery()

        if self._crash_recovery_pending and not self._is_server_active():
            self.label_uptime.setText("Uptime: -")
            self.stats_tab.set_real_uptime_seconds(None)
            self.label_status.setText(f"Status: Crash Recovery ({self._crash_recovery_remaining}s) - Press Stop to cancel")
        elif self._is_server_active() and self._server_stopping:
            self.label_uptime.setText("Uptime: -")
            self.stats_tab.set_real_uptime_seconds(None)
            self.label_status.setText("Status: Stopping...")
        elif self._is_server_active() and self._startup_timed_out:
            self.label_uptime.setText("Uptime: -")
            self.stats_tab.set_real_uptime_seconds(None)
            self.label_status.setText("Status: Startup Timeout (Running)")
        elif self._is_server_active() and self._server_ready and self._server_started_at is not None:
            now = datetime.now()

            iteration_elapsed = now - self._server_started_at
            iteration_seconds = int(iteration_elapsed.total_seconds())

            if self._session_started_at is None:
                self._session_started_at = self._server_started_at
            total_elapsed = now - self._session_started_at
            total_seconds = int(total_elapsed.total_seconds())

            total_h = total_seconds // 3600
            total_m = (total_seconds % 3600) // 60
            total_s = total_seconds % 60

            iter_h = iteration_seconds // 3600
            iter_m = (iteration_seconds % 3600) // 60
            iter_s = iteration_seconds % 60

            self.label_uptime.setText(
                f"Uptime: {total_h:02d}:{total_m:02d}:{total_s:02d} "
                f"({iter_h:02d}:{iter_m:02d}:{iter_s:02d})"
            )
            # Keep Stats tab tied to current iteration runtime.
            self.stats_tab.set_real_uptime_seconds(iteration_seconds)
            self.label_status.setText("Status: Running")
        elif self._is_server_active() and self._server_starting:
            self.label_uptime.setText("Uptime: -")
            self.stats_tab.set_real_uptime_seconds(None)
            self.label_status.setText("Status: Starting...")
        else:
            self.label_uptime.setText("Uptime: -")
            self.stats_tab.set_real_uptime_seconds(None)
            self.label_status.setText("Status: Stopped")
            self._server_starting = False
            self._server_stopping = False
            self._startup_timed_out = False
            self._server_ready = False
            self._server_started_at = None
            if not self._pending_restart and not self._crash_recovery_pending:
                self._release_server_lock()
        self._update_rcon_state()
        self._update_control_buttons()
        self._update_mod_actions_state()
        self._update_runtime_lock_states()
        self._process_mod_pending_restart()
        self._handle_auto_restart()
        self._refresh_discord_preview()
        self._update_discord_repeat_timer()

    def closeEvent(self, event):
        if self._is_server_active():
            QMessageBox.warning(self, "Server Running", "Stop the server before closing the application.")
            event.ignore()
            return
        if not self._pending_restart and not self._crash_recovery_pending:
            self._release_server_lock()
        self.settings_tab.save_state()
        self._save_ui_state()
        event.accept()