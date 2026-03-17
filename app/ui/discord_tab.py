import json
import re
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QMessageBox
from PySide6.QtCore import QSettings, Signal
from .settings_store import get_app_settings


DEFAULT_DISCORD_TEMPLATE = {
    "content": None,
    "embeds": [
        {
            "title": "**Survivors**",
            "color": 16745728,
            "fields": [
                {
                    "name": "Online:",
                    "value": "{{online_players_formatted}}",
                },
                {
                    "name": "Offline:",
                    "value": "{{offline_players_formatted}}",
                },
            ],
        },
        {
            "title": "In-Game:",
            "description": "**Date:** {{ingame_date}}\n**Time:** {{ingame_time}}\n{{weather_icon}} {{weather}}\n🌡 {{temperature_c}}°C",
            "color": 16745728,
        },
    ],
    "attachments": [],
}


class DiscordTab(QWidget):
    send_webhook_requested = Signal(str, str, object)
    repeat_settings_changed = Signal()

    def __init__(self):
        super().__init__()
        self._settings = get_app_settings()
        self._last_rendered_preview_text = ""
        self.setup_ui()
        self.load_state()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        label_width = 180

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        webhook_label = QLabel("Webhook ID:")
        webhook_label.setFixedWidth(label_width)
        grid.addWidget(webhook_label, 0, 0)

        self.webhook_id = QLineEdit()
        self.webhook_id.setPlaceholderText("Enter Discord webhook ID or URL")
        grid.addWidget(self.webhook_id, 0, 1)

        message_id_label = QLabel("Message ID (optional):")
        message_id_label.setFixedWidth(label_width)
        grid.addWidget(message_id_label, 1, 0)

        self.message_id = QLineEdit()
        self.message_id.setPlaceholderText("Optional message ID")
        grid.addWidget(self.message_id, 1, 1)

        payload_label = QLabel("Template:")
        payload_label.setFixedWidth(label_width)
        grid.addWidget(payload_label, 2, 0)

        self.template_info = QLabel("Using fixed built-in Discord template based on server stats.")
        self.template_info.setWordWrap(True)
        grid.addWidget(self.template_info, 2, 1)

        preview_label = QLabel("Rendered JSON (preview):")
        preview_label.setFixedWidth(label_width)
        grid.addWidget(preview_label, 3, 0)

        self.rendered_preview = QPlainTextEdit()
        self.rendered_preview.setReadOnly(True)
        self.rendered_preview.setMinimumHeight(220)
        grid.addWidget(self.rendered_preview, 3, 1)

        self.template_status = QLabel("Template status: Waiting for stats data")
        grid.addWidget(self.template_status, 4, 1)

        self.send_status = QLabel("Send status: Idle")
        grid.addWidget(self.send_status, 5, 1)

        repeat_label = QLabel("Repeat Push:")
        repeat_label.setFixedWidth(label_width)
        grid.addWidget(repeat_label, 6, 0)

        self.repeat_enabled = QPushButton()
        self.repeat_enabled.setCheckable(True)
        self.repeat_enabled.setChecked(False)
        self.repeat_enabled.clicked.connect(self._on_repeat_toggled)
        self._update_repeat_button_text()
        grid.addWidget(self.repeat_enabled, 6, 1)

        repeat_seconds_label = QLabel("Repeat Interval (seconds):")
        repeat_seconds_label.setFixedWidth(label_width)
        grid.addWidget(repeat_seconds_label, 7, 0)

        self.repeat_interval_seconds = QSpinBox()
        self.repeat_interval_seconds.setRange(1, 86400)
        self.repeat_interval_seconds.setValue(60)
        grid.addWidget(self.repeat_interval_seconds, 7, 1)

        self.send_button = QPushButton("Send Webhook")
        self.send_button.clicked.connect(self._on_send_clicked)
        grid.addWidget(self.send_button, 8, 1)

        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)

        self.webhook_id.editingFinished.connect(self.save_state)
        self.message_id.editingFinished.connect(self.save_state)
        self.repeat_interval_seconds.valueChanged.connect(lambda _v: self._on_repeat_setting_changed())

    def load_state(self):
        webhook_id = self._settings.value("discord/webhook_id", "", type=str)
        message_id = self._settings.value("discord/message_id", "", type=str)
        repeat_enabled = self._settings.value("discord/repeat_enabled", False, type=bool)
        repeat_interval_seconds = self._settings.value("discord/repeat_interval_seconds", 60, type=int)

        self.webhook_id.setText(webhook_id)
        self.message_id.setText(message_id)
        self.repeat_enabled.setChecked(bool(repeat_enabled))
        self._update_repeat_button_text()
        self.repeat_interval_seconds.setValue(max(1, int(repeat_interval_seconds)))

    def save_state(self):
        self._settings.setValue("discord/webhook_id", self.webhook_id.text().strip())
        self._settings.setValue("discord/message_id", self.message_id.text().strip())
        self._settings.setValue("discord/repeat_enabled", self.repeat_enabled.isChecked())
        self._settings.setValue("discord/repeat_interval_seconds", int(self.repeat_interval_seconds.value()))

    def _on_repeat_setting_changed(self):
        self.save_state()
        self.repeat_settings_changed.emit()

    def _update_repeat_button_text(self):
        state = "Disable" if self.repeat_enabled.isChecked() else "Enable"
        self.repeat_enabled.setText(f"{state} Repeating Webhook Push")

    def _on_repeat_toggled(self):
        if not self.repeat_enabled.isChecked():
            result = QMessageBox.warning(
                self,
                "Disable Repeating Push",
                "You are about to disable repeating webhook push. Are you sure?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if result != QMessageBox.Yes:
                self.repeat_enabled.setChecked(True)

        self._update_repeat_button_text()
        self._on_repeat_setting_changed()

    def _replace_placeholders_in_string(self, text, context):
        pattern = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

        def repl(match):
            key = match.group(1)
            return str(context.get(key, ""))

        return pattern.sub(repl, text)

    def _render_value(self, value, context):
        if isinstance(value, dict):
            return {k: self._render_value(v, context) for k, v in value.items()}
        if isinstance(value, list):
            return [self._render_value(v, context) for v in value]
        if isinstance(value, str):
            return self._replace_placeholders_in_string(value, context)
        return value

    def update_rendered_preview(self, context):
        try:
            rendered = self._render_value(DEFAULT_DISCORD_TEMPLATE, context or {})
            rendered_text = json.dumps(rendered, ensure_ascii=False, indent=2)
            if rendered_text != self._last_rendered_preview_text:
                self.rendered_preview.setPlainText(rendered_text)
                self._last_rendered_preview_text = rendered_text
            self.template_status.setText("Template status: OK")
        except Exception as exc:
            self.template_status.setText(f"Template status: Render failed ({exc})")

    def _on_send_clicked(self):
        webhook_text = self.webhook_id.text().strip()
        message_id = self.message_id.text().strip()
        rendered_text = self.rendered_preview.toPlainText().strip()

        if not webhook_text:
            self.set_send_status("Send status: Webhook field is required")
            return
        if not rendered_text:
            self.set_send_status("Send status: Nothing to send (rendered JSON is empty)")
            return

        try:
            payload = json.loads(rendered_text)
        except Exception as exc:
            self.set_send_status(f"Send status: Rendered JSON is invalid ({exc})")
            return

        self.set_send_status("Send status: Sending...")
        self.send_webhook_requested.emit(webhook_text, message_id, payload)

    def get_rendered_payload(self):
        rendered_text = self.rendered_preview.toPlainText().strip()
        if not rendered_text:
            return None
        try:
            return json.loads(rendered_text)
        except Exception:
            return None

    def is_repeat_enabled(self):
        return self.repeat_enabled.isChecked()

    def get_repeat_interval_seconds(self):
        return int(self.repeat_interval_seconds.value())

    def set_send_status(self, text):
        self.send_status.setText(text)
