# Knox Overseer (Cross-Platform)

Cross-platform Project Zomboid dedicated server manager with a desktop UI.

## What this project does

- Starts a Project Zomboid dedicated server with platform-specific defaults.
- Streams live server logs into the app UI.
- Sends admin commands through FIFO (Linux systemd socket flow) or process stdin.
- Supports graceful stop (`save` then `quit`) and force stop.

## Why this is a new project

This folder is intentionally separate from the existing project. It focuses on clean process control and platform-aware defaults.

## Requirements

- Linux or Windows host
- Python 3.10+
- Project Zomboid dedicated server installed (example: `/opt/pzserver`)
- Optional FIFO control socket (example: `/opt/pzserver/zomboid.control`) when using a Linux systemd socket setup

## Install

```bash
cd knox-overseer-linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python -m app.main
```

## Recommended settings in the UI

Linux defaults:

- Server Directory: `/opt/pzserver`
- Start Command: `bash start-server.sh -servername servertest`
- Control FIFO: `/opt/pzserver/zomboid.control`

Windows defaults:

- Server Directory: `C:\Program Files (x86)\Steam\steamapps\common\Project Zomboid Dedicated Server`
- Start Command: `StartServer64.bat`
- Control FIFO: empty (commands are sent through process stdin)

If you do not use the systemd FIFO method, clear Control FIFO and use force stop as needed.

## Notes from official dedicated-server docs

- Linux start command pattern: `bash start-server.sh` with optional `-servername` and `-nosteam`.
- Default config/save paths are under `~/Zomboid`.
- Typical required public ports: `16261/udp` and `16262/udp`.

## Development

Run tests:

```bash
pytest -q
```
