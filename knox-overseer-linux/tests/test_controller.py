from app.config import ServerConfig, default_config_for_platform
from app.controller import LinuxServerController


def test_build_command_parses_linux_command():
    cfg = ServerConfig(start_command="bash start-server.sh -servername pz42")
    ctl = LinuxServerController(cfg)
    assert ctl.build_command() == ["bash", "start-server.sh", "-servername", "pz42"]


def test_build_command_rejects_empty():
    cfg = ServerConfig(start_command="  ")
    ctl = LinuxServerController(cfg)

    try:
        ctl.build_command()
        assert False, "expected ValueError"
    except ValueError:
        assert True


def test_platform_defaults_linux():
    cfg = default_config_for_platform("Linux")
    assert cfg.server_dir == "/opt/pzserver"
    assert cfg.start_command.startswith("bash start-server.sh")


def test_platform_defaults_windows():
    cfg = default_config_for_platform("Windows")
    assert "Project Zomboid Dedicated Server" in cfg.server_dir
    assert cfg.start_command == "StartServer64.bat"
    assert cfg.control_fifo == ""
