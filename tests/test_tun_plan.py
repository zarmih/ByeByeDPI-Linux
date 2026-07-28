import pytest
import os
import sys
from unittest.mock import patch, MagicMock
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))
import tun_plan

def test_parse_default_route_dhcp():
    output = "default via 192.168.1.1 dev enp3s0 proto dhcp metric 100 \n169.254.0.0/16 dev enp3s0 scope link metric 1000"
    gw, iface = tun_plan.parse_default_route(output)
    assert gw == "192.168.1.1"
    assert iface == "enp3s0"

def test_parse_default_route_static():
    output = "default via 10.0.0.254 dev eth1 \n10.0.0.0/24 dev eth1 proto kernel scope link src 10.0.0.1"
    gw, iface = tun_plan.parse_default_route(output)
    assert gw == "10.0.0.254"
    assert iface == "eth1"

def test_parse_default_route_missing():
    output = "192.168.1.0/24 dev enp3s0 proto kernel scope link src 192.168.1.5 metric 100"
    with pytest.raises(tun_plan.NetworkDiscoveryError, match="No IPv4 default route found"):
        tun_plan.parse_default_route(output)

def test_parse_default_route_invalid_format():
    output = "default is here"
    with pytest.raises(tun_plan.NetworkDiscoveryError, match="No IPv4 default route found"):
        tun_plan.parse_default_route(output)

def test_parse_source_ip_standard():
    output = "192.168.1.1 dev enp3s0 src 192.168.1.5 uid 1000 \n    cache "
    ip = tun_plan.parse_source_ip(output)
    assert ip == "192.168.1.5"

def test_parse_source_ip_multiline():
    output = "192.168.1.1 dev enp3s0 \n src 10.0.0.9 uid 1000"
    ip = tun_plan.parse_source_ip(output)
    assert ip == "10.0.0.9"

def test_parse_source_ip_missing():
    output = "192.168.1.1 dev enp3s0 uid 1000 \n    cache "
    with pytest.raises(tun_plan.NetworkDiscoveryError, match="Could not determine source IP"):
        tun_plan.parse_source_ip(output)

def test_parse_connected_prefixes():
    output = """default via 192.168.1.1 dev enp3s0 
10.8.0.0/24 dev tun0 proto kernel scope link src 10.8.0.2 
192.168.1.0/24 dev enp3s0 proto kernel scope link src 192.168.1.5 
172.17.0.0/16 dev docker0 proto kernel scope link src 172.17.0.1 linkdown """
    prefixes = tun_plan.parse_connected_prefixes(output, "enp3s0")
    assert "192.168.1.0/24" in prefixes
    assert "10.8.0.0/24" in prefixes
    assert "172.17.0.0/16" in prefixes
    assert "default" not in prefixes
    assert len(prefixes) == 3

def test_parse_connected_prefixes_duplicate_filtered():
    output = "10.0.0.0/24 dev eth0 scope link \n10.0.0.0/24 dev eth0 scope link \n192.168.0.0/24 dev eth1 scope link"
    prefixes = list(dict.fromkeys(tun_plan.parse_connected_prefixes(output, "eth0")))
    assert len(prefixes) == 2
    assert "10.0.0.0/24" in prefixes

def test_create_plan_success():
    with patch('tun_plan.execute_discovery') as mock_exec:
        def mock_run(cmd):
            if "default" in cmd:
                return "default via 10.0.0.1 dev eth0"
            elif "get" in cmd:
                return "10.0.0.1 dev eth0 src 10.0.0.5"
            elif "show" in cmd and "dev" in cmd:
                return "10.0.0.0/24 dev eth0 proto kernel scope link src 10.0.0.5"
            elif "link" in cmd and "show" in cmd:
                return "1: lo:\n2: eth0:"
            elif "rule" in cmd and "show" in cmd:
                return "0: from all lookup local\n32766: from all lookup main"
            return ""
        
        mock_exec.side_effect = mock_run

        plan = tun_plan.create_plan()
        assert plan.gateway_ip == "10.0.0.1"
        assert plan.physical_interface == "eth0"
        assert plan.physical_ip == "10.0.0.5"
        assert plan.connected_prefixes == ["10.0.0.0/24"]
        assert plan.tun_ip == "198.18.0.1"
        assert plan.rule_priority_bypass_physical == 1000
        assert plan.rule_priority_bypass_lan == 1100
        assert plan.rule_priority_gateway == 1190
        assert plan.rule_priority_catch_all == 2000

def test_plan_to_dict():
    plan = tun_plan.TunPlan(
        table_id=10808, tun_interface="byedpi0", tun_ip="198.18.0.1",
        physical_interface="eth0", physical_ip="10.0.0.5", gateway_ip="10.0.0.1",
        connected_prefixes=["10.0.0.0/24"], rule_priority_bypass_physical=1000,
        rule_priority_bypass_lan=1100, rule_priority_gateway=1190, rule_priority_catch_all=2000
    )
    d = plan.to_dict()
    assert d["tun_ip"] == "198.18.0.1"
    assert d["rule_priority_catch_all"] == 2000
    if "physical_interface" in d:
        del d["physical_interface"]
    if "physical_ip" in d:
        del d["physical_ip"]
    if "gateway_ip" in d:
        del d["gateway_ip"]
    assert "physical_interface" not in d # Not sent to helper

def test_create_plan_discovery_fails():
    with patch('tun_plan.execute_discovery', return_value=""):
        with pytest.raises(tun_plan.NetworkDiscoveryError, match="No IPv4 default route"):
            tun_plan.create_plan()

def test_create_plan_source_fails():
    with patch('tun_plan.execute_discovery') as mock_exec:
        def mock_run(cmd):
            if "default" in cmd:
                return "default via 10.0.0.1 dev eth0"
            return ""
        mock_exec.side_effect = mock_run
        with pytest.raises(tun_plan.NetworkDiscoveryError, match="Could not determine source"):
            tun_plan.create_plan()

def test_execute_discovery_success():
    with patch('subprocess.run') as mock_run:
        m = MagicMock()
        m.returncode = 0
        m.stdout = "test output"
        mock_run.return_value = m
        res = tun_plan.execute_discovery(["ip", "route"])
        assert res == "test output"

def test_execute_discovery_failure():
    with patch('subprocess.check_output', side_effect=subprocess.CalledProcessError(1, ["ip", "route"])):
        with pytest.raises(tun_plan.NetworkDiscoveryError, match="Command failed"):
            tun_plan.execute_discovery(["ip", "route"])

def test_execute_discovery_timeout():
    with patch('subprocess.run', side_effect=tun_plan.subprocess.TimeoutExpired(cmd=["ip"], timeout=5)):
        with pytest.raises(tun_plan.NetworkDiscoveryError, match="timed out"):
            tun_plan.execute_discovery(["ip", "route"])

