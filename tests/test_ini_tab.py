from app.ui.ini_tab import parse_ini
from app.ui.ini_tab import IniTab
from PySide6.QtWidgets import QLabel


def test_parse_ini_preserves_general_and_sections():
    raw = """# top comment
Public=true

[Steam]
; section comment
Port=16261
ServerWelcomeMessage=Hello there
"""

    sections, original_lines = parse_ini(raw)

    assert len(original_lines) == 7
    assert sections[0]["name"] == "General"
    assert sections[0]["fields"][0]["key"] == "Public"
    assert sections[0]["fields"][0]["raw_value"] == "true"
    assert sections[0]["fields"][0]["comments"] == ["top comment"]

    steam_section = next(section for section in sections if section["name"] == "Steam")
    assert [field["key"] for field in steam_section["fields"]] == ["Port", "ServerWelcomeMessage"]
    assert steam_section["fields"][0]["comments"] == ["section comment"]
    assert steam_section["fields"][1]["raw_value"] == "Hello there"


def test_parse_ini_ignores_invalid_lines():
    raw = """NotASetting
Another:Thing
ValidKey = 42
"""

    sections, _ = parse_ini(raw)

    assert [field["key"] for field in sections[0]["fields"]] == ["ValidKey"]


def test_ini_tab_load_rebuilds_when_placeholder_is_showing(tmp_path, qapp):
    ini_path = tmp_path / "servertest.ini"
    ini_path.write_text("Public=true\nPort=16261\n", encoding="utf-8")

    tab = IniTab()

    # Simulate stale state where cache exists but the scroll area still points
    # to the initial placeholder label.
    tab._field_widgets = {
        ("General", "Stale"): {
            "key": "Stale",
            "widget": None,
            "wtype": "raw",
            "line_idx": 0,
            "original_value": "x",
            "editable": True,
            "row": None,
            "section": "General",
            "search_text": "",
        }
    }

    tab._current_path = str(ini_path)
    tab.load()

    assert not isinstance(tab._scroll.widget(), QLabel)
    assert len(tab._field_widgets) == 2