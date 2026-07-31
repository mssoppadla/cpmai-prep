"""app.core.domains — resolver tolerance for legacy stored spellings.

Early bulk imports stored the sheet's domain cell verbatim ("D-I
Trustworthy", "D-II Identify Business Needs and Solutions", …), which
split the results screen into duplicate buckets. get() must resolve
every historically observed spelling to its canonical code.
"""
import pytest

from app.core import domains as reg


@pytest.mark.parametrize("raw,code", [
    # Canonical inputs keep working.
    ("D-I", "D-I"),
    ("d-iii", "D-III"),
    ("trustworthy-ai", "D-I"),
    ("Trustworthy AI", "D-I"),
    ("identify data needs", "D-III"),
    # '&' vs 'and', punctuation and case drift.
    ("Identify Business Needs and Solutions", "D-II"),
    ("Manage AI Model Development and Evaluation", "D-IV"),
    # Legacy "code + label" free-text exactly as seen in prod data.
    ("D-I Trustworthy", "D-I"),
    ("D-II Identify Business Needs and Solutions", "D-II"),
    ("D-III Identify Data needs", "D-III"),
    ("D-IV Manage AI Model Development and Evaluation", "D-IV"),
    ("D-V Model Operationalize", "D-V"),
    # Code + separator + full name (editor-style label).
    ("D-I — Trustworthy AI", "D-I"),
    # Spaced-code free-text exactly as seen in the dev DB, including a
    # drifted label ("Manage Data model …" ≠ the canonical name).
    ("D I - Trustworthy AI", "D-I"),
    ("D II - Identify Business needs and Solutions", "D-II"),
    ("D III -Identify Data Needs", "D-III"),
    ("D IV - Manage Data model Development and Evaluation", "D-IV"),
    ("D V - Model Operationalization", "D-V"),
])
def test_get_resolves_all_accepted_spellings(raw, code):
    d = reg.get(raw)
    assert d is not None, f"{raw!r} did not resolve"
    assert d.code == code


@pytest.mark.parametrize("raw", [None, "", "   ", "General AI", "D-99 Whatever"])
def test_get_rejects_blank_and_unknown(raw):
    assert reg.get(raw) is None


def test_prefix_token_never_bleeds_across_codes():
    # "D-II …" must resolve by its own token, not the "D-I" prefix.
    assert reg.get("D-II anything at all").code == "D-II"
    assert reg.get("D-I anything at all").code == "D-I"


def test_display_name_falls_back_to_raw_then_unassigned():
    assert reg.display_name("D-V Model Operationalize") == "Model Operationalization"
    assert reg.display_name("General AI") == "General AI"
    assert reg.display_name("") == "Unassigned"
    assert reg.display_name(None) == "Unassigned"
