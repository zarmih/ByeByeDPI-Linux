# Changelog

All notable user-facing changes are documented here.

## [Unreleased]

## 0.3.0 — 2026-07-29

### Added
- Favorites toggle in Strategy Library and main window for quick access to best strategies.
- "Select Best Favorite" button to pick the top-performing favorite strategy.
- Settings Schema v1: full safe export and import of user settings with validation, preview, and rollback.
- Rootless XDG autostart management (Start at login) via the settings menu.

### Fixed
- ProcessManager lifecycle: proper thread join, stdout pipe closure and idempotent stop preventing ResourceWarning and zombie file descriptors.
- Favorites loading from QSettings now handles None, bare strings, non-list types and stale strategy IDs without crashing.
- Release builder correctly ignores nested untracked directories (e.g. vendor submodules not on the current branch).
- App Updater rewritten for strict SemVer parsing, secure downloads, explicit confirmations, and strict GitHub API validation.
- Trailing whitespace cleanup across all modified source files.

## 0.2.0 — 2026-07-26

### Added

- PySide6 desktop client with safe `ciadpi` lifecycle and system-tray controls.
- Official strategy library: 60 Android strategies and 139 targets in 8 groups.
- Matrix testing, ranking, target details, filters, Pause/Resume, ETA and best-strategy selection.
- Versioned JSON result bundles, CSV export, local history and comparison of runs.
- Optional GNOME SOCKS proxy integration with an atomic crash-recovery journal.
- Persistent strategy/target selections and configurable connection/total timeouts.
- Rootless user installer/uninstaller, desktop entry, original icon and diagnostics report.
- Validated Update Center with pinned upstream SHA, content preview/diff, backups and rollback.
- Deterministic source-release builder with embedded ByeDPI submodule sources and SHA256 manifest.
- GitHub Actions test matrix for Python 3.10 and 3.12.

### Security

- No root, DNS, route, firewall, nftables or NetworkManager changes.
- Imported bundles and upstream update files are size-limited and schema-validated.
- GNOME recovery, history and update backups use one deterministic XDG data root.
- Secret fields, URL credentials, sensitive query parameters and local paths are redacted from reports.

### Known limitations

- GNOME system proxy is not a transparent VPN/TUN and can be ignored by individual applications.
- Effectiveness of a strategy depends on the provider, network and current filtering behaviour.
- Release artifacts are source archives; `ciadpi` is compiled locally by the installer.
