import urllib.request
import urllib.parse
import urllib.error
import json
import re
import hashlib
import hmac
import os
import tempfile
import stat
import secrets
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
from version import __version__

API_URL = "https://api.github.com/repos/zarmih/ByeByeDPI-Linux/releases/latest"
MAX_API_BYTES = 1024 * 1024
MAX_ASSET_BYTES = 10 * 1024 * 1024
MAX_CHECKSUM_BYTES = 256

@dataclass(frozen=True)
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
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
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

def validate_api_url(url: str) -> str:
    if url != API_URL:
        raise AppUpdaterError(f"Untrusted API URL: {url}")
    return url

def validate_release_page_url(url: str, tag: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise AppUpdaterError("Invalid scheme")
    if parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise AppUpdaterError("Invalid url components")
    if parsed.port not in (None, 443):
        raise AppUpdaterError("Invalid port")
    if parsed.hostname != "github.com":
        raise AppUpdaterError("Untrusted host")

    expected_path_1 = f"/zarmih/ByeByeDPI-Linux/releases/tag/{tag}"
    expected_path_2 = "/zarmih/ByeByeDPI-Linux/releases/latest"
    decoded_path = urllib.parse.unquote(parsed.path)
    if decoded_path not in (expected_path_1, expected_path_2):
        raise AppUpdaterError(f"Untrusted release page path: {decoded_path}")
    return url

def validate_asset_url(url: str, tag: str, asset_name: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise AppUpdaterError("Invalid scheme")
    if parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise AppUpdaterError("Invalid url components")
    if parsed.port not in (None, 443):
        raise AppUpdaterError("Invalid port")
    if parsed.hostname != "github.com":
        raise AppUpdaterError("Untrusted host")

    expected_path = f"/zarmih/ByeByeDPI-Linux/releases/download/{tag}/{asset_name}"
    decoded_path = urllib.parse.unquote(parsed.path)
    if decoded_path != expected_path:
        raise AppUpdaterError(f"Untrusted asset path: {decoded_path}")
    return url

def validate_release_info(release: ReleaseInfo):
    if not isinstance(release, ReleaseInfo):
        raise AppUpdaterError("Invalid ReleaseInfo object")
    try:
        _parse_semver(release.version)
    except ValueError:
        raise AppUpdaterError(f"Invalid semver: {release.version}")

    tag = f"v{release.version}"
    if release.asset_name != f"ByeByeDPI-Linux-{release.version}.tar.gz":
        raise AppUpdaterError("Invalid asset name format")

    validate_asset_url(release.download_url, tag, release.asset_name)
    validate_asset_url(release.sha256_url, tag, f"{release.asset_name}.sha256")
    validate_release_page_url(release.html_url, tag)

class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != "https":
            raise urllib.error.URLError("Redirect must be https")

        if parsed.username or parsed.password or parsed.fragment:
            raise urllib.error.URLError("Invalid redirect components")
        if parsed.port not in (None, 443):
            raise urllib.error.URLError("Invalid redirect port")

        allowed_hosts = {
            "objects.githubusercontent.com",
            "github-releases.githubusercontent.com",
            "release-assets.githubusercontent.com"
        }
        if parsed.hostname not in allowed_hosts:
            raise urllib.error.URLError(f"Untrusted redirect host: {parsed.hostname}")

        return super().redirect_request(req, fp, code, msg, headers, newurl)

def check_for_updates(api_url: str = API_URL, current_version: str = __version__) -> Optional[ReleaseInfo]:
    req = urllib.request.Request(validate_api_url(api_url), headers={"User-Agent": "ByeByeDPI-Linux-Updater/1.0", "Accept": "application/vnd.github.v3+json"})
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

    if not tag_name.startswith("v"):
        return None
    version_clean = tag_name[1:]
    try:
        _parse_semver(version_clean)
    except ValueError:
        return None

    try:
        if not is_newer(version_clean, current_version):
            return None
    except ValueError:
        return None

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
        html_url=validate_release_page_url(html_url, tag_name),
        download_url=validate_asset_url(tar_url, tag_name, expected_tar),
        sha256_url=validate_asset_url(sha256_url, tag_name, expected_sha),
        asset_name=expected_tar
    )

def download_update(release: ReleaseInfo, dest_dir: str) -> str:
    validate_release_info(release)

    dest_dir_path = Path(dest_dir)
    if dest_dir_path.is_symlink():
        raise AppUpdaterError("Destination must not be a symlink")
    dest_dir_path = dest_dir_path.resolve()

    try:
        dir_fd = os.open(dest_dir_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as e:
        raise AppUpdaterError(f"Failed to open destination directory: {e}")

    try:
        st = os.fstat(dir_fd)
        if st.st_uid != os.getuid():
            raise AppUpdaterError("Destination directory not owned by current user")
        if st.st_mode & 0o022:
            raise AppUpdaterError("Destination directory is group/world writable")

        try:
            os.stat(release.asset_name, dir_fd=dir_fd, follow_symlinks=False)
            raise AppUpdaterError("Target file already exists")
        except FileNotFoundError:
            pass
        except OSError as e:
            raise AppUpdaterError(f"Target file access error: {e}")

        opener = urllib.request.build_opener(SafeRedirectHandler())

        req_sha = urllib.request.Request(release.sha256_url, headers={"User-Agent": "ByeByeDPI-Linux-Updater/1.0"})
        try:
            with opener.open(req_sha, timeout=10) as resp:
                sha_content = resp.read(MAX_CHECKSUM_BYTES + 1)
                if len(sha_content) > MAX_CHECKSUM_BYTES:
                    raise AppUpdaterError("Checksum file too large")
                sha_content = sha_content.decode("utf-8")
        except AppUpdaterError:
            raise
        except Exception as e:
            raise AppUpdaterError(f"Failed to fetch checksum: {e}")

        m = re.fullmatch(r"([0-9a-fA-F]{64})[ \t]+\*?([^/\s\\]+)(?:\r?\n)?", sha_content)
        if not m:
            raise AppUpdaterError("Invalid checksum file format")

        expected_sha = m.group(1)
        checksum_filename = m.group(2)

        if checksum_filename != release.asset_name:
            raise AppUpdaterError("Checksum filename mismatch")

        req_tar = urllib.request.Request(release.download_url, headers={"User-Agent": "ByeByeDPI-Linux-Updater/1.0"})
        temp_name = None
        fd = None
        try:
            for _ in range(10):
                temp_name = f".dl-{secrets.token_hex(8)}.tmp"
                try:
                    fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dir_fd)
                    break
                except FileExistsError:
                    continue
                except OSError as e:
                    raise AppUpdaterError(f"Failed to create temporary file: {e}")
            else:
                raise AppUpdaterError("Could not generate a unique temporary filename")

            hasher = hashlib.sha256()
            downloaded = 0
            with opener.open(req_tar, timeout=30) as resp:
                content_length = resp.headers.get("Content-Length")
                if content_length is not None:
                    if not content_length.isdigit():
                        raise AppUpdaterError("Invalid Content-Length")
                    cl_int = int(content_length)
                    if cl_int <= 0 or cl_int > MAX_ASSET_BYTES:
                        raise AppUpdaterError("Asset Content-Length invalid or too large")

                with os.fdopen(fd, "wb", closefd=True) as f:
                    fd = None
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

            try:
                os.link(temp_name, release.asset_name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd, follow_symlinks=False)
                linked = True
            except FileExistsError:
                raise AppUpdaterError("Target file already exists")
            except OSError as e:
                raise AppUpdaterError(f"Failed to link to final destination: {e}")

            try:
                try:
                    os.unlink(temp_name, dir_fd=dir_fd)
                    temp_name = None
                except OSError:
                    pass
                os.fsync(dir_fd)
            except Exception:
                if linked:
                    try:
                        os.unlink(release.asset_name, dir_fd=dir_fd)
                        os.fsync(dir_fd)
                    except OSError:
                        pass
                raise

        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if temp_name is not None:
                try:
                    os.unlink(temp_name, dir_fd=dir_fd)
                except OSError:
                    pass

    finally:
        os.close(dir_fd)

    return str(dest_dir_path / release.asset_name)
