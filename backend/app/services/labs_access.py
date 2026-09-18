"""Lab access resolution — the ONE place that decides what a visitor may
see of a lab.

Inputs: the lab's admin settings (mode, cut point, enabled, title), the
visitor (None / a User) and the visitor's live subscriptions. Output: a
``LabAccess`` that both the JSON access endpoint and the embed route
(via a signed, short-lived lab token) consume. The frontend never
re-derives policy; it only renders what this module says.

Entitlement rule (mirrors the exam-set paywall, see
``exam_service._can_access_exam_set``):
  * a live subscription = status 'active', not revoked, not expired;
  * a live subscription with NO plan_id (legacy) unlocks every lab;
  * otherwise the lab must be listed in the plan's perks["labs"].
Course enrolments on their own (admin_grant without a subscription) do
NOT unlock labs — grant the plan instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.labs_registry import (
    ACCESS_MODES, LabDef, normalise_perk_labs,
)
from app.core.security import JWT_ALGORITHM
from app.core.settings_store import settings_store
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User


LAB_TOKEN_TTL_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class LabSettings:
    enabled: bool
    title: str
    mode: str          # one of ACCESS_MODES
    free_upto: str     # section id, "" = none


@dataclass
class LabAccess:
    lab: LabDef
    settings: LabSettings
    full: bool
    free_upto_index: int          # last free section index; -1 = none (only meaningful when not full)
    reason: str                   # "ok" | "signin" | "plan" | "disabled"
    plans: list[dict] = field(default_factory=list)   # [{"slug","name"}] plans that unlock this lab
    user_id: int = 0
    basis: str = "anon"           # what the visitor proved: anon | user (logged in) | plan (entitled)

    @property
    def mode(self) -> str:
        return self.settings.mode

    @property
    def locked_sections(self) -> list:
        if self.full:
            return []
        return list(self.lab.sections[self.free_upto_index + 1:])


def lab_settings(lab: LabDef) -> LabSettings:
    mode = settings_store.get_str(lab.setting("access"), "free")
    if mode not in ACCESS_MODES or not lab.gated:
        mode = "free"
    if mode == "preview" and not lab.cuttable:
        mode = "plan"
    return LabSettings(
        enabled=settings_store.get_bool(lab.setting("enabled"), True),
        title=(settings_store.get_str(lab.setting("title"), "") or lab.title)[:80],
        mode=mode,
        free_upto=settings_store.get_str(lab.setting("free_upto"), ""),
    )


def _live_subscriptions(db: Session, user_id: int) -> list[Subscription]:
    now = datetime.now(timezone.utc)
    return (db.query(Subscription)
            .filter(Subscription.user_id == user_id,
                    Subscription.status == "active",
                    Subscription.revoked_at.is_(None))
            .filter((Subscription.expires_at.is_(None))
                    | (Subscription.expires_at > now))
            .all())


def user_unlocks_lab(db: Session, user: User | None, slug: str) -> bool:
    """True when one of the user's live subscriptions unlocks ``slug``."""
    if user is None:
        return False
    subs = _live_subscriptions(db, user.id)
    if not subs:
        return False
    if any(s.plan_id is None for s in subs):
        return True     # legacy blanket-access rows
    plan_ids = {s.plan_id for s in subs}
    for plan in db.query(Plan).filter(Plan.id.in_(plan_ids)).all():
        if slug in normalise_perk_labs(plan.perks):
            return True
    return False


def plans_unlocking(db: Session, slug: str) -> list[dict]:
    """Active, on-sale plans that list this lab — what the lock panel
    names. Ordered like the pricing page."""
    out = []
    for plan in (db.query(Plan).filter(Plan.is_active.is_(True))
                 .order_by(Plan.display_order, Plan.id).all()):
        if slug in normalise_perk_labs(plan.perks):
            out.append({"slug": plan.slug, "name": plan.name})
    return out


def resolve_access(db: Session, lab: LabDef, user: User | None) -> LabAccess:
    st = lab_settings(lab)
    uid = user.id if user else 0
    if not st.enabled:
        return LabAccess(lab, st, full=False, free_upto_index=-1,
                         reason="disabled", user_id=uid)
    basis = "user" if user is not None else "anon"
    if st.mode == "free":
        return LabAccess(lab, st, full=True, free_upto_index=-1, reason="ok",
                         user_id=uid, basis=basis)
    if st.mode == "signin":
        if user is not None:
            return LabAccess(lab, st, full=True, free_upto_index=-1, reason="ok",
                             user_id=uid, basis="user")
        return LabAccess(lab, st, full=False, free_upto_index=-1, reason="signin",
                         user_id=uid, basis="anon")
    # preview / plan
    plans = plans_unlocking(db, lab.slug)
    if user_unlocks_lab(db, user, lab.slug):
        return LabAccess(lab, st, full=True, free_upto_index=-1, reason="ok",
                         plans=plans, user_id=uid, basis="plan")
    upto = lab.section_index(st.free_upto) if st.mode == "preview" else -1
    return LabAccess(lab, st, full=False, free_upto_index=upto,
                     reason="plan", plans=plans, user_id=uid, basis=basis)


# ------------------------------------------------------------ tokens
# The embed route (an <iframe src>) cannot carry an Authorization header,
# so the access endpoint hands the browser a short-lived token that
# encodes the DECISION (not the identity). The embed route verifies it
# and serves exactly what the decision allows. Anonymous visitors need
# no token: the route resolves them as user=None.

def sign_lab_token(access: LabAccess) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "type": "lab",
        "slug": access.lab.slug,
        "basis": access.basis,
        "sub": str(access.user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=LAB_TOKEN_TTL_SECONDS)).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_lab_token(token: str, slug: str) -> dict | None:
    """Claims for a valid lab token bound to ``slug``; None otherwise.
    Never raises — an invalid token simply degrades to anonymous."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != "lab" or payload.get("slug") != slug:
        return None
    return payload


def access_from_token(db: Session, lab: LabDef, claims: dict) -> LabAccess:
    """Rebuild a LabAccess from token claims against the CURRENT
    settings. The token carries only what the visitor PROVED when it
    was minted (anon / logged in / plan member), so an admin tightening
    a lab mid-session takes effect at the next load and a token minted
    while the lab was free unlocks nothing once it is plan-gated."""
    st = lab_settings(lab)
    live = resolve_access(db, lab, None)       # what anonymous gets right now
    if not st.enabled or st.mode == "free":
        return live
    basis = claims.get("basis") or "anon"
    uid = int(claims.get("sub") or 0)
    unlocked = (basis in ("user", "plan")) if st.mode == "signin" else basis == "plan"
    if unlocked:
        return LabAccess(lab, st, full=True, free_upto_index=-1, reason="ok",
                         plans=live.plans, user_id=uid, basis=basis)
    return LabAccess(lab, st, full=False, free_upto_index=live.free_upto_index,
                     reason=live.reason, plans=live.plans, user_id=uid, basis=basis)
