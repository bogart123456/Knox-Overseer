from app.ui.console_tab import ConsoleTab


def test_send_input_emits_and_clears(qapp):
    tab = ConsoleTab()
    captured = []
    tab.input_sent.connect(captured.append)

    tab.input_line.setText("save")
    tab.send_input()

    assert captured == ["save"]
    assert tab.input_line.text() == ""


def test_send_rcon_emits_and_clears(qapp):
    tab = ConsoleTab()
    captured = []
    tab.rcon_command.connect(captured.append)

    tab.rcon_input.setText("players")
    tab.send_rcon()

    assert captured == ["players"]
    assert tab.rcon_input.text() == ""
