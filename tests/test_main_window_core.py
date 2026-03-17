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
