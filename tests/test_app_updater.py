import pytest
import os
import tempfile
import urllib.request
import urllib.error
import sys
import hashlib
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app_updater import (
    is_newer, _parse_semver, check_for_updates, download_update,
    ReleaseInfo, AppUpdaterError
)
from unittest.mock import patch, MagicMock
from io import BytesIO

def test_parse_semver():
    assert _parse_semver("1.2.3") == (1, 2, 3, None)
    assert _parse_semver("1.2.3-test") == (1, 2, 3, "test")
    assert _parse_semver("0.3.0") == (0, 3, 0, None)

    with pytest.raises(ValueError):
        _parse_semver("invalid")
    with pytest.raises(ValueError):
        _parse_semver("1.2")
    with pytest.raises(ValueError):
        _parse_semver("1.2.3.4")
    with pytest.raises(ValueError):
        _parse_semver("")

def test_is_newer():
    assert is_newer("1.2.3", "1.2.2")
    assert is_newer("0.3.0", "0.2.0")
    assert not is_newer("0.2.0", "0.3.0")
    assert not is_newer("1.0.0", "1.0.0")
    assert not is_newer("invalid", "1.0.0")

    # Prerelease rules
    assert is_newer("1.0.0", "1.0.0-alpha")
    assert is_newer("1.0.0-beta", "1.0.0-alpha")
    assert not is_newer("1.0.0-alpha", "1.0.0")
    assert is_newer("1.0.0-alpha.1", "1.0.0-alpha")

@patch('urllib.request.build_opener')
def test_check_for_updates_newer(mock_build_opener):
    mock_resp = MagicMock()
    data = {
        "tag_name": "v0.4.0",
        "body": "Test release",
        "html_url": "https://github.com/zarmih/ByeByeDPI-Linux/releases/tag/v0.4.0",
        "assets": [
            {
                "name": "ByeByeDPI-Linux-0.4.0.tar.gz",
                "browser_download_url": "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.0.tar.gz"
            },
            {
                "name": "ByeByeDPI-Linux-0.4.0.tar.gz.sha256",
                "browser_download_url": "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.0.tar.gz.sha256"
            }
        ]
    }
    mock_resp.read.return_value = json.dumps(data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    mock_opener = MagicMock()
    mock_opener.open.return_value = mock_resp
    mock_build_opener.return_value = mock_opener

    info = check_for_updates(current_version="0.3.0")
    assert info is not None
    assert info.version == "0.4.0"
    assert info.download_url == "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.0.tar.gz"
    assert info.sha256_url == "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.0.tar.gz.sha256"

@patch('urllib.request.build_opener')
def test_check_for_updates_older(mock_build_opener):
    mock_resp = MagicMock()
    data = {
        "tag_name": "v0.3.0",
        "assets": []
    }
    mock_resp.read.return_value = json.dumps(data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    mock_opener = MagicMock()
    mock_opener.open.return_value = mock_resp
    mock_build_opener.return_value = mock_opener

    info = check_for_updates(current_version="0.3.0")
    assert info is None

@patch('urllib.request.build_opener')
def test_check_for_updates_api_overflow(mock_build_opener):
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"x" * (1024 * 1024 + 1)
    mock_resp.__enter__.return_value = mock_resp
    mock_opener = MagicMock()
    mock_opener.open.return_value = mock_resp
    mock_build_opener.return_value = mock_opener

    with pytest.raises(AppUpdaterError, match="API response too large"):
        check_for_updates(current_version="0.3.0")

def test_download_update_dest_checks():
    release = ReleaseInfo(
        version="0.4.0",
        body="",
        html_url="https://github.com/zarmih/ByeByeDPI-Linux/releases/tag/v0.4.0",
        download_url="https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.0.tar.gz",
        sha256_url="https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.0.tar.gz.sha256",
        asset_name="ByeByeDPI-Linux-0.4.0.tar.gz"
    )
    with pytest.raises(AppUpdaterError, match="Failed to open destination directory:"):
        download_update(release, "/non/existent/dir")

@patch('urllib.request.build_opener')
def test_download_update_success(mock_build_opener):
    dest_dir = tempfile.mkdtemp()

    content = b"test content"
    digest = hashlib.sha256(content).hexdigest()

    mock_sha_resp = MagicMock()
    mock_sha_resp.read.return_value = f"{digest}  ByeByeDPI-Linux-0.4.0.tar.gz\n".encode("utf-8")
    mock_sha_resp.__enter__.return_value = mock_sha_resp

    mock_tar_resp = MagicMock()
    mock_tar_resp.headers = {"Content-Length": str(len(content))}
    mock_tar_resp.read.side_effect = [content, b""]
    mock_tar_resp.__enter__.return_value = mock_tar_resp

    mock_opener = MagicMock()
    mock_opener.open.side_effect = [mock_sha_resp, mock_tar_resp]
    mock_build_opener.return_value = mock_opener

    release = ReleaseInfo(
        version="0.4.0",
        body="",
        html_url="https://github.com/zarmih/ByeByeDPI-Linux/releases/tag/v0.4.0",
        download_url="https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.0.tar.gz",
        sha256_url="https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.0.tar.gz.sha256",
        asset_name="ByeByeDPI-Linux-0.4.0.tar.gz"
    )

    out_path = download_update(release, dest_dir)
    assert os.path.exists(out_path)
    with open(out_path, "rb") as f:
        assert f.read() == content

    mock_tar_resp.read.side_effect = [content, Exception("network error")]
    mock_opener.open.side_effect = [mock_sha_resp, mock_tar_resp]

    import dataclasses
    release = dataclasses.replace(
        release,
        version="0.4.1",
        asset_name="ByeByeDPI-Linux-0.4.1.tar.gz",
        download_url="https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.1/ByeByeDPI-Linux-0.4.1.tar.gz",
        sha256_url="https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.1/ByeByeDPI-Linux-0.4.1.tar.gz.sha256"
    )

    mock_sha_resp.read.return_value = f"{digest}  ByeByeDPI-Linux-0.4.1.tar.gz\n".encode("utf-8")

    with pytest.raises(AppUpdaterError):
        download_update(release, dest_dir)

    assert not os.path.exists(os.path.join(dest_dir, release.asset_name))
