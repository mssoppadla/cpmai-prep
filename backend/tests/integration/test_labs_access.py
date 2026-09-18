"""Lab access modes × visitors × plans — the policy behind /labs.

Covers: the registry-driven index, the four access modes, plan
entitlement through perks["labs"] (purchase-equivalent admin grant,
untick, revoke, expiry), legacy no-plan subscriptions, the embed token
narrowing to CURRENT settings, and plan-schema validation.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core import settings_store as ss_module
from app.core.labs_registry import LABS, get_lab
from app.models.subscription import Subscription
from app.services.labs_access import sign_lab_token, verify_lab_token
from tests.conftest import auth_header

PLANS = "/api/v1/admin/plans"
GRANT = "/api/v1/admin/users/{uid}/subscriptions"
REVOKE = "/api/v1/admin/subscriptions/{sid}/revoke"
WALK = "phase-2-3-walkthrough"


@pytest.fixture(autouse=True)
def _fresh_settings():
    ss_module._local.clear()
    try:
        from app.core.redis import redis_client
        for k in redis_client.keys(ss_module.CACHE_PREFIX + "*"):
            redis_client.delete(k)
    except Exception:
        pass
    yield
    ss_module._local.clear()


def _set(client, admin, key, value):
    r = client.patch(f"/api/v1/admin/settings/{key}",
                     headers=auth_header(client, admin.email),
                     json={"value": value})
    assert r.status_code == 200, r.text


def _mk_plan(client, admin, slug, labs, active=True):
    r = client.post(PLANS, headers=auth_header(client, admin.email),
                    json={"name": f"Plan {slug}", "slug": slug,
                          "bundle_type": "custom", "base_price_paise": 100000,
                          "duration_days": 365, "is_active": active,
                          "perks": {"labs": labs}})
    assert r.status_code == 201, r.text
    return r.json()


def _grant(client, admin, uid, plan_id, days=30):
    r = client.post(GRANT.format(uid=uid),
                    headers=auth_header(client, admin.email),
                    json={"plan_id": plan_id, "period_days": days,
                          "reason": "labs test"})
    assert r.status_code == 201, r.text
    return r.json()


def _access(client, slug, user=None, t=None):
    h = auth_header(client, user.email) if user else {}
    q = f"?t={t}" if t else ""
    r = client.get(f"/api/v1/content/labs/{slug}/access{q}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------ registry
def test_registry_is_consistent():
    slugs = [l.slug for l in LABS]
    assert len(slugs) == len(set(slugs))
    for lab in LABS:
        ids = [s.id for s in lab.sections]
        assert len(ids) == len(set(ids)), lab.slug
        if lab.sections:
            assert lab.gated, f"{lab.slug}: sections need an asset"
        assert lab.group in ("interactive", "walkthrough")


def test_index_lists_every_lab_free_by_default(client):
    r = client.get("/api/v1/content/labs")
    assert r.status_code == 200
    body = r.json()
    assert [b["slug"] for b in body] == [l.slug for l in sorted(LABS, key=lambda l: l.order)]
    for b in body:
        assert b["mode"] == "free" and b["enabled"] is True
    walk = next(b for b in body if b["slug"] == WALK)
    assert walk["cuttable"] is True and len(walk["sections"]) == 22
    assert walk["title"] == "CPMAI Phase II & III Walkthrough"


def test_unknown_slug_404s(client):
    assert client.get("/api/v1/content/labs/nope/access").status_code == 404


# ------------------------------------------------------------ modes
def test_free_mode_full_for_everyone(client, user):
    assert _access(client, WALK)["full"] is True
    assert _access(client, WALK, user)["full"] is True


def test_signin_mode_ignores_plans(client, admin, user):
    _set(client, admin, "labs.walkthrough_access", "signin")
    anon = _access(client, WALK)
    assert anon["full"] is False and anon["reason"] == "signin"
    assert anon["free_upto_index"] == -1
    assert _access(client, WALK, user)["full"] is True   # no plan needed


def test_preview_mode_cuts_at_section(client, admin, user):
    _set(client, admin, "labs.walkthrough_access", "preview")
    _set(client, admin, "labs.walkthrough_free_upto", "s6")
    a = _access(client, WALK, user)
    assert a["full"] is False and a["reason"] == "plan"
    assert a["free_upto_index"] == 7
    assert [s["id"] for s in a["locked_sections"]][0] == "s7"
    assert len(a["locked_sections"]) == 22 - 8
    assert a["plans"] == []          # nothing ticked yet → generic CTA


def test_preview_without_cut_point_shows_nothing(client, admin):
    _set(client, admin, "labs.walkthrough_access", "preview")
    a = _access(client, WALK)
    assert a["free_upto_index"] == -1 and len(a["locked_sections"]) == 22


def test_plan_mode_locks_body(client, admin, user):
    _set(client, admin, "labs.walkthrough_access", "plan")
    _set(client, admin, "labs.walkthrough_free_upto", "s6")   # ignored in plan mode
    a = _access(client, WALK, user)
    assert a["full"] is False and a["free_upto_index"] == -1


def test_invalid_mode_and_cut_are_rejected(client, admin):
    h = auth_header(client, admin.email)
    r = client.patch("/api/v1/admin/settings/labs.walkthrough_access",
                     headers=h, json={"value": "vip"})
    assert r.status_code == 422
    r = client.patch("/api/v1/admin/settings/labs.walkthrough_free_upto",
                     headers=h, json={"value": "sec99"})
    assert r.status_code == 422


def test_preview_on_uncuttable_lab_behaves_like_plan(client, admin, user):
    _set(client, admin, "labs.pipeline_lab_access", "preview")
    a = _access(client, "data-pipeline-navigator", user)
    assert a["mode"] == "plan" and a["full"] is False


def test_disabled_lab_reports_disabled(client, admin, user):
    _set(client, admin, "labs.walkthrough_enabled", False)
    a = _access(client, WALK, user)
    assert a["enabled"] is False and a["full"] is False and a["reason"] == "disabled"


# ------------------------------------------------------------ plans
def test_plan_ticking_lab_unlocks_existing_subscriber(client, admin, user):
    _set(client, admin, "labs.walkthrough_access", "plan")
    plan = _mk_plan(client, admin, "course-plan", labs=[])
    _grant(client, admin, user.id, plan["id"])
    assert _access(client, WALK, user)["full"] is False
    # admin ticks the lab later → already-subscribed user unlocks immediately
    r = client.patch(f"{PLANS}/{plan['id']}",
                     headers=auth_header(client, admin.email),
                     json={"perks": {"labs": [WALK]}})
    assert r.status_code == 200, r.text
    assert r.json()["labs"] == [{"slug": WALK, "title": "CPMAI Phase II & III Walkthrough"}]
    a = _access(client, WALK, user)
    assert a["full"] is True
    assert a["plans"] == [{"slug": "course-plan", "name": "Plan course-plan"}]


def test_plan_without_this_lab_does_not_unlock(client, admin, user):
    _set(client, admin, "labs.walkthrough_access", "plan")
    other = _mk_plan(client, admin, "exam-bundle", labs=["ml-training-pipeline"])
    _grant(client, admin, user.id, other["id"])
    assert _access(client, WALK, user)["full"] is False
    assert _access(client, "ml-training-pipeline", user)["full"] is True


def test_untick_revoke_and_expiry_remove_access(client, admin, user, db):
    _set(client, admin, "labs.walkthrough_access", "plan")
    plan = _mk_plan(client, admin, "cp", labs=[WALK])
    sub = _grant(client, admin, user.id, plan["id"])
    assert _access(client, WALK, user)["full"] is True
    # untick
    client.patch(f"{PLANS}/{plan['id']}", headers=auth_header(client, admin.email),
                 json={"perks": {"labs": []}})
    assert _access(client, WALK, user)["full"] is False
    # re-tick, then revoke the subscription
    client.patch(f"{PLANS}/{plan['id']}", headers=auth_header(client, admin.email),
                 json={"perks": {"labs": [WALK]}})
    assert _access(client, WALK, user)["full"] is True
    r = client.post(REVOKE.format(sid=sub["id"]),
                    headers=auth_header(client, admin.email),
                    json={"reason": "test"})
    assert r.status_code == 200, r.text
    assert _access(client, WALK, user)["full"] is False
    # a fresh grant that has already expired grants nothing
    row = Subscription(user_id=user.id, plan="cp", plan_id=plan["id"],
                       status="active", source="manual_admin_grant",
                       expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    db.add(row); db.commit()
    assert _access(client, WALK, user)["full"] is False


def test_legacy_subscription_without_plan_unlocks_everything(client, admin, user, db):
    _set(client, admin, "labs.walkthrough_access", "plan")
    db.add(Subscription(user_id=user.id, plan="pro", plan_id=None, status="active"))
    db.commit()
    assert _access(client, WALK, user)["full"] is True


def test_lock_panel_names_only_active_plans_that_tick_the_lab(client, admin):
    _set(client, admin, "labs.walkthrough_access", "plan")
    _mk_plan(client, admin, "a-plan", labs=[WALK])
    _mk_plan(client, admin, "b-plan", labs=["nested-cross-validation"])
    _mk_plan(client, admin, "c-plan", labs=[WALK], active=False)
    a = _access(client, WALK)
    assert [p["slug"] for p in a["plans"]] == ["a-plan"]


def test_public_plans_carry_lab_titles(client, admin):
    _mk_plan(client, admin, "with-labs", labs=[WALK, "nested-cross-validation"])
    r = client.get("/api/v1/pricing/plans")
    assert r.status_code == 200
    plan = next(p for p in r.json() if p["slug"] == "with-labs")
    assert [l["slug"] for l in plan["labs"]] == [WALK, "nested-cross-validation"]


def test_plan_rejects_unknown_lab_slug(client, admin):
    r = client.post(PLANS, headers=auth_header(client, admin.email),
                    json={"name": "Bad", "slug": "bad", "bundle_type": "custom",
                          "base_price_paise": 100000,
                          "perks": {"labs": ["not-a-lab"]}})
    assert r.status_code == 422


# ------------------------------------------------------------ tokens
def test_embed_token_round_trips_and_narrows_to_live_settings(client, admin, user):
    _set(client, admin, "labs.walkthrough_access", "signin")
    a = _access(client, WALK, user)
    assert a["full"] is True
    tok = a["embed_token"]
    claims = verify_lab_token(tok, WALK)
    assert claims and claims["basis"] == "user" and claims["sub"] == str(user.id)
    assert verify_lab_token(tok, "ml-training-pipeline") is None
    # the embed route replays the token with no bearer → still full
    assert _access(client, WALK, t=tok)["full"] is True
    # admin tightens the lab to plan-only → the SAME token no longer unlocks
    _set(client, admin, "labs.walkthrough_access", "plan")
    assert _access(client, WALK, t=tok)["full"] is False
    # garbage token degrades to anonymous, never 4xx
    assert _access(client, WALK, t="nonsense")["full"] is False


def test_token_minted_while_free_grants_nothing_once_gated(client, admin):
    tok = _access(client, WALK)["embed_token"]      # free mode
    _set(client, admin, "labs.walkthrough_access", "plan")
    assert _access(client, WALK, t=tok)["full"] is False
