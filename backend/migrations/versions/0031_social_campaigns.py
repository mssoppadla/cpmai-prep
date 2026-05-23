"""Phase 1 PR #7 follow-up: social automation — campaigns + campaign_runs.

The fourth feature group of Phase 1 (per docs/roadmap/phase-1-scope.md).
Lands the schema for in-process AI-generated content scheduling. The
runtime path (APScheduler, workflow runners, admin queue) builds on
this in subsequent S-A* commits.

# campaigns

A scheduled, named, repeatable workflow. An admin defines:
  * name + description (operator-facing label)
  * workflow_type (which Python runner executes when the schedule fires)
  * schedule_cron (5-field cron expression)
  * config_json (workflow-specific config — e.g. course_id for
                 the session-reminder workflow, prompt template for the
                 weekly-content workflow)
  * active (campaigns can be paused without losing config)

# campaign_runs

One row per scheduler invocation. Captures:
  * started_at + finished_at (timing observability)
  * status (queued / running / done / failed)
  * generated_content (the AI output — copy/pasted by admin in
                       social-queue or auto-posted by future provider
                       integrations)
  * posted_at + posted_to_platforms (JSONB list of {platform, url, ts})
  * error (traceback string when status='failed')

Per contract:
  - I-1: tenant_id default 1 on both tables
  - M-1, M-2, M-3: additive only, downgrade NotImplementedError, single tx

Revision ID: 0031_social_campaigns (20 chars ≤ 32 ✓).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# JSONB on prod (Postgres) for richer indexing; model declares generic
# JSON so SQLite unit tests can build the schema.
revision = "0031_social_campaigns"
down_revision = "0030_zoom_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ────────────────────────── campaigns ──────────────────────────
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer,
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False, server_default="1"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text),
        # The workflow Python class to invoke. Validated against the
        # registered runners in app.services.social.runners.WORKFLOWS.
        # Values: weekly_content, session_reminder, auto_clip,
        #         recording_published
        sa.Column("workflow_type", sa.String(64), nullable=False),
        # 5-field cron — APScheduler parses it. Empty / NULL means
        # "manual run only".
        sa.Column("schedule_cron", sa.String(120)),
        # Workflow-specific config. Schema varies by workflow_type;
        # the runner's expected shape is documented in the runner class.
        sa.Column("config_json", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        # Audit trail + soft-delete
        sa.Column("created_by", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), onupdate=sa.func.now(),
                  nullable=False),
        sa.Column("is_deleted", sa.Boolean, nullable=False,
                  server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.UniqueConstraint("tenant_id", "name", name="uq_campaigns_tenant_name"),
    )
    op.create_index(
        "ix_campaigns_active_tenant",
        "campaigns",
        ["tenant_id", "active"],
        postgresql_where=sa.text("active = true AND is_deleted = false"),
    )

    # ────────────────────────── campaign_runs ──────────────────────────
    op.create_table(
        "campaign_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer,
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False, server_default="1"),
        sa.Column("campaign_id", sa.Integer,
                  sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        # Lifecycle:
        #   queued    — created by APScheduler, awaiting executor pickup
        #   running   — runner.run() in progress
        #   done      — runner returned, content available in admin queue
        #   posted    — admin (or future auto-poster) confirmed posting
        #   failed    — runner raised; see error field
        #   cancelled — admin cancelled before completion
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        # The AI-generated content. Plain text — workflows that produce
        # rich content (images, videos) reference the asset in
        # config_json or a future asset table; this is the post body.
        sa.Column("generated_content", sa.Text),
        # When admin marks "posted" via the social-queue UI.
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("posted_to_platforms", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        # Traceback string for status='failed' runs. Truncated to ~4KB
        # at insert time to keep DB rows small.
        sa.Column("error", sa.Text),
    )
    op.create_index(
        "ix_campaign_runs_status_tenant",
        "campaign_runs",
        ["tenant_id", "status", "started_at"],
    )


def downgrade() -> None:
    raise NotImplementedError(
        "0031_social_campaigns: downgrade is intentionally unimplemented. "
        "Dropping these tables would lose every scheduled workflow + the "
        "generated-content history operators may have used for reporting. "
        "Per contract M-2, write a forward migration that archives first."
    )
