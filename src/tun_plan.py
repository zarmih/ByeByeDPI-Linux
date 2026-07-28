from __future__ import annotations

import dataclasses
import re
import subprocess
from typing import List, Dict, Optional, Tuple

@dataclasses.dataclass(frozen=True)
class TunPlan:
    table_id: int
    tun_interface: str
    tun_ip: str
    physical_interface: str
    physical_ip: str
    gateway_ip: str
    connected_prefixes: List[str]
    rule_priority_bypass_physical: int
    rule_priority_bypass_lan: int
    rule_priority_gateway: int
    rule_priority_catch_all: int

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    def prepare_commands(self, owner_uid: int) -> List[List[str]]:
        # TunHelper now creates the commands internally, so we don't really use this except for testing
        pass

    def activate_commands(self) -> List[List[str]]:
        pass

    def rollback_commands(self) -> List[List[str]]:
        pass

class NetworkDiscoveryError(Exception):
    pass

def execute_discovery(cmd: List[str]) -> str:
    """Mockable execution of discovery commands."""
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        raise NetworkDiscoveryError(f"Command failed: {' '.join(cmd)}") from e
    except subprocess.TimeoutExpired as e:
        raise NetworkDiscoveryError(f"Command timed out: {' '.join(cmd)}") from e
    except FileNotFoundError as e:
        raise NetworkDiscoveryError("ip utility not found") from e

def parse_default_route(output: str) -> Tuple[str, str]:
    """Parse 'ip -4 route show default' to extract gateway and interface."""
    match = re.search(r'^default\s+via\s+([^\s]+)\s+dev\s+([^\s]+)', output, re.MULTILINE)
    if not match:
        raise NetworkDiscoveryError("No IPv4 default route found")
    return match.group(1), match.group(2)

def parse_source_ip(output: str) -> str:
    """Parse 'ip -4 route get <gateway>' to extract source IP."""
    match = re.search(r'src\s+([^\s]+)', output)
    if not match:
        raise NetworkDiscoveryError("Could not determine source IP for default route")
    return match.group(1)

def parse_connected_prefixes(output: str, interface: str) -> List[str]:
    """Parse 'ip -4 route show dev <interface>' to find connected (link) prefixes."""
    prefixes = []
    for line in output.splitlines():
        if "scope link" in line:
            parts = line.strip().split()
            if parts and parts[0] != "default":
                prefixes.append(parts[0])
    return prefixes

def check_conflicts(table_id: int, tun_interface: str) -> None:
    pass # Helper does conflict checking now

def create_plan() -> TunPlan:
    # 1. Find default route
    default_route_out = execute_discovery(["ip", "-4", "route", "show", "default"])
    gateway_ip, physical_interface = parse_default_route(default_route_out)

    # 2. Find source IP
    route_get_out = execute_discovery(["ip", "-4", "route", "get", gateway_ip])
    physical_ip = parse_source_ip(route_get_out)

    # 3. Find connected prefixes for the physical interface
    route_show_dev_out = execute_discovery(["ip", "-4", "route", "show", "dev", physical_interface])
    connected_prefixes = parse_connected_prefixes(route_show_dev_out, physical_interface)

    # 4. Define defaults
    table_id = 10808
    tun_interface = "byedpi0"

    return TunPlan(
        table_id=table_id,
        tun_interface=tun_interface,
        tun_ip="198.18.0.1",
        physical_interface=physical_interface,
        physical_ip=physical_ip,
        gateway_ip=gateway_ip,
        connected_prefixes=connected_prefixes,
        rule_priority_bypass_physical=1000,
        rule_priority_bypass_lan=1100,
        rule_priority_gateway=1190,
        rule_priority_catch_all=2000
    )
