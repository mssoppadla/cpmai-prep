"""Canonical CPMAI ECO (Exam Content Outline) domains.

The certification exam is organised by *domain*, not by the six CPMAI
*phases* (topics). Each question still carries a phase (`topic_id`) for
authoring, but results and focused practice roll up by domain — which is
what this module defines.

There are five domains. Four of them align 1:1 or 1:many with phases;
the fifth — Trustworthy AI — is cross-cutting and cannot be derived from
a phase (a Trustworthy question may live in any phase), so domain is an
explicit attribute on each question (`Question.domain`, storing the code
below, e.g. "D-I").

This is intentionally a code-level constant rather than a DB table: the
ECO domain set is fixed by the certification body and changes only when
the exam blueprint itself changes (a deploy-worthy event), so a table
would add migration overhead without buying admin flexibility.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Domain:
    code: str           # stable identifier stored on Question.domain (e.g. "D-I")
    name: str           # human label shown in UI / exports
    slug: str           # URL-safe id (unused in routing today but handy)
    order: int          # display order
    weight: int         # approximate ECO exam weighting (percent)
    phase_codes: tuple[str, ...]   # CPMAI phase codes this domain spans


# Ordered D-I … D-V. `phase_codes` empty for the cross-cutting domain.
DOMAINS: tuple[Domain, ...] = (
    Domain("D-I",   "Trustworthy AI",                              "trustworthy-ai",     1, 15, ()),
    Domain("D-II",  "Identify Business Needs & Solutions",         "business-needs",     2, 26, ("BU",)),
    Domain("D-III", "Identify Data Needs",                         "data-needs",         3, 26, ("DU", "DP")),
    Domain("D-IV",  "Manage AI Model Development & Evaluation",    "model-dev-eval",     4, 16, ("MD", "EV")),
    Domain("D-V",   "Model Operationalization",                    "operationalization", 5, 17, ("DE",)),
)

_BY_CODE: dict[str, Domain] = {d.code: d for d in DOMAINS}
_BY_SLUG: dict[str, Domain] = {d.slug: d for d in DOMAINS}
# Lower-cased name → domain, so imports tolerate admins typing the label.
_BY_NAME: dict[str, Domain] = {d.name.lower(): d for d in DOMAINS}

# Phase (topic) code → domain code. Trustworthy (D-I) is never derived.
_PHASE_TO_DOMAIN: dict[str, str] = {
    pc: d.code for d in DOMAINS for pc in d.phase_codes
}


def all_domains() -> tuple[Domain, ...]:
    return DOMAINS


def get(code: str | None) -> Domain | None:
    """Resolve a stored domain value to a Domain. Accepts the code
    ("D-I"), the slug, or the human name (case-insensitive). Returns
    None for blank/unknown values."""
    if not code:
        return None
    key = code.strip()
    return (_BY_CODE.get(key)
            or _BY_CODE.get(key.upper())
            or _BY_SLUG.get(key.lower())
            or _BY_NAME.get(key.lower()))


def is_valid_code(code: str | None) -> bool:
    return bool(code) and code in _BY_CODE


def display_name(code: str | None) -> str:
    """Human label for a stored domain value. Falls back to the raw
    value (legacy free-text) or 'Unassigned' when blank."""
    d = get(code)
    if d:
        return d.name
    return (code or "").strip() or "Unassigned"


def domain_for_phase_code(phase_code: str | None) -> str | None:
    """Default domain code for a CPMAI phase code (None for unknown).
    Used to backfill legacy questions and to suggest a domain in the
    bulk template — never returns D-I (cross-cutting, not derivable)."""
    if not phase_code:
        return None
    return _PHASE_TO_DOMAIN.get(phase_code.strip().upper())
