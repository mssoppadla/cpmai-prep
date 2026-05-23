"""Workflow runners — one class per registered workflow_type.

Adding a new workflow type:
  1. Implement a subclass of ``WorkflowRunner`` here
  2. Register it in ``WORKFLOWS``
  3. Add the literal string to ``WORKFLOW_TYPES`` in schemas/social.py
  4. Add a frontend form section under /admin/campaigns that knows
     how to render this runner's config_json schema

Each runner is pure-function-shaped: ``.run(campaign, db) -> str`` returns
the generated content text. Side effects (LLM calls, FFmpeg invocation)
are allowed; DB writes are NOT — the caller (``runner.execute()``)
manages campaign_run row state.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.models.social import Campaign
from app.models.zoom import ZoomSession


log = structlog.get_logger("social.runners")


# ──────────────────────────────────────────────────────────────────────
# Base class
# ──────────────────────────────────────────────────────────────────────
class WorkflowRunner(ABC):
    """Base class for all campaign workflow types."""

    #: Required keys in campaign.config_json. The runner ``validate_config``
    #: raises ValueError if any are missing.
    required_config_keys: tuple[str, ...] = ()

    #: Optional keys with defaults. Filled in if absent.
    config_defaults: dict[str, Any] = {}

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Apply defaults + validate required keys. Mutated copy returned."""
        merged = {**self.config_defaults, **(config or {})}
        for key in self.required_config_keys:
            if key not in merged or merged[key] in ("", None):
                raise ValueError(
                    f"{type(self).__name__} requires config_json key {key!r}"
                )
        return merged

    @abstractmethod
    def run(self, campaign: Campaign, db: Session) -> str:
        """Execute the workflow. Return the generated content text.

        Raise on failure — the caller logs the traceback to the run's
        ``error`` column and marks the run failed.
        """
        ...


# ──────────────────────────────────────────────────────────────────────
# Weekly content
# ──────────────────────────────────────────────────────────────────────
class WeeklyContentRunner(WorkflowRunner):
    """OpenAI text → admin queue. The most basic + most useful workflow.

    config_json shape:
      {
        "prompt": "Write a 200-word LinkedIn post about ...",
        "tone":   "professional" | "casual" | "energetic",      # optional
        "max_words": 200                                          # optional
      }
    """
    required_config_keys = ("prompt",)
    config_defaults = {"tone": "professional", "max_words": 250}

    def run(self, campaign: Campaign, db: Session) -> str:
        config = self.validate_config(campaign.config_json or {})
        # Lazy-import the LLM registry to avoid pulling vendor client
        # imports into every place that imports runners.py.
        from app.services.assistant.llm_registry import LLMRegistry
        try:
            provider = LLMRegistry.get_active()
        except Exception as e:
            raise RuntimeError(
                "No active LLM provider configured. Set one in "
                f"/admin/llm-providers to enable AI-generated campaigns. "
                f"({e})"
            ) from e
        system = (
            "You are a content writer for an EdTech company. Generate "
            f"a single {config['tone']} social-media post of no more than "
            f"{config['max_words']} words. Plain text only; no markdown. "
            "End with one or two relevant hashtags."
        )
        prompt = config["prompt"]
        text = provider.complete(
            system=system,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=int(config["max_words"]) * 6,
        )
        return (text or "").strip()


# ──────────────────────────────────────────────────────────────────────
# Session reminder
# ──────────────────────────────────────────────────────────────────────
class SessionReminderRunner(WorkflowRunner):
    """Find scheduled Zoom sessions starting in ~24h, generate a reminder.

    config_json shape:
      {
        "window_hours": 24,                # how far ahead to look
        "course_id": <int>                 # optional — limit to this course
      }
    """
    config_defaults = {"window_hours": 24}

    def run(self, campaign: Campaign, db: Session) -> str:
        config = self.validate_config(campaign.config_json or {})
        window_hours = int(config.get("window_hours", 24))

        now = datetime.now(timezone.utc)
        window_end = now + timedelta(hours=window_hours)
        q = db.query(ZoomSession).filter(
            ZoomSession.tenant_id == campaign.tenant_id,
            ZoomSession.is_deleted.is_(False),
            ZoomSession.status == "scheduled",
            ZoomSession.scheduled_at > now,
            ZoomSession.scheduled_at <= window_end,
        )
        if config.get("course_id"):
            q = q.filter(ZoomSession.course_id == config["course_id"])
        sessions = q.order_by(ZoomSession.scheduled_at).all()

        if not sessions:
            return (
                f"No sessions scheduled in the next {window_hours}h. "
                "Skipping reminder."
            )

        # If multiple, generate a digest. For now, one paragraph per session.
        lines = ["📚 Coming up:"]
        for s in sessions:
            when = s.scheduled_at.strftime("%a %d %b at %H:%M UTC")
            lines.append(
                f"• {s.title} — {when} ({s.duration_minutes} min). "
                f"Join from your dashboard."
            )
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────
# Auto-clip (stub — full FFmpeg + Whisper integration is future work)
# ──────────────────────────────────────────────────────────────────────
class AutoClipRunner(WorkflowRunner):
    """Trigger an admin-queue entry for clip generation on a long video.

    Full implementation needs FFmpeg scene detection + Whisper
    transcript-driven highlight scoring + clip extraction. For v1 this
    runner queues a placeholder content row that signals the operator
    to run the clipping pipeline manually.

    config_json shape:
      {
        "source_url":  "/uploads/.../lecture.mp4",
        "target_clips": 3,                     # how many shorts to extract
        "max_length_seconds": 90
      }
    """
    required_config_keys = ("source_url",)
    config_defaults = {"target_clips": 3, "max_length_seconds": 90}

    def run(self, campaign: Campaign, db: Session) -> str:
        config = self.validate_config(campaign.config_json or {})
        # Real FFmpeg-driven clip extraction TODO. This stub gives the
        # operator a clear "next step" string so the queue is useful
        # even while the full pipeline is unbuilt.
        return (
            f"[auto-clip queued] Source: {config['source_url']}\n"
            f"Targets: {config['target_clips']} clips up to "
            f"{config['max_length_seconds']}s each. Run the manual\n"
            f"clip-extraction pipeline against the source URL above\n"
            f"once the FFmpeg automation lands (S-A2 follow-up)."
        )


# ──────────────────────────────────────────────────────────────────────
# Recording published (triggered by zoom webhook, not the scheduler)
# ──────────────────────────────────────────────────────────────────────
class RecordingPublishedRunner(WorkflowRunner):
    """When a Zoom recording archive completes, generate a "Now available"
    post. Triggered by the recording.completed webhook handler, NOT by
    APScheduler — campaign.schedule_cron is ignored for this type.

    config_json shape:
      {
        "course_id": <int> | null       # filter to one course's recordings
      }
    """

    def run(self, campaign: Campaign, db: Session) -> str:
        # Webhook-driven runs pass the recording context via the
        # campaign_run.config_json overrides. v1: simple template.
        config = campaign.config_json or {}
        return (
            "📹 New recording available. Catch up on the latest session "
            "in your dashboard.\n"
            f"(course_id filter: {config.get('course_id', 'any')})"
        )


# ──────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────
WORKFLOWS: dict[str, WorkflowRunner] = {
    "weekly_content":      WeeklyContentRunner(),
    "session_reminder":    SessionReminderRunner(),
    "auto_clip":           AutoClipRunner(),
    "recording_published": RecordingPublishedRunner(),
}


def workflow_meta() -> list[dict[str, Any]]:
    """Return metadata about each registered workflow, for the admin
    form. Drives the per-workflow config_json field rendering."""
    return [
        {
            "workflow_type": "weekly_content",
            "label": "Weekly AI content",
            "description": "Generate a post from a prompt on a schedule. "
                           "Output lands in the admin queue.",
            "config_schema": {
                "prompt": {"type": "string", "required": True,
                           "placeholder": "Write a 200-word LinkedIn post about ..."},
                "tone": {"type": "select", "options": ["professional", "casual", "energetic"]},
                "max_words": {"type": "number", "default": 250, "min": 50, "max": 1000},
            },
        },
        {
            "workflow_type": "session_reminder",
            "label": "Session reminder",
            "description": "24h before a scheduled Zoom session, generate a "
                           "reminder post for the admin queue.",
            "config_schema": {
                "window_hours": {"type": "number", "default": 24, "min": 1, "max": 168},
                "course_id": {"type": "course_picker"},
            },
        },
        {
            "workflow_type": "auto_clip",
            "label": "Auto-clip long video",
            "description": "Queue a clip-extraction task on a source video URL. "
                           "Full automation lands in a future PR.",
            "config_schema": {
                "source_url": {"type": "string", "required": True,
                               "placeholder": "/uploads/.../lecture.mp4"},
                "target_clips": {"type": "number", "default": 3, "min": 1, "max": 10},
                "max_length_seconds": {"type": "number", "default": 90, "min": 15, "max": 300},
            },
        },
        {
            "workflow_type": "recording_published",
            "label": "Recording published",
            "description": "Triggered by the Zoom recording.completed webhook. "
                           "Generates a 'now available' post.",
            "config_schema": {
                "course_id": {"type": "course_picker"},
            },
        },
    ]
