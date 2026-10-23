"""Pruebas del analisis del sondeo. IPs de ejemplo en 192.0.2.0/24 (documentacion)."""

from __future__ import annotations

import pytest

from services.service_probe import (
    NetInterface,
    ProbeResult,
    default_address,
    detect_clipboard,
    detect_session,
    format_report,
    interfaces_from_adapters,
    network_of,
    parse_default_iface,
    parse_ip_addr,
    parse_listening_ports,
    parse_ufw_conf,
)

IP_ADDR = (
    "2: wlp2s0    inet 192.0.2.10/24 brd 192.0.2.255 scope global dynamic wlp2s0\\"
    "       valid_lft 85000sec preferred_lft 85000sec\n"
    "3: docker0    inet 198.51.100.1/16 brd 198.51.100.255 scope global docker0\\"
    "       valid_lft forever preferred_lft forever\n"
)


def test_parse_ip_addr():
    assert parse_ip_addr(IP_ADDR) == [
        NetInterface("wlp2s0", "192.0.2.10", "192.0.2.0/24"),
        NetInterface("docker0", "198.51.100.1", "198.51.0.0/16"),
    ]
    assert parse_ip_addr("") == []


def test_network_of_finds_the_interface_subnet():
    interfaces = parse_ip_addr(IP_ADDR)
    assert network_of("192.0.2.10", interfaces) == "192.0.2.0/24"
    assert network_of("198.51.100.1", interfaces) == "198.51.0.0/16"
    with pytest.raises(ValueError):
        network_of("203.0.113.7", interfaces)


def test_parse_default_iface():
    route = "default via 192.0.2.1 dev wlp2s0 proto dhcp metric 600\n"
    assert parse_default_iface(route) == "wlp2s0"
    assert parse_default_iface("") == ""


def test_default_address_is_the_default_route_interface():
    interfaces = parse_ip_addr(IP_ADDR)
    assert default_address(interfaces, "wlp2s0") == "192.0.2.10"
    assert default_address(interfaces, "") == ""
    assert default_address([], "wlp2s0") == ""


def test_parse_ufw_conf():
    assert parse_ufw_conf("# comentario\nENABLED=yes\nLOGLEVEL=low\n") == "activo"
    assert parse_ufw_conf("ENABLED=no\n") == "inactivo"
    assert parse_ufw_conf("LOGLEVEL=low\n") == "desconocido"
    assert parse_ufw_conf(None) == "no instalado"


def test_parse_listening_ports():
    tcp = (
        "LISTEN 0      128          0.0.0.0:22        0.0.0.0:*\n"
        "LISTEN 0      128             [::]:22           [::]:*\n"
        "LISTEN 0      4096   127.0.0.53%lo:53        0.0.0.0:*\n"
    )
    assert parse_listening_ports(tcp) == {22, 53}
    udp = "UNCONN 0      0            0.0.0.0:5353      0.0.0.0:*\n"
    assert parse_listening_ports(udp) == {5353}
    assert parse_listening_ports("basura\n") == set()


def test_detect_session():
    assert detect_session({"XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "X-Cinnamon"}) == (
        "x11",
        "X-Cinnamon",
    )
    assert detect_session({"WAYLAND_DISPLAY": "wayland-0"}) == ("wayland", "")
    assert detect_session({"XDG_SESSION_TYPE": "tty", "DISPLAY": ":0"}) == ("x11", "")
    assert detect_session({"XDG_SESSION_TYPE": "tty"}) == ("tty", "")
    assert detect_session({}) == ("tty", "")


def test_detect_clipboard():
    def which_all(tool):
        return f"/usr/bin/{tool}"

    def which_none(tool):
        return None

    assert detect_clipboard("x11", which_all) == ("xclip", "xclip")
    assert detect_clipboard("wayland", which_all) == ("wl-copy + wl-paste", "wl-clipboard")
    assert detect_clipboard("x11", which_none) == ("falta xclip", "xclip")
    assert detect_clipboard("tty", which_all) == ("sin sesion grafica", "")


def test_format_report_marks_default_route_and_missing_package():
    result = ProbeResult(
        hostname="equipo",
        user="usuario",
        python="3.12.3",
        session_type="x11",
        desktop="X-Cinnamon",
        clipboard_tool="falta xclip",
        clipboard_package="xclip",
        interfaces=[NetInterface("wlp2s0", "192.0.2.10", "192.0.2.0/24")],
        default_iface="wlp2s0",
        ufw="activo",
    )
    report = format_report(result)
    assert "| Sesion grafica | x11 (X-Cinnamon) |" in report
    assert "falta xclip (paquete xclip)" in report
    assert "wlp2s0 192.0.2.10 (192.0.2.0/24) *" in report
    assert "| sshd del sistema (puerto 22) | no escucha |" in report


def test_interfaces_from_ifaddr_adapters():
    from types import SimpleNamespace as NS

    adapters = [
        NS(
            nice_name="Wi-Fi",
            ips=[
                NS(ip="192.0.2.20", network_prefix=24),
                NS(ip=("fe80::1", 0, 0), network_prefix=64),
            ],
        ),
        NS(nice_name="Loopback", ips=[NS(ip="127.0.0.1", network_prefix=8)]),
        NS(nice_name="Ethernet", ips=[NS(ip="169.254.3.4", network_prefix=16)]),
    ]
    assert interfaces_from_adapters(adapters) == [
        NetInterface("Wi-Fi", "192.0.2.20", "192.0.2.0/24")
    ]
