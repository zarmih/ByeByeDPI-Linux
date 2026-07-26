# ByeByeDPI-Linux Roadmap

The goal is functional Linux equivalence for the useful desktop workflow, not a literal copy of Android VPNService.

## Completed foundation

- [x] PySide6 frontend with GTK3/Tkinter fallbacks.
- [x] Local `ciadpi` SOCKS5 lifecycle and proxy checks.
- [x] 60 upstream strategies and 139 targets in 8 groups.
- [x] Matrix testing, ranking, details, Pause/Resume, ETA and JSON/CSV reports.
- [x] Schema v2 history, comparison, validation and privacy redaction.
- [x] Persistent main/library settings, selected targets and configurable timeouts.
- [x] Diagnostics and system tray lifecycle.
- [x] Optional GNOME SOCKS integration with atomic crash-recovery journal.
- [x] Rootless user installer/uninstaller and desktop/icon resources.

## Next safe product work

- [x] GUI update center with preview, pinned source SHA, content diff, backup and rollback.
- [ ] Signed/reproducible release artifacts and CI builds.
- [ ] KDE proxy adapter with the same journal/rollback guarantees.
- [ ] Per-application setup guides and browser launch helpers.
- [ ] Broader distro/Wayland regression testing.

## Explicitly out of scope for the current safe mode

- Transparent TUN/VPN routing.
- Automatic changes to DNS, firewall, nftables, routes or NetworkManager.
- Claims that every application honours GNOME proxy settings.
