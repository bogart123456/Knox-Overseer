from app.ui.settings_tab import SettingsTab


def test_default_server_dir_is_relative(qapp):
    tab = SettingsTab()
    assert tab.server_dir.text() == "."


def test_detection_interval_mapping(qapp):
    tab = SettingsTab()
    tab.mod_detection_rate.setCurrentText("Every 1 minute")
    assert tab.get_mod_detection_interval_ms() == 60_000

    tab.mod_detection_rate.setCurrentText("Every 1 hour")
    assert tab.get_mod_detection_interval_ms() == 3_600_000


def test_runtime_lock_disables_sensitive_fields(qapp):
    tab = SettingsTab()
    tab.set_runtime_lock(True)

    assert not tab.ini_path.isEnabled()
    assert not tab.browse_button.isEnabled()
    assert not tab.server_dir.isEnabled()
    assert not tab.launch_params.isEnabled()


def test_resolve_relative_path(qapp):
    tab = SettingsTab()
    resolved = tab.resolve_path(".")
    assert resolved
