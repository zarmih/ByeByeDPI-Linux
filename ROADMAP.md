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
  - [x] Existing annotated version-tag validation and tag-triggered GitHub Release automation.
  - [x] Deterministic source archive + external SHA-256 checksum uploaded as the release candidate.
  - [ ] Cryptographically signed maintainer tags (no signing key is configured on this workstation yet).
  - [ ] Packaged Linux runtime/binary artifact.
- [ ] KDE proxy adapter with the same journal/rollback guarantees as the GNOME adapter.
- [x] Per-application setup guides and browser launch helpers.
  - Firefox manual SOCKS5 + proxy DNS guide.
  - Chromium-family isolated-profile launcher with local-port preflight.
  - curl `socks5h` example for proxy-side DNS resolution.
- [x] Broader distro/Wayland regression testing.
  - [x] CI regression matrix: Ubuntu 22.04 + 24.04 on Python 3.10 + 3.12.
  - [x] Real Qt display smoke under a Weston headless Wayland compositor.

## Deferred / explicitly out of current safe mode
- Transparent TUN/VPN routing.
- Automatic DNS, firewall, nftables, route or NetworkManager changes.
- Unattended application of remote test-target updates. Target updates stay reviewable through the existing preview/apply/rollback flow.

See `docs/ROADMAP.md` for the full rationale and completed foundation.
