# Releasing ByeByeDPI-Linux

## Preconditions

- The main repository and `vendor/byedpi` submodule must be clean.
- The submodule must be initialized.
- Tests, compileall and all offscreen smoke tests must pass.
- `src/version.py` and `pyproject.toml` must contain the same semantic version.

## Build a source archive

```bash
scripts/build-release.sh --output-dir dist
```

The builder uses the latest Git commit timestamp as `SOURCE_DATE_EPOCH`, copies only Git-tracked project/submodule sources, normalizes ownership, permissions and timestamps, and emits:

```text
ByeByeDPI-Linux-VERSION.tar.gz
ByeByeDPI-Linux-VERSION.tar.gz.sha256
```

The archive contains `RELEASE-METADATA.json`, an internal `SHA256SUMS`, GPL-3.0 project terms, third-party notices and the MIT-licensed ByeDPI source. It intentionally excludes the locally built `vendor/byedpi/ciadpi` binary; the rootless installer builds that executable on the target machine. The installer automatically accelerates dependency installation using `uv` if present in the system, with a seamless fallback to standard `pip`.

For a controlled reproducibility check:

```bash
scripts/build-release.sh \
  --version 0.2.0 \
  --source-date-epoch 1700000000 \
  --output-dir /tmp/release-a
```

A dirty working tree is rejected. `--allow-dirty` exists only for local development tests and marks the archive metadata accordingly.

## Verify

```bash
sha256sum -c dist/ByeByeDPI-Linux-0.2.0.tar.gz.sha256
mkdir -p /tmp/byebyedpi-release
tar -xzf dist/ByeByeDPI-Linux-0.2.0.tar.gz -C /tmp/byebyedpi-release
cd /tmp/byebyedpi-release/ByeByeDPI-Linux-0.2.0
sha256sum -c SHA256SUMS
./scripts/install-user.sh --dry-run
```

## CI

`.github/workflows/ci.yml` builds `ciadpi`, runs the test suite on Ubuntu 22.04 and 24.04 with Python 3.10 and 3.12, runs Qt offscreen smoke checks, and performs a real Qt display smoke under a Weston headless Wayland compositor. It then creates the deterministic source archive and uploads it as a workflow artifact.

## Automated tag release workflow

`.github/workflows/release.yml` validates an existing annotated `vX.Y.Z` tag, checks that the tag matches both `pyproject.toml` and `src/version.py`, builds the deterministic source archive, verifies its external SHA-256 file and uploads the result as a release candidate.

A push of a future version tag publishes the validated assets with GitHub CLI using `--verify-tag`; the workflow refuses to overwrite an existing release. The workflow can also be run manually with `publish=false` to perform a safe release-candidate dry run without creating or modifying a GitHub Release.

The release workflow only detects whether an annotated tag contains a PGP/SSH signature block; it does **not** claim cryptographic trust by itself. Maintainer tag signing remains a separate prerequisite until a real signing key and trust policy are configured.

Recommended future tag flow after signing is configured:

```bash
git tag -s vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```
