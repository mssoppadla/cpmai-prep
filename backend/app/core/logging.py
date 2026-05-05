"""Structlog setup with correlation IDs."""
import logging
import structlog
from asgi_correlation_id.context import correlation_id
from app.core.config import settings


def _add_correlation_ids(_, __, event_dict):
    rid = correlation_id.get()
    if rid:
        event_dict["request_id"] = rid
    return event_dict


def configure_logging():
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    processors = [
        structlog.contextvars.merge_contextvars,
        _add_correlation_ids,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if settings.LOG_FORMAT == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
