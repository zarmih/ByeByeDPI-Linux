import urllib.request
import urllib.parse
import urllib.error
import json
import re
import hashlib
import hmac
import os
import tempfile
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
from version import __version__

API_URL = "https://api.github.com/repos/zarmih/ByeByeDPI-Linux/releases/latest"
MAX_API_BYTES = 1024 * 1024
MAX_ASSET_BYTES = 10 * 1024 * 1024

@dataclass
class ReleaseInfo:
    version: str
    body: str
    html_url: str
    download_url: str
    sha256_url: str
    asset_name: str

class AppUpdaterError(Exception):
    pass

SEMVER_REGEX = re.compile(
    r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][a-zA-Z0-9-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][a-zA-Z0-9-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)

def _parse_semver(v: str):
    m = SEMVER_REGEX.match(v)
    if not m:
        raise ValueError(f"Invalid semver: {v}")
    major, minor, patch, prerelease, build = m.groups()
    return int(major), int(minor), int(patch), prerelease

def _compare_prerelease(p1: Optional[str], p2: Optional[str]) -> int:
    if p1 == p2:
        return 0
    if p1 is None:
        return 1
    if p2 is None:
        return -1
    parts1 = p1.split('.')
    parts2 = p2.split('.')
    for a, b in zip(parts1, parts2):
        if a == b: continue
        a_is_num = a.isdigit()
        b_is_num = b.isdigit()
        if a_is_num and not b_is_num: return -1
        if not a_is_num and b_is_num: return 1
        if a_is_num and b_is_num:
            return 1 if int(a) > int(b) else -1
        return 1 if a > b else -1
    return 1 if len(parts1) > len(parts2) else -1

def is_newer(latest: str, current: str) -> bool:
    try:
        l_maj, l_min, l_pat, l_pre = _parse_semver(latest)
        c_maj, c_min, c_pat, c_pre = _parse_semver(current)
    except ValueError:
        return False
    if (l_maj, l_min, l_pat) > (c_maj, c_min, c_pat): return True
    if (l_maj, l_min, l_pat) < (c_maj, c_min, c_pat): return False
    return _compare_prerelease(l_pre, c_pre) > 0

def safe_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise AppUpdaterError(f"Invalid scheme in url: {url}")
    if parsed.username or parsed.password:
        raise AppUpdaterError("User info not allowed in url")
    if parsed.fragment:
        raise AppUpdaterError("Fragment not allowed in url")
    if parsed.port not in (None, 443):
        raise AppUpdaterError("Non-standard port not allowed in url")
    netloc = parsed.hostname.lower() if parsed.hostname else ""
    if netloc not in ("github.com", "api.github.com", "objects.githubusercontent.com", "github-releases.githubusercontent.com"):
        raise AppUpdaterError(f"Untrusted host in url: {url}")
    return url

class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            safe_url(newurl)
        except AppUpdaterError as e:
            raise urllib.error.URLError(str(e))
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def check_for_updates(api_url: str = API_URL, current_version: str = __version__) -> Optional[ReleaseInfo]:
    req = urllib.request.Request(safe_url(api_url), headers={"User-Agent": "ByeByeDPI-Linux-Updater/1.0", "Accept": "application/vnd.github.v3+json"})
    opener = urllib.request.build_opener(SafeRedirectHandler())
    try:
        with opener.open(req, timeout=10) as resp:
            content = resp.read(MAX_API_BYTES + 1)
            if len(content) > MAX_API_BYTES:
                raise AppUpdaterError("API response too large")
            data = json.loads(content.decode("utf-8"))
    except Exception as e:
        raise AppUpdaterError(f"Failed to check updates: {e}")

    if not isinstance(data, dict):
        raise AppUpdaterError("Invalid JSON structure")

    tag_name = data.get("tag_name")
    if not isinstance(tag_name, str) or not tag_name:
        return None

    if not is_newer(tag_name, current_version):
        return None
    version_clean = tag_name.lstrip('v')

    assets = data.get("assets")
    if not isinstance(assets, list):
        raise AppUpdaterError("Invalid assets structure")

    expected_tar = f"ByeByeDPI-Linux-{version_clean}.tar.gz"
    expected_sha = f"{expected_tar}.sha256"

    tar_url = None
    sha256_url = None
    for asset in assets:
        if not isinstance(asset, dict): continue
        name = asset.get("name")
        if name == expected_tar:
            if tar_url: raise AppUpdaterError("Duplicate tar asset")
            tar_url = asset.get("browser_download_url")
        elif name == expected_sha:
            if sha256_url: raise AppUpdaterError("Duplicate sha256 asset")
            sha256_url = asset.get("browser_download_url")

    if not tar_url or not isinstance(tar_url, str) or not sha256_url or not isinstance(sha256_url, str):
        raise AppUpdaterError("Release assets missing or invalid")

    body = data.get("body", "")
    if not isinstance(body, str):
        body = ""
    if len(body) > 4096:
        body = body[:4093] + "..."

    html_url = data.get("html_url")
    if not isinstance(html_url, str):
        html_url = "https://github.com/zarmih/ByeByeDPI-Linux/releases/latest"

    return ReleaseInfo(
        version=version_clean,
        body=body,
        html_url=safe_url(html_url),
        download_url=safe_url(tar_url),
        sha256_url=safe_url(sha256_url),
        asset_name=expected_tar
    )

def download_update(release: ReleaseInfo, dest_dir: str) -> str:
    dest_path = Path(dest_dir).resolve()
    if not dest_path.is_dir() or dest_path.is_symlink():
        raise AppUpdaterError("Destination must be a real directory")
    if not os.access(dest_path, os.W_OK):
        raise AppUpdaterError("Destination directory is not writable")

    opener = urllib.request.build_opener(SafeRedirectHandler())

    req_sha = urllib.request.Request(release.sha256_url, headers={"User-Agent": "ByeByeDPI-Linux-Updater/1.0"})
    try:
        with opener.open(req_sha, timeout=10) as resp:
            sha_content = resp.read(1024).decode("utf-8")
    except Exception as e:
        raise AppUpdaterError(f"Failed to fetch checksum: {e}")

    sha_lines = [line.strip() for line in sha_content.splitlines() if line.strip()]
    if len(sha_lines) != 1:
        raise AppUpdaterError("Checksum file must contain exactly one line")

    parts = sha_lines[0].split()
    if len(parts) < 2:
        raise AppUpdaterError("Invalid checksum file format")

    expected_sha = parts[0]
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha):
        raise AppUpdaterError("Invalid checksum format")

    if parts[1] != release.asset_name and not parts[1].endswith("/" + release.asset_name):
        raise AppUpdaterError("Checksum filename mismatch")

    req_tar = urllib.request.Request(release.download_url, headers={"User-Agent": "ByeByeDPI-Linux-Updater/1.0"})
    out_path = dest_path / release.asset_name

    if out_path.is_symlink() or out_path.exists():
        raise AppUpdaterError("Target file already exists")

    fd, temp_path = tempfile.mkstemp(dir=dest_path, prefix="dl-", suffix=".tmp")
    try:
        os.chmod(temp_path, 0o600)
        hasher = hashlib.sha256()
        downloaded = 0
        with opener.open(req_tar, timeout=30) as resp:
            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_ASSET_BYTES:
                raise AppUpdaterError("Asset too large based on Content-Length")

            with os.fdopen(fd, "wb") as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > MAX_ASSET_BYTES:
                        raise AppUpdaterError("File too large")
                    hasher.update(chunk)
                    f.write(chunk)
                f.flush()
                os.fsync(f.fileno())

        if not hmac.compare_digest(hasher.hexdigest().lower(), expected_sha.lower()):
            raise AppUpdaterError("Checksum verification failed")

        os.replace(temp_path, out_path)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise AppUpdaterError(f"Download failed: {e}")

    return str(out_path)
