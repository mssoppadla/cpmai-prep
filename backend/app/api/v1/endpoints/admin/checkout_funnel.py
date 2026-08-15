"""Checkout Follow-ups — the "who almost paid" screen.

One read-only endpoint joining what already exists (payments + journey
events + user contacts) so the operator stops stitching three admin
screens together by hand:

  * needs_followup — payments that started but didn't finish: status
    "failed" (any age in window) or "created" older than
    ABANDONED_AFTER_MIN (still-fresh "created" rows are people mid-
    checkout right now — nagging them would be premature). Buyers who
    LATER captured a payment inside the window are excluded: they
    finished, there is nothing to follow up.
  * pricing_visitors — /pricing page.views in the window from people
    with NO payment row in the window. Signed-in visitors carry
    contact details; anonymous ones carry anon_id + geo/device so the
    operator can jump to their session timeline in Visitor Insights.
  * summary — visitors / started / captured for a conversion glance.

Deliberately read-only and admin-gated; window is minutes-based like
/admin/error-logs so the same mental model applies.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.journey_event import JourneyEvent
from app.models.payment import Payment
from app.models.plan import Plan
from app.models.user import User

router = APIRouter()

# "created" younger than this is someone mid-checkout, not abandoned.
ABANDONED_AFTER_MIN = 15


def _user_out(u: "User | None") -> dict | None:
    if not u:
        return None
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "whatsapp": getattr(u, "whatsapp", None),
        "linkedin_id": getattr(u, "linkedin_id", None),
    }


@router.get("")
def checkout_funnel(
    window_minutes: int = Query(default=1440, ge=5, le=43_200),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=window_minutes)
    abandoned_cutoff = now - timedelta(minutes=ABANDONED_AFTER_MIN)

    # ── Who completed (used for exclusions + summary) ────────────────
    captured_user_ids = {
        uid for (uid,) in db.query(Payment.user_id)
        .filter(Payment.created_at >= since,
                Payment.status == "captured",
                Payment.user_id.isnot(None)).all()
    }

    # ── Needs follow-up: failed, or created-and-stale ────────────────
    followup_rows = (
        db.query(Payment, User, Plan)
        .outerjoin(User, User.id == Payment.user_id)
        .outerjoin(Plan, Plan.id == Payment.plan_id)
        .filter(Payment.created_at >= since)
        .filter(
            (Payment.status == "failed")
            | ((Payment.status == "created")
               & (Payment.created_at <= abandoned_cutoff))
        )
        .order_by(Payment.created_at.desc())
        .limit(200)
        .all()
    )
    needs_followup = [
        {
            "payment_id": p.id,
            "status": p.status,
            "provider_order_id": p.provider_order_id,
            "plan_name": pl.name if pl else None,
            "amount_paise": p.amount_paise,
            "currency": p.currency,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "user": _user_out(u),
        }
        for p, u, pl in followup_rows
        if p.user_id not in captured_user_ids  # they finished later
    ]

    # ── Pricing visitors with no payment activity in the window ─────
    ordered_user_ids = {
        uid for (uid,) in db.query(Payment.user_id)
        .filter(Payment.created_at >= since,
                Payment.user_id.isnot(None)).all()
    }
    views = (
        db.query(JourneyEvent)
        .filter(JourneyEvent.event == "page.view",
                JourneyEvent.path == "/pricing",
                JourneyEvent.created_at >= since)
        .order_by(JourneyEvent.created_at.desc())
        .limit(1000)
        .all()
    )
    # Collapse to one row per identity (latest view wins); a visitor is
    # "identified" by user_id when signed in, else anon_id.
    seen: set = set()
    visitors = []
    user_cache: dict[int, User | None] = {}
    for ev in views:
        key = ("u", ev.user_id) if ev.user_id else ("a", ev.anon_id)
        if key in seen or (ev.user_id is None and not ev.anon_id):
            continue
        seen.add(key)
        if ev.user_id and ev.user_id in ordered_user_ids:
            continue  # they at least started checkout — other list's job
        u = None
        if ev.user_id:
            if ev.user_id not in user_cache:
                user_cache[ev.user_id] = db.get(User, ev.user_id)
            u = user_cache[ev.user_id]
        visitors.append({
            "user": _user_out(u),
            "anon_id": ev.anon_id if not ev.user_id else None,
            "last_seen_at": ev.created_at.isoformat() if ev.created_at else None,
            "country": ev.country,
            "city": ev.city,
            "device": ev.device,
            "utm_source": ev.utm_source,
        })
        if len(visitors) >= 200:
            break

    started = (db.query(func.count(Payment.id))
               .filter(Payment.created_at >= since).scalar() or 0)
    captured = (db.query(func.count(Payment.id))
                .filter(Payment.created_at >= since,
                        Payment.status == "captured").scalar() or 0)

    return {
        "window_minutes": window_minutes,
        "since": since.isoformat(),
        "needs_followup": needs_followup,
        "pricing_visitors": visitors,
        "summary": {
            "visitors": len(seen),
            "started": started,
            "captured": captured,
            "needs_followup": len(needs_followup),
        },
    }
