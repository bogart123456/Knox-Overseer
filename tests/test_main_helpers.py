import os
import app.main as app_main


def test_resource_path_dev_mode(monkeypatch):
    monkeypatch.setattr(app_main.sys, "frozen", False, raising=False)
    path = app_main._resource_path("assets", "icons", "icon.png")
    assert path.endswith(os.path.join("assets", "icons", "icon.png"))
