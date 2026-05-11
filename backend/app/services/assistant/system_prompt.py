"""System-prompt assembly with admin-configurable guardrails.

Every handler builds its own intent-specific system prompt (e.g.
ContentHandler's "explain CPMAI concepts…"). On top of that, the
admin can configure THREE global guardrail strings that get prepended:

  - assistant.system_prompt_preamble — high-level identity/persona
    ("You are CPMAI Prep's official assistant. Be concise.")
  - assistant.allowed_topics — comma-or-newline list of topics the
    bot is happy to discuss ("CPMAI BoK, ML/AI fundamentals, ...")
  - assistant.banned_topics — topics to refuse politely, with one
    explicit exception group ("PMP-only methodologies, EXCEPT
    questions about PMI's CPMAI program itself")

Combined into one preamble that's stable for the duration of a
request. Admin edits land in subsequent chats without a deploy.

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
    if banned:
        ban_block = (
            "BANNED — politely decline to discuss these:\n" + banned)
        if exceptions:
            ban_block += (
                "\n\nException — these specific items ARE allowed even when "
                "they touch the banned list:\n" + exceptions)
        parts.append(ban_block)

    if not parts:
        return ""
    return "\n\n".join(parts) + "\n\n"


def with_preamble(handler_system: str) -> str:
    """Convenience for handlers — `with_preamble(SYSTEM)` returns the
    full prompt with admin guardrails prepended."""
    preamble = assemble_preamble()
    return preamble + handler_system if preamble else handler_system
