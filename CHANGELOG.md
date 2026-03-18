# Changelog

All notable changes to this project will be documented in this file.

## [1.1.0] - 2026-03-18

### Added

- Added a new reusable configuration editor foundation in `app/ui/sandbox_tab.py`.
- Added a dedicated INI editor tab and parser in `app/ui/ini_tab.py`.
- Added shared UI controls in `app/ui/widgets.py` (`CheckMarkBox`, no-wheel combo/spin widgets).
- Added sandbox path preview and quick-open flow from Settings in `app/ui/settings_tab.py`.
- Added startup/preparation overlay with progress messaging in `app/ui/main_window.py`.
- Added regression and parser coverage in:
  - `tests/test_ini_tab.py`
  - `tests/test_main_window_core.py`
  - `tests/test_mods_tab.py`
  - `tests/test_main_helpers.py`
  - `tests/test_settings_tab.py`

### Changed

- Reworked startup and tab loading orchestration in `app/ui/main_window.py` to improve responsiveness and reduce perceived freezes.
- Integrated new tabs into the main window flow in `app/ui/main_window.py`:
  - `INI`
  - `Sandbox`
- Updated dark palette and stylesheet behavior in `app/main.py` for improved visual consistency.
- Updated backup options UI in `app/ui/backup_tab.py` to use shared widgets.
- Expanded ignore patterns in `.gitignore` for packaging/runtime artifacts and private internal workflow files.

### Fixed

- Fixed sandbox editor behavior to handle schema growth from mod-added settings without missing new fields.
- Fixed duplicate/invalid mod ID extraction from markup-heavy workshop descriptions in `app/ui/mods_tab.py`.
- Fixed unnecessary Mods reload after visiting Settings when INI path did not change in `app/ui/main_window.py`.
- Fixed stutter-prone refresh behavior by adding explicit loading overlay during mod refresh operations.
- Hardened workshop metadata fetches in `app/ui/mods_tab.py`:
  - Added network timeout.
  - Added cache reuse.
  - Added targeted refresh support for changed workshop IDs.
- Improved server startup diagnostics for missing dedicated server JAR path in `app/ui/main_window.py`.

### Verification

- Full test suite passing at release time: 32 passed.
- PyInstaller build verified and artifact produced at `dist/Knox Overseer.exe`.
