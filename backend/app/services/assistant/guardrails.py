"""Input/output safety + per-actor daily limits driven by settings_store."""
import re
from datetime import datetime, timedelta, timezone
from app.core.database import SessionLocal
from app.core.redis import redis_client
from app.core.settings_store import settings_store
from app.core.exceptions import GuardrailViolation, ChatLimitReached
from app.models.user import User

INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I),
    re.compile(r"system\s*prompt", re.I),
    re.compile(r"reveal\s+(your\s+)?(instructions|system|prompt)", re.I),
    re.compile(r"</?(system|admin)>", re.I),
]

OUTPUT_BLOCKLIST = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"rzp_(live|test)_[A-Za-z0-9]+"),
    re.compile(r"BEGIN (RSA|OPENSSH) PRIVATE KEY"),
]


def _next_utc_midnight() -> str:
    now = datetime.now(timezone.utc)
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return nxt.isoformat()


class AssistantGuardrails:
    def check_input(self, message: str, *, user_id: int | None,
                    anon_id: str | None) -> str:
        max_chars = settings_store.get_int("chat.max_input_chars", 4000)
        if len(message) > max_chars:
            raise GuardrailViolation("input_too_long",
                                     f"Message exceeds {max_chars} chars.")
        for pat in INJECTION_PATTERNS:
            if pat.search(message):
                raise GuardrailViolation("injection_detected",
                                         "Request contains disallowed instructions.")
        self._check_cooldown(user_id, anon_id)
        return message.strip()

    def check_daily_limit(self, *, user_id: int | None,
                          anon_id: str | None) -> dict:
        if user_id:
            # Per-user override takes precedence over the global setting.
            # Why: power users + paid SaaS tiers should not require an
            # admin to bump the global cap (and bump everyone else with
            # it). Cost: one extra SELECT per chat turn — read-mostly,
            # indexed by primary key.
            override = _user_chat_override(user_id)
            limit = (override if override is not None
                     else settings_store.get_int("chat.daily_limit.authenticated", 25))
            scope, ident = "user", user_id
        elif anon_id:
            limit = settings_store.get_int("chat.daily_limit.anonymous", 5)
            scope, ident = "anon", anon_id
        else:
            # Anonymous flow needs ANY identity to track daily-cap usage —
            # missing both means the frontend forgot to mint an anon_id.
            # Message is admin-configurable so it can read as a friendly
            # "please sign in" rather than a technical bug-trap; the user
            # ALSO sees this string when they hit /assistant before being
            # signed in, so the wording is user-facing copy.
            raise GuardrailViolation("no_identity", settings_store.get_str(
                "assistant.anonymous_no_identity_message",
                "Please sign in to continue chatting. Anonymous chat needs "
                "a browser identifier — refresh the page or sign in.",
            ))

        day_key = datetime.now(timezone.utc).strftime("%Y%m%d")
        key = f"chat:daily:{scope}:{ident}:{day_key}"
        try:
            used = redis_client.incr(key)
            if used == 1:
                redis_client.expire(key, 90_000)
        except Exception:
            used = 1  # fail-open under Redis outage; daily cap not enforced

        if used > limit:
            try:
                redis_client.decr(key)
            except Exception:
                pass
            raise ChatLimitReached(limit, _next_utc_midnight())

        return {"used": used, "limit": limit,
                "remaining": max(0, limit - used),
                "reset_at_utc": _next_utc_midnight()}

    def _check_cooldown(self, user_id, anon_id):
        cd = settings_store.get("chat.cooldown_seconds", 2)
        try:
            cd = int(cd)
        except (TypeError, ValueError):
            cd = 0
        if cd <= 0:
            return
        ident = f"u{user_id}" if user_id else f"a{anon_id}"
        key = f"chat:cooldown:{ident}"
        try:
            if redis_client.set(key, "1", nx=True, ex=cd) is None:
                raise GuardrailViolation("cooldown",
                                         f"Slow down — wait {cd}s between messages.")
        except GuardrailViolation:
            raise
        except Exception:
            pass

    def check_output(self, text: str) -> str:
        for pat in OUTPUT_BLOCKLIST:
            if pat.search(text):
                return "[Response blocked by safety filter. Please rephrase.]"
        max_out = settings_store.get_int("chat.max_output_chars", 4000)
        return text[:max_out] + ("…" if len(text) > max_out else "")


def _user_chat_override(user_id: int) -> int | None:
    """Read users.daily_chat_limit_override. None = no override set.

    Uses a short-lived session — the orchestrator's request session
    isn't passed down here; opening + closing is cheap (single PK
    fetch) and avoids threading the session through every guardrail
    call site.
    """
    try:
        with SessionLocal() as db:
            u = db.get(User, user_id)
            return u.daily_chat_limit_override if u else None
    except Exception:
        # Defensive: if the column doesn't exist yet (mid-deploy / fresh
        # SQLite test DB), fall back to "no override". Never blocks a
        # chat turn because of a DB hiccup.
        return None
