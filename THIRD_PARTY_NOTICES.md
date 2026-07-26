# Third-party notices

ByeByeDPI-Linux contains or redistributes material from the following projects.

## ByeByeDPI Android data

- Project: `romanvht/ByeByeDPI`
- Material used: strategy and proxy-test target lists under `app/src/main/assets`
- Local generated files: `data/strategies.json`, `data/test_targets.json`
- License: GNU General Public License version 3
- Pinned source revision is recorded inside the generated JSON metadata and in exported test result bundles.

The repository root `LICENSE` contains the GPL version 3 text used for ByeByeDPI-Linux (GPL-3.0-only) and this derived data.

## ByeDPI / ciadpi

- Project: `hufrea/byedpi`
- Location: `vendor/byedpi` Git submodule
- Use: the `ciadpi` local SOCKS5 executable is built from this source
- License: MIT

The upstream MIT license is preserved at `vendor/byedpi/LICENSE` and must remain in source and binary distributions.

## PySide6 / Qt for Python

PySide6 is installed as a runtime dependency and is not copied into this source repository. Qt for Python is distributed by its copyright holders under its published open-source and commercial licensing terms. Installers download it from the configured Python package index unless an offline package source is supplied.

## No endorsement

ByeByeDPI-Linux is an independent, unofficial project. The names of upstream projects and contributors are used only for attribution and compatibility information; they do not imply endorsement.
