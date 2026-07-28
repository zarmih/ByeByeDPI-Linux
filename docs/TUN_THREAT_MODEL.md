# TUN Mode Threat Model

## Privilege Boundary
- **GUI (Unprivileged):** Manages user configuration and controls proxy backends (`ciadpi`, `hev-socks5-tunnel`).
- **TUN Helper (Root):** Executes exact, pre-defined network routing changes.
- **Mutual Distrust:** The helper inherently distrusts the GUI. It strictly validates all incoming arrays (no shell injections) and performs state validation before any modification. The Helper does NOT read configuration files from user directories.

## Identified Threats & Mitigations

### 1. Route Leaks and Loopbacks
- **Threat:** SOCKS proxy traffic routes back into TUN, causing infinite loops and dropped packets.
- **Mitigation:** The SOCKS proxy binds explicitly to the physical interface IP. The helper establishes a high-priority policy routing rule (`ip rule add from <physical_ip> lookup main`) overriding the TUN rule.

### 2. Arbitrary Command Execution
- **Threat:** Attackers exploit the `pkexec` boundary to run arbitrary commands via `tun-helper`.
- **Mitigation:** `tun-helper` is restricted to an allowlist of actions (`prepare`, `activate`, `rollback`, `recover`). It uses strict sub-command routing with `subprocess.Popen(shell=False)` and fixed executable paths (`/sbin/ip`, `/sbin/sysctl`).

### 3. Orphaned Network States
- **Threat:** Application crashes, leaving the network in an inaccessible state (default route broken).
- **Mitigation:** The helper utilizes a root-owned atomic journal in `/run/byebyedpi-linux/tun_recovery_journal.json`. It monitors the GUI's PID (`/proc/PID/stat` starttime). If the process terminates unexpectedly, the helper triggers an idempotent teardown to restore connectivity immediately.

### 4. Malicious Helper Modification
- **Threat:** User-space malware modifies the helper to escalate privileges next time it's invoked.
- **Mitigation:** `tun-helper` must be installed to `/usr/libexec/byebyedpi-linux/` with root ownership via manual scripts. The GUI will perform hash validation before invoking it.

### 5. IPv6 Leakage
- **Threat:** IPv4 traffic is tunneled, but IPv6 traffic bypasses the proxy if dual-stack is enabled on the host.
- **Mitigation:** In v0.3 MVP, IPv6 is entirely unhandled (direct). Users must be warned explicitly that IPv6 circumvention is disabled by default.

### 6. Local Network Interception
- **Threat:** The TUN intercepts traffic destined for the local network (e.g. 192.168.1.0/24), breaking access to local resources.
- **Mitigation:** The helper explicitly dynamically detects connected prefixes and adds higher-priority bypass rules for them.
