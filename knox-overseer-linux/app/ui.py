from __future__ import annotations

import os
import platform

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QWidget,
)

from .config import ServerConfig
from .config import default_config_for_platform
from .controller import LinuxServerController


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Knox Overseer")
        self.resize(980, 680)

        self._settings = QSettings("KnoxOverseer", "CrossPlatform")
        self._controller = LinuxServerController(self._load_config())

        self._build_ui()
        self._apply_loaded_values()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_controller)
        self._poll_timer.start(100)

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)

        layout = QGridLayout(root)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)

        self.server_dir = QLineEdit()
        self.start_command = QLineEdit()
        self.control_fifo = QLineEdit()
        self.console_command = QLineEdit()
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)

        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_server_dir)

        start_btn = QPushButton("Start")
        start_btn.clicked.connect(self._start_server)
        self.start_btn = start_btn

        stop_btn = QPushButton("Stop Graceful")
        stop_btn.clicked.connect(self._stop_graceful)
        self.stop_btn = stop_btn

        force_btn = QPushButton("Stop Force")
        force_btn.clicked.connect(self._stop_force)
        self.force_btn = force_btn

        send_btn = QPushButton("Send Console Command")
        send_btn.clicked.connect(self._send_console_command)

        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self._save_config)

        self.status = QLabel("Stopped")

        layout.addWidget(QLabel("Server Directory"), 0, 0)
        layout.addWidget(self.server_dir, 0, 1)
        layout.addWidget(browse, 0, 2)

        layout.addWidget(QLabel("Start Command"), 1, 0)
        layout.addWidget(self.start_command, 1, 1, 1, 2)

        layout.addWidget(QLabel("Control FIFO"), 2, 0)
        layout.addWidget(self.control_fifo, 2, 1, 1, 2)

        row = QHBoxLayout()
        row.addWidget(start_btn)
        row.addWidget(stop_btn)
        row.addWidget(force_btn)
        row.addWidget(save_btn)
        layout.addLayout(row, 3, 0, 1, 3)

        layout.addWidget(QLabel("Server Console Command"), 4, 0)
        layout.addWidget(self.console_command, 4, 1)
        layout.addWidget(send_btn, 4, 2)

        layout.addWidget(QLabel("Logs"), 5, 0)
        layout.addWidget(self.logs, 6, 0, 1, 3)
        layout.addWidget(self.status, 7, 0, 1, 3)

    def _load_config(self) -> ServerConfig:
        defaults = default_config_for_platform(platform.system())
        return ServerConfig(
            server_dir=self._settings.value("server_dir", defaults.server_dir, type=str),
            start_command=self._settings.value(
                "start_command", defaults.start_command, type=str
            ),
            control_fifo=self._settings.value("control_fifo", defaults.control_fifo, type=str),
        )

    def _apply_loaded_values(self) -> None:
        self.server_dir.setText(self._controller.config.server_dir)
        self.start_command.setText(self._controller.config.start_command)
        self.control_fifo.setText(self._controller.config.control_fifo)
        self._update_button_state()

    def _update_controller_config_from_inputs(self) -> None:
        self._controller.config = ServerConfig(
            server_dir=self.server_dir.text().strip(),
            start_command=self.start_command.text().strip(),
            control_fifo=self.control_fifo.text().strip(),
        )

    def _save_config(self) -> None:
        self._update_controller_config_from_inputs()
        cfg = self._controller.config
        self._settings.setValue("server_dir", cfg.server_dir)
        self._settings.setValue("start_command", cfg.start_command)
        self._settings.setValue("control_fifo", cfg.control_fifo)
        self._append_log("[info] settings saved")

    def _browse_server_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select Project Zomboid server directory")
        if selected:
            self.server_dir.setText(os.path.normpath(selected))

    def _start_server(self) -> None:
        try:
            self._update_controller_config_from_inputs()
            self._controller.start()
            self._append_log("[info] launch requested")
            self._update_button_state()
        except Exception as exc:
            QMessageBox.critical(self, "Start failed", str(exc))

    def _stop_graceful(self) -> None:
        self._controller.stop_graceful()
        self._update_button_state()

    def _stop_force(self) -> None:
        self._controller.stop_force()
        self._update_button_state()

    def _send_console_command(self) -> None:
        text = self.console_command.text().strip()
        if not text:
            return
        try:
            self._update_controller_config_from_inputs()
            self._controller.send_console_command(text)
            self.console_command.clear()
        except Exception as exc:
            QMessageBox.warning(self, "Command failed", str(exc))

    def _append_log(self, line: str) -> None:
        self.logs.appendPlainText(line)
        cursor = self.logs.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.logs.setTextCursor(cursor)

    def _poll_controller(self) -> None:
        while True:
            line = self._controller.poll_log_line(timeout=0.0)
            if line is None:
                break
            self._append_log(line)
        self._update_button_state()

    def _update_button_state(self) -> None:
        running = self._controller.state.running
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.force_btn.setEnabled(running)
        self.status.setText("Running" if running else "Stopped")


def run() -> int:
    app = QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()
