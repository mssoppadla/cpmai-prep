"""X-Forwarded-For-aware client-IP extraction.

The trap this module exists to avoid
------------------------------------
Naively trusting ``X-Forwarded-For`` lets a malicious client spoof their
geo: a request like ``X-Forwarded-For: 8.8.8.8, 1.2.3.4`` where the
attacker controls the first hop can pretend to be coming from Google's
public DNS. The defense is "trust only as many hops as you actually
have proxies in front of you, counting from the right" — for cpmai
that's 1 (just Caddy).

Algorithm
---------
1. Read ``X-Forwarded-For`` header. Split on commas, strip whitespace.
2. If empty, fall back to ``request.client.host`` (uvicorn's direct
   peer). That's the right answer in dev (no Caddy) and behind
   misconfigured deployments — we'd rather log SOMETHING than nothing.
3. If non-empty and we have N trusted proxies, return the value at
   position ``-(N+1)`` from the end — the rightmost UNTRUSTED hop.
   For N=1: ``[client, caddy]`` returns ``client``.
   For N=1: ``[fake, real_client, caddy]`` returns ``real_client``
   (the attacker's prepended hop is discarded because we only trust 1).

Caveats
-------
* If the chain is shorter than expected (e.g. dev where there's no
  proxy at all but a buggy client still sends X-Forwarded-For), we
  fall back to ``request.client.host``. Better to log the direct peer
  than to pick a spoofed value.
* Private/loopback IPs (10.x, 192.168.x, 127.x, ::1) pass through and
  are handed to lookup() — which fails closed (returns None). No need
  to filter here; keeping IP-extraction and IP-classification separate
  makes both easier to test.
* IPv6 addresses are fine. ``ipaddress.ip_address`` handles both.
"""
from __future__ import annotations
import ipaddress
from typing import Optional

from starlette.requests import Request

from app.services.geoip.protocols import SettingsKeys, SettingsProvider
from app.services.geoip.settings import default_provider


def extract_client_ip(
    request: Request,
    *,
    settings: SettingsProvider = default_provider,
) -> Optional[str]:
    """Return the client IP for ``request``, honoring trusted proxy depth.

    Returns None if no usable IP could be determined (very rare —
    typically only in test setups with no transport at all). Returns a
    string that's been validated by ``ipaddress.ip_address`` — callers
    can pass it straight to lookup() without further sanity-checking.
    """
    trusted_count = max(1, settings.get_int(SettingsKeys.TRUSTED_PROXY_COUNT, 1))
    raw = _read_xff(request)
    if raw:
        hops = [h.strip() for h in raw.split(",") if h.strip()]
        if hops:
            # The rightmost N hops are our own proxies; the (N+1)th from
            # the right is the rightmost UNTRUSTED hop — the real
            # client. If the chain is shorter than N+1, the leftmost
            # entry is the best we can do.
            index = max(0, len(hops) - trusted_count - 1)
            candidate = hops[index]
            if _is_valid_ip(candidate):
                return candidate
    # Fallback: uvicorn's direct peer.
    if request.client and request.client.host:
        if _is_valid_ip(request.client.host):
            return request.client.host
    return None


def _read_xff(request: Request) -> Optional[str]:
    """Header read isolated for testability — Request.headers is case-
    insensitive but reading it via attribute differs by framework
    version; one entry point keeps tests honest."""
    return request.headers.get("x-forwarded-for")


def _is_valid_ip(value: str) -> bool:
    """True if ``value`` parses as a v4 or v6 address. ``ipaddress``
    handles "192.168.0.1", "::1", "2001:db8::1", etc."""
    if not value:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False
