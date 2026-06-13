"""URL safety validator — prevent SSRF via private/loopback IPs, DNS rebinding, and restricted schemes."""
from __future__ import annotations

import ipaddress
import socket
import time
from collections import OrderedDict
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

# DNS cache: hostname → (ips, timestamp) — TTL-based to mitigate DNS rebinding
_DNS_CACHE: OrderedDict[str, tuple[list[str], float]] = OrderedDict()
_DNS_CACHE_TTL = 300  # 5 minutes
_DNS_CACHE_MAX = 1024


def _resolve_hostname(hostname: str) -> list[str]:
    """Resolve hostname to all IP addresses, with TTL-based caching."""
    now = time.time()

    # Check cache
    if hostname in _DNS_CACHE:
        ips, ts = _DNS_CACHE[hostname]
        if now - ts < _DNS_CACHE_TTL:
            return ips
        # Expired — remove
        del _DNS_CACHE[hostname]

    # Resolve
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        ips = list({r[4][0] for r in results})
    except socket.gaierror:
        ips = []

    # Cache result
    _DNS_CACHE[hostname] = (ips, now)
    if len(_DNS_CACHE) > _DNS_CACHE_MAX:
        _DNS_CACHE.popitem(last=False)  # Evict oldest

    return ips


def clear_dns_cache() -> None:
    """Clear the DNS cache (for testing)."""
    _DNS_CACHE.clear()


def _is_private_ip(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in net for net in PRIVATE_PREFIXES)
    except ValueError:
        return False


def is_safe_url(url: str) -> bool:
    """Return True only if *url* uses http(s) and does not target private/loopback hosts.

    DNS rebinding mitigation: cached resolution results are checked against private ranges.
    If any resolved IP is private at the time of URL creation, the URL is rejected.
    The cache TTL ensures that a malicious DNS server cannot change results between
    creation and access (rebinding attack).
    """
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

    # Check resolved IPs (with DNS cache)
    for ip_str in _resolve_hostname(hostname):
        if _is_private_ip(ip_str):
            return False

    return True