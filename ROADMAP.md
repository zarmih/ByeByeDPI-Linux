# ROADMAP

This file is the short project-level roadmap. `docs/ROADMAP.md` is the detailed source of truth for scope and safety constraints.

## Completed — v0.3.0 (Desktop Usability)
- [x] Settings Schema v1 (safe export/import).
- [x] Rootless XDG autostart.
- [x] Favorites management and filtering.
- [x] Secure application updates with manual check and verification.
- [x] Validated strategy/test-target update center with preview, backup, apply and rollback.
- [x] Reproducible source-release artifacts, checksums and CI builds.

## Next safe product work
- [ ] Signed release tags and packaged binary artifacts.
- [ ] KDE proxy adapter with the same journal/rollback guarantees as the GNOME adapter.
- [ ] Per-application setup guides and browser launch helpers.
- [ ] Broader distro/Wayland regression testing.

## Deferred / explicitly out of current safe mode
- Transparent TUN/VPN routing.
- Automatic DNS, firewall, nftables, route or NetworkManager changes.
- Unattended application of remote test-target updates. Target updates stay reviewable through the existing preview/apply/rollback flow.

See `docs/ROADMAP.md` for the full rationale and completed foundation.
