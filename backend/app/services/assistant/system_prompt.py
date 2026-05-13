"""System-prompt assembly with admin-configurable guardrails.

Every handler builds its own intent-specific system prompt (e.g.
ContentHandler's "explain CPMAI concepts…"). On top of that, the
admin can configure FOUR global guardrail strings that get prepended:

  - assistant.system_prompt_preamble — high-level identity/persona
    ("You are CPMAI Prep's official assistant. Be concise.")
  - assistant.allowed_topics — comma-or-newline list of topics the
    bot is happy to discuss freely ("CPMAI BoK, ML/AI fundamentals, ...")
  - assistant.allowed_exceptions — ADDITIONAL topics the bot may
    discuss even though they aren't in allowed_topics. Use this for
    one-off subjects you want to allow without expanding the main
    scope statement (e.g. "GDPR rules", "PMI exam registration").
    Items here also override the banned list — if a subject is both
    banned and excepted, the exception wins.
  - assistant.banned_topics — topics to refuse politely ("PMP-only
    methodologies, internal company finance"). Subordinate to
    allowed_exceptions above.

Combined into one preamble that's stable for the duration of a
request. Admin edits land in subsequent chats without a deploy.

History note (2026-05-14): `allowed_exceptions` originally only
extended the banned list and was silently dropped when banned_topics
was empty. Operator reported that adding "GDPR Rules" to exceptions
didn't unlock the topic — because banned_topics was empty AND the LLM
was rejecting GDPR for not being in allowed_topics. Fixed by making
exceptions a top-level "ALSO ALLOWED" block that's independent of
both lists. The field name now matches the behavior.

Why a separate module: the LLM-bound handlers (Content/FAQ/Account)
all need it; PmiReferenceHandler doesn't (it makes no LLM call); and
keeping the assembly logic in one place makes the resulting prompt
easy to inspect during eval debugging.
"""
from app.core.settings_store import settings_store


def assemble_preamble() -> str:
    """Return the admin-configured guardrail header, or empty string if
    nothing is set. Handlers prepend this to their intent-specific
    system prompt."""
    parts: list[str] = []

    preamble = settings_store.get_str("assistant.system_prompt_preamble", "").strip()
    if preamble:
        parts.append(preamble)

    allowed = settings_store.get_str("assistant.allowed_topics", "").strip()
    banned  = settings_store.get_str("assistant.banned_topics",  "").strip()
    exceptions = settings_store.get_str("assistant.allowed_exceptions", "").strip()

    if allowed:
        parts.append(
            "TOPIC SCOPE — discuss these subjects freely:\n" + allowed)
    if exceptions:
        # Top-level "ALSO ALLOWED" block. Independent of both
        # allowed_topics and banned_topics: items here are brought
        # IN-scope even if they aren't in TOPIC SCOPE, and they
        # override anything in BANNED. The "even if not listed above"
        # wording is crucial — without it the model tends to treat
        # this as a no-op when TOPIC SCOPE is already narrow.
        parts.append(
            "ALSO ALLOWED — these specific subjects ARE in scope, even "
            "if they don't appear in TOPIC SCOPE above and even if they "
            "would otherwise be banned. Answer questions about them the "
            "same way you would for any in-scope subject:\n" + exceptions)
    if banned:
        parts.append(
            "BANNED — politely decline to discuss these UNLESS the "
            "subject is in the ALSO ALLOWED list above:\n" + banned)

    if not parts:
        return ""
    return "\n\n".join(parts) + "\n\n"


def with_preamble(handler_system: str) -> str:
    """Convenience for handlers — `with_preamble(SYSTEM)` returns the
    full prompt with admin guardrails prepended."""
    preamble = assemble_preamble()
    return preamble + handler_system if preamble else handler_system
