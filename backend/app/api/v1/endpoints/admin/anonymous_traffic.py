"""Admin view over anonymous-visitor activity.

Reads the ``assistant.anon.*`` events written by /api/v1/assistant/anon-event.
Returns three rollups for the operator dashboard:

  1. Headline: unique anonymous visitors in the selected window
     (de-duplicated by ``metadata.anon_id``).
  2. By region: ranked list — where unconverted traffic is coming from,
     keyed on (country, city) so the same flavour of "Location" the
     leads table renders below shows up here too.
  3. By day: daily counts — date-wise split for the window.

Why aggregate server-side rather than ship raw rows: even at ~10 anon
bubble-opens per day, a 30-day window can be a few hundred rows. The
frontend asks "what's the rollup" not "give me the rows", so we shape
the response to what the dashboard needs. Operator can drill into raw
audit_logs by action prefix if they ever need the per-event detail.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_admin_user, get_db
from app.models.audit_log import AuditLog
from app.models.user import User

router = APIRouter()


# Same window taxonomy the assistant-drift dashboard uses. Keeping these
# aligned means a future operator can flip windows on either dashboard
# with the same mental model.
_WINDOW_TO_DELTA = {
    "24h": timedelta(hours=24),
    "7d":  timedelta(days=7),
    "30d": timedelta(days=30),
}
WindowLiteral = Literal["24h", "7d", "30d"]

# Every anon event lands under this action prefix. The dashboard query
# scans audit_logs for actions matching this — the (created_at, action)
# index makes that scan cheap regardless of total table size.
_ANON_ACTION_PREFIX = "assistant.anon."


@router.get("/summary")
def anonymous_traffic_summary(
    window: WindowLiteral = Query("7d"),
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    """Aggregated anonymous-visitor traffic for the selected window.

    Example payload::

        {
          "window": "7d",
          "since":  "2026-05-07T12:00:00Z",
          "totals": {
            "unique_anons": 42,        // distinct anon_id values seen
            "events":       137,        // total anon.* events (anons * avg actions)
          },
          "by_region": [
            {"country": "IN", "city": "Bengaluru", "events": 30, "unique_anons": 11},
            {"country": "IN", "city": "Mumbai",    "events": 28, "unique_anons":  8},
            {"country": "US", "city": "Seattle",   "events": 32, "unique_anons": 11},
            {"country": null,"city": null,         "events": 47, "unique_anons": 12}  // IP unresolved
          ],
          "by_day": [
            {"day": "2026-05-07", "events":  8, "unique_anons":  4},
            {"day": "2026-05-08", "events": 12, "unique_anons":  6},
            ...
          ]
        }

    Bucketing by anon_id de-dupes the same browser opening the chat 5
    times in a session. The single-event counts also surface so the
    operator can see "high-intent" anons (multiple opens) vs "drive-by"
    anons (one open) if they want.

    Grouping by (country, city) — not just country — matches the
    "Location" column the leads table renders below this widget. A
    country with multiple cities will produce multiple rows (Bengaluru
    vs Mumbai are separate buckets). Within-country sub-locations can
    surface as separate rows in the ranked list, which is what we want
    operationally — operators can see WHICH city the unconverted
    interest is concentrated in.

    Country = null is preserved deliberately — anonymous visitors with
    private/datacenter/proxy IPs won't resolve, and those are worth
    surfacing distinctly rather than silently hiding under "Unknown".
    """
    since = datetime.now(timezone.utc) - _WINDOW_TO_DELTA[window]

    rows = (db.query(AuditLog)
            .filter(AuditLog.action.like(_ANON_ACTION_PREFIX + "%"))
            .filter(AuditLog.created_at >= since)
            .all())

    # Per-region: keyed on the (country, city) tuple so each city
    # surfaces as its own row in the ranked list. unique_anons is the
    # number operators usually want ("how many DIFFERENT people from
    # Bengaluru?"); events is useful for spotting bot spikes.
    region_events: dict[tuple[str | None, str | None], int] = defaultdict(int)
    region_anons:  dict[tuple[str | None, str | None], set[str]] = defaultdict(set)

    # Per-day: same split. Use the row's created_at date (UTC) so the
    # dashboard isn't fighting timezones — operators can mentally shift
    # if they care.
    day_events: dict[str, int] = defaultdict(int)
    day_anons:  dict[str, set[str]] = defaultdict(set)

    seen_anons: set[str] = set()
    total_events = 0

    for r in rows:
        meta = r.metadata_json or {}
        country = meta.get("country")  # ISO-3166-1 alpha-2 or None
        city    = meta.get("city")     # GeoIP city name or None
        anon_id = meta.get("anon_id") or f"_no_anon_{r.id}"
        # The fallback _no_anon_<row_id> ensures uniqueness for rows
        # with a missing anon_id (very rare — middleware injects one,
        # but defensive). It won't conflate "no anon_id" rows together
        # into one fake user.

        region_key = (country, city)
        region_events[region_key] += 1
        region_anons[region_key].add(anon_id)

        day_key = r.created_at.astimezone(timezone.utc).date().isoformat()
        day_events[day_key] += 1
        day_anons[day_key].add(anon_id)

        seen_anons.add(anon_id)
        total_events += 1

    by_region = sorted(
        [
            {
                "country": c,
                "city":    city,
                "events":  e,
                "unique_anons": len(region_anons[(c, city)]),
            }
            for (c, city), e in region_events.items()
        ],
        key=lambda d: d["events"],
        reverse=True,
    )

    # Fill in zero-count days so the dashboard renders a continuous
    # bar chart rather than skipping gaps. Iterate from the window's
    # start date forward to today.
    start_day = since.date()
    end_day = datetime.now(timezone.utc).date()
    by_day: list[dict] = []
    cursor: date = start_day
    while cursor <= end_day:
        key = cursor.isoformat()
        by_day.append({
            "day": key,
            "events": day_events.get(key, 0),
            "unique_anons": len(day_anons.get(key, set())),
        })
        cursor = cursor + timedelta(days=1)

    return {
        "window": window,
        "since": since.isoformat().replace("+00:00", "Z"),
        "totals": {
            "unique_anons": len(seen_anons),
            "events": total_events,
        },
        "by_region": by_region,
        "by_day": by_day,
    }
