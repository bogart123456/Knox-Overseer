import os
import sys
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTimeEdit, QGridLayout, QFileDialog, QMessageBox, QComboBox
from PySide6.QtCore import Signal, QSettings, QTime
from .settings_store import get_app_settings

class SettingsTab(QWidget):
    ini_selected = Signal(str)
    sandbox_edit_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self._settings = get_app_settings()
        self.setup_ui()
        self.load_state()

    def _detect_default_ini_path(self):
        user_home = os.path.expanduser("~")
        candidate = os.path.join(user_home, "Zomboid", "Server", "servertest.ini")
        return candidate.replace("\\", "/")

    def _has_manual_ini_path(self):
        return self._settings.value("settings/ini_path_manual", False, type=bool)

    def _set_manual_ini_path(self, value=True):
        self._settings.setValue("settings/ini_path_manual", bool(value))

    def _default_server_dir_text(self):
        # Keep default relative so packaged executable works when placed in server folder.
        return "."

    def _default_launch_params(self):
        common = (
            "--enable-native-access=ALL-UNNAMED "
            "-Djava.awt.headless=true "
            "-Dzomboid.steam=1 "
            "-Dzomboid.znetlog=1 "
            "-XX:+UseZGC "
            "-XX:-CreateCoredumpOnCrash "
            "-XX:-OmitStackTraceInFastThrow "
            "-Xms8g -Xmx8g "
        )
        if sys.platform == "win32":
            return (
                f"{common}"
                "-Djava.library.path=natives/;natives/win64/;. "
                "-cp java/;java/projectzomboid.jar "
                "zombie.network.GameServer"
            )
        return (
            f"{common}"
            "-Djava.library.path=natives/:natives/linux64/:. "
            "-cp java/:java/projectzomboid.jar "
            "zombie.network.GameServer"
        )

    def _runtime_base_dir(self):
        if getattr(sys, "frozen", False):
            return os.path.dirname(os.path.abspath(sys.executable))
        return os.path.dirname(os.path.abspath(sys.argv[0]))

    def resolve_path(self, text):
        raw = (text or "").strip()
        if not raw:
            return ""
        if os.path.isabs(raw):
            return os.path.normpath(raw)
        return os.path.normpath(os.path.join(self._runtime_base_dir(), raw))

    def get_server_dir_absolute(self):
        return self.resolve_path(self.server_dir.text())

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        label_width = 170
        button_width = 90

        # INI file selection
        ini_layout = QHBoxLayout()
        ini_label = QLabel("Server Config (INI):")
        ini_label.setFixedWidth(label_width)
        ini_layout.addWidget(ini_label)
        self.ini_path = QLineEdit()
        self.ini_path.setText(self._detect_default_ini_path())
        self.ini_path.editingFinished.connect(self.on_ini_path_changed)
        ini_layout.addWidget(self.ini_path)
        self.browse_button = QPushButton("Browse")
        self.browse_button.setFixedWidth(button_width)
        self.browse_button.clicked.connect(self.browse_ini_file)
        ini_layout.addWidget(self.browse_button)
        layout.addLayout(ini_layout)

        # Sandbox Vars (derived from INI path)
        sandbox_layout = QHBoxLayout()
        sandbox_label = QLabel("Sandbox Vars:")
        sandbox_label.setFixedWidth(label_width)
        sandbox_layout.addWidget(sandbox_label)
        self.sandbox_vars_path = QLineEdit()
        self.sandbox_vars_path.setReadOnly(True)
        self.sandbox_vars_path.setPlaceholderText("Derived from INI path above")
        self.sandbox_vars_path.setStyleSheet("color: #999;")
        sandbox_layout.addWidget(self.sandbox_vars_path)
        self.edit_sandbox_button = QPushButton("Edit Vars")
        self.edit_sandbox_button.setFixedWidth(button_width)
        self.edit_sandbox_button.setEnabled(False)
        self.edit_sandbox_button.clicked.connect(self._on_edit_sandbox_clicked)
        sandbox_layout.addWidget(self.edit_sandbox_button)
        layout.addLayout(sandbox_layout)

        # Server directory selection
        server_layout = QHBoxLayout()
        server_label = QLabel("Server Directory:")
        server_label.setFixedWidth(label_width)
        server_layout.addWidget(server_label)
        self.server_dir = QLineEdit()
        self.server_dir.setText(self._default_server_dir_text())
        server_layout.addWidget(self.server_dir)
        self.browse_server_button = QPushButton("Browse")
        self.browse_server_button.setFixedWidth(button_width)
        self.browse_server_button.clicked.connect(self.browse_server_dir)
        server_layout.addWidget(self.browse_server_button)
        layout.addLayout(server_layout)

        # RCON host selection
        rcon_host_layout = QHBoxLayout()
        rcon_host_label = QLabel("RCON Host:")
        rcon_host_label.setFixedWidth(label_width)
        rcon_host_layout.addWidget(rcon_host_label)
        self.rcon_host = QLineEdit("localhost")
        rcon_host_layout.addWidget(self.rcon_host)
        rcon_host_layout.addSpacing(button_width)
        layout.addLayout(rcon_host_layout)

        # Launch params
        launch_layout = QHBoxLayout()
        launch_label = QLabel("Java Arguments:")
        launch_label.setFixedWidth(label_width)
        launch_layout.addWidget(launch_label)
        self.launch_params = QLineEdit(self._default_launch_params())
        launch_layout.addWidget(self.launch_params)
        launch_layout.addSpacing(button_width)
        layout.addLayout(launch_layout)

        # Auto restart (mirrors Mod Auto Update section layout)
        auto_restart_grid = QGridLayout()
        auto_restart_grid.setHorizontalSpacing(10)
        auto_restart_grid.setVerticalSpacing(8)

        auto_restart_label = QLabel("Auto-Restart:")
        auto_restart_label.setFixedWidth(label_width)
        auto_restart_grid.addWidget(auto_restart_label, 0, 0)

        self.auto_restart_check = QPushButton()
        self.auto_restart_check.setCheckable(True)
        self.auto_restart_check.setChecked(True)
        self.auto_restart_check.clicked.connect(self.on_auto_restart_toggled)
        self._update_toggle_button_text(self.auto_restart_check, "Auto-Restart")
        self.auto_restart_check.setMinimumWidth(220)
        auto_restart_grid.addWidget(self.auto_restart_check, 0, 1)

        alert_label = QLabel("Alert Before Shutdown:")
        alert_label.setFixedWidth(label_width)
        auto_restart_grid.addWidget(alert_label, 1, 0)
        self.alert_before_shutdown = QComboBox()
        self.alert_before_shutdown.addItems(["1hr", "30mins", "15mins", "10mins", "5mins"])
        self.alert_before_shutdown.setCurrentText("1hr")
        self.alert_before_shutdown.setMinimumWidth(140)
        auto_restart_grid.addWidget(self.alert_before_shutdown, 1, 1)

        schedule_label = QLabel("Restart Schedule:")
        schedule_label.setFixedWidth(label_width)
        auto_restart_grid.addWidget(schedule_label, 2, 0)
        self.restart_time = QTimeEdit()
        self.restart_time.setDisplayFormat("HH:mm")
        self.restart_time.setMinimumWidth(140)
        auto_restart_grid.addWidget(self.restart_time, 2, 1)

        crash_restart_label = QLabel("Crash Auto-Restart:")
        crash_restart_label.setFixedWidth(label_width)
        auto_restart_grid.addWidget(crash_restart_label, 3, 0)
        self.crash_restart_check = QPushButton()
        self.crash_restart_check.setCheckable(True)
        self.crash_restart_check.setChecked(True)
        self.crash_restart_check.clicked.connect(self.on_crash_restart_toggled)
        self._update_toggle_button_text(self.crash_restart_check, "Crash Auto-Restart")
        self.crash_restart_check.setMinimumWidth(220)
        auto_restart_grid.addWidget(self.crash_restart_check, 3, 1)

        crash_delay_label = QLabel("Crash Restart Delay:")
        crash_delay_label.setFixedWidth(label_width)
        auto_restart_grid.addWidget(crash_delay_label, 4, 0)
        self.crash_restart_delay = QComboBox()
        self.crash_restart_delay.addItems(["5s", "10s", "30s", "60s"])
        self.crash_restart_delay.setCurrentText("10s")
        self.crash_restart_delay.setMinimumWidth(140)
        auto_restart_grid.addWidget(self.crash_restart_delay, 4, 1)

        auto_restart_grid.setColumnStretch(1, 1)
        layout.addLayout(auto_restart_grid)

        # RCON messages
        rcon_grid = QGridLayout()
        rcon_grid.setHorizontalSpacing(10)
        rcon_grid.setVerticalSpacing(8)

        auto_mod_label = QLabel("Mod Auto Update:")
        auto_mod_label.setFixedWidth(label_width)
        rcon_grid.addWidget(auto_mod_label, 0, 0)

        self.auto_mod_check = QPushButton()
        self.auto_mod_check.setCheckable(True)
        self.auto_mod_check.setChecked(True)
        self.auto_mod_check.clicked.connect(self.on_auto_mod_toggled)
        self._update_toggle_button_text(self.auto_mod_check, "Auto Mod Update Detection")
        self.auto_mod_check.setMinimumWidth(220)
        rcon_grid.addWidget(self.auto_mod_check, 0, 1)

        mod_alert_label = QLabel("Mod Update Alert Time:")
        mod_alert_label.setFixedWidth(label_width)
        rcon_grid.addWidget(mod_alert_label, 1, 0)
        self.mod_update_alert_time = QComboBox()
        self.mod_update_alert_time.addItems(["1hr", "30mins", "15mins", "10mins", "5mins"])
        self.mod_update_alert_time.setCurrentText("10mins")
        self.mod_update_alert_time.setMinimumWidth(140)
        rcon_grid.addWidget(self.mod_update_alert_time, 1, 1)

        detection_rate_label = QLabel("Mod Detection Rate:")
        detection_rate_label.setFixedWidth(label_width)
        rcon_grid.addWidget(detection_rate_label, 2, 0)
        self.mod_detection_rate = QComboBox()
        self.mod_detection_rate.addItems([
            "Every 1 minute",
            "Every 2 minutes",
            "Every 5 minutes",
            "Every 10 minutes",
            "Every 15 minutes",
            "Every 30 minutes",
            "Every 1 hour",
        ])
        self.mod_detection_rate.setCurrentText("Every 5 minutes")
        self.mod_detection_rate.setMinimumWidth(140)
        rcon_grid.addWidget(self.mod_detection_rate, 2, 1)
        rcon_grid.setColumnStretch(1, 1)
        layout.addLayout(rcon_grid)

        self._apply_auto_restart_lock()

        # Update sandbox vars path whenever INI path changes.
        self.ini_path.editingFinished.connect(self._update_sandbox_path_display)

        # Persist settings changes automatically.
        self.ini_path.editingFinished.connect(self.save_state)
        self.server_dir.editingFinished.connect(self.save_state)
        self.rcon_host.editingFinished.connect(self.save_state)
        self.launch_params.editingFinished.connect(self.save_state)
        self.restart_time.timeChanged.connect(lambda _t: self.save_state())
        self.alert_before_shutdown.currentTextChanged.connect(lambda _t: self.save_state())
        self.mod_update_alert_time.currentTextChanged.connect(lambda _t: self.save_state())
        self.mod_detection_rate.currentTextChanged.connect(lambda _t: self.save_state())
        self.auto_restart_check.toggled.connect(lambda _v: self.save_state())
        self.crash_restart_check.toggled.connect(lambda _v: self.save_state())
        self.crash_restart_delay.currentTextChanged.connect(lambda _t: self.save_state())
        self.auto_mod_check.toggled.connect(lambda _v: self.save_state())

    def get_sandbox_vars_path(self, ini_path=None):
        """Return the expected SandboxVars.lua path derived from the INI file path."""
        if ini_path is None:
            ini_path = self.ini_path.text().strip()
        if not ini_path:
            return ""
        base = os.path.splitext(os.path.basename(ini_path))[0]
        return os.path.join(os.path.dirname(ini_path), f"{base}_SandboxVars.lua")

    def _update_sandbox_path_display(self, ini_path=None):
        path = self.get_sandbox_vars_path(ini_path)
        self.sandbox_vars_path.setText(path.replace("\\", "/") if path else "")
        exists = os.path.isfile(path) if path else False
        self.edit_sandbox_button.setEnabled(bool(path))
        self.sandbox_vars_path.setStyleSheet(
            "color: #999;" if exists else "color: #c77;"
        )

    def _on_edit_sandbox_clicked(self):
        path = self.get_sandbox_vars_path()
        if path:
            self.sandbox_edit_requested.emit(path)

    def load_state(self):
        if self._has_manual_ini_path():
            ini_path = self._settings.value("settings/ini_path", self.ini_path.text(), type=str)
        else:
            ini_path = self._detect_default_ini_path()
        server_dir = self._settings.value("settings/server_dir", self.server_dir.text(), type=str)
        launch_params = self._settings.value("settings/launch_params", self.launch_params.text(), type=str)
        rcon_host = self._settings.value("settings/rcon_host", self.rcon_host.text(), type=str)
        auto_restart = self._settings.value("settings/auto_restart", self.auto_restart_check.isChecked(), type=bool)
        crash_restart = self._settings.value("settings/crash_restart", self.crash_restart_check.isChecked(), type=bool)
        crash_restart_delay = self._settings.value("settings/crash_restart_delay", self.crash_restart_delay.currentText(), type=str)
        restart_time = self._settings.value("settings/restart_time", self.restart_time.time().toString("HH:mm"), type=str)
        alert_before_shutdown = self._settings.value("settings/alert_before_shutdown", self.alert_before_shutdown.currentText(), type=str)
        auto_mod_check = self._settings.value("settings/auto_mod_check", self.auto_mod_check.isChecked(), type=bool)
        mod_update_alert_time = self._settings.value("settings/mod_update_alert_time", self.mod_update_alert_time.currentText(), type=str)
        mod_detection_rate = self._settings.value("settings/mod_detection_rate", self.mod_detection_rate.currentText(), type=str)

        self.ini_path.setText(ini_path)
        self.server_dir.setText(server_dir)
        self.launch_params.setText(launch_params)
        self.rcon_host.setText((rcon_host or "localhost").strip() or "localhost")
        self.auto_restart_check.setChecked(bool(auto_restart))
        self.crash_restart_check.setChecked(bool(crash_restart))
        self.auto_mod_check.setChecked(bool(auto_mod_check))

        parsed_time = QTime.fromString(restart_time, "HH:mm")
        if parsed_time.isValid():
            self.restart_time.setTime(parsed_time)

        if self.alert_before_shutdown.findText(alert_before_shutdown) >= 0:
            self.alert_before_shutdown.setCurrentText(alert_before_shutdown)
        if self.mod_update_alert_time.findText(mod_update_alert_time) >= 0:
            self.mod_update_alert_time.setCurrentText(mod_update_alert_time)
        if self.mod_detection_rate.findText(mod_detection_rate) >= 0:
            self.mod_detection_rate.setCurrentText(mod_detection_rate)
        if self.crash_restart_delay.findText(crash_restart_delay) >= 0:
            self.crash_restart_delay.setCurrentText(crash_restart_delay)

        self._update_toggle_button_text(self.auto_restart_check, "Auto-Restart")
        self._update_toggle_button_text(self.crash_restart_check, "Crash Auto-Restart")
        self._update_toggle_button_text(self.auto_mod_check, "Auto Mod Update Detection")
        self._apply_auto_restart_lock()
        self._update_sandbox_path_display(self.ini_path.text())

    def save_state(self):
        ini_path = self.ini_path.text().strip()
        if self._has_manual_ini_path():
            self._settings.setValue("settings/ini_path", ini_path)
        else:
            self._settings.remove("settings/ini_path")
        self._settings.setValue("settings/server_dir", self.server_dir.text().strip())
        self._settings.setValue("settings/rcon_host", self.rcon_host.text().strip() or "localhost")
        self._settings.setValue("settings/launch_params", self.launch_params.text().strip())
        self._settings.setValue("settings/auto_restart", self.auto_restart_check.isChecked())
        self._settings.setValue("settings/crash_restart", self.crash_restart_check.isChecked())
        self._settings.setValue("settings/crash_restart_delay", self.crash_restart_delay.currentText())
        self._settings.setValue("settings/restart_time", self.restart_time.time().toString("HH:mm"))
        self._settings.setValue("settings/alert_before_shutdown", self.alert_before_shutdown.currentText())
        self._settings.setValue("settings/auto_mod_check", self.auto_mod_check.isChecked())
        self._settings.setValue("settings/mod_update_alert_time", self.mod_update_alert_time.currentText())
        self._settings.setValue("settings/mod_detection_rate", self.mod_detection_rate.currentText())

    def _update_toggle_button_text(self, button, feature_name):
        state = "Disable" if button.isChecked() else "Enable"
        button.setText(f"{state} {feature_name}")

    def _confirm_disable(self, feature_name):
        result = QMessageBox.warning(
            self,
            "Disable Feature",
            f"You are about to disable {feature_name}. Are you sure?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return result == QMessageBox.Yes

    def on_auto_restart_toggled(self, checked):
        if not checked and not self._confirm_disable("Auto-Restart"):
            self.auto_restart_check.setChecked(True)
        self._update_toggle_button_text(self.auto_restart_check, "Auto-Restart")
        self._apply_auto_restart_lock()

    def on_auto_mod_toggled(self, checked):
        if not checked and not self._confirm_disable("Auto Mod Update Detection"):
            self.auto_mod_check.setChecked(True)
        self._update_toggle_button_text(self.auto_mod_check, "Auto Mod Update Detection")

    def on_crash_restart_toggled(self, checked):
        if not checked and not self._confirm_disable("Crash Auto-Restart"):
            self.crash_restart_check.setChecked(True)
        self._update_toggle_button_text(self.crash_restart_check, "Crash Auto-Restart")

    def _apply_auto_restart_lock(self):
        enabled = self.auto_restart_check.isChecked()
        # Lock schedule changes while auto-restart is active.
        self.restart_time.setEnabled(not enabled)

    def get_alert_start_minutes(self):
        text = self.alert_before_shutdown.currentText().strip().lower()
        mapping = {
            "1hr": 60,
            "30mins": 30,
            "15mins": 15,
            "10mins": 10,
            "5mins": 5,
        }
        return mapping.get(text, 60)

    def get_mod_update_alert_minutes(self):
        text = self.mod_update_alert_time.currentText().strip().lower()
        mapping = {
            "1hr": 60,
            "30mins": 30,
            "15mins": 15,
            "10mins": 10,
            "5mins": 5,
        }
        return mapping.get(text, 10)

    def get_mod_detection_interval_ms(self):
        text = self.mod_detection_rate.currentText().strip().lower()
        mapping = {
            "every 1 minute": 60_000,
            "every 2 minutes": 120_000,
            "every 5 minutes": 300_000,
            "every 10 minutes": 600_000,
            "every 15 minutes": 900_000,
            "every 30 minutes": 1_800_000,
            "every 1 hour": 3_600_000,
        }
        return mapping.get(text, 300_000)

    def get_rcon_host(self):
        return (self.rcon_host.text().strip() or "localhost")

    def is_crash_restart_enabled(self):
        return self.crash_restart_check.isChecked()

    def get_crash_restart_delay_seconds(self):
        text = self.crash_restart_delay.currentText().strip().lower()
        mapping = {
            "5s": 5,
            "10s": 10,
            "30s": 30,
            "60s": 60,
        }
        return mapping.get(text, 10)

    def set_runtime_lock(self, locked):
        # Lock file/path and launch config fields while server is active.
        self.ini_path.setEnabled(not locked)
        self.browse_button.setEnabled(not locked)
        self.server_dir.setEnabled(not locked)
        self.browse_server_button.setEnabled(not locked)
        self.launch_params.setEnabled(not locked)
        self.edit_sandbox_button.setEnabled(not locked and bool(self.ini_path.text().strip()))

    def browse_ini_file(self):
        initial_dir = os.path.dirname(self.ini_path.text().strip()) or os.path.dirname(self._detect_default_ini_path())
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Server Config INI File", initial_dir, "INI Files (*.ini);;All Files (*)")
        if file_path:
            self.ini_path.setText(file_path)
            self._set_manual_ini_path(True)
            self.save_state()
            self._update_sandbox_path_display(file_path)
            self.ini_selected.emit(file_path)

    def on_ini_path_changed(self):
        ini_path = self.ini_path.text().strip()
        if ini_path:
            self._set_manual_ini_path(True)
            self.save_state()
            self._update_sandbox_path_display(ini_path)
            self.ini_selected.emit(ini_path)

    def browse_server_dir(self):
        initial = self.get_server_dir_absolute() or self._runtime_base_dir()
        dir_path = QFileDialog.getExistingDirectory(self, "Select Server Directory", initial)
        if dir_path:
            self.server_dir.setText(dir_path)
            self.save_state()