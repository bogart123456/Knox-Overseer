from PySide6.QtWidgets import QLineEdit
from app.ui.mods_tab import ModsTab


class _SettingsStub:
    def __init__(self):
        self.ini_path = QLineEdit()


def test_populate_mods_includes_local_mods(qapp):
    tab = ModsTab(_SettingsStub())
    tab.fetch_mod_details = lambda wid: {
        "title": f"Workshop {wid}",
        "description": "",
        "creator": "",
        "time_updated": 0,
        "mod_ids": [f"wid_{wid}"],
    }

    tab.populate_mods_table(["123"], enabled_mods={"LocalModA"}, mods_list=["LocalModA"])

    ids = [tab.mods_table.item(r, 1).text() for r in range(tab.mods_table.rowCount())]
    assert "wid_123" in ids
    assert "LocalModA" in ids


def test_set_mod_actions_enabled(qapp):
    tab = ModsTab(_SettingsStub())
    tab.set_mod_actions_enabled(False)

    assert not tab.add_mod_button.isEnabled()
    assert not tab.remove_mod_button.isEnabled()
    assert not tab.move_up_button.isEnabled()
    assert not tab.move_down_button.isEnabled()
