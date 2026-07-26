# ByeByeDPI-Linux Roadmap

Based on Android ByeByeDPI scenario, adapted for Linux desktop environment.

## Phase 1: Core UX and Persistence (Current)
- [x] Save user settings (strategy, custom args, window geometry, etc.) using QSettings.
- [x] First-run diagnostics: check `ciadpi` binary, port availability, curl, file permissions, clear errors with copy report button.
- [x] System tray integration (Start/Stop/Check/Open/Quit, proper `ciadpi` termination).

## Phase 2: System Integration (Optional/Safe)
- [ ] Safe user-level GNOME proxy integration via `gsettings` (optional, snapshot previous, state-journal, rollback).
- [ ] Installation prep: desktop file, placeholder icon, `install-user.sh` and `uninstall-user.sh` without root, installing to `~/.local`.
- [ ] Automated tests for persistence, diagnostics, gsettings adapter/rollback with mock-commands.

## Phase 3: Advanced Features
- [ ] Auto-update rules/strategies (simulating Android's update mechanism).
- [ ] Global shortcut or DBus interface for quick toggling.
- [ ] Support for KDE and other desktop environments proxy settings.
- [ ] Statistics and traffic monitoring UI.
