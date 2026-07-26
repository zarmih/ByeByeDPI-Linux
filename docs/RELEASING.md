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

`.github/workflows/ci.yml` builds `ciadpi`, runs tests and Qt offscreen smoke checks on Python 3.10 and 3.12, then creates the deterministic source archive and uploads it as a workflow artifact. A maintainer should publish a GitHub release only after that workflow succeeds and the checksum is independently verified.
