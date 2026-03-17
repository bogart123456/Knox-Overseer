from app.ui.backup_tab import BackupTab


def test_backup_period_mapping(qapp):
    tab = BackupTab()
    tab.interval_combo.setCurrentText("10 minutes")
    assert tab.get_backup_period_minutes() == 10

    tab.interval_combo.setCurrentText("1 hour")
    assert tab.get_backup_period_minutes() == 60


def test_backup_paths_from_ini(qapp):
    tab = BackupTab()
    tab.set_ini_path(r"C:\\Users\\Xander\\Zomboid\\Server\\servertest.ini")

    save_path = tab.get_save_source_path()
    backup_path = tab.get_backup_dir_path()

    save_norm = save_path.replace("\\", "/")
    backup_norm = backup_path.replace("\\", "/")
    assert save_norm.endswith("Zomboid/Saves/Multiplayer/servertest")
    assert backup_norm.endswith("Zomboid/backups")


def test_runtime_lock_disables_controls(qapp):
    tab = BackupTab()
    tab.set_runtime_lock(True)

    assert not tab.interval_combo.isEnabled()
    assert not tab.max_backups_spin.isEnabled()
    assert not tab.backup_on_start_check.isEnabled()
    assert not tab.restore_button.isEnabled()
