"""Structlog setup with correlation IDs.

Logs go to two destinations:
  1. stdout — human-readable (or JSON when LOG_FORMAT=json), for `docker
     compose logs backend`.
  2. /app/logs/app.jsonl — always JSON, rotated at 10 MiB × 5 files. The
     /app/logs path is mounted from ./backend/logs on the host so you can
     `tail -f backend/logs/app.jsonl` from your terminal.

Every line carries `request_id` (from the correlation middleware), so you
can reconstruct one user's journey by grepping the file for their ID.

Admin actions written via app.core.audit.audit_log() are mirrored here as
`audit.<action>` events with the actor user_id and metadata.
"""
import logging
import logging.handlers
import pathlib

import structlog
from asgi_correlation_id.context import correlation_id

from app.core.config import settings


LOG_DIR = pathlib.Path("/app/logs") if pathlib.Path("/app").exists() \
          else pathlib.Path(__file__).resolve().parents[2] / "logs"
LOG_FILE = LOG_DIR / "app.jsonl"


def _add_correlation_ids(_, __, event_dict):
    rid = correlation_id.get()
    if rid:
        event_dict["request_id"] = rid
    return event_dict


def configure_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        _add_correlation_ids,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # Tell structlog to emit through the stdlib logging system so we can
    # attach multiple handlers (stdout + file) with different formats.
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )

    json_renderer = structlog.processors.JSONRenderer()
    console_renderer = structlog.dev.ConsoleRenderer(colors=False)

    file_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            json_renderer,
        ],
    )
    stream_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            json_renderer if settings.LOG_FORMAT == "json" else console_renderer,
        ],
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    stream_h = logging.StreamHandler()
    stream_h.setFormatter(stream_formatter)
    root.addHandler(stream_h)

    # Rotating file: 10 MiB × 5 keeps ~50 MiB of history. Always JSON.
    file_h = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
    )
    file_h.setFormatter(file_formatter)
    root.addHandler(file_h)
