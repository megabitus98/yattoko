import socket

import pytest

import main
from config import BotText
from engine.errors import classify
from fakes import FakeClient, fake_downloader, fake_message
from utils.netcheck import BlockedHost, check_url

NO_OWN_IPS = frozenset()


def resolves_to(*addresses):
    def resolver(host, port, family=0, type=0, proto=0, flags=0):
        return [
            (
                (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (a, 0, 0, 0))
                if ":" in a
                else (socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 0))
            )
            for a in addresses
        ]

    return resolver


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.1.2.3", "192.168.1.1", "100.64.0.1", "169.254.1.1"]
)
def test_private_and_loopback_refused(address):
    with pytest.raises(BlockedHost):
        check_url("https://video.example/x", NO_OWN_IPS, resolves_to(address))


def test_every_address_must_pass():
    with pytest.raises(BlockedHost):
        check_url(
            "https://video.example/x",
            NO_OWN_IPS,
            resolves_to("142.250.0.1", "10.0.0.1"),
        )


@pytest.mark.parametrize(
    "address",
    [
        "2607:f8b0:4004:800::200e",  # a public IPv6 address: an AAAA-only host
        "64:ff9b::a00:1",  # NAT64 of 10.0.0.1
        "::ffff:10.0.0.1",  # IPv4-mapped
    ],
)
def test_ipv6_and_nat64_refused(address):
    with pytest.raises(BlockedHost):
        check_url("https://video.example/x", NO_OWN_IPS, resolves_to(address))


def test_asks_for_ipv4_only():
    # YouTube, TikTok and Instagram also have AAAA records; only the A records matter (source_address 0.0.0.0)
    asked = []

    def resolver(host, port, **kwargs):
        asked.append(kwargs.get("family"))
        return resolves_to("142.250.0.1")(host, port)

    check_url("https://www.youtube.com/watch?v=x", NO_OWN_IPS, resolver)
    assert asked == [socket.AF_INET]


def test_real_resolver_numeric_only():
    # the real getaddrinfo with check_url's arguments; AI_NUMERICHOST keeps it off DNS
    def numeric(*args, **kwargs):
        return socket.getaddrinfo(*args, **kwargs, flags=socket.AI_NUMERICHOST)

    check_url("http://142.250.0.1/x", NO_OWN_IPS, numeric)
    for url in ("http://127.0.0.1/x", "http://[::1]/x", "http://[64:ff9b::a00:1]/x"):
        with pytest.raises(BlockedHost):
            check_url(url, NO_OWN_IPS, numeric)


def test_unresolvable_refused():
    def fails(*args, **kwargs):
        raise socket.gaierror(socket.EAI_NONAME, "unknown host")

    for resolver in (fails, resolves_to()):
        with pytest.raises(BlockedHost):
            check_url("https://video.example/x", NO_OWN_IPS, resolver)


def test_own_public_ip_refused():
    # 203.0.113.7 is a documentation address, which is_global refuses by itself; the global address
    # shows that own_ips is what refuses it
    with pytest.raises(BlockedHost):
        check_url(
            "https://home.example/",
            frozenset({"203.0.113.7"}),
            resolves_to("203.0.113.7"),
        )
    check_url("https://home.example/", NO_OWN_IPS, resolves_to("142.250.0.7"))
    with pytest.raises(BlockedHost):
        check_url(
            "https://home.example/",
            frozenset({"142.250.0.7"}),
            resolves_to("142.250.0.7"),
        )


@pytest.mark.parametrize("host", ["youtu.be", "vm.tiktok.com", "instagr.am"])
def test_short_link_hosts_pass(host):
    assert (
        check_url(f"https://{host}/abc", NO_OWN_IPS, resolves_to("142.250.0.1")) is None
    )


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://video.example/x", "https:///x", "video.example/x"],
)
def test_file_scheme_refused(url):
    with pytest.raises(BlockedHost):
        check_url(url, NO_OWN_IPS, resolves_to("142.250.0.1"))


def test_blocked_link_gets_unavailable_reply():
    # the downloader checks the host before anything else (conftest resolves numeric hosts to themselves)
    assert classify(BlockedHost("refused")) == "unavailable"
    with pytest.raises(BlockedHost):
        fake_downloader("http://10.0.0.1/video.mp4")

    message, replies = fake_message("http://10.0.0.1/video.mp4")
    main.download_handler(FakeClient(), message)
    assert replies == [BotText.downloading, BotText.unavailable]
