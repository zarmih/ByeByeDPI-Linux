# ByeByeDPI-Linux TUN Architecture

## Overview
This document outlines the architecture for the system-wide TUN mode (virtual network interface) in ByeByeDPI-Linux. The goal is to provide transparent proxying for applications that ignore GNOME `gsettings`, similar to Android's VPNService, while adhering to strict security constraints.

## Components
1. **Unprivileged GUI (Python):** Manages user interaction, starts `ciadpi`, and orchestrates the TUN lifecycle.
2. **ciadpi (C, SOCKS5 Proxy):** Runs unprivileged, bound locally, and handles DPI bypass.
3. **hev-socks5-tunnel (C):** A lightweight unprivileged process that converts TUN traffic to SOCKS5 UDP/TCP requests.
4. **TUN Helper (Python):** A minimal, stdlib-only, root-owned helper executed via Polkit (`pkexec`) strictly for creating the network interface and routing rules.

## Two-Phase Initialization
To ensure safe startup and prevent leaks, the system starts in two phases:
1. **Prepare Phase:**
   - GUI starts `ciadpi` bound explicitly to the primary physical network interface IP (e.g., `ciadpi -I 192.168.1.5`).
   - GUI calls `tun-helper prepare`.
   - Helper securely creates a persistent TUN interface (`byedpi0`) owned by the invoking user.
   - Helper sets up bypass routes to ensure `ciadpi` traffic and local LAN traffic do not enter the TUN (Loop Prevention).
   - *No default route into TUN is set yet.*
2. **Activate Phase:**
   - GUI starts `hev-socks5-tunnel` unprivileged. It attaches to `byedpi0`.
   - GUI verifies readiness.
   - GUI calls `tun-helper activate`.
   - Helper adds the default route `0.0.0.0/0` into `byedpi0` via Policy Routing.

## Routing and Loop Prevention
- Traffic originating from the physical interface's IP (used by `ciadpi`) is routed to the main table (`priority 90`).
- Connected prefixes (LAN) and gateway routes are routed to the main table (`priority 95`).
- All other IPv4 traffic is routed to the custom table `10808` (`priority 100`), which has a default route to `byedpi0`.

## State and Recovery
- **Journaling:** The helper maintains an atomic, locked journal at `/run/byebyedpi-linux/tun_recovery_journal.json` (owned by root, mode 0600).
- **Watchdog:** The helper monitors the GUI's PID and its `starttime` in `/proc/PID/stat`. It also monitors the default route and interface IP. If any condition breaks, the helper triggers an automatic idempotent rollback.
- **Rollback:** Idempotent cleanup of exactly the rules and interfaces created, ensuring no foreign network objects are modified.
