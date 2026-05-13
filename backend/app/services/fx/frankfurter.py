"""Frankfurter HTTP client (ECB-published FX rates, free, no API key).

The endpoint we use:

    GET https://api.frankfurter.dev/v1/latest?from=INR
    →
    {
      "amount": 1.0,
      "base":   "INR",
      "date":   "2026-05-12",     ← ECB publishes once daily ~16:00 CET
      "rates": {
        "USD": 0.012,             ← USD per 1 INR
        "EUR": 0.0089,
        ...
      }
    }

We INVERT each rate to "INR per 1 unit of currency" (the form
PricingService consumes), because the rest of the codebase is
INR-denominated.

Why this endpoint:
  * No API key, no signup
  * Sourced from ECB reference rates (more reliable than aggregators)
  * 29-31 currencies covered (intersection with Razorpay's set =
    practical auto-rate universe)
  * Their old domain ``api.frankfurter.app`` redirects to .dev — we
    hit .dev directly to skip the redirect

Failure modes we surface:
  * Network: DNS / timeout / connect-refused → NetworkError
  * 4xx/5xx → NetworkError with status code in message
  * 200 but missing "rates" or non-numeric values → FXDataError
"""
from __future__ import annotations
from typing import Optional

import httpx

from app.services.fx.domain import FXDataError, NetworkError


FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
USER_AGENT = "cpmai-fx/1.0 (https://cpmaiexamprep.com)"
DEFAULT_TIMEOUT = 30.0


def fetch_rates_inr_base(
    *, codes: Optional[list[str]] = None, timeout: float = DEFAULT_TIMEOUT,
) -> tuple[dict[str, float], str]:
    """Fetch live INR-base rates from Frankfurter.

    Args:
        codes: optional whitelist of target currencies. If None, fetches
               everything Frankfurter publishes (~29-31 currencies).
               If supplied, we ask Frankfurter for just those — narrower
               response, but we still cope if Frankfurter doesn't have
               one (missing from result dict).
        timeout: HTTP request timeout in seconds.

    Returns:
        (rates_dict, date_str) where ``rates_dict`` maps currency code →
        INR per 1 unit (already inverted from Frankfurter's USD-per-INR
        form), and ``date_str`` is the YYYY-MM-DD ECB publication date.

    Raises:
        NetworkError: connectivity failure or non-200 response.
        FXDataError: response body malformed.
    """
    params: dict[str, str] = {"from": "INR"}
    if codes:
        # Frankfurter accepts comma-separated codes.
        params["to"] = ",".join(c.strip().upper() for c in codes if c)
    headers = {"User-Agent": USER_AGENT}

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(FRANKFURTER_URL, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise NetworkError(
            f"Frankfurter request failed: {type(exc).__name__}: {exc}"
        ) from exc

    if resp.status_code != 200:
        raise NetworkError(
            f"Frankfurter returned HTTP {resp.status_code}. "
            f"Body: {(resp.text or '').strip()[:200]!r}"
        )

    try:
        body = resp.json()
    except ValueError as exc:
        raise FXDataError(
            f"Frankfurter response is not JSON: {exc}. "
            f"Body: {(resp.text or '').strip()[:200]!r}"
        ) from exc

    if not isinstance(body, dict) or "rates" not in body:
        raise FXDataError(
            f"Frankfurter response missing 'rates' field. Got keys: "
            f"{list(body.keys()) if isinstance(body, dict) else type(body).__name__}"
        )

    raw_rates = body["rates"]
    if not isinstance(raw_rates, dict):
        raise FXDataError(
            f"Frankfurter 'rates' is not an object: got "
            f"{type(raw_rates).__name__}"
        )

    inverted: dict[str, float] = {}
    for code, usd_per_inr in raw_rates.items():
        # Defensive: skip entries that aren't a 3-letter alpha code or
        # whose value isn't a positive number.
        if not isinstance(code, str) or len(code.strip()) != 3 \
                or not code.strip().isalpha():
            continue
        try:
            r = float(usd_per_inr)
        except (TypeError, ValueError):
            continue
        if r <= 0:
            continue
        # Invert: Frankfurter publishes "0.012 USD per 1 INR".
        # We want "INR per 1 USD" = 1 / 0.012 = 83.33.
        inverted[code.strip().upper()] = round(1.0 / r, 6)

    if not inverted:
        raise FXDataError(
            "Frankfurter returned 0 usable currency rates. "
            "API contract may have changed — check the docs at "
            "https://api.frankfurter.dev/."
        )

    date_str = body.get("date") if isinstance(body.get("date"), str) else ""
    return inverted, date_str
