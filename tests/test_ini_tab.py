from app.ui.ini_tab import parse_ini


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