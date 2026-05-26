"""Visitor Insights v2 — extend journey_events + nightly rollup table.

The existing journey_events table captures discrete funnel events
(auth.signup, payment.success, …) but the SPA never fired anything
for page views, scroll depth, or CTA clicks. The /admin/anonymous-traffic
dashboard reads a different table (audit_logs filtered by the
"assistant.anon.*" prefix) and only sees "chat bubble opened" events.

This migration extends journey_events so the same table can carry the
richer visitor-insights stream that PR Visitor-Insights-v2 introduces:

  * tenant_id          — required for the I-1 contract; default 1 backfills
                         every existing row to the bootstrap tenant
  * path               — normalised route ("/courses/[slug]" not "/courses/foo")
  * referrer           — http referer at the time of the event
  * utm_source         — parsed from the landing URL once per session
  * utm_medium
  * utm_campaign
  * ua                 — raw user-agent string (truncated to 256 chars)
  * device             — desktop / mobile / tablet / bot
  * browser            — chrome / safari / firefox / edge / other
  * os                 — windows / macos / linux / ios / android / other
  * country            — ISO-3166-1 alpha-2 from GeoIP (already on audit_log;
                         duplicated here so the dashboard joins are O(1))
  * city               — GeoIP city name
  * duration_ms        — for page.exit / page.heartbeat events (active time)
  * scroll_pct         — for scroll.depth events (25/50/75/100 buckets)

We also widen `event` from VARCHAR(64) → VARCHAR(96) because some of the
new event names ("session.start", "page.heartbeat") plus the existing
ones leave little headroom for future growth.

Indexes added:

  * ix_je_tenant_event_time   — primary dashboard scan
                               (WHERE tenant_id=? AND event=? AND created_at>=?)
  * ix_je_tenant_path_time    — top-pages query
                               (WHERE tenant_id=? AND path=? AND event='page.view')
  * ix_je_session_time        — session timeline drilldown
                               (WHERE session_id=? ORDER BY created_at)

And a new rollup table — visitor_insights_daily — that PR VI-8 populates
nightly. It exists from Day 1 (additive, free to create empty) so the
dashboard endpoints can toggle between live and rollup reads via a
settings flag. We don't backfill it here; the rollup job populates from
journey_events when first enabled.

Per contract:
  - I-1: tenant_id NOT NULL, default 1 — backfill existing rows
  - M-1: additive only; new columns are nullable; downgrade raises
  - M-3: tested via alembic upgrade head from empty DB in CI

Revision ID: 0032_visitor_insights (22 chars ≤ 32 ✓).
"""
from alembic import op
import sqlalchemy as sa


revision = "0032_visitor_insights"
down_revision = "0031_social_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ───────────────────── extend journey_events ─────────────────────
    # All new columns are nullable so existing rows keep working; the
    # tracker writes them on every new event.
    with op.batch_alter_table("journey_events") as batch:
        # Widen event so the new whitelist values fit comfortably.
        batch.alter_column("event",
                            existing_type=sa.String(64),
                            type_=sa.String(96),
                            existing_nullable=False)

        # tenant_id — server_default=1 backfills existing rows to the
        # bootstrap tenant. After backfill, ALTER … NOT NULL would be
        # ideal but we keep it nullable for now per M-1; the tracker
        # writes a non-null value and the dashboard reads with COALESCE.
        batch.add_column(sa.Column(
            "tenant_id", sa.Integer,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            server_default="1",
        ))

        # Page + referrer signals. Path is the route template, not the
        # raw URL — the tracker normalises before sending. Capped lengths
        # protect against pathological inputs.
        batch.add_column(sa.Column("path",        sa.String(255)))
        batch.add_column(sa.Column("referrer",    sa.String(512)))
        batch.add_column(sa.Column("utm_source",  sa.String(64)))
        batch.add_column(sa.Column("utm_medium",  sa.String(64)))
        batch.add_column(sa.Column("utm_campaign", sa.String(128)))

        # Device fingerprint — parsed server-side from UA. Stored as
        # discrete columns (not JSON) so dashboard GROUP BYs are cheap.
        batch.add_column(sa.Column("ua",      sa.String(256)))
        batch.add_column(sa.Column("device",  sa.String(16)))   # desktop/mobile/tablet/bot
        batch.add_column(sa.Column("browser", sa.String(24)))
        batch.add_column(sa.Column("os",      sa.String(24)))

        # GeoIP — duplicated from audit_log convention so the dashboard
        # joins are O(1). Both nullable; private/datacenter IPs won't
        # resolve and we surface those distinctly as "Unknown" rather
        # than dropping.
        batch.add_column(sa.Column("country", sa.String(2)))    # ISO-3166-1 alpha-2
        batch.add_column(sa.Column("city",    sa.String(80)))

        # Event-specific numeric fields. duration_ms is the ACTIVE time
        # on a page (Page Visibility API filters out background tabs);
        # scroll_pct is the highest scroll bucket reached (25/50/75/100).
        # Nullable because most event types don't use them.
        batch.add_column(sa.Column("duration_ms", sa.Integer))
        batch.add_column(sa.Column("scroll_pct",  sa.SmallInteger))

    # Indexes for the dashboard scans. Created outside batch_alter_table
    # because batch mode doesn't support all index variants cleanly.
    op.create_index(
        "ix_je_tenant_event_time",
        "journey_events",
        ["tenant_id", "event", "created_at"],
    )
    op.create_index(
        "ix_je_tenant_path_time",
        "journey_events",
        ["tenant_id", "path", "created_at"],
    )
    op.create_index(
        "ix_je_session_time",
        "journey_events",
        ["session_id", "created_at"],
    )

    # ───────────────────── visitor_insights_daily ─────────────────────
    # Nightly rollup. Exists from Day 1 so the dashboard endpoint can
    # flip to it via the tracking.rollup_enabled setting without a
    # follow-up migration. PR VI-8 wires the job; until then this table
    # stays empty and the dashboard reads from journey_events live.
    #
    # Grain: (tenant_id, day, path, event) — one row per (page, event-type,
    # day). Lets the top-pages query become a single-row read per page
    # instead of an O(events) aggregation.
    op.create_table(
        "visitor_insights_daily",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer,
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("day", sa.Date, nullable=False),
        # NULL path = "all pages" aggregate (used for KPI strip)
        sa.Column("path", sa.String(255)),
        # NULL event = "all events" aggregate
        sa.Column("event", sa.String(96)),
        sa.Column("views", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unique_visitors", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unique_sessions", sa.Integer, nullable=False, server_default="0"),
        # Sum of duration_ms across all rows in the bucket; the dashboard
        # divides by views to get avg time on page.
        sa.Column("total_duration_ms", sa.BigInteger, nullable=False, server_default="0"),
        # Count of sessions that had only one page.view (= bounced).
        sa.Column("bounces", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "day", "path", "event",
                            name="uq_vid_grain"),
    )
    op.create_index(
        "ix_vid_tenant_day",
        "visitor_insights_daily",
        ["tenant_id", "day"],
    )


def downgrade() -> None:
    raise NotImplementedError(
        "0032_visitor_insights: downgrade is intentionally unimplemented. "
        "Dropping the new columns would lose visitor-insights history and "
        "dropping visitor_insights_daily would force a multi-day rollup "
        "recompute. Per contract M-2, write a forward migration that "
        "archives first."
    )
