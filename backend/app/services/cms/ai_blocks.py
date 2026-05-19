"""AI-assisted block generation for CMS content pages.

Three operations the admin UI exposes:

  * ``generate_page(prompt)`` — turn a free-form description into a
    full BlockNote block list. e.g. "Write a study guide for the
    Business Understanding phase with 3 sections and a CTA at the end".

  * ``fill_block(block_type, context)`` — produce content for a single
    empty block. e.g. block_type="paragraph", context="this block sits
    under a heading 'Why CPMAI matters'".

  * ``improve_block(text, tone)`` — rewrite a single block's text in
    the requested tone (shorter / longer / friendlier / formal /
    fix grammar). Returns the rewritten string; the UI swaps it in.

Design notes:

  * **Cross-LLM**. The service goes through ``LLMRegistry.get_active()``
    so whichever provider the operator configured (OpenAI, Anthropic,
    or stub for tests) does the work. We hand the provider a plain
    ``system + messages`` shape — no provider-specific features.

  * **Defensive parsing**. Models occasionally emit prose around the
    JSON, malformed JSON, or markdown fences. ``_extract_blocks()``
    strips fences, locates the first ``[`` and the matching ``]``, and
    falls back to a single paragraph block containing the raw response
    if parsing fails. The UI gets *something* useful even on
    bad responses — never crashes.

  * **Schema constraint**. We accept only a small allowlist of block
    types (paragraph, heading, bulletListItem, numberedListItem). Any
    block type the model invents that isn't in the allowlist gets
    coerced to "paragraph". This matches what the BlockNote-Mantine
    default editor supports cleanly; we'll widen the allowlist when
    PR #6+ adds custom block types.

  * **Stateless**. No caching, no per-tenant state. Just prompt-in,
    blocks-out. The endpoint is the audit + RBAC surface.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Literal

from app.services.assistant.llm_registry import LLMRegistry


_log = logging.getLogger(__name__)


# ----------------------------------------------------- types

# BlockNote block types we generate / accept. Extend cautiously — the
# Mantine theme renders these out of the box; custom blocks need a
# matching React component on the frontend.
ALLOWED_BLOCK_TYPES = frozenset({
    "paragraph", "heading", "bulletListItem", "numberedListItem",
})

ImproveTone = Literal["shorter", "longer", "friendlier", "formal", "grammar"]


# ----------------------------------------------------- prompts

_SYSTEM_GENERATE_PAGE = """\
You are an expert content writer for an educational platform. The user
will describe a page they want written. Respond with ONLY a JSON array
of BlockNote blocks. Do NOT wrap in markdown code fences. Do NOT add
prose before or after the JSON.

Allowed block types:
- {"type": "heading", "props": {"level": 1|2|3}, "content": "..."}
- {"type": "paragraph", "content": "..."}
- {"type": "bulletListItem", "content": "..."}
- {"type": "numberedListItem", "content": "..."}

Each block must include "type" and "content". "props" is optional and
only meaningful on headings. Keep "content" as a plain string.

Aim for a clear, scannable structure: one h1, 3-5 h2 sections, short
paragraphs, occasional bullet lists. Do not exceed 30 blocks.
"""

_SYSTEM_FILL_BLOCK = """\
You are an expert content writer. The user will give you context and
ask you to fill a single block of a specific type. Respond with ONLY
the text content for that block — no JSON, no markdown fences, no
explanation. For a heading, just the heading text. For a paragraph,
2-4 sentences. For a list item, one short line. No more than 200 words.
"""

_SYSTEM_IMPROVE = {
    "shorter":    "Rewrite the user's text to be shorter while preserving meaning. Return ONLY the rewritten text, no explanation.",
    "longer":     "Rewrite the user's text to be longer, adding helpful detail. Return ONLY the rewritten text, no explanation.",
    "friendlier": "Rewrite the user's text in a friendlier, warmer tone. Return ONLY the rewritten text, no explanation.",
    "formal":     "Rewrite the user's text in a more formal, professional tone. Return ONLY the rewritten text, no explanation.",
    "grammar":    "Fix grammar and clarity issues in the user's text. Keep the meaning identical. Return ONLY the corrected text, no explanation.",
}


# ----------------------------------------------------- public API

def generate_page(prompt: str) -> list[dict[str, Any]]:
    """Generate a full block list from a free-form prompt.

    Falls back to a single-paragraph block containing the raw response
    if the model returns un-parseable content. Never raises (except on
    catastrophic provider errors).
    """
    if not prompt or not prompt.strip():
        return []
    provider = LLMRegistry.get_active()
    response = provider.complete(
        system=_SYSTEM_GENERATE_PAGE,
        messages=[{"role": "user", "content": prompt}],
    )
    blocks = _extract_blocks(response)
    return [_normalise_block(b) for b in blocks]


def fill_block(block_type: str, context: str) -> str:
    """Produce text content for a single empty block of ``block_type``."""
    bt = block_type if block_type in ALLOWED_BLOCK_TYPES else "paragraph"
    user = (
        f"Write content for a single {bt} block.\n\n"
        f"Context:\n{context.strip() or '(none)'}"
    )
    provider = LLMRegistry.get_active()
    return provider.complete(
        system=_SYSTEM_FILL_BLOCK,
        messages=[{"role": "user", "content": user}],
    ).strip()


def improve_block(text: str, tone: ImproveTone) -> str:
    """Rewrite ``text`` in the requested tone. Returns plain text."""
    if not text or not text.strip():
        return text
    system = _SYSTEM_IMPROVE.get(tone, _SYSTEM_IMPROVE["grammar"])
    provider = LLMRegistry.get_active()
    return provider.complete(
        system=system,
        messages=[{"role": "user", "content": text}],
    ).strip()


# ----------------------------------------------------- internals

# Some providers wrap output in ```json ... ``` fences despite the
# system prompt telling them not to. Strip these defensively.
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _extract_blocks(response: str) -> list[dict[str, Any]]:
    """Locate and parse the JSON block array in ``response``.

    Strategy:
      1. Strip markdown code fences if present.
      2. Find the FIRST '[' and the LAST ']' — assume that's the array.
      3. json.loads the slice. Bail with a fallback if it doesn't parse.

    On any failure, returns a single paragraph block containing the
    raw response so the UI gets *something*. Never raises.
    """
    if not response:
        return []
    cleaned = _FENCE_RE.sub("", response).strip()
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start < 0 or end < 0 or end <= start:
        _log.warning("ai_blocks: no JSON array found, falling back to paragraph")
        return [{"type": "paragraph", "content": cleaned}]
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        _log.warning("ai_blocks: JSON decode failed, falling back to paragraph")
        return [{"type": "paragraph", "content": cleaned}]
    if not isinstance(parsed, list):
        return [{"type": "paragraph", "content": cleaned}]
    return [b for b in parsed if isinstance(b, dict)]


def _normalise_block(b: dict[str, Any]) -> dict[str, Any]:
    """Coerce a raw block dict into a shape the editor can render.

    * Unknown ``type`` → "paragraph"
    * Heading without ``props.level`` → level 2
    * Heading with level outside 1..3 → clamped to 1..3
    * Adds a UUID ``id`` so BlockNote can track the block across saves
    """
    btype = b.get("type", "paragraph")
    if btype not in ALLOWED_BLOCK_TYPES:
        btype = "paragraph"
    out: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "type": btype,
        "content": _coerce_content(b.get("content")),
    }
    if btype == "heading":
        level = b.get("props", {}).get("level", 2)
        try:
            level = int(level)
        except (TypeError, ValueError):
            level = 2
        out["props"] = {"level": max(1, min(3, level))}
    return out


def _coerce_content(c: Any) -> str:
    """Content can come back as a string, a list of inline objects, or
    occasionally a nested dict. We collapse to a plain string."""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        # BlockNote inline content array: [{type:"text", text:"...", ...}]
        parts = []
        for item in c:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    if isinstance(c, dict) and "text" in c:
        return str(c["text"])
    return ""
