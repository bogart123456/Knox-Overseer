import json
from app.ui.discord_tab import DiscordTab


def test_placeholder_rendering(qapp):
    tab = DiscordTab()
    text = tab._replace_placeholders_in_string("Online: {{online}}", {"online": 3})
    assert text == "Online: 3"


def test_send_requires_webhook(qapp):
    tab = DiscordTab()
    tab.rendered_preview.setPlainText(json.dumps({"content": "hello"}))
    tab.webhook_id.setText("")
    tab._on_send_clicked()
    assert "required" in tab.send_status.text().lower()


def test_send_emits_payload(qapp):
    tab = DiscordTab()
    payload = {"content": "ok"}
    tab.rendered_preview.setPlainText(json.dumps(payload))
    tab.webhook_id.setText("https://discord.com/api/webhooks/1/2")
    tab.message_id.setText("123")

    captured = []
    tab.send_webhook_requested.connect(lambda w, m, p: captured.append((w, m, p)))
    tab._on_send_clicked()

    assert len(captured) == 1
    assert captured[0][0].startswith("https://discord.com/")
    assert captured[0][1] == "123"
    assert captured[0][2] == payload
