import os
import sys
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings


ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
APP_DIR = os.path.join(ROOT_DIR, "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def isolated_qsettings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    settings = QSettings("KnoxOverseer", "Knox Overseer")
    settings.clear()
    settings.sync()
    yield
    settings = QSettings("KnoxOverseer", "Knox Overseer")
    settings.clear()
    settings.sync()
