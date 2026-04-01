import os
from types import SimpleNamespace

from PySide6.QtWidgets import QPushButton
from app.ui.main_window import MainWindow


def _build_lightweight_window(monkeypatch):
    def fake_setup(self):
        self.button_start = QPushButton()
        self.button_stop = QPushButton()
        self.button_restart = QPushButton()

    monkeypatch.setattr(MainWindow, "setup_ui", fake_setup)
    monkeypatch.setattr(MainWindow, "connect_signals", lambda self: None)
    monkeypatch.setattr(MainWindow, "_restore_ui_state", lambda self: None)
    return MainWindow()


def test_update_control_buttons_blocks_start_when_crash_pending(qapp, monkeypatch):
    win = _build_lightweight_window(monkeypatch)
    win._crash_recovery_pending = True
    win._server_starting = False
    win._server_stopping = False
    monkeypatch.setattr(win, "_is_server_active", lambda: False)

    win._update_control_buttons()

    assert not win.button_start.isEnabled()
    assert win.button_stop.isEnabled()


def test_restart_state_helper(qapp, monkeypatch):
    win = _build_lightweight_window(monkeypatch)
    win._pending_restart = False
    win._restart_requested = False
    assert win._is_restart_in_progress() is False

    win._pending_restart = True
    assert win._is_restart_in_progress() is True


def test_mod_update_immediate_restart_emits_signal(qapp, monkeypatch):
    win = _build_lightweight_window(monkeypatch)
    win._mod_baseline = {"123": 1}

    monkeypatch.setattr(win, "_collect_workshop_rows", lambda: [("123", "Test Mod")])
    monkeypatch.setattr(
        win,
        "_fetch_mod_versions",
        lambda _rows: ({"123": 2}, {"123": "Test Mod"}, {"123": {"time_updated": 2}}),
    )
    monkeypatch.setattr(win, "_get_player_count", lambda: 0)

    requested = []
    win.restart_request_signal.connect(requested.append)

    win._run_mod_check()

    assert requested == ["ModUpdate"]


def test_parse_players_count_response_supports_header_format(qapp, monkeypatch):
    win = _build_lightweight_window(monkeypatch)
    response = "Players connected (2):\nAlice\nBob"

    assert win._parse_players_count_response(response) == 2


def test_mod_update_detection_emits_detected_message(qapp, monkeypatch):
    win = _build_lightweight_window(monkeypatch)
    win._mod_baseline = {"123": 1}

    monkeypatch.setattr(win, "_collect_workshop_rows", lambda: [("123", "Test Mod")])
    monkeypatch.setattr(
        win,
        "_fetch_mod_versions",
        lambda _rows: ({"123": 2}, {"123": "Test Mod"}, {"123": {"time_updated": 2}}),
    )
    monkeypatch.setattr(win, "_get_player_count", lambda: 0)

    events = []
    win.output_signal.connect(events.append)

    win._run_mod_check()

    assert any("Detected updated mods: Test Mod" in event for event in events)


def test_stop_server_allows_internal_stop_while_starting(qapp, monkeypatch):
    win = _build_lightweight_window(monkeypatch)
    win.console_tab = SimpleNamespace(
        set_rcon_enabled=lambda _enabled: None,
        terminal_output=SimpleNamespace(append=lambda _text: None),
    )

    class _FakeStdin:
        def __init__(self):
            self.commands = []

        def write(self, text):
            self.commands.append(text)

        def flush(self):
            return None

    fake_stdin = _FakeStdin()
    win.server_process = SimpleNamespace(stdin=fake_stdin)
    win._server_starting = True
    win._server_stopping = False
    monkeypatch.setattr(win, "_is_server_active", lambda: True)

    win.stop_server(intentional=False)

    assert "quit\n" in fake_stdin.commands
    assert win._server_stopping is True


def test_crash_countdown_can_be_cancelled(qapp, monkeypatch):
    win = _build_lightweight_window(monkeypatch)
    win._crash_recovery_pending = True
    win._crash_recovery_remaining = 5
    win._stop_requested_by_user = True
    win._server_starting = False
    win._server_stopping = False
    monkeypatch.setattr(win, "_is_server_active", lambda: False)

    events = []
    win.output_signal.connect(events.append)
    win._tick_crash_recovery_countdown()

    assert win._crash_recovery_pending is False
    assert win._crash_recovery_remaining == 0
    assert any("cancelled" in e.lower() for e in events)


def test_on_ini_selected_same_path_keeps_loaded_markers(monkeypatch):
    win = MainWindow.__new__(MainWindow)
    same_path = os.path.normpath("C:/Server/servertest.ini")
    win._active_ini_path = same_path
    win._loaded_for_ini = {
        "mods": same_path,
        "logs": same_path,
        "ini": same_path,
        "sandbox": same_path,
    }

    win._update_server_name_label = lambda _p: None
    win.stats_tab = SimpleNamespace(set_ini_path=lambda _p: None)
    win.backup_tab = SimpleNamespace(set_ini_path=lambda _p: None)
    win.tab_widget = SimpleNamespace(currentWidget=lambda: None)

    MainWindow._on_ini_selected(win, same_path, load_visible_tab=False)

    assert win._loaded_for_ini["mods"] == same_path
    assert win._loaded_for_ini["logs"] == same_path
    assert win._loaded_for_ini["ini"] == same_path
    assert win._loaded_for_ini["sandbox"] == same_path


def test_on_ini_selected_new_path_invalidates_loaded_markers(monkeypatch):
    win = MainWindow.__new__(MainWindow)
    old_path = os.path.normpath("C:/Server/servertest.ini")
    new_path = os.path.normpath("C:/Server/new_server.ini")
    win._active_ini_path = old_path
    win._loaded_for_ini = {
        "mods": old_path,
        "logs": old_path,
        "ini": old_path,
        "sandbox": old_path,
    }

    win._update_server_name_label = lambda _p: None
    win.stats_tab = SimpleNamespace(set_ini_path=lambda _p: None)
    win.backup_tab = SimpleNamespace(set_ini_path=lambda _p: None)
    win.tab_widget = SimpleNamespace(currentWidget=lambda: None)

    MainWindow._on_ini_selected(win, new_path, load_visible_tab=False)

    assert win._active_ini_path == new_path
    assert win._loaded_for_ini["mods"] is None
    assert win._loaded_for_ini["logs"] is None
    assert win._loaded_for_ini["ini"] is None
    assert win._loaded_for_ini["sandbox"] is None


def test_load_mods_if_needed_skips_when_cached():
    win = MainWindow.__new__(MainWindow)
    ini_path = os.path.normpath("C:/Server/servertest.ini")
    call_count = {"count": 0}

    win._active_ini_path = ini_path
    win._loaded_for_ini = {"mods": ini_path}
    win.mods_tab = SimpleNamespace(load_mods=lambda _p: call_count.__setitem__("count", call_count["count"] + 1))

    MainWindow._load_mods_if_needed(win)
    assert call_count["count"] == 0

    win._loaded_for_ini["mods"] = None
    MainWindow._load_mods_if_needed(win)
    assert call_count["count"] == 1
    assert win._loaded_for_ini["mods"] == ini_path


def test_send_discord_webhook_rejects_non_numeric_message_id(qapp, monkeypatch):
    win = _build_lightweight_window(monkeypatch)
    statuses = []
    thread_started = {"value": False}

    class _FakeThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            thread_started["value"] = True

    monkeypatch.setattr("app.ui.main_window.threading.Thread", _FakeThread)
    win.discord_send_status_signal.connect(statuses.append)

    win._send_discord_webhook("https://discord.com/api/webhooks/1/2", "not-a-number", {"content": "x"})

    assert thread_started["value"] is False
    assert any("digits only" in s for s in statuses)


def test_send_discord_worker_captures_message_id_from_post(qapp, monkeypatch):
    win = _build_lightweight_window(monkeypatch)
    captured_ids = []
    statuses = []

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"id": "987654321"}

    def _fake_request(method, url, headers, json, timeout):
        return _Resp()

    monkeypatch.setattr("app.ui.main_window.requests.request", _fake_request)
    win.discord_message_id_signal.connect(captured_ids.append)
    win.discord_send_status_signal.connect(statuses.append)

    win._discord_repeat_sending = True
    win._send_discord_webhook_worker("https://discord.com/api/webhooks/1/2", "", {"content": "x"})

    assert captured_ids == ["987654321"]
    assert any("Success" in s for s in statuses)
    assert win._discord_repeat_sending is False


def test_send_discord_worker_does_not_fallback_to_post_on_patch_error(qapp, monkeypatch):
    win = _build_lightweight_window(monkeypatch)
    statuses = []
    fallback_called = {"value": False}

    class _Resp:
        status_code = 404
        text = "missing"

    def _fake_request(method, url, headers, json, timeout):
        return _Resp()

    def _fake_post(*args, **kwargs):
        fallback_called["value"] = True
        return _Resp()

    monkeypatch.setattr("app.ui.main_window.requests.request", _fake_request)
    monkeypatch.setattr("app.ui.main_window.requests.post", _fake_post)
    win.discord_send_status_signal.connect(statuses.append)

    win._discord_repeat_sending = True
    win._send_discord_webhook_worker("https://discord.com/api/webhooks/1/2", "123", {"content": "x"})

    assert fallback_called["value"] is False
    assert any("HTTP 404" in s for s in statuses)
    assert win._discord_repeat_sending is False
