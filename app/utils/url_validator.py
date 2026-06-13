"""URL safety validator — prevent SSRF via private/loopback IPs and restricted schemes."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

PRIVATE_PREFIXES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local (AWS metadata)
    ipaddress.ip_network("0.0.0.0/8"),      # "This" network
]

FORBIDDEN_HOSTNAMES = {"localhost", "localhost.localdomain"}


def _resolve_hostname(hostname: str) -> list[str]:
    """Resolve hostname to all IP addresses."""
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        return {r[4][0] for r in results}
    except socket.gaierror:
        return []


def _is_private_ip(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in net for net in PRIVATE_PREFIXES)
    except ValueError:
        return False


def is_safe_url(url: str) -> bool:
    """Return True only if *url* uses http(s) and does not target private/loopback hosts."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    lower = hostname.lower()
    if lower in FORBIDDEN_HOSTNAMES:
        return False

    # Check literal IP
    if _is_private_ip(hostname):
        return False

    # Check resolved IPs
    for ip_str in _resolve_hostname(hostname):
        if _is_private_ip(ip_str):
            return False

    return True
