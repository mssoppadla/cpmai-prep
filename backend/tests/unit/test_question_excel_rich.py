"""Rich-text ↔ Excel round-trip pins (2026-09).

The contract the admin was promised, verbatim:
  * export projects rich HTML into readable cells — **bold**, *italic*,
    __underline__, "- " / "1. " lists, real newlines, and [image: url]
    tokens sitting EXACTLY where each image sits (mid-sentence stays
    mid-sentence)
  * an untouched cell re-imports as a byte-for-byte no-op
  * an edited cell rebuilds; tokens become <img> at their position
  * images are NEVER silently lost: tokens gone but stored value had
    images → images kept (appended) + warning; dead token → skipped +
    warning
  * plain legacy strings stay plain in both directions
"""
from pathlib import Path

import pytest

from app.services.question_excel import (
    cell_text_to_html, html_to_cell_text, merge_cell_rich,
)

RICH = ('Phase 2 profiles the data. <b>Remember the order.</b><br>'
        '<img src="/uploads/1/2026/09/aa-diagram.png" alt="">'
        '<br>Second line after the image.')


# ------------------------------------------------------------ export

def test_plain_legacy_value_projects_unchanged():
    assert html_to_cell_text("score < 70% fails 🎯\nline two") \
        == "score < 70% fails 🎯\nline two"


def test_rich_value_projects_readable_with_positioned_token():
    assert html_to_cell_text(RICH) == (
        "Phase 2 profiles the data. **Remember the order.**\n"
        "[image: /uploads/1/2026/09/aa-diagram.png]\n"
        "Second line after the image.")


def test_mid_sentence_image_stays_mid_sentence():
    v = 'The pipeline <img src="/uploads/1/f.png" alt=""> runs left to right.'
    assert html_to_cell_text(v) \
        == "The pipeline [image: /uploads/1/f.png] runs left to right."


def test_lists_project_and_rebuild():
    v = "<ul><li>first</li><li>second</li></ul><ol><li>one</li><li>two</li></ol>"
    cell = html_to_cell_text(v)
    assert "- first" in cell and "- second" in cell
    assert "1. one" in cell and "2. two" in cell
    rebuilt = cell_text_to_html(cell)
    assert "<ul><li>first</li><li>second</li></ul>" in rebuilt
    assert "<ol><li>one</li><li>two</li></ol>" in rebuilt


# ------------------------------------------------------------ import

def test_untouched_cell_is_byte_for_byte_noop():
    stored, warn = merge_cell_rich(html_to_cell_text(RICH), RICH)
    assert stored == RICH          # identical object content — no rebuild
    assert warn is None


def test_edited_cell_rebuilds_with_image_at_its_position(tmp_path):
    (tmp_path / "1/2026/09").mkdir(parents=True)
    (tmp_path / "1/2026/09/aa-diagram.png").write_bytes(b"png")
    cell = ("NEW text before. [image: /uploads/1/2026/09/aa-diagram.png] "
            "And **after**.")
    stored, warn = merge_cell_rich(cell, RICH, upload_root=tmp_path)
    assert warn is None
    assert stored == ('NEW text before. '
                      '<img src="/uploads/1/2026/09/aa-diagram.png" alt=""> '
                      'And <b>after</b>.')


def test_tokens_missing_keeps_images_and_warns():
    stored, warn = merge_cell_rich("totally new text, no token", RICH)
    assert '<img src="/uploads/1/2026/09/aa-diagram.png"' in stored
    assert "totally new text, no token" in stored
    assert warn and "kept 1 image(s)" in warn


def test_dead_image_token_skipped_with_warning(tmp_path):
    cell = "text [image: /uploads/1/2026/09/gone.png] more"
    stored, warn = merge_cell_rich(cell, "", upload_root=tmp_path)
    assert "<img" not in (stored or "")
    assert warn and "not found" in warn


def test_plain_edit_of_plain_value_stays_plain():
    stored, warn = merge_cell_rich("just new plain words", "old plain words")
    assert stored == "just new plain words"
    assert warn is None


def test_blank_cell_clears_plain_field():
    stored, warn = merge_cell_rich("", "old plain words")
    assert stored is None and warn is None


def test_emoji_and_angle_brackets_survive_round_trip():
    cell = "score < 70% fails 🎯 **really**"
    stored, _ = merge_cell_rich(cell, "")
    assert "🎯" in stored
    assert "&lt; 70%" in stored          # escaped, so never parsed as a tag
    assert "<b>really</b>" in stored
    assert html_to_cell_text(stored) == cell
