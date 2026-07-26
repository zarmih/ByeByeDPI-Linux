# Security model

## What the application changes

ByeByeDPI Linux starts the vendored `ciadpi` executable as a local SOCKS5 proxy bound to `127.0.0.1`. It does not require root and does not edit routes, DNS, firewall, nftables, iptables or NetworkManager.

The optional GNOME integration changes only user-level `gsettings` keys under `org.gnome.system.proxy*`. It configures the **SOCKS** schema, not HTTP/HTTPS endpoints.

## GNOME recovery journal

Before applying GNOME proxy settings, the program snapshots every available relevant key (global mode, auto-config URL, ignore hosts, same-proxy flag, and HTTP/HTTPS/FTP/SOCKS host/port values). The snapshot is written atomically to the application data directory.

A second Apply is refused while a journal exists. Stop, Quit and application startup attempt restoration. The journal is deleted only after every saved key is restored successfully. A partial failure leaves the journal in place and reports an error.

## Important limitations

- GNOME system proxy is not a VPN, TUN device or transparent network redirect.
- Applications may ignore desktop proxy settings or implement their own networking stack.
- The user's public IP address is not hidden from destination servers.
- A successful HTTP/TLS probe means the connection completed; it does not prove that video, voice calls or every application feature works.
- Imported result bundles and update files are treated as untrusted data. They are size-limited and validated; strategy strings are data and are never evaluated with `eval`, `exec` or a shell.

## Tests and privileges

Automated tests inject a fake `gsettings` runner. They do not execute real `gsettings set` commands. Installation and uninstallation scripts reject unsafe prefixes and do not invoke `sudo`.
