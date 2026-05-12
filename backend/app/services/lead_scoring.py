"""Rule-based lead scoring — 0..100 ranking signal for /admin/leads.

Pure function over a ``Lead`` instance — no DB lookups except an
optional repeat-visitor check that the caller passes in. Returns an
int in ``[0, 100]`` (clipped). Higher = warmer.

**Rules (see docs/backlog.md for the original spec)**

UTM source (max +20):
  - ``google`` or ``google_ads``    → +20
  - ``linkedin`` or ``linkedin_ads`` → +15
  - direct (no utm_source)           → +10
  - ``organic`` / ``seo``            → +5

Plan-interest signal (+20 if matched):
  - ``interests`` list contains any of: premium, monthly, yearly,
    subscribe, subscription, plan, pricing

Phone provided (+15)

Notes-quality signal (+10):
  - ``notes`` length between 50 and 200 chars (sweet spot — short
    enough to be focused, long enough to convey real intent)

Repeat-visitor signal (+15):
  - caller passes ``is_repeat=True`` if another lead with the same
    email (or anon_id) already exists. Defaults False if unknown.

Landing-page signal (max +15):
  - ``landing_url`` contains ``/pricing``  → +15
  - ``landing_url`` contains ``/exams``    → +10
  - any other landing page                 → +5

**Why rule-based, not ML**

At our volume (single-digit leads/day), ML would overfit and burn
review cycles tweaking model artifacts. Rules are explainable to the
operator ("why is this lead HOT?" → "google ad + phone + pricing
page"), easy to A/B by editing one number, and cheap to compute
synchronously on every insert.

Tier labels for UI badging (see ``score_tier``):
  - **HOT**  : score ≥ 70
  - **WARM** : 40 ≤ score < 70
  - **COLD** : score < 40
"""
from __future__ import annotations
from typing import Optional, Protocol


# Substrings searched (case-insensitive) inside ``Lead.interests`` to
# detect explicit plan intent. Kept centralized so the threshold and
# vocabulary stay co-located with the scoring rule.
_PLAN_INTENT_KEYWORDS = (
    "premium", "monthly", "yearly", "subscribe", "subscription",
    "plan", "pricing",
)

# Notes between this many characters are considered "high quality
# intent." Too-short suggests a tire-kicker; too-long suggests a paste
# of unrelated content.
_NOTES_MIN, _NOTES_MAX = 50, 200


class _LeadShape(Protocol):
    """Minimal shape this function needs from ``Lead``. Declared as a
    Protocol so the same scorer works against the SQLAlchemy model AND
    against test fixtures without inheriting from Base."""
    phone: Optional[str]
    utm_source: Optional[str]
    landing_url: Optional[str]
    interests: Optional[list]
    notes: Optional[str]


def calculate_lead_score(lead: _LeadShape, *,
                         is_repeat: bool = False) -> int:
    """Return a 0..100 score for the given lead.

    ``is_repeat=True`` adds the repeat-visitor bonus. Callers that
    already have a DB session should set this based on a count query;
    callers that don't (e.g. unit tests) can pass False.
    """
    score = 0

    # UTM source — clearest intent signal we have.
    utm = (lead.utm_source or "").strip().lower()
    if utm in {"google", "google_ads"}:
        score += 20
    elif utm in {"linkedin", "linkedin_ads"}:
        score += 15
    elif not utm:
        # No UTM at all = "direct" traffic, generally warmer than a
        # cold organic SEO visit because they bookmarked/remembered us.
        score += 10
    elif utm in {"organic", "seo"}:
        score += 5
    # Any other utm value (e.g. a campaign experiment we haven't scored
    # yet) gets 0 — better to under-score than misranked.

    # Plan-interest keywords in the free-form interests list.
    interests = lead.interests or []
    interests_text = " ".join(str(x).lower() for x in interests)
    if any(kw in interests_text for kw in _PLAN_INTENT_KEYWORDS):
        score += 20

    # Phone provided is a strong intent signal — anyone willing to be
    # contacted by phone is several rungs warmer than email-only.
    if (lead.phone or "").strip():
        score += 15

    # Notes-quality. Empty / very short / overly long all get 0.
    notes_len = len((lead.notes or "").strip())
    if _NOTES_MIN <= notes_len <= _NOTES_MAX:
        score += 10

    # Repeat visitor — caller-supplied boolean. Keeps this function
    # pure and DB-free.
    if is_repeat:
        score += 15

    # Landing-page hint: pricing > exams > anything else > nothing.
    url = (lead.landing_url or "").lower()
    if "/pricing" in url:
        score += 15
    elif "/exams" in url:
        score += 10
    elif url:
        score += 5

    # Clip to [0, 100] in case the rules ever sum above 100 (today's
    # max is 95, but adding rules in the future shouldn't break the
    # contract).
    return max(0, min(100, score))


def score_tier(score: Optional[int]) -> str:
    """Bucket a numeric score into the operator-facing tier label.

    Returns ``"unknown"`` for ``None`` (the pre-migration backfill case
    or a lead created before scoring shipped). Admin UI renders this
    as a neutral chip so old rows don't look mis-scored.
    """
    if score is None:
        return "unknown"
    if score >= 70:
        return "hot"
    if score >= 40:
        return "warm"
    return "cold"
