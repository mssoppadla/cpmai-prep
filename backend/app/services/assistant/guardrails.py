"""Input/output safety + per-actor daily limits driven by settings_store."""
import re
from datetime import datetime, timedelta, timezone
from app.core.redis import redis_client
from app.core.settings_store import settings_store
from app.core.exceptions import GuardrailViolation, ChatLimitReached

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
            limit = settings_store.get_int("chat.daily_limit.authenticated", 25)
            scope, ident = "user", user_id
        elif anon_id:
            limit = settings_store.get_int("chat.daily_limit.anonymous", 5)
            scope, ident = "anon", anon_id
        else:
            raise GuardrailViolation("no_identity",
                                     "Anonymous request without anon_id.")

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
