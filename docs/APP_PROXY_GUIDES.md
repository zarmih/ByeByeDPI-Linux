# Application proxy guides

ByeByeDPI-Linux exposes a local SOCKS5 proxy, normally at `127.0.0.1:1080`. These recipes route only the selected application through that local proxy. They do **not** change DNS, firewall, routes, NetworkManager, or the desktop-wide proxy configuration.

> ByeDPI is not a VPN. Using the local SOCKS proxy does not hide your public IP address from the destination service.

## Firefox

Firefox has its own proxy UI, so no launcher helper is required:

1. Open **Settings** → **Network Settings** → **Settings…**.
2. Choose **Manual proxy configuration**.
3. Set **SOCKS Host** to `127.0.0.1` and **Port** to the ByeByeDPI port (default `1080`).
4. Select **SOCKS v5**.
5. Enable **Proxy DNS when using SOCKS v5**.
6. Save the settings.

To stop using ByeByeDPI, return Firefox to **No proxy** or your previous proxy mode.

## Chromium / Google Chrome / Brave

The repository includes a dependency-free launcher helper:

```bash
python3 scripts/launch_browser_proxy.py --port 1080
```

Open a URL immediately:

```bash
python3 scripts/launch_browser_proxy.py --port 1080 --url https://example.com/
```

Select a browser explicitly if auto-detection does not find the one you want:

```bash
python3 scripts/launch_browser_proxy.py \
  --browser google-chrome \
  --port 1080 \
  --url https://example.com/
```

Preview the exact command without checking the local port or starting a process:

```bash
python3 scripts/launch_browser_proxy.py --browser chromium --port 1080 --dry-run
```

The helper:

- verifies that `127.0.0.1:<port>` is accepting connections before a real launch;
- passes Chromium's `--proxy-server=socks5://127.0.0.1:<port>` option;
- adds a host-resolver rule so URL hostnames are resolved through the SOCKS5 path rather than normal Chromium URL resolution;
- uses a dedicated profile under `${XDG_CACHE_HOME:-~/.cache}/byebyedpi-linux/browser-profiles/`, so it does not modify the normal browser profile;
- invokes the browser directly with an argv list (`shell=False`) and never changes the system proxy.

The command-line proxy behaviour follows Chromium's documented SOCKS proxy configuration:

- https://chromium.googlesource.com/website/+/HEAD/site/developers/design-documents/network-stack/socks-proxy/index.md
- https://chromium.googlesource.com/chromium/src/+/main/net/docs/proxy.md

### Important Chromium limitation

Chromium documents that `--proxy-server` applies to URL loads; browser components outside normal URL loads can still behave differently. Treat the helper as per-browser traffic routing, not a system-wide VPN or a guarantee that every browser subsystem is tunneled.

## curl

For a one-off command, use `socks5h://` so hostname resolution is performed through the SOCKS proxy:

```bash
curl --proxy socks5h://127.0.0.1:1080 https://example.com/
```

This follows curl's documented `--proxy` protocol syntax. `socks5h` is the SOCKS5 mode where the proxy resolves the destination hostname.

Official reference: https://curl.se/docs/manpage.html

## Troubleshooting

Check the local port before configuring an application:

```bash
python3 - <<'PY'
import socket
with socket.create_connection(("127.0.0.1", 1080), timeout=1):
    print("SOCKS port is reachable")
PY
```

If the helper reports that the port is unavailable, start ByeByeDPI first or pass the actual SOCKS port with `--port`.
