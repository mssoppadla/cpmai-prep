"""Multi-gateway control plane — Phase 1 pins (spec T1-T6, T11-adjacent).

docs/payments-multi-gateway-spec.md. Core promises:
  * defaults reproduce the legacy behavior byte-for-byte (sentinel path)
  * listing flags + display mode drive /payments/gateway-options
  * a tampered/unlisted provider_config_id can never mint an order
  * the kill switch stops non-INR instantly, INR never affected
  * creation-time fallback walks the listed order only when enabled
  * webhooks verify against EVERY enabled Razorpay account's secret
  * the INR rail can never be fully unlisted
"""
import pytest

from tests.conftest import auth_header
from app.core import settings_store as ss_module
from app.services.payment_registry import PaymentRegistry
from app.models.payment_provider import PaymentProviderConfig
from app.models.plan import Plan


@pytest.fixture(autouse=True)
def _fresh_payment_state():
    """These tests toggle runtime settings (display mode, kill switch)
    and provider rows. The settings store's in-process cache (30s TTL)
    outlives the per-test DB, so one test's toggle would leak into the
    next — clear both cache layers and the registry around every test."""
    def _clear():
        ss_module._local.clear()
        # Redis layer too (fakeredis persists across tests): drop only
        # the settings-cache keys, not unrelated state.
        try:
            from app.core.redis import redis_client
            for k in redis_client.keys(ss_module.CACHE_PREFIX + "*"):
                redis_client.delete(k)
        except Exception:
            pass
        PaymentRegistry.invalidate()
    _clear()
    yield
    _clear()


def _mk_provider(client, admin, name, ptype="razorpay", **listing):
    """Create a provider via the real admin API, then apply listing."""
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/payment-providers", headers=h, json={
        "name": name, "provider_type": ptype, "mode": "test",
        "display_name": name.title(),
        "public_key": f"rzp_test_{name}", "api_secret": f"secret_{name}",
        "webhook_secret": f"whsec_{name}",
        "is_enabled": True, "priority": 100,
    })
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    if listing:
        r = client.patch(f"/api/v1/admin/payment-providers/{pid}/listing",
                         headers=h, json=listing)
        assert r.status_code == 200, r.text
    return pid


def _seed_plan(db):
    plan = Plan(name="CP Plan", slug="cp-plan", bundle_type="exam_bundle",
                base_price_paise=99900, currency="INR", duration_days=365,
                perks={}, is_active=True, display_order=10)
    db.add(plan); db.commit(); db.refresh(plan)
    return plan


# ── T1: gateway-options ──────────────────────────────────────────────

def test_options_default_auto_no_listing_is_empty_and_harmless(client):
    r = client.get("/api/v1/payments/gateway-options?currency=USD")
    assert r.status_code == 200
    assert r.json() == {"mode": "auto", "options": []}


def test_options_choice_mode_lists_by_rank(client, admin):
    a = _mk_provider(client, admin, "companyrzp",
                     listed_for_intl=True, intl_rank=20)
    b = _mk_provider(client, admin, "stripeco", listed_for_intl=True,
                     intl_rank=10)
    h = auth_header(client, admin.email)
    client.patch("/api/v1/admin/settings/payments.intl_display_mode",
                 headers=h, json={"value": "choice"})
    r = client.get("/api/v1/payments/gateway-options?currency=USD").json()
    assert r["mode"] == "choice"
    assert [o["provider_config_id"] for o in r["options"]] == [b, a]
    assert r["options"][0]["label"] == "Stripeco"


def test_options_auto_mode_returns_single_head(client, admin):
    _mk_provider(client, admin, "gwone", listed_for_intl=True, intl_rank=5)
    _mk_provider(client, admin, "gwtwo", listed_for_intl=True, intl_rank=9)
    r = client.get("/api/v1/payments/gateway-options?currency=USD").json()
    assert r["mode"] == "auto"
    assert len(r["options"]) == 1


def test_options_inr_always_single_even_in_choice_mode(client, admin):
    _mk_provider(client, admin, "inrone", listed_for_inr=True)
    _mk_provider(client, admin, "inrtwo", listed_for_inr=True)
    h = auth_header(client, admin.email)
    client.patch("/api/v1/admin/settings/payments.intl_display_mode",
                 headers=h, json={"value": "choice"})
    r = client.get("/api/v1/payments/gateway-options?currency=INR").json()
    assert r["mode"] == "auto" and len(r["options"]) == 1


def test_options_kill_switch_empties_intl_not_inr(client, admin):
    _mk_provider(client, admin, "gwintl", listed_for_intl=True)
    _mk_provider(client, admin, "gwinr", listed_for_inr=True)
    h = auth_header(client, admin.email)
    client.patch("/api/v1/admin/settings/payments.intl_enabled",
                 headers=h, json={"value": False})
    assert client.get(
        "/api/v1/payments/gateway-options?currency=USD").json()["options"] == []
    assert len(client.get(
        "/api/v1/payments/gateway-options?currency=INR").json()["options"]) == 1


# ── T2: order creation honors/validates the choice ───────────────────

def test_order_rejects_unlisted_provider_config_id(client, db, user, admin):
    _seed_plan(db)
    enabled_unlisted = _mk_provider(client, admin, "unlisted")  # no listing
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "cp-plan", "currency": "INR",
        "provider_config_id": enabled_unlisted,
    })
    assert r.status_code == 422, r.text


def test_order_rejects_unknown_provider_config_id(client, db, user):
    _seed_plan(db)
    h = auth_header(client, user.email)
    r = client.post("/api/v1/payments/orders", headers=h, json={
        "plan_slug": "cp-plan", "currency": "INR",
        "provider_config_id": 99999,
    })
    assert r.status_code == 422, r.text


# ── T4/T11: listing PATCH guards ─────────────────────────────────────

def test_cannot_unlist_last_inr_gateway(client, admin):
    pid = _mk_provider(client, admin, "onlyinr", listed_for_inr=True)
    h = auth_header(client, admin.email)
    r = client.patch(f"/api/v1/admin/payment-providers/{pid}/listing",
                     headers=h, json={"listed_for_inr": False})
    assert r.status_code == 422, r.text


def test_unlist_allowed_when_another_inr_entry_exists(client, admin):
    a = _mk_provider(client, admin, "inra", listed_for_inr=True)
    _mk_provider(client, admin, "inrb", listed_for_inr=True)
    h = auth_header(client, admin.email)
    r = client.patch(f"/api/v1/admin/payment-providers/{a}/listing",
                     headers=h, json={"listed_for_inr": False})
    assert r.status_code == 200
    assert r.json()["listed_for_inr"] is False


def test_listing_patch_requires_admin(client, user, admin):
    pid = _mk_provider(client, admin, "sec")
    r = client.patch(f"/api/v1/admin/payment-providers/{pid}/listing",
                     headers=auth_header(client, user.email),
                     json={"listed_for_intl": True})
    assert r.status_code in (401, 403)


def test_new_payment_settings_editable_and_validated(client, admin):
    h = auth_header(client, admin.email)
    ok = client.patch("/api/v1/admin/settings/payments.intl_display_mode",
                      headers=h, json={"value": "choice"})
    assert ok.status_code == 200
    bad = client.patch("/api/v1/admin/settings/payments.intl_display_mode",
                       headers=h, json={"value": "everyone"})
    assert bad.status_code == 422


# ── T3/T5: fallback + multi-account webhook (unit-level seams) ───────

def test_candidates_sentinel_when_no_listing(db):
    """Pre-0047-shaped data (no listing rows) → legacy sentinel [None]:
    create_order resolves via get_for_currency, the seam the legacy
    tests patch. This is the no-regression guarantee."""
    assert PaymentRegistry.candidate_config_ids("INR") == [None]
    assert PaymentRegistry.candidate_config_ids("USD") == [None]


def test_candidates_follow_listing_order(client, admin):
    a = _mk_provider(client, admin, "ca", listed_for_intl=True, intl_rank=30)
    b = _mk_provider(client, admin, "cb", listed_for_intl=True, intl_rank=3)
    assert PaymentRegistry.candidate_config_ids("USD") == [b, a]
    assert PaymentRegistry.candidate_config_ids("USD", requested_id=a) == [a]


# ── INR revenue split (personal vs company account) ──────────────────

def _set_split(client, admin, split):
    h = auth_header(client, admin.email)
    r = client.patch("/api/v1/admin/settings/payments.inr_split",
                     headers=h, json={"value": split})
    assert r.status_code == 200, r.text


def test_inr_split_routes_by_weight(client, admin, monkeypatch):
    from app.services import payment_registry as reg
    a = _mk_provider(client, admin, "personalacct", listed_for_inr=True)
    b = _mk_provider(client, admin, "companyacct", listed_for_inr=True)
    _set_split(client, admin, {str(a): 70, str(b): 30})

    # Draw lands in the first 70% → personal account heads the order.
    monkeypatch.setattr(reg, "_rand", lambda: 0.10)
    assert PaymentRegistry.candidate_config_ids("INR") == [a, b]
    # Draw lands in the last 30% → company account heads; personal
    # stays behind it as the fallback.
    monkeypatch.setattr(reg, "_rand", lambda: 0.90)
    assert PaymentRegistry.candidate_config_ids("INR") == [b, a]


def test_inr_split_empty_or_stale_is_legacy_order(client, admin,
                                                  monkeypatch):
    from app.services import payment_registry as reg
    a = _mk_provider(client, admin, "soloinr", listed_for_inr=True)
    b = _mk_provider(client, admin, "otherinr", listed_for_inr=True)
    baseline = PaymentRegistry.candidate_config_ids("INR")
    # Weights referencing ids that are NOT INR-listed (e.g. a delisted
    # account) can't hijack routing.
    _set_split(client, admin, {"99998": 50, "99999": 50})
    monkeypatch.setattr(reg, "_rand", lambda: 0.99)
    assert PaymentRegistry.candidate_config_ids("INR") == baseline
    assert set(baseline) == {a, b}


def test_inr_split_never_affects_intl(client, admin, monkeypatch):
    from app.services import payment_registry as reg
    a = _mk_provider(client, admin, "intlone", listed_for_intl=True,
                     intl_rank=1)
    b = _mk_provider(client, admin, "intltwo", listed_for_intl=True,
                     intl_rank=2)
    _set_split(client, admin, {str(a): 1, str(b): 99})
    monkeypatch.setattr(reg, "_rand", lambda: 0.99)
    assert PaymentRegistry.candidate_config_ids("USD") == [a, b]


def test_intl_split_routes_by_weight_and_spares_inr(client, admin,
                                                    monkeypatch):
    from app.services import payment_registry as reg
    h = auth_header(client, admin.email)
    a = _mk_provider(client, admin, "intlrzp", listed_for_intl=True,
                     intl_rank=1, listed_for_inr=True)
    b = _mk_provider(client, admin, "intlstripe", listed_for_intl=True,
                     intl_rank=2, listed_for_inr=True)
    r = client.patch("/api/v1/admin/settings/payments.intl_split",
                     headers=h, json={"value": {str(a): 50, str(b): 50}})
    assert r.status_code == 200, r.text

    # Equal split: draw in the first half → a; second half → b.
    monkeypatch.setattr(reg, "_rand", lambda: 0.25)
    assert PaymentRegistry.candidate_config_ids("USD") == [a, b]
    monkeypatch.setattr(reg, "_rand", lambda: 0.75)
    assert PaymentRegistry.candidate_config_ids("USD") == [b, a]
    # INR rail has its own (unset) map → untouched rank/priority order.
    assert PaymentRegistry.candidate_config_ids("INR") == [a, b]


def test_intl_split_bypassed_by_explicit_customer_choice(client, admin,
                                                         monkeypatch):
    from app.services import payment_registry as reg
    h = auth_header(client, admin.email)
    a = _mk_provider(client, admin, "chooserzp", listed_for_intl=True,
                     intl_rank=1)
    b = _mk_provider(client, admin, "choosepp", listed_for_intl=True,
                     intl_rank=2)
    client.patch("/api/v1/admin/settings/payments.intl_split",
                 headers=h, json={"value": {str(a): 100, str(b): 0}})
    monkeypatch.setattr(reg, "_rand", lambda: 0.0)   # split would say a
    assert PaymentRegistry.candidate_config_ids(
        "USD", requested_id=b) == [b]


def test_inr_split_single_entry_routes_all_traffic(client, admin,
                                                   monkeypatch):
    """Operator case: '100% of INR to the company account' via
    {company_id: 100} — no need to delist the personal account, which
    stays behind as fallback."""
    from app.services import payment_registry as reg
    a = _mk_provider(client, admin, "persacct", listed_for_inr=True)
    b = _mk_provider(client, admin, "compacct", listed_for_inr=True)
    _set_split(client, admin, {str(b): 100})
    monkeypatch.setattr(reg, "_rand", lambda: 0.0)
    assert PaymentRegistry.candidate_config_ids("INR") == [b, a]
    monkeypatch.setattr(reg, "_rand", lambda: 0.999)
    assert PaymentRegistry.candidate_config_ids("INR") == [b, a]


def test_inr_split_rejects_bad_shapes(client, admin):
    h = auth_header(client, admin.email)
    for bad in (["1", "2"], {"x": 10}, {"1": "lots"}, {"1": 500}):
        r = client.patch("/api/v1/admin/settings/payments.inr_split",
                         headers=h, json={"value": bad})
        assert r.status_code == 422, (bad, r.text)


class _CapturingProvider:
    """Stands in for any gateway class; records what it was asked to
    charge. Accepts the registry's constructor kwargs."""
    name = "razorpay"
    captured: list = []

    def __init__(self, key_id=None, key_secret=None, webhook_secret=None,
                 mode="test", **_cfg):
        self.key_id = key_id

    def create_order(self, amount_minor, receipt=None, currency="INR", **kw):
        _CapturingProvider.captured.append(
            {"amount": amount_minor, "currency": currency})
        return {"id": f"order_{len(_CapturingProvider.captured)}",
                "amount": amount_minor, "currency": currency}


def test_cross_currency_amount_identical_across_gateways(
        client, db, user, admin, monkeypatch):
    """Operator requirement: cross-currency orders must use the daily-
    updated FX conversion, and the amount must be IDENTICAL no matter
    which listed gateway the customer picks — FX happens in the quote,
    BEFORE gateway selection, so a gateway can never change the price."""
    from app.services import payment_registry as reg
    monkeypatch.setitem(reg.PROVIDER_CLASSES, "razorpay", _CapturingProvider)
    _CapturingProvider.captured = []
    PaymentRegistry.invalidate()

    _seed_plan(db)   # ₹999.00
    h = auth_header(client, admin.email)
    # FX via the LIVE system's admin-override channel (the daily cron
    # writes fx_live_raw; overrides win and need no freshness window —
    # same resolution path production quotes use). 1 USD = ₹83.00.
    r = client.patch("/api/v1/admin/settings/pricing.fx_overrides",
                     headers=h, json={"value": {"USD": 83.0}})
    assert r.status_code == 200, r.text

    a = _mk_provider(client, admin, "gwx", listed_for_intl=True, intl_rank=1)
    b = _mk_provider(client, admin, "gwy", listed_for_intl=True, intl_rank=2)
    client.patch("/api/v1/admin/settings/payments.intl_display_mode",
                 headers=h, json={"value": "choice"})

    uh = auth_header(client, user.email)
    for gw in (a, b):
        r = client.post("/api/v1/payments/orders", headers=uh, json={
            "plan_slug": "cp-plan", "currency": "USD",
            "provider_config_id": gw,
        })
        assert r.status_code == 201, r.text
        assert r.json()["currency"] == "USD"

    amounts = [c["amount"] for c in _CapturingProvider.captured]
    currencies = {c["currency"] for c in _CapturingProvider.captured}
    assert len(amounts) == 2
    assert amounts[0] == amounts[1], "gateway choice must never change the price"
    assert currencies == {"USD"}
    # And the amount is the FX conversion of ₹999 at 83.00, not ₹-denominated.
    assert 1100 <= amounts[0] <= 1300, amounts


class _KeyBoundProvider:
    """Fake gateway whose signature check only passes for its own
    key_id — models two Razorpay accounts with distinct secrets."""
    name = "razorpay"

    def __init__(self, key_id=None, key_secret=None, webhook_secret=None,
                 mode="test", **_cfg):
        self.key_id = key_id

    def verify_payment_signature(self, order_id, payment_id, signature):
        return signature == self.key_id


def test_verify_uses_the_account_that_minted_the_order(
        client, db, user, admin, monkeypatch):
    """Prod 2026-08-17: with the 95/5 INR split, orders minted by the
    non-active account failed browser verification ('Invalid payment
    signature') because verify resolved the provider by CURRENCY (the
    active account) instead of by the payment's provider_config_id."""
    from app.services import payment_registry as reg
    from app.models.payment import Payment
    monkeypatch.setitem(reg.PROVIDER_CLASSES, "razorpay", _KeyBoundProvider)
    PaymentRegistry.invalidate()

    plan = _seed_plan(db)
    a = _mk_provider(client, admin, "activeacct", listed_for_inr=True)
    b = _mk_provider(client, admin, "splitacct", listed_for_inr=True)
    h = auth_header(client, admin.email)
    # Make A the "active" pointer — the split-routed order goes to B.
    r = client.patch("/api/v1/admin/settings/payment.active_provider_id",
                     headers=h, json={"value": a})
    assert r.status_code == 200, r.text

    p = Payment(user_id=user.id, plan_id=plan.id, provider_name="razorpay",
                provider_config_id=b, provider_order_id="order_splitb1",
                amount_paise=99900, currency="INR", status="created",
                idempotency_key="idem_splitb1")
    db.add(p); db.commit()

    uh = auth_header(client, user.email)
    # Signature signed by B's key must verify (was 400 pre-fix)...
    r = client.post("/api/v1/payments/verify", headers=uh, json={
        "order_id": "order_splitb1", "payment_id": "pay_x",
        "signature": "rzp_test_splitacct",
    })
    assert r.status_code == 200, r.text
    # ...and A's key must NOT pass for B's order.
    db.refresh(p); p.status = "created"; p.subscription_id = None
    db.commit()
    r = client.post("/api/v1/payments/verify", headers=uh, json={
        "order_id": "order_splitb1", "payment_id": "pay_x",
        "signature": "rzp_test_activeacct",
    })
    assert r.status_code == 400


def test_enabled_by_type_returns_every_enabled_account(client, admin, db):
    a = _mk_provider(client, admin, "wha")
    b = _mk_provider(client, admin, "whb")
    got = [pid for pid, _prov in PaymentRegistry.enabled_by_type("razorpay")]
    assert set([a, b]).issubset(set(got))
    # Disabled accounts drop out (still resolvable by id for history,
    # but never part of webhook verification fan-out).
    row = db.get(PaymentProviderConfig, a)
    row.is_enabled = False
    db.commit()
    PaymentRegistry.invalidate()
    got = [pid for pid, _p in PaymentRegistry.enabled_by_type("razorpay")]
    assert a not in got and b in got
