"""Pin the "deleted user can re-signup via Google" contract.

The contract this pins (decided 2026-05-13, see lessons doc row 40)
==================================================================

When ``DELETE /admin/users/{id}`` or ``DELETE /users/me`` runs the
soft-delete, the user row is redacted:

  * email      -> "deleted-{id}@redacted.invalid"
  * google_id  -> NULL
  * password_hash -> NULL
  * is_active  -> False

If that same person later clicks "Sign in with Google", the
``DefaultSqlAlchemyProvisioner.find_or_create`` lookup misses on
both ``google_id`` (now NULL on the old row) and ``email`` (the old
row has the redacted "deleted-X@redacted.invalid" instead of their
real email). So it falls through to "create new user" and the person
gets a fresh account — a different ``user.id`` from the deleted row.

This is INTENTIONAL — it's the GDPR "right to be forgotten" behavior.
The user's old account is genuinely gone; they're a fresh person to
the system.

If admin instead wanted "delete = ban this signup" semantics, we'd
have to keep ``google_id`` (or a hash of the original email) on the
deleted row so the lookup finds it and trips the ``is_active=False``
check. That's a future decision; for now the contract is "re-signup
allowed", and this test pins it.

Why this test exists
====================
Someone reading the soft-delete code in 6 months might think
"the deleted user can come back? that's a bug" and try to "fix" it
by retaining google_id on delete. That's a meaningful contract change
that needs a real product decision, not a refactor — this test makes
sure it can't happen silently.
"""
from app.models.user import User, UserRole
from app.services.auth.google_auth.provisioner import (
    DefaultSqlAlchemyProvisioner, GoogleClaims,
)
from app.services.user_deletion import soft_delete_user


def _google_claims(*, sub: str, email: str, name: str = "Test User") -> GoogleClaims:
    """Build a GoogleClaims for the provisioner. Mimics what
    verify_google_id_token would produce for a real Google JWT, minus
    the JWT round-trip."""
    return GoogleClaims({
        "sub": sub,
        "email": email,
        "email_verified": True,
        "name": name,
    })


def _make_provisioner(db) -> DefaultSqlAlchemyProvisioner:
    """Build a provisioner against the test db. Same shape the real
    /auth/google endpoint constructs."""
    return DefaultSqlAlchemyProvisioner(db, User, UserRole)


def test_google_signup_works_for_a_brand_new_user(db):
    """Sanity: with no existing user, Google sign-in creates one."""
    prov = _make_provisioner(db)
    claims = _google_claims(sub="ggsub-fresh-001",
                             email="fresh@example.com")
    user = prov.find_or_create(claims)
    assert user.id is not None
    assert user.email == "fresh@example.com"
    assert user.google_id == "ggsub-fresh-001"
    assert user.is_active is True
    assert user.__google_provisioning__["created"] is True


def test_google_signup_after_admin_delete_creates_NEW_account(db):
    """REGRESSION GUARD for the GDPR-style contract: a deleted user
    who re-Google-signs-up gets a brand-new account row, NOT a 'banned'
    response.

    The lookup chain in the provisioner:
      1. by google_id -> MISS (we nulled it during soft-delete)
      2. by email     -> MISS (we redacted it to deleted-X@redacted.invalid)
      3. create new   -> HIT  (returns a fresh row with is_active=True)
    """
    prov = _make_provisioner(db)

    # Step 1 — original Google signup.
    first_login = prov.find_or_create(_google_claims(
        sub="ggsub-aaa-111", email="alice@example.com", name="Alice"))
    original_id = first_login.id
    original_google_id = first_login.google_id

    # Step 2 — admin soft-deletes the account.
    soft_delete_user(db, first_login)

    db.refresh(first_login)
    assert first_login.deleted_at is not None
    assert first_login.is_active is False
    assert first_login.google_id is None             # redaction wiped it
    assert first_login.email == f"deleted-{original_id}@redacted.invalid"

    # Step 3 — same person clicks "Sign in with Google" again. Same
    # Google account (same sub + email).
    second_login = prov.find_or_create(_google_claims(
        sub="ggsub-aaa-111", email="alice@example.com", name="Alice"))

    # The provisioner CREATED a new row, NOT linked to the deleted one.
    assert second_login.id != original_id, (
        "Re-signup must create a NEW user row. If this is now equal, "
        "either (a) the soft-delete is leaking google_id (intentional ban-list "
        "semantics, requires product decision — see lessons doc row 40), or "
        "(b) the email lookup matched the deleted row (which would mean "
        "redaction failed)."
    )
    assert second_login.email == "alice@example.com"
    assert second_login.google_id == original_google_id  # same person
    assert second_login.is_active is True
    assert second_login.__google_provisioning__["created"] is True

    # The OLD soft-deleted row is unchanged by the new signup.
    db.refresh(first_login)
    assert first_login.deleted_at is not None
    assert first_login.is_active is False
    assert first_login.email == f"deleted-{original_id}@redacted.invalid"


def test_google_signup_after_self_delete_also_creates_NEW_account(db):
    """Same contract for GDPR self-delete — this is the path where it
    matters MOST that the user can come back (right to be forgotten)."""
    prov = _make_provisioner(db)

    first = prov.find_or_create(_google_claims(
        sub="ggsub-bbb-222", email="bob@example.com", name="Bob"))
    first_id = first.id

    # Same service — no distinction between admin-delete and self-delete
    # at this layer (intentional; see lessons doc row 40).
    soft_delete_user(db, first)
    db.refresh(first)

    second = prov.find_or_create(_google_claims(
        sub="ggsub-bbb-222", email="bob@example.com", name="Bob"))
    assert second.id != first_id
    assert second.is_active is True


def test_subsequent_google_login_on_active_user_does_NOT_create_new_account(db):
    """Inverse safety check: the contract ONLY creates a new account
    when the original row's google_id is NULL (i.e. it's been
    deleted). A normal returning login finds-and-updates the same
    row.

    Without this, we'd be unable to distinguish 'returning user' from
    'first signup' — every login would create a duplicate."""
    prov = _make_provisioner(db)

    first = prov.find_or_create(_google_claims(
        sub="ggsub-ccc-333", email="charlie@example.com"))
    second = prov.find_or_create(_google_claims(
        sub="ggsub-ccc-333", email="charlie@example.com"))

    # Same row both times.
    assert second.id == first.id
    assert second.__google_provisioning__["created"] is False
    assert second.__google_provisioning__["login"] is True


def test_active_user_with_matching_email_but_no_google_id_gets_linked(db):
    """Adjacent contract: a returning user who originally signed up via
    PASSWORD (so google_id is NULL but email matches) gets their Google
    LINKED to the existing row, NOT a new row.

    This is distinct from the deleted-user case because is_active=True
    and email is unchanged. A bug in the find_or_create lookup that
    accidentally treated deleted+null-google_id like password+null-google_id
    would mistakenly LINK Google to the deleted row (and a subsequent
    login would then be on the soft-deleted row, which would trip
    is_active=False and PermissionError out — confusing for the user).
    """
    from app.core.security import hash_password
    existing = User(
        email="dora@example.com",
        password_hash=hash_password("apassword12345"),
        name="Dora",
    )
    db.add(existing); db.commit()

    prov = _make_provisioner(db)
    linked = prov.find_or_create(_google_claims(
        sub="ggsub-ddd-444", email="dora@example.com"))

    # Same row, now with google_id set.
    assert linked.id == existing.id
    assert linked.google_id == "ggsub-ddd-444"
    assert linked.__google_provisioning__["linked"] is True
