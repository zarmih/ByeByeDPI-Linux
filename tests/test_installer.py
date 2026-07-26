import os
import subprocess
from pathlib import Path

def setup_mocks(bin_dir, tmp_path):
    uv_mock = bin_dir / "uv"
    uv_mock.write_text("#!/bin/sh\necho \"UV CALLED\" > \"$MOCK_OUTPUT_DIR/uv_called.txt\"\nexit 0\n")
    uv_mock.chmod(0o755)

    python_mock = bin_dir / "python3"
    python_mock.write_text("""#!/bin/sh
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
    mkdir -p "$3/bin"
    cp "$0" "$3/bin/python"
    exit 0
fi
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
    echo "PIP CALLED" > "$MOCK_OUTPUT_DIR/pip_called.txt"
fi
exit 0
""")
    python_mock.chmod(0o755)

    make_mock = bin_dir / "make"
    make_mock.write_text("#!/bin/sh\nexit 0\n")
    make_mock.chmod(0o755)

def test_installer_uses_uv_when_available(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    setup_mocks(bin_dir, tmp_path)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["MOCK_OUTPUT_DIR"] = str(tmp_path)
    prefix = tmp_path / "prefix"

    result = subprocess.run(
        ["bash", "scripts/install-user.sh", "--prefix", str(prefix)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "uv_called.txt").exists()
    assert not (tmp_path / "pip_called.txt").exists()

def test_installer_falls_back_to_pip(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    setup_mocks(bin_dir, tmp_path)
    (bin_dir / "uv").unlink()

    env = os.environ.copy()
    paths = env["PATH"].split(":")
    paths = [p for p in paths if not (Path(p) / "uv").exists()]
    env["PATH"] = f"{bin_dir}:{':'.join(paths)}"
    env["MOCK_OUTPUT_DIR"] = str(tmp_path)
    prefix = tmp_path / "prefix"
    
    result = subprocess.run(
        ["bash", "scripts/install-user.sh", "--prefix", str(prefix)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "uv_called.txt").exists()
    assert (tmp_path / "pip_called.txt").exists()
