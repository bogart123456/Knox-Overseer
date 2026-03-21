from PySide6.QtWidgets import QLineEdit, QTableWidgetItem
from app.ui.mods_tab import ModsTab
from app.ui.mods_tab import MANDATORY_MOD_ID, MANDATORY_WORKSHOP_ID


class _SettingsStub:
    def __init__(self):
        self.ini_path = QLineEdit()


def test_populate_mods_includes_local_mods(qapp):
    tab = ModsTab(_SettingsStub())
    tab.fetch_mod_details = lambda wid, use_cache=True: {
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


def test_load_mods_does_not_auto_refresh(qapp, tmp_path):
    tab = ModsTab(_SettingsStub())
    ini_path = tmp_path / "server.ini"
    ini_path.write_text("WorkshopItems=123\nMods=TestMod\n", encoding="utf-8")

    called = {"populate": 0, "refresh": 0}
    tab.populate_mods_table = lambda workshop_ids, enabled_mods, mods_list: called.__setitem__("populate", called["populate"] + 1)
    tab.refresh_mods = lambda workshop_ids=None: called.__setitem__("refresh", called["refresh"] + 1)

    tab.load_mods(str(ini_path))

    assert called["populate"] == 1
    assert called["refresh"] == 0


def test_fetch_mod_details_parses_and_deduplicates_ids_preserving_order(qapp, monkeypatch):
    tab = ModsTab(_SettingsStub())

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": {
                    "publishedfiledetails": [
                        {
                            "result": 1,
                            "title": "Sample",
                            "description": "Mod ID: [/b][code]Alpha[/code]; Beta; Alpha",
                            "creator": "author",
                            "time_updated": 123,
                        }
                    ]
                }
            }

    monkeypatch.setattr("app.ui.mods_tab.requests.post", lambda *args, **kwargs: _Resp())
    data = tab.fetch_mod_details("999", use_cache=False)

    assert data["mod_ids"] == ["Alpha", "Beta"]


def test_refresh_mods_can_target_specific_workshop_ids(qapp):
    tab = ModsTab(_SettingsStub())
    tab.mods_table.setRowCount(2)
    tab.mod_data_list = [
        {"title": "A", "description": "", "creator": "", "time_updated": 0, "mod_ids": ["A"]},
        {"title": "B", "description": "", "creator": "", "time_updated": 0, "mod_ids": ["B"]},
    ]
    tab.mods_table.setItem(0, 2, QTableWidgetItem("111"))
    tab.mods_table.setItem(1, 2, QTableWidgetItem("222"))

    calls = []
    tab.fetch_mod_details = lambda wid, use_cache=False: calls.append(wid) or {
        "title": wid,
        "description": "",
        "creator": "",
        "time_updated": 0,
        "mod_ids": [wid],
    }

    tab.refresh_mods(workshop_ids={"222"})
    assert calls == ["222"]


def test_save_config_does_not_force_knoxoverseer_on_linux(qapp, tmp_path, monkeypatch):
    tab = ModsTab(_SettingsStub())
    ini_path = tmp_path / "server.ini"
    ini_path.write_text("WorkshopItems=\nMods=\n", encoding="utf-8")
    tab.settings_tab.ini_path.setText(str(ini_path))

    monkeypatch.setattr("app.ui.mods_tab.sys.platform", "linux")

    tab._add_mod_row("LocalOnly", "LocalOnly", "", "Local", {}, True)
    ok = tab.save_config_silent()
    assert ok is True

    content = ini_path.read_text(encoding="utf-8")
    assert MANDATORY_MOD_ID not in content
    assert MANDATORY_WORKSHOP_ID not in content


def test_save_config_forces_knoxoverseer_on_non_linux(qapp, tmp_path, monkeypatch):
    tab = ModsTab(_SettingsStub())
    ini_path = tmp_path / "server.ini"
    ini_path.write_text("WorkshopItems=\nMods=\n", encoding="utf-8")
    tab.settings_tab.ini_path.setText(str(ini_path))

    monkeypatch.setattr("app.ui.mods_tab.sys.platform", "win32")

    tab._add_mod_row("LocalOnly", "LocalOnly", "", "Local", {}, True)
    ok = tab.save_config_silent()
    assert ok is True

    content = ini_path.read_text(encoding="utf-8")
    assert MANDATORY_MOD_ID in content
    assert MANDATORY_WORKSHOP_ID in content
