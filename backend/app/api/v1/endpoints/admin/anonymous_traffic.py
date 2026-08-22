"""Admin view over visitor traffic — known users vs anonymous.

Feeds the Contacts page's Daily/Weekly/Monthly visitors widget from
journey_events (the same data every other analytics surface uses —
previously this read only the assistant widget's audit-log pings, so
it undercounted and could never tell known from anonymous).

Classification, per event row:

  * ``user_id`` set → a KNOWN user's visit.
  * only ``anon_id`` set → look up anon_identity_links:
      - linked and the event is AFTER ``linked_at`` → KNOWN (the
        person signed up earlier; even signed-out visits from that
        browser attribute to their account from that moment on).
      - linked but the event PRE-dates the link → counted as an
        anonymous visit (historical counts are not rewritten), and the
        visitor surfaces in ``signed_up`` — "of M anonymous, K have
        since signed up and are tracked as known going forward".
      - not linked → truly anonymous.
  * neither id (legacy sendBeacon rows) → counts toward ``events``
    only; no visitor identity to bucket.

``returning_anonymous`` = anonymous visitors seen on 2+ distinct days
inside the window — the "same unknown person keeps coming back" count.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_admin_user, get_db
from app.models.anon_identity_link import AnonIdentityLink
from app.models.journey_event import JourneyEvent
from app.models.user import User

router = APIRouter()


# Same window taxonomy the assistant-drift dashboard uses.
_WINDOW_TO_DELTA = {
    "24h": timedelta(hours=24),
    "7d":  timedelta(days=7),
    "30d": timedelta(days=30),
}
WindowLiteral = Literal["24h", "7d", "30d"]


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/summary")
def anonymous_traffic_summary(
    window: WindowLiteral = Query("7d"),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    """Known/anonymous visitor rollup for the selected window.

    Payload::

        {
          "window": "7d", "since": "...Z",
          "totals": {
            "known_users": 5,          // distinct signed-in/linked visitors
            "anonymous": 10,           // distinct unlinked (at event time) visitors
            "signed_up": 2,            // of those, have since created an account
            "returning_anonymous": 3,  // anonymous seen on 2+ distinct days
            "events": 137
          },
          "by_region": [{"country","city","events","known_users","anonymous"}],
          "by_day":    [{"day","events","known_users","anonymous"}]
        }
    """
    since = datetime.now(timezone.utc) - _WINDOW_TO_DELTA[window]

    rows = (db.query(JourneyEvent.user_id, JourneyEvent.anon_id,
                     JourneyEvent.country, JourneyEvent.city,
                     JourneyEvent.created_at)
            .filter(JourneyEvent.created_at >= since)
            .all())

    # Resolve links only for anon_ids actually present in the window.
    window_anon_ids = {r.anon_id for r in rows if r.anon_id}
    links: dict[str, datetime] = {}
    if window_anon_ids:
        for l in (db.query(AnonIdentityLink)
                  .filter(AnonIdentityLink.anon_id.in_(window_anon_ids))
                  .all()):
            links[l.anon_id] = _as_utc(l.linked_at)

    region_events: dict[tuple, int] = defaultdict(int)
    region_known: dict[tuple, set] = defaultdict(set)
    region_anon:  dict[tuple, set] = defaultdict(set)
    day_events: dict[str, int] = defaultdict(int)
    day_known:  dict[str, set] = defaultdict(set)
    day_anon:   dict[str, set] = defaultdict(set)
    known_users: set = set()
    anon_visitors: set[str] = set()
    anon_days: dict[str, set[str]] = defaultdict(set)   # anon_id → days seen
    total_events = 0

    for r in rows:
        total_events += 1
        created = _as_utc(r.created_at)
        day_key = created.date().isoformat()
        region_key = (r.country, r.city)
        region_events[region_key] += 1
        day_events[day_key] += 1

        known_key = None
        anon_key = None
        linked_at = links.get(r.anon_id) if r.anon_id else None
        if linked_at is not None and created < linked_at:
            # Event pre-dates the signup. The login-time backfill stamps
            # user_id onto these rows (so the PROFILE timeline is
            # complete), but the widget's history is never rewritten:
            # they stay anonymous visits here, surfacing in signed_up.
            anon_key = r.anon_id
        elif r.user_id is not None:
            known_key = f"u:{r.user_id}"
        elif linked_at is not None:
            # Previously-signed-up browser revisiting (even signed
            # out): a known user's visit from the link onward.
            known_key = f"a:{r.anon_id}"
        elif r.anon_id:
            anon_key = r.anon_id
        # else: legacy row with no identity — events-only.

        if known_key is not None:
            known_users.add(known_key)
            region_known[region_key].add(known_key)
            day_known[day_key].add(known_key)
        elif anon_key is not None:
            anon_visitors.add(anon_key)
            region_anon[region_key].add(anon_key)
            day_anon[day_key].add(anon_key)
            anon_days[anon_key].add(day_key)

    signed_up = sum(1 for a in anon_visitors if a in links)
    returning_anonymous = sum(1 for days in anon_days.values()
                              if len(days) >= 2)

    by_region = sorted(
        [{"country": c, "city": city, "events": e,
          "known_users": len(region_known[(c, city)]),
          "anonymous": len(region_anon[(c, city)])}
         for (c, city), e in region_events.items()],
        key=lambda d: d["events"], reverse=True,
    )

    # Continuous day series (zero-filled) so the bar chart has no gaps.
    start_day = since.date()
    end_day = datetime.now(timezone.utc).date()
    by_day: list[dict] = []
    cursor: date = start_day
    while cursor <= end_day:
        key = cursor.isoformat()
        by_day.append({
            "day": key,
            "events": day_events.get(key, 0),
            "known_users": len(day_known.get(key, set())),
            "anonymous": len(day_anon.get(key, set())),
        })
        cursor = cursor + timedelta(days=1)

    return {
        "window": window,
        "since": since.isoformat().replace("+00:00", "Z"),
        "totals": {
            "known_users": len(known_users),
            "anonymous": len(anon_visitors),
            "signed_up": signed_up,
            "returning_anonymous": returning_anonymous,
            "events": total_events,
        },
        "by_region": by_region,
        "by_day": by_day,
    }
