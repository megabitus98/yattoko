#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - netcheck.py
# Modified 2026 by megabitus98 (fork): new file, the host check: only http(s) links to public IPv4 addresses that are not the home's own

import ipaddress
import socket
from urllib.parse import urlsplit


class BlockedHost(Exception):
    """The link points at an address the bot must not fetch (reply BotText.unavailable)."""


def check_url(url: str, own_ips: frozenset[str], resolver=socket.getaddrinfo) -> None:
    # Defence in depth only: redirects, media URLs inside pages and DNS rebinding get past it;
    # the egress NetworkPolicy is the real control. Messages go to the log only, never to users.
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:  # e.g. a broken IPv6 literal
        raise BlockedHost("unparsable link") from None
    if parts.scheme not in ("http", "https") or not host:
        raise BlockedHost("not an http(s) link with a host")
    try:
        # Downloads are IPv4 only (source_address 0.0.0.0), so only A records count: dual-stack hosts pass,
        # AAAA-only hosts and IPv6 literals do not resolve here.
        infos = resolver(host, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise BlockedHost(f"{host} has no IPv4 address") from None
    if not infos:
        raise BlockedHost(f"{host} has no IPv4 address")
    for *_, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        ip = getattr(ip, "ipv4_mapped", None) or ip
        # is_global counts multicast as global; it is never a download source
        if ip.version != 4 or not ip.is_global or ip.is_multicast or str(ip) in own_ips:
            # no address in the message: it may be one of the home's own
            raise BlockedHost(f"{host} resolves to a refused address")
