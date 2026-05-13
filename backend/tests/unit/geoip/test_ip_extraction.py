"""X-Forwarded-For extraction tests.

The bug shapes we're guarding against:

  * Client supplies a spoofed X-Forwarded-For header to make their
    request look like it's coming from a different country. With
    trusted_proxy_count=1 (our default — one Caddy hop), only the
    rightmost hop is trusted; everything else is potentially client-
    supplied and ignored.

  * No X-Forwarded-For header (dev environment, direct hits to
    uvicorn) — we fall back to request.client.host.

  * Bad data in the header (junk strings, empty values, missing IPs)
    — we ignore and fall through to the next candidate.
"""
from types import SimpleNamespace

import pytest

from app.services.geoip.ip_extraction import extract_client_ip
from app.services.geoip.protocols import SettingsKeys


def _make_request(*, xff: str | None = None,
                  client_host: str | None = "127.0.0.1"):
    """Build a minimal Starlette-Request-shaped stub. Only the attrs
    extract_client_ip touches need to be real; the rest can be missing."""
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(
        headers=headers,
        client=SimpleNamespace(host=client_host) if client_host else None,
    )


def test_no_xff_falls_back_to_client_host(settings):
    """Dev path: no proxy, uvicorn sees the client directly."""
    request = _make_request(xff=None, client_host="203.0.113.1")
    assert extract_client_ip(request, settings=settings) == "203.0.113.1"


def test_no_xff_no_client_returns_none(settings):
    """Test transport: no proxy, no .client at all."""
    request = _make_request(xff=None, client_host=None)
    assert extract_client_ip(request, settings=settings) is None


def test_xff_single_hop_returns_value(settings):
    """One hop, one trusted proxy: the only hop IS the client."""
    request = _make_request(xff="203.0.113.1")
    assert extract_client_ip(request, settings=settings) == "203.0.113.1"


def test_xff_two_hops_default_proxy_count_returns_first(settings):
    """`client, caddy`. trusted_proxy_count=1 (default) means we trust
    the rightmost 1 hop (caddy) and the (rightmost+1)th from the right
    is the real client."""
    # Note: by default settings.get_int returns 0 — extract_client_ip
    # bumps that to 1 via max(1, ...). So this exercises the default
    # without explicitly seeding.
    request = _make_request(xff="203.0.113.1, 10.0.0.1")
    assert extract_client_ip(request, settings=settings) == "203.0.113.1"


def test_xff_spoofed_extra_hop_is_discarded(settings):
    """Attack: client prepends a fake hop to make themselves look like
    Google DNS (8.8.8.8). With trusted_proxy_count=1, we still only
    look at index -2 — the rightmost UNTRUSTED hop, which is the
    REAL client, not the spoofed one."""
    request = _make_request(xff="8.8.8.8, 203.0.113.1, 10.0.0.1")
    # The chain has 3 hops; trusted=1 → index = 3 - 1 - 1 = 1 → 203.0.113.1
    assert extract_client_ip(request, settings=settings) == "203.0.113.1"


def test_xff_with_two_trusted_proxies(settings):
    """Future: cloudflare in front of caddy → 2 trusted hops. The
    setting changes, not the code."""
    settings.set(SettingsKeys.TRUSTED_PROXY_COUNT, 2)
    request = _make_request(xff="8.8.8.8, 203.0.113.1, 172.16.0.1, 10.0.0.1")
    # 4 hops, trusted=2 → index = 4 - 2 - 1 = 1 → 203.0.113.1
    assert extract_client_ip(request, settings=settings) == "203.0.113.1"


def test_xff_invalid_ip_falls_back_to_client(settings):
    """If the parsed candidate isn't a valid IP, we fall through to
    .client.host. Defense against malformed XFF headers."""
    request = _make_request(xff="not-an-ip-at-all", client_host="203.0.113.2")
    assert extract_client_ip(request, settings=settings) == "203.0.113.2"


def test_xff_ipv6_value(settings):
    """IPv6 addresses are valid client IPs."""
    request = _make_request(xff="2001:db8::1")
    assert extract_client_ip(request, settings=settings) == "2001:db8::1"


def test_xff_whitespace_tolerance(settings):
    """Real proxies vary in whitespace; we strip aggressively."""
    request = _make_request(xff="  203.0.113.1  ,  10.0.0.1  ")
    assert extract_client_ip(request, settings=settings) == "203.0.113.1"


def test_xff_empty_string_falls_back(settings):
    """Some proxies send `X-Forwarded-For:` with no value. Treat as absent."""
    request = _make_request(xff="", client_host="203.0.113.3")
    assert extract_client_ip(request, settings=settings) == "203.0.113.3"


def test_trusted_proxy_count_clamps_to_minimum_one(settings):
    """Setting trusted_proxy_count=0 or negative would expose the
    rightmost (proxy) hop as the 'client'. We clamp to min=1."""
    settings.set(SettingsKeys.TRUSTED_PROXY_COUNT, 0)
    request = _make_request(xff="203.0.113.1, 10.0.0.1")
    # With clamp=1, the answer is the leftmost (client), not the rightmost (proxy).
    assert extract_client_ip(request, settings=settings) == "203.0.113.1"
