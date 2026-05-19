"""Unit tests for the ai_blocks service.

These don't hit the LLM — they pin the *parsing + normalisation* layer
that runs after whatever the provider returns. The parsing layer is
where most real-world bugs live: models that wrap output in markdown
fences, models that add prose before/after the JSON, models that emit
unknown block types, etc.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.cms.ai_blocks import (
    ALLOWED_BLOCK_TYPES,
    _coerce_content,
    _extract_blocks,
    _normalise_block,
    fill_block,
    generate_page,
    improve_block,
)


# ----------------------------------------------------- allowlist contract

def test_allowed_block_types_is_a_known_set():
    """Pin the Phase 1 block-type allowlist. Adding types here must
    be matched by a frontend renderer that handles them."""
    assert ALLOWED_BLOCK_TYPES == frozenset({
        "paragraph", "heading", "bulletListItem", "numberedListItem",
    })


# ----------------------------------------------------- _extract_blocks

def test_extract_blocks_plain_json_array():
    raw = '[{"type": "heading", "content": "Hi"}, {"type": "paragraph", "content": "Body"}]'
    blocks = _extract_blocks(raw)
    assert len(blocks) == 2
    assert blocks[0]["type"] == "heading"


def test_extract_blocks_strips_markdown_fences():
    raw = '```json\n[{"type": "paragraph", "content": "Hi"}]\n```'
    blocks = _extract_blocks(raw)
    assert len(blocks) == 1
    assert blocks[0]["content"] == "Hi"


def test_extract_blocks_strips_bare_fences():
    """Some models emit ``` without the language tag."""
    raw = '```\n[{"type": "paragraph", "content": "Hi"}]\n```'
    blocks = _extract_blocks(raw)
    assert len(blocks) == 1


def test_extract_blocks_tolerates_prose_before_json():
    raw = 'Here is your page:\n\n[{"type": "paragraph", "content": "Hi"}]'
    blocks = _extract_blocks(raw)
    assert len(blocks) == 1
    assert blocks[0]["content"] == "Hi"


def test_extract_blocks_tolerates_prose_after_json():
    raw = '[{"type": "paragraph", "content": "Hi"}]\nLet me know if you want changes!'
    blocks = _extract_blocks(raw)
    assert len(blocks) == 1


def test_extract_blocks_no_array_falls_back_to_paragraph():
    """When the LLM doesn't emit a JSON array, return a single
    paragraph block with the raw text so the UI gets *something*."""
    raw = "I don't think I can do that."
    blocks = _extract_blocks(raw)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "paragraph"
    assert "I don't think" in blocks[0]["content"]


def test_extract_blocks_malformed_json_falls_back_to_paragraph():
    raw = '[{"type": "paragraph", "content": "Hi",,,]'  # extra commas → invalid
    blocks = _extract_blocks(raw)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "paragraph"


def test_extract_blocks_non_array_falls_back():
    """Top-level object instead of array → fallback."""
    raw = '{"type": "paragraph", "content": "Hi"}'
    blocks = _extract_blocks(raw)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "paragraph"


def test_extract_blocks_empty_response_returns_empty():
    assert _extract_blocks("") == []
    assert _extract_blocks(None) == []  # type: ignore[arg-type]


# ----------------------------------------------------- _normalise_block

def test_normalise_block_adds_uuid_id():
    out = _normalise_block({"type": "paragraph", "content": "Hi"})
    assert out["id"]
    assert len(out["id"]) >= 32  # UUID4 stringified


def test_normalise_block_coerces_unknown_type_to_paragraph():
    out = _normalise_block({"type": "fakeBlock", "content": "Hi"})
    assert out["type"] == "paragraph"


def test_normalise_block_keeps_known_types():
    for t in ("paragraph", "heading", "bulletListItem", "numberedListItem"):
        out = _normalise_block({"type": t, "content": "x"})
        assert out["type"] == t


def test_normalise_heading_defaults_to_level_2():
    out = _normalise_block({"type": "heading", "content": "Title"})
    assert out["props"] == {"level": 2}


def test_normalise_heading_clamps_level():
    """Levels above 3 (eg h4-h6) get clamped to h3 — Phase 1 only
    renders h1/h2/h3."""
    out = _normalise_block({"type": "heading", "props": {"level": 6}, "content": "x"})
    assert out["props"] == {"level": 3}
    out = _normalise_block({"type": "heading", "props": {"level": 0}, "content": "x"})
    assert out["props"] == {"level": 1}


def test_normalise_heading_handles_string_level():
    """Some models emit level as a string (e.g. "1" not 1)."""
    out = _normalise_block({"type": "heading", "props": {"level": "2"}, "content": "x"})
    assert out["props"] == {"level": 2}


def test_normalise_block_coerces_list_content_to_string():
    """BlockNote inline content may come back as an array of {text:...}
    objects — collapse to a flat string for storage."""
    out = _normalise_block({
        "type": "paragraph",
        "content": [{"type": "text", "text": "Hi "}, {"type": "text", "text": "there"}],
    })
    assert out["content"] == "Hi there"


# ----------------------------------------------------- _coerce_content

@pytest.mark.parametrize("raw, expected", [
    ("plain string", "plain string"),
    ([{"text": "a"}, {"text": "b"}], "ab"),
    ([{"type": "text", "text": "x"}], "x"),
    ([], ""),
    (None, ""),
    (42, ""),
    ({"text": "wrapped"}, "wrapped"),
])
def test_coerce_content(raw, expected):
    assert _coerce_content(raw) == expected


# ----------------------------------------------------- public API smoke

class _FakeProvider:
    """Stand-in for whatever LLMRegistry.get_active() returns."""
    def __init__(self, response: str):
        self._response = response
        self.calls: list[tuple[str, list]] = []

    def complete(self, system, messages, **kwargs):
        self.calls.append((system, messages))
        return self._response


def test_generate_page_returns_normalised_blocks():
    fake = _FakeProvider(
        '[{"type": "heading", "props": {"level": 1}, "content": "Hi"}, '
        '{"type": "paragraph", "content": "Body"}]'
    )
    with patch("app.services.cms.ai_blocks.LLMRegistry.get_active",
               return_value=fake):
        blocks = generate_page("Write a study guide")
    assert len(blocks) == 2
    assert blocks[0]["type"] == "heading"
    assert blocks[0]["props"] == {"level": 1}
    assert all("id" in b for b in blocks)
    # The provider was called with the prompt
    assert len(fake.calls) == 1
    assert fake.calls[0][1][0]["content"] == "Write a study guide"


def test_generate_page_empty_prompt_short_circuits():
    """Don't waste an LLM call on an empty prompt."""
    fake = _FakeProvider("[]")
    with patch("app.services.cms.ai_blocks.LLMRegistry.get_active",
               return_value=fake):
        blocks = generate_page("")
    assert blocks == []
    assert fake.calls == []


def test_fill_block_returns_provider_text_stripped():
    fake = _FakeProvider("  Hello there.  \n")
    with patch("app.services.cms.ai_blocks.LLMRegistry.get_active",
               return_value=fake):
        text = fill_block("paragraph", "context here")
    assert text == "Hello there."


def test_fill_block_unknown_type_coerced_to_paragraph_in_prompt():
    fake = _FakeProvider("ok")
    with patch("app.services.cms.ai_blocks.LLMRegistry.get_active",
               return_value=fake):
        fill_block("fakeBlock", "context")
    user_msg = fake.calls[0][1][0]["content"]
    assert "paragraph block" in user_msg  # coerced from fakeBlock


def test_improve_block_returns_rewritten_text():
    fake = _FakeProvider("Polished version.")
    with patch("app.services.cms.ai_blocks.LLMRegistry.get_active",
               return_value=fake):
        text = improve_block("Original", "friendlier")
    assert text == "Polished version."


def test_improve_block_unknown_tone_falls_back_to_grammar():
    """If somehow a tone outside the Literal slipped through the
    schema layer, default to grammar so we don't crash."""
    fake = _FakeProvider("Fixed.")
    with patch("app.services.cms.ai_blocks.LLMRegistry.get_active",
               return_value=fake):
        text = improve_block("Original", "weird_unknown")  # type: ignore[arg-type]
    assert text == "Fixed."


def test_improve_block_empty_input_returns_input():
    """No LLM call for empty text."""
    fake = _FakeProvider("should not be called")
    with patch("app.services.cms.ai_blocks.LLMRegistry.get_active",
               return_value=fake):
        text = improve_block("", "shorter")
    assert text == ""
    assert fake.calls == []
