"""Currency catalogues — what Razorpay can charge + what Frankfurter publishes.

These are SHIPPED-AS-CODE constants. Reasons:

  * Razorpay's supported-currency list changes roughly once a year (new
    additions, never removals). Hardcoding lets the picker offer the
    full list without an HTTP round-trip on every page load.
  * Frankfurter's set is also stable — ECB only adds/removes when an
    economy joins/leaves their reference basket.
  * If/when either list changes, this file is a single-PR update with
    a comment pointing at the source-of-truth docs.

Source of truth — Razorpay
--------------------------
https://razorpay.com/docs/payments/payments/international-payments/
(Settings → International Payments → "Supported currencies" section)

Last verified: 2026-05-13. ~100 codes that Razorpay International can
process. Most have card-network support; some are PayPal/bank-transfer
only — but the ``order.create`` API accepts all of them. Whether the
charge actually clears depends on the buyer's card network.

Source of truth — Frankfurter
-----------------------------
https://api.frankfurter.dev/v1/currencies
(JSON dict, ~30 codes, ECB-published daily.)

The intersection of the two sets is the practical "auto-rate" universe.
Outside that intersection:
  * Frankfurter-only currencies → not in Razorpay → can't charge anyway
  * Razorpay-only currencies → admin sets a manual rate via
    ``pricing.fx_overrides`` in settings (e.g. AED, SAR — Middle East
    currencies pegged to USD so the override is a one-time write).
"""
from __future__ import annotations


# ====================================================================
# Razorpay International — supported currencies as of 2026-05-13.
# ====================================================================
# Razorpay's order.create API accepts ANY of these in the ``currency``
# field. Auto-debit / e-mandate support varies; one-time payments work
# for all. Re-verify the list against the Razorpay docs link in the
# module docstring whenever you add new currencies to FX_OVERRIDES.
RAZORPAY_SUPPORTED_CURRENCIES: frozenset[str] = frozenset({
    "AED", "ALL", "AMD", "ANG", "ARS", "AUD", "AWG", "AZN", "BAM",
    "BBD", "BDT", "BGN", "BHD", "BIF", "BMD", "BND", "BOB", "BRL",
    "BSD", "BWP", "BZD", "CAD", "CHF", "CLP", "CNY", "COP", "CRC",
    "CUP", "CVE", "CZK", "DJF", "DKK", "DOP", "DZD", "EGP", "ETB",
    "EUR", "FJD", "GBP", "GEL", "GHS", "GIP", "GMD", "GNF", "GTQ",
    "GYD", "HKD", "HNL", "HRK", "HTG", "HUF", "IDR", "ILS", "INR",
    "JMD", "JOD", "JPY", "KES", "KGS", "KHR", "KMF", "KRW", "KWD",
    "KYD", "KZT", "LAK", "LBP", "LKR", "LRD", "LSL", "MAD", "MDL",
    "MGA", "MKD", "MMK", "MNT", "MOP", "MUR", "MVR", "MWK", "MXN",
    "MYR", "MZN", "NAD", "NGN", "NIO", "NOK", "NPR", "NZD", "OMR",
    "PEN", "PGK", "PHP", "PKR", "PLN", "QAR", "RON", "RSD", "RUB",
    "RWF", "SAR", "SCR", "SEK", "SGD", "SLL", "SOS", "SSP", "SVC",
    "SZL", "THB", "TJS", "TND", "TRY", "TTD", "TWD", "TZS", "UAH",
    "UGX", "USD", "UYU", "UZS", "VND", "XAF", "XCD", "XOF", "XPF",
    "YER", "ZAR", "ZMW",
})


# ====================================================================
# Frankfurter (ECB-reference) — supported currencies.
# ====================================================================
# These are the codes for which the cron job will fetch live mid-market
# rates. Currencies in Razorpay's set but not here can still be enabled
# via ``pricing.fx_overrides`` (admin sets the rate manually).
#
# Verify with:  curl https://api.frankfurter.dev/v1/currencies
FRANKFURTER_SUPPORTED_CURRENCIES: frozenset[str] = frozenset({
    "AUD", "BGN", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "EUR",
    "GBP", "HKD", "HUF", "IDR", "ILS", "INR", "ISK", "JPY", "KRW",
    "MXN", "MYR", "NOK", "NZD", "PHP", "PLN", "RON", "SEK", "SGD",
    "THB", "TRY", "USD", "ZAR",
})


# ====================================================================
# Display symbols.
# ====================================================================
# For the ~100 supported Razorpay codes we don't ship symbols for ALL
# of them — that bloats the bundle for currencies we'll never actually
# display. The set below covers everything Frankfurter publishes (the
# practical picker default) plus a few Middle-East peggers admin is
# likely to add via overrides.
_SYMBOLS: dict[str, str] = {
    "INR": "₹",     # ₹
    "USD": "$",
    "EUR": "€",     # €
    "GBP": "£",     # £
    "JPY": "¥",     # ¥
    "CNY": "¥",     # ¥
    "AUD": "A$",
    "CAD": "CA$",
    "CHF": "CHF",
    "NZD": "NZ$",
    "SGD": "S$",
    "HKD": "HK$",
    "ZAR": "R",
    "NOK": "kr",
    "SEK": "kr",
    "DKK": "kr",
    "MXN": "MX$",
    "BRL": "R$",
    "KRW": "₩",     # ₩
    "TRY": "₺",     # ₺
    "PLN": "zł",    # zł
    "CZK": "Kč",    # Kč
    "HUF": "Ft",
    "RON": "lei",
    "BGN": "lv",
    "ILS": "₪",     # ₪
    "IDR": "Rp",
    "MYR": "RM",
    "PHP": "₱",     # ₱
    "THB": "฿",     # ฿
    "ISK": "kr",
    # Middle East (admin-override candidates).
    "AED": "AED",
    "SAR": "SAR",
    "OMR": "OMR",
    "QAR": "QAR",
    "BHD": "BHD",
    "KWD": "KWD",
    # African (admin-override candidates).
    "KES": "KSh",
    "GHS": "GH₵",   # GH₵
    "EGP": "E£",    # E£
    "NGN": "₦",     # ₦
    # South-Asian (admin-override candidates).
    "PKR": "PKR",
    "BDT": "৳",     # ৳
    "LKR": "Rs",
    "NPR": "NRs",
}


def symbol_for(code: str) -> str:
    """Return the display symbol for ``code``, or the code itself as a
    fallback. Frontend uses this for the currency picker label and
    inline amount rendering (e.g. ``$12.59``).

    Falling back to the ISO code is intentional — better to render
    ``HKD 12.59`` for an admin-overridden currency we don't have a
    symbol for than to crash or show empty.
    """
    if not code or not isinstance(code, str):
        return code or ""
    return _SYMBOLS.get(code.strip().upper(), code.strip().upper())
