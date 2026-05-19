"""Unit tests for the ContentPage ORM model + schema validation.

Pins the structural invariants so accidental schema drift breaks here
(fast) instead of in integration tests (slow) or in production.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.models.content_page import NAV_VISIBILITY_CHOICES, ContentPage
from app.schemas.content_page import (
    ContentPageCreateIn,
    ContentPageUpdateIn,
)


# ----------------------------------------------------- NAV_VISIBILITY_CHOICES

def test_nav_visibility_choices_match_contract():
    """Phase 1 scope §1 group 1: always | authenticated | subscribed | hidden."""
    assert NAV_VISIBILITY_CHOICES == (
        "always", "authenticated", "subscribed", "hidden",
    )


# ----------------------------------------------------- model defaults

def test_content_page_defaults_to_tenant_one(db, default_tenant):
    """Contract I-1: tenant_id defaults to 1 when not specified."""
    page = ContentPage(slug="about", title="About Us")
    db.add(page); db.commit(); db.refresh(page)
    assert page.tenant_id == 1
    assert page.blocks == []
    assert page.nav_visibility == "always"
    assert page.nav_order == 100
    assert page.is_published is False
    assert page.is_deleted is False
    assert page.deleted_at is None
    assert page.deleted_by is None


def test_content_page_effective_nav_label_falls_back_to_title(db, default_tenant):
    """nav_label override is optional — title is the default."""
    no_label = ContentPage(slug="a", title="About Us")
    with_label = ContentPage(slug="b", title="Privacy Policy", nav_label="Privacy")
    db.add_all([no_label, with_label]); db.commit()
    assert no_label.effective_nav_label == "About Us"
    assert with_label.effective_nav_label == "Privacy"


# ----------------------------------------------------- slug uniqueness

def test_slug_unique_within_tenant(db, default_tenant):
    """Two pages with the same slug in the same tenant violate the
    UniqueConstraint (tenant_id, slug)."""
    db.add(ContentPage(slug="about", title="About v1"))
    db.commit()
    db.add(ContentPage(slug="about", title="About v2"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ----------------------------------------------------- Pydantic schema validation

@pytest.mark.parametrize("good_slug", [
    "about", "study-guide", "phase-1-tenants-foundation",
    "a", "a-b-c", "abc123", "p2",
])
def test_create_schema_accepts_valid_slug(good_slug):
    payload = ContentPageCreateIn(slug=good_slug, title="ok")
    assert payload.slug == good_slug


@pytest.mark.parametrize("bad_slug", [
    "",                       # empty
    "Study-Guide",            # uppercase
    "study guide",            # whitespace
    "-leading-dash",          # leading dash
    "trailing-dash-",         # trailing dash
    "double--dash",           # consecutive dashes
    "weird_underscore",       # underscore not allowed
    "/slash",                 # slash
    "?query",                 # punctuation
])
def test_create_schema_rejects_invalid_slug(bad_slug):
    with pytest.raises(ValidationError):
        ContentPageCreateIn(slug=bad_slug, title="ok")


def test_create_schema_rejects_unknown_nav_visibility():
    with pytest.raises(ValidationError):
        ContentPageCreateIn(slug="a", title="t", nav_visibility="public")


@pytest.mark.parametrize("v", ["always", "authenticated", "subscribed", "hidden"])
def test_create_schema_accepts_each_nav_visibility(v):
    payload = ContentPageCreateIn(slug="a", title="t", nav_visibility=v)
    assert payload.nav_visibility == v


def test_create_schema_blocks_defaults_to_empty_list():
    payload = ContentPageCreateIn(slug="a", title="t")
    assert payload.blocks == []


def test_update_schema_all_fields_optional():
    """PATCH should accept an empty body and produce no updates."""
    payload = ContentPageUpdateIn()
    assert payload.model_dump(exclude_unset=True) == {}


def test_update_schema_partial_update_only_includes_provided_fields():
    payload = ContentPageUpdateIn(title="New Title")
    dumped = payload.model_dump(exclude_unset=True)
    assert dumped == {"title": "New Title"}


def test_update_schema_validates_slug_when_provided():
    with pytest.raises(ValidationError):
        ContentPageUpdateIn(slug="Bad Slug")
