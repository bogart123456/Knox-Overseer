import os
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QFileDialog,
    QComboBox,
    QSpinBox,
    QCheckBox,
)
from PySide6.QtCore import Signal, QSettings
from .settings_store import get_app_settings


class BackupTab(QWidget):
    backup_settings_changed = Signal()
    restore_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self._settings = get_app_settings()
        self._current_ini_path = ""
        self.setup_ui()
        self.load_state()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        label_width = 180
        button_width = 110

        options_grid = QGridLayout()
        options_grid.setHorizontalSpacing(10)
        options_grid.setVerticalSpacing(8)

        interval_label = QLabel("Backup Interval:")
        interval_label.setFixedWidth(label_width)
        options_grid.addWidget(interval_label, 0, 0)

        self.interval_combo = QComboBox()
        self.interval_combo.addItems([
            "Off",
            "5 minutes",
            "10 minutes",
            "15 minutes",
            "30 minutes",
            "1 hour",
            "2 hours",
            "4 hours",
            "6 hours",
            "12 hours",
            "24 hours",
        ])
        self.interval_combo.setCurrentText("10 minutes")
        self.interval_combo.setMinimumWidth(170)
        options_grid.addWidget(self.interval_combo, 0, 1)

        max_backups_label = QLabel("Max Backups:")
        max_backups_label.setFixedWidth(label_width)
        options_grid.addWidget(max_backups_label, 1, 0)

        self.max_backups_spin = QSpinBox()
        self.max_backups_spin.setRange(1, 999)
        self.max_backups_spin.setValue(20)
        self.max_backups_spin.setMinimumWidth(90)
        options_grid.addWidget(self.max_backups_spin, 1, 1)

        on_start_label = QLabel("Backup On Start:")
        on_start_label.setFixedWidth(label_width)
        options_grid.addWidget(on_start_label, 2, 0)

        self.backup_on_start_check = QCheckBox()
        self.backup_on_start_check.setChecked(True)
        options_grid.addWidget(self.backup_on_start_check, 2, 1)

        on_version_label = QLabel("Backup On Version Change:")
        on_version_label.setFixedWidth(label_width)
        options_grid.addWidget(on_version_label, 3, 0)

        self.backup_on_version_check = QCheckBox()
        self.backup_on_version_check.setChecked(True)
        options_grid.addWidget(self.backup_on_version_check, 3, 1)

        options_grid.setColumnStretch(1, 1)
        layout.addLayout(options_grid)

        restore_grid = QGridLayout()
        restore_grid.setHorizontalSpacing(10)
        restore_grid.setVerticalSpacing(8)

        restore_title = QLabel("Restore Backup")
        restore_grid.addWidget(restore_title, 0, 0)

        restore_path_label = QLabel("Backup ZIP File:")
        restore_path_label.setFixedWidth(label_width)
        restore_grid.addWidget(restore_path_label, 1, 0)

        path_layout = QHBoxLayout()
        self.restore_zip_path = QLineEdit()
        path_layout.addWidget(self.restore_zip_path)
        self.browse_restore_zip = QPushButton("Browse")
        self.browse_restore_zip.setFixedWidth(button_width)
        self.browse_restore_zip.clicked.connect(self._browse_restore_zip)
        path_layout.addWidget(self.browse_restore_zip)
        restore_grid.addLayout(path_layout, 1, 1)

        self.restore_button = QPushButton("Restore Backup")
        self.restore_button.setFixedWidth(180)
        self.restore_button.clicked.connect(self._request_restore)
        restore_grid.addWidget(self.restore_button, 2, 1)

        status_title = QLabel("Backup Status:")
        status_title.setFixedWidth(label_width)
        restore_grid.addWidget(status_title, 3, 0)

        self.status_label = QLabel("Idle")
        self.status_label.setWordWrap(True)
        restore_grid.addWidget(self.status_label, 3, 1)

        restore_grid.setColumnStretch(1, 1)
        layout.addLayout(restore_grid)

        layout.addStretch(1)

        self.interval_combo.currentTextChanged.connect(self._on_backup_setting_changed)
        self.max_backups_spin.valueChanged.connect(self._on_backup_setting_changed)
        self.backup_on_start_check.toggled.connect(lambda _v: self._on_backup_setting_changed())
        self.backup_on_version_check.toggled.connect(lambda _v: self._on_backup_setting_changed())
        self.restore_zip_path.editingFinished.connect(self.save_state)

    def load_state(self):
        interval = self._settings.value("backup/interval", self.interval_combo.currentText(), type=str)
        max_backups = self._settings.value("backup/max_backups", self.max_backups_spin.value(), type=int)
        backup_on_start = self._settings.value("backup/on_start", self.backup_on_start_check.isChecked(), type=bool)
        backup_on_version = self._settings.value("backup/on_version_change", self.backup_on_version_check.isChecked(), type=bool)
        restore_zip_path = self._settings.value("backup/restore_zip_path", "", type=str)

        if self.interval_combo.findText(interval) >= 0:
            self.interval_combo.setCurrentText(interval)

        self.max_backups_spin.setValue(max(1, int(max_backups)))
        self.backup_on_start_check.setChecked(bool(backup_on_start))
        self.backup_on_version_check.setChecked(bool(backup_on_version))
        self.restore_zip_path.setText(restore_zip_path)

    def save_state(self):
        self._settings.setValue("backup/interval", self.interval_combo.currentText())
        self._settings.setValue("backup/max_backups", int(self.max_backups_spin.value()))
        self._settings.setValue("backup/on_start", self.backup_on_start_check.isChecked())
        self._settings.setValue("backup/on_version_change", self.backup_on_version_check.isChecked())
        self._settings.setValue("backup/restore_zip_path", self.restore_zip_path.text().strip())

    def _on_backup_setting_changed(self):
        self.save_state()
        self.backup_settings_changed.emit()

    def set_ini_path(self, ini_path):
        self._current_ini_path = (ini_path or "").strip()

    def get_save_source_path(self):
        if not self._current_ini_path:
            return ""
        server_name = os.path.splitext(os.path.basename(self._current_ini_path))[0]
        server_dir = os.path.dirname(self._current_ini_path)
        zomboid_root = os.path.dirname(server_dir)
        return os.path.join(zomboid_root, "Saves", "Multiplayer", server_name)

    def get_backup_dir_path(self):
        if self._current_ini_path:
            server_dir = os.path.dirname(self._current_ini_path)
            zomboid_root = os.path.dirname(server_dir)
            return os.path.join(zomboid_root, "backups")
        return os.path.join(os.path.expanduser("~"), "Zomboid", "backups")

    def get_backup_period_minutes(self):
        text = self.interval_combo.currentText().strip().lower()
        mapping = {
            "off": 0,
            "5 minutes": 5,
            "10 minutes": 10,
            "15 minutes": 15,
            "30 minutes": 30,
            "1 hour": 60,
            "2 hours": 120,
            "4 hours": 240,
            "6 hours": 360,
            "12 hours": 720,
            "24 hours": 1440,
        }
        return mapping.get(text, 0)

    def get_max_backups(self):
        return int(self.max_backups_spin.value())

    def is_backup_on_start_enabled(self):
        return self.backup_on_start_check.isChecked()

    def is_backup_on_version_change_enabled(self):
        return self.backup_on_version_check.isChecked()

    def set_status(self, text):
        self.status_label.setText(text)

    def set_runtime_lock(self, locked):
        # Prevent modifying backup/restore settings while server is running.
        self.interval_combo.setEnabled(not locked)
        self.max_backups_spin.setEnabled(not locked)
        self.backup_on_start_check.setEnabled(not locked)
        self.backup_on_version_check.setEnabled(not locked)
        self.restore_zip_path.setEnabled(not locked)
        self.browse_restore_zip.setEnabled(not locked)
        self.restore_button.setEnabled(not locked)

    def _browse_restore_zip(self):
        initial_dir = self.get_backup_dir_path()
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Backup ZIP", initial_dir, "ZIP Files (*.zip);;All Files (*)")
        if file_path:
            self.restore_zip_path.setText(file_path)
            self.save_state()

    def _request_restore(self):
        zip_path = self.restore_zip_path.text().strip()
        if not zip_path:
            self.set_status("Select a backup ZIP before restoring.")
            return
        self.save_state()
        self.restore_requested.emit(zip_path)
