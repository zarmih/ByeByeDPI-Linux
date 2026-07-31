import pytest
import os
import tempfile
import urllib.request
import urllib.error
from unittest.mock import patch, MagicMock

from app_updater import (
    validate_api_url, validate_release_page_url, validate_asset_url,
    validate_release_info, SafeRedirectHandler, AppUpdaterError, ReleaseInfo,
    check_for_updates, download_update
)
from app_update_dialog import AppUpdateDialog, CheckUpdateThread, DownloadUpdateThread

def test_validate_api_url():
    valid = "https://api.github.com/repos/zarmih/ByeByeDPI-Linux/releases/latest"
    assert validate_api_url(valid) == valid

    with pytest.raises(AppUpdaterError):
        validate_api_url("https://api.github.com/repos/attacker/ByeByeDPI-Linux/releases/latest")

def test_validate_release_page_url():
    valid_tag = "https://github.com/zarmih/ByeByeDPI-Linux/releases/tag/v1.0.0"
    valid_latest = "https://github.com/zarmih/ByeByeDPI-Linux/releases/latest"

    assert validate_release_page_url(valid_tag, "v1.0.0") == valid_tag
    assert validate_release_page_url(valid_latest, "v1.0.0") == valid_latest

    invalid_urls = [
        "http://github.com/zarmih/ByeByeDPI-Linux/releases/tag/v1.0.0",
        "https://user:pass@github.com/zarmih/ByeByeDPI-Linux/releases/tag/v1.0.0",
        "https://github.com:8443/zarmih/ByeByeDPI-Linux/releases/tag/v1.0.0",
        "https://github.com/zarmih/ByeByeDPI-Linux/releases/tag/v1.0.0?query=1",
        "https://github.com/zarmih/ByeByeDPI-Linux/releases/tag/v1.0.0#fragment",
        "https://github.com/attacker/ByeByeDPI-Linux/releases/tag/v1.0.0",
        "https://github.com/zarmih/ByeByeDPI-Linux/releases/tag/v2.0.0",
        "https://evilhack.com/zarmih/ByeByeDPI-Linux/releases/tag/v1.0.0",
        "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v1.0.0/asset.tar.gz"
    ]
    for url in invalid_urls:
        with pytest.raises(AppUpdaterError):
            validate_release_page_url(url, "v1.0.0")

def test_validate_asset_url():
    valid = "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v1.0.0/ByeByeDPI-Linux-1.0.0.tar.gz"
    assert validate_asset_url(valid, "v1.0.0", "ByeByeDPI-Linux-1.0.0.tar.gz") == valid

    invalid_urls = [
        "http://github.com/zarmih/ByeByeDPI-Linux/releases/download/v1.0.0/ByeByeDPI-Linux-1.0.0.tar.gz",
        "https://user:pass@github.com/zarmih/ByeByeDPI-Linux/releases/download/v1.0.0/ByeByeDPI-Linux-1.0.0.tar.gz",
        "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v1.0.0/ByeByeDPI-Linux-1.0.0.tar.gz?token=abc",
        "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v2.0.0/ByeByeDPI-Linux-1.0.0.tar.gz",
        "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v1.0.0/ByeByeDPI-Linux-2.0.0.tar.gz",
        "https://github.com/attacker/ByeByeDPI-Linux/releases/download/v1.0.0/ByeByeDPI-Linux-1.0.0.tar.gz",
        "https://github.com.attacker.com/zarmih/ByeByeDPI-Linux/releases/download/v1.0.0/ByeByeDPI-Linux-1.0.0.tar.gz"
    ]
    for url in invalid_urls:
        with pytest.raises(AppUpdaterError):
            validate_asset_url(url, "v1.0.0", "ByeByeDPI-Linux-1.0.0.tar.gz")

def test_safe_redirect_handler():
    handler = SafeRedirectHandler()
    valid_redirects = [
        "https://objects.githubusercontent.com/foo",
        "https://github-releases.githubusercontent.com/foo",
        "https://release-assets.githubusercontent.com/foo"
    ]

    for url in valid_redirects:
        # Mocking super().redirect_request would require patching, just test it doesn't raise our specific URLError
        with patch("urllib.request.HTTPRedirectHandler.redirect_request") as mock_super:
            handler.redirect_request(None, None, 302, "Found", None, url)
            mock_super.assert_called()

    invalid_redirects = [
        "http://objects.githubusercontent.com/foo",
        "https://attacker.com/foo",
        "https://github.com.attacker.com/foo",
        "https://user:pass@objects.githubusercontent.com/foo",
        "https://objects.githubusercontent.com/foo#frag",
        "https://objects.githubusercontent.com:8443/foo",
        "https://github.com/foo",
        "https://api.github.com/foo"
    ]
    for url in invalid_redirects:
        with pytest.raises(urllib.error.URLError):
            handler.redirect_request(None, None, 302, "Found", None, url)

class MockEvent:
    def __init__(self):
        self.accepted = False
        self.ignored = False
    def accept(self):
        self.accepted = True
        self.ignored = False
    def ignore(self):
        self.ignored = True
        self.accepted = False

class FakeCheckThread:
    def __init__(self):
        self._is_running = True
        self.result = MagicMock()
        self.error = MagicMock()
        self.finished = MagicMock()
    def start(self):
        pass
    def isRunning(self):
        return self._is_running
    def finish_mock(self):
        self._is_running = False
        self.finished.emit()
    def deleteLater(self):
        pass

def test_dialog_smoke_lifecycle(monkeypatch):
    import app_update_dialog
    monkeypatch.setattr(app_update_dialog, "CheckUpdateThread", FakeCheckThread)
    from PySide6.QtWidgets import QApplication
    if not QApplication.instance():
        app = QApplication([])
    else:
        app = QApplication.instance()

    dialog = AppUpdateDialog()
    assert dialog.checker is not None
    assert dialog.checker.isRunning()

    # Simulate closing while running
    event = MockEvent()
    dialog.closeEvent(event)
    assert event.ignored
    assert not event.accepted

    # Finish the thread gracefully
    dialog.checker.finish_mock()
    dialog.on_checker_finished()
    assert dialog.checker is None

    # Now close should be accepted
    event2 = MockEvent()
    dialog.closeEvent(event2)
    assert event2.accepted
    assert not event2.ignored

import dataclasses

def test_checksum_blank_line():
    release = ReleaseInfo("0.4.0", "", "https://github.com/zarmih/ByeByeDPI-Linux/releases/tag/v0.4.0", "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.0.tar.gz", "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.0.tar.gz.sha256", "ByeByeDPI-Linux-0.4.0.tar.gz")
    dest_dir = tempfile.mkdtemp()

    with patch('urllib.request.build_opener') as mock_build_opener:
        mock_sha_resp = MagicMock()
        mock_sha_resp.read.return_value = b"d000000000000000000000000000000000000000000000000000000000000000  ByeByeDPI-Linux-0.4.0.tar.gz\n\n"
        mock_sha_resp.__enter__.return_value = mock_sha_resp

        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_sha_resp
        mock_build_opener.return_value = mock_opener

        with pytest.raises(AppUpdaterError, match="Invalid checksum file format"):
            download_update(release, dest_dir)

def test_frozen_dataclass_mutation():
    release = ReleaseInfo("0.4.0", "", "https://a", "https://b", "https://c", "ByeByeDPI-Linux-0.4.0.tar.gz")
    with pytest.raises(dataclasses.FrozenInstanceError):
        release.version = "0.5.0"

def test_release_info_inconsistent_asset():
    release = ReleaseInfo("0.4.0", "", "https://github.com/zarmih/ByeByeDPI-Linux/releases/tag/v0.4.0", "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.1.tar.gz", "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.1.tar.gz.sha256", "ByeByeDPI-Linux-0.4.1.tar.gz")
    with pytest.raises(AppUpdaterError, match="Invalid asset name format"):
        validate_release_info(release)

def test_stale_random_temp_does_not_block():
    release = ReleaseInfo("0.4.0", "", "https://github.com/zarmih/ByeByeDPI-Linux/releases/tag/v0.4.0", "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.0.tar.gz", "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.0.tar.gz.sha256", "ByeByeDPI-Linux-0.4.0.tar.gz")
    dest_dir = tempfile.mkdtemp()

    with patch('secrets.token_hex', side_effect=["abcd", "efgh"]):
        with open(os.path.join(dest_dir, ".dl-abcd.tmp"), "w") as f:
            f.write("stale")

        content = b"test"
        import hashlib
        digest = hashlib.sha256(content).hexdigest()

        with patch('urllib.request.build_opener') as mock_build_opener:
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

            download_update(release, dest_dir)

            assert os.path.exists(os.path.join(dest_dir, "ByeByeDPI-Linux-0.4.0.tar.gz"))
            assert os.path.exists(os.path.join(dest_dir, ".dl-abcd.tmp"))
            assert not os.path.exists(os.path.join(dest_dir, ".dl-efgh.tmp"))

def test_race_target_appearing():
    release = ReleaseInfo("0.4.0", "", "https://github.com/zarmih/ByeByeDPI-Linux/releases/tag/v0.4.0", "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.0.tar.gz", "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.0.tar.gz.sha256", "ByeByeDPI-Linux-0.4.0.tar.gz")
    dest_dir = tempfile.mkdtemp()

    content = b"test"
    import hashlib
    digest = hashlib.sha256(content).hexdigest()

    def side_effect_read(*args, **kwargs):
        # Create target here to simulate race
        with open(os.path.join(dest_dir, release.asset_name), "w") as f:
            f.write("race")
        return b""

    with patch('urllib.request.build_opener') as mock_build_opener:
        mock_sha_resp = MagicMock()
        mock_sha_resp.read.return_value = f"{digest}  ByeByeDPI-Linux-0.4.0.tar.gz\n".encode("utf-8")
        mock_sha_resp.__enter__.return_value = mock_sha_resp

        mock_tar_resp = MagicMock()
        mock_tar_resp.headers = {"Content-Length": str(len(content))}
        # Need something that acts as a bound method or lambda
        mock_tar_resp.read.side_effect = [content, side_effect_read()]
        mock_tar_resp.__enter__.return_value = mock_tar_resp

        mock_opener = MagicMock()
        mock_opener.open.side_effect = [mock_sha_resp, mock_tar_resp]
        mock_build_opener.return_value = mock_opener

        with pytest.raises(AppUpdaterError, match="Target file already exists"):
            download_update(release, dest_dir)

        with open(os.path.join(dest_dir, release.asset_name), "r") as f:
            assert f.read() == "race"

        temps = [f for f in os.listdir(dest_dir) if f.endswith(".tmp")]
        assert len(temps) == 0

def test_partial_chunk_write():
    release = ReleaseInfo("0.4.0", "", "https://github.com/zarmih/ByeByeDPI-Linux/releases/tag/v0.4.0", "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.0.tar.gz", "https://github.com/zarmih/ByeByeDPI-Linux/releases/download/v0.4.0/ByeByeDPI-Linux-0.4.0.tar.gz.sha256", "ByeByeDPI-Linux-0.4.0.tar.gz")
    dest_dir = tempfile.mkdtemp()

    content_chunks = [b"chunk1", b"chunk2", b"chunk3"]
    import hashlib
    digest = hashlib.sha256(b"".join(content_chunks)).hexdigest()

    with patch('urllib.request.build_opener') as mock_build_opener:
        mock_sha_resp = MagicMock()
        mock_sha_resp.read.return_value = f"{digest}  ByeByeDPI-Linux-0.4.0.tar.gz\n".encode("utf-8")
        mock_sha_resp.__enter__.return_value = mock_sha_resp

        mock_tar_resp = MagicMock()
        mock_tar_resp.headers = {"Content-Length": str(sum(len(c) for c in content_chunks))}
        mock_tar_resp.read.side_effect = content_chunks + [b""]
        mock_tar_resp.__enter__.return_value = mock_tar_resp

        mock_opener = MagicMock()
        mock_opener.open.side_effect = [mock_sha_resp, mock_tar_resp]
        mock_build_opener.return_value = mock_opener

        out_path = download_update(release, dest_dir)
        with open(out_path, "rb") as f:
            assert f.read() == b"chunk1chunk2chunk3"
