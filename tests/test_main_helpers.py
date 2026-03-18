import os
import app.main as app_main


def test_resource_path_dev_mode(monkeypatch):
    monkeypatch.setattr(app_main.sys, "frozen", False, raising=False)
    path = app_main._resource_path("assets", "icons", "icon.png")
    assert path.endswith(os.path.join("assets", "icons", "icon.png"))


def test_resource_path_frozen_mode_uses_meipass(monkeypatch):
    monkeypatch.setattr(app_main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app_main.sys, "_MEIPASS", r"C:\\bundle", raising=False)

    path = app_main._resource_path("assets", "icons", "icon.png")

    assert path == os.path.join(r"C:\\bundle", "assets", "icons", "icon.png")
