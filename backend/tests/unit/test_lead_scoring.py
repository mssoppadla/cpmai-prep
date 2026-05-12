"""Unit tests for ``app.services.lead_scoring.calculate_lead_score``.

Pure function over a duck-typed lead. We use simple ``SimpleNamespace``
fixtures rather than the SQLAlchemy ``Lead`` model so each test is
isolated and fast — no DB, no transaction setup.

The tests pin the EXACT scoring contract documented in the module's
docstring, so any future rule tweak shows up as a deliberate test
update (not a silent regression).
"""
from types import SimpleNamespace
from app.services.lead_scoring import calculate_lead_score, score_tier


def _lead(**overrides):
    """Helper to build a ``Lead``-shaped object with all scoring inputs
    defaulted to "no signal" (score 0 baseline). Override only what
    matters to the test for clarity."""
    base = dict(
        phone=None,
        utm_source=None,
        landing_url=None,
        interests=None,
        notes=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------- UTM source signal -------------------------------------

def test_utm_google_scores_20():
    assert calculate_lead_score(_lead(utm_source="google")) == 20


def test_utm_google_ads_alias_also_scores_20():
    assert calculate_lead_score(_lead(utm_source="google_ads")) == 20


def test_utm_linkedin_scores_15():
    assert calculate_lead_score(_lead(utm_source="linkedin")) == 15


def test_utm_none_scores_10_direct_traffic():
    # No utm_source = direct visit (bookmarked, typed URL, etc.) —
    # generally a warmer signal than cold organic SEO.
    assert calculate_lead_score(_lead(utm_source=None)) == 10


def test_utm_empty_string_scores_10_treated_as_direct():
    assert calculate_lead_score(_lead(utm_source="")) == 10


def test_utm_organic_scores_5():
    assert calculate_lead_score(_lead(utm_source="organic")) == 5


def test_utm_unknown_scores_0_no_misranking():
    # Untracked utm values get 0 — better to under-score than misrank.
    assert calculate_lead_score(_lead(utm_source="some_random_partner")) == 0


# ---------- Plan-interest signal ---------------------------------

def test_plan_interest_premium_scores_20():
    # 10 for direct traffic + 20 for plan interest = 30
    assert calculate_lead_score(_lead(interests=["premium plan"])) == 30


def test_plan_interest_monthly_scores_20():
    assert calculate_lead_score(_lead(interests=["monthly billing"])) == 30


def test_plan_interest_case_insensitive():
    assert calculate_lead_score(_lead(interests=["PRICING info"])) == 30


def test_plan_interest_only_matches_keywords():
    # Random non-keyword interests = no bonus
    assert calculate_lead_score(_lead(interests=["mascara", "puppies"])) == 10


# ---------- Phone signal -----------------------------------------

def test_phone_provided_scores_15():
    assert calculate_lead_score(_lead(phone="+91 9876543210")) == 25


def test_phone_empty_or_whitespace_only_no_bonus():
    assert calculate_lead_score(_lead(phone="   ")) == 10


# ---------- Notes-quality signal ---------------------------------

def test_notes_sweet_spot_scores_10():
    # 60 chars — in the [50, 200] sweet spot
    notes = "Looking for the CPMAI exam prep tailored to AI ML domains."
    assert 50 <= len(notes) <= 200
    assert calculate_lead_score(_lead(notes=notes)) == 20


def test_notes_too_short_no_bonus():
    assert calculate_lead_score(_lead(notes="hi")) == 10


def test_notes_too_long_no_bonus():
    # Past the 200-char ceiling — paste-of-random-content territory
    assert calculate_lead_score(_lead(notes="x" * 500)) == 10


# ---------- Repeat-visitor signal --------------------------------

def test_repeat_visitor_adds_15():
    assert calculate_lead_score(_lead(), is_repeat=True) == 25
    assert calculate_lead_score(_lead(), is_repeat=False) == 10


# ---------- Landing-page signal ----------------------------------

def test_pricing_landing_scores_15():
    assert calculate_lead_score(_lead(
        landing_url="https://cpmaiexamprep.com/pricing")) == 25


def test_exams_landing_scores_10():
    assert calculate_lead_score(_lead(
        landing_url="https://cpmaiexamprep.com/exams")) == 20


def test_other_landing_scores_5():
    assert calculate_lead_score(_lead(
        landing_url="https://cpmaiexamprep.com/blog/foo")) == 15


# ---------- Composite / clipping ---------------------------------

def test_full_hot_lead_clips_at_100():
    # Hypothetical lead with every positive signal: google + premium +
    # phone + notes + repeat + /pricing = 20+20+15+10+15+15 = 95.
    # Headroom of 5 today; clipping check guards against future rules
    # that might overflow 100.
    notes = "Looking for the CPMAI exam prep tailored to AI ML domains."
    score = calculate_lead_score(_lead(
        utm_source="google",
        interests=["monthly premium plan"],
        phone="+91 9876543210",
        notes=notes,
        landing_url="https://cpmaiexamprep.com/pricing",
    ), is_repeat=True)
    assert score == 95
    assert score <= 100


# ---------- score_tier ------------------------------------------

def test_tier_buckets():
    # Sweep boundary values so future tweaks to thresholds get caught.
    assert score_tier(None) == "unknown"
    assert score_tier(0)   == "cold"
    assert score_tier(39)  == "cold"
    assert score_tier(40)  == "warm"
    assert score_tier(69)  == "warm"
    assert score_tier(70)  == "hot"
    assert score_tier(100) == "hot"
