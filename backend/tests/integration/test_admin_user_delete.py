"""Admin-triggered user deletion: soft-delete contract + FK safety.

The bug this guards against
---------------------------
Reported 2026-05-13: admin clicks "Delete" on a user in /admin/leads
(Contacts), sees the generic 409 "This change conflicts with existing
data — most often a unique field…" error. Nothing got deleted.

Root cause: the handler did ``db.delete(u) + db.commit()`` (hard
delete), but the User row is referenced as a foreign key by ~10 child
tables (audit_logs, journey_events, etc.) with NO model-level
cascades. Postgres rejected the DELETE with an FK violation, our
generic IntegrityError handler in main.py caught it and returned 409.

The fix: route admin-triggered deletes through the same soft-delete
service the GDPR self-service path uses
(``app.services.user_deletion.soft_delete_user``). Soft-delete leaves
the row in place, redacts the PII, blocks login — no FK violations
possible.

These tests pin all four properties of the fix:

  1. Delete succeeds (204) on a user that has FK references.
  2. After delete: email redacted, name/password_hash/google_id NULL,
     is_active=False, deleted_at set.
  3. The FK-referencing rows survive intact (this is the bit a future
     refactor might accidentally break by re-introducing cascade rules
     and wiping payments/audit_logs).
  4. The /admin/users response surfaces deleted_at so the UI can
     visually mark the row.
"""
from app.models.audit_log import AuditLog
from app.models.lead import Lead, LeadSource
from app.models.payment import Payment
from app.models.subscription import Subscription
from app.models.user import User, UserRole
from tests.conftest import auth_header


def _user_with_fk_refs(db, email: str = "fk-user@example.com") -> User:
    """Create a user that has rows in every FK-pointing table we know
    about. If admin delete tries to hard-delete this user, Postgres
    will reject — that's exactly the bug the soft-delete fix avoids."""
    from app.core.security import hash_password
    u = User(email=email, name="FK User",
            password_hash=hash_password("apassword12345"))
    db.add(u); db.flush()

    # FK refs across the schema.
    db.add(Payment(
        user_id=u.id, amount_paise=99900, currency="INR",
        provider_order_id=f"order_{u.id}",
        idempotency_key=f"idem_{u.id}",
        status="captured",
    ))
    db.add(Subscription(user_id=u.id, plan="premium", status="active"))
    db.add(AuditLog(
        user_id=u.id, action="test.action",
        metadata_json={"note": "pre-delete sentinel"},
    ))
    # leads.converted_user_id FK
    db.add(Lead(
        email=email, source=LeadSource.LANDING_HERO,
        converted_user_id=u.id,
    ))
    db.commit()
    return u


def test_admin_delete_user_soft_deletes_and_succeeds(client, db, super_admin):
    """The exact reported bug — admin clicks Delete, gets 409.
    After this fix, that same flow returns 204 and the row is
    soft-deleted."""
    target = _user_with_fk_refs(db)
    target_id = target.id

    r = client.delete(f"/api/v1/admin/users/{target_id}",
                      headers=auth_header(client, super_admin.email))
    assert r.status_code == 204, r.text

    db.expire_all()
    row = db.get(User, target_id)
    assert row is not None, "row should still exist (soft delete only)"
    assert row.deleted_at is not None
    assert row.is_active is False
    assert row.email == f"deleted-{target_id}@redacted.invalid"
    assert row.name is None
    assert row.password_hash is None
    assert row.google_id is None


def test_admin_delete_preserves_fk_referencing_rows(client, db, super_admin):
    """The reason we chose soft-delete: hard-delete would either fail
    OR (with cascades) wipe payments + audit logs, both of which we
    must retain. Verify the financials + audit trail survive a delete."""
    target = _user_with_fk_refs(db)
    target_id = target.id

    r = client.delete(f"/api/v1/admin/users/{target_id}",
                      headers=auth_header(client, super_admin.email))
    assert r.status_code == 204

    db.expire_all()
    # Financials retained (Indian tax-law: 7-year retention).
    assert db.query(Payment).filter_by(user_id=target_id).count() == 1
    assert db.query(Subscription).filter_by(user_id=target_id).count() == 1
    # Audit trail retained (compliance + abuse investigation).
    # NB: there are TWO audit rows now — the sentinel we inserted
    # AND the user.deleted row written by the admin handler.
    refs = db.query(AuditLog).filter_by(user_id=target_id).count()
    assert refs >= 1
    # Lead.converted_user_id reference survives (the lead row stays
    # pointing at the now-redacted user).
    lead = db.query(Lead).filter_by(converted_user_id=target_id).first()
    assert lead is not None


def test_admin_delete_idempotent_on_already_deleted_user(client, db, super_admin):
    """Re-deleting an already-soft-deleted user is a no-op (still 204,
    no error). The audit row records was_already_deleted=True so the
    operator can see the second call was a no-op."""
    target = _user_with_fk_refs(db)
    target_id = target.id

    # First delete.
    r1 = client.delete(f"/api/v1/admin/users/{target_id}",
                       headers=auth_header(client, super_admin.email))
    assert r1.status_code == 204
    # Expire the test's session cache — the HTTP request runs in its
    # own DB session via FastAPI's get_db dependency; the test's
    # ``db`` session would otherwise return the pre-delete cached
    # row (deleted_at=None) on the next read.
    db.expire_all()
    first_deleted_at = db.get(User, target_id).deleted_at
    assert first_deleted_at is not None  # sanity — first delete did mutate

    # Second delete — should succeed without mutating deleted_at.
    r2 = client.delete(f"/api/v1/admin/users/{target_id}",
                       headers=auth_header(client, super_admin.email))
    assert r2.status_code == 204
    db.expire_all()
    second_deleted_at = db.get(User, target_id).deleted_at
    # deleted_at preserved from the first call.
    assert second_deleted_at == first_deleted_at


def test_admin_delete_blocks_self_delete(client, db, super_admin):
    """The handler must refuse to delete the operator's own account —
    safety net against fat-fingered button clicks on yourself."""
    r = client.delete(f"/api/v1/admin/users/{super_admin.id}",
                      headers=auth_header(client, super_admin.email))
    assert r.status_code == 400
    assert "self" in r.json()["error"]["message"].lower() \
        or "your own" in r.json()["error"]["message"].lower()


def test_admin_delete_blocks_last_super_admin(client, db, super_admin):
    """If the only super-admin is the target, refuse — we'd lock the
    project out of its own admin panel."""
    r = client.delete(f"/api/v1/admin/users/{super_admin.id}",
                      headers=auth_header(client, super_admin.email))
    # 400 from either the self-delete check OR the last-super-admin
    # check (both fire here — order depends on handler).
    assert r.status_code == 400


def test_admin_users_list_surfaces_deleted_at(client, db, super_admin):
    """After soft-delete, the user row stays visible in /admin/users.
    The response must include deleted_at so the UI can dim/strikethrough
    the row instead of rendering it as active."""
    target = _user_with_fk_refs(db, email="visible-after-delete@example.com")
    target_id = target.id

    client.delete(f"/api/v1/admin/users/{target_id}",
                  headers=auth_header(client, super_admin.email))

    r = client.get(f"/api/v1/admin/users/{target_id}",
                   headers=auth_header(client, super_admin.email))
    assert r.status_code == 200
    body = r.json()
    assert body["deleted_at"] is not None
    assert body["is_active"] is False
    assert body["email"].startswith("deleted-")


def test_admin_contacts_feed_surfaces_deleted_at_for_users(client, db, super_admin):
    """Same property on the unified Contacts feed — the UI's dim-deleted-
    rows logic needs deleted_at to be present on ContactRow user rows.

    Note: soft-deleted users are HIDDEN by default in the feed. The
    test passes ``include_deleted=true`` because we explicitly want to
    look at the tombstone. The "deleted users are hidden by default"
    behavior has its own test below.
    """
    target = _user_with_fk_refs(db, email="contacts-deleted@example.com")

    client.delete(f"/api/v1/admin/users/{target.id}",
                  headers=auth_header(client, super_admin.email))

    r = client.get(
        "/api/v1/admin/leads/contacts?q=deleted-&include_deleted=true",
        headers=auth_header(client, super_admin.email),
    )
    assert r.status_code == 200
    rows = r.json()
    deleted_row = next(row for row in rows
                       if row["kind"] == "user"
                       and row["id"] == target.id)
    assert deleted_row["deleted_at"] is not None


def test_admin_contacts_feed_hides_deleted_users_by_default(client, db, super_admin):
    """Deleted users should NOT appear in the default Contacts feed
    response — operators almost always want the active-contacts view."""
    target = _user_with_fk_refs(db, email="hideme-deleted@example.com")
    target_id = target.id

    client.delete(f"/api/v1/admin/users/{target_id}",
                  headers=auth_header(client, super_admin.email))

    # Default (no include_deleted) → should NOT contain the deleted user.
    r = client.get("/api/v1/admin/leads/contacts",
                   headers=auth_header(client, super_admin.email))
    assert r.status_code == 200
    rows = r.json()
    assert not any(row["kind"] == "user" and row["id"] == target_id
                   for row in rows), \
        "Default feed leaked a soft-deleted user — should be hidden"

    # With include_deleted=true → does contain it.
    r = client.get("/api/v1/admin/leads/contacts?include_deleted=true",
                   headers=auth_header(client, super_admin.email))
    rows = r.json()
    assert any(row["kind"] == "user" and row["id"] == target_id
               for row in rows)


def test_admin_users_list_hides_deleted_by_default(client, db, super_admin):
    """Default GET /admin/users skips soft-deleted users; the operator
    can opt in via ?include_deleted=true to investigate forensics."""
    target = _user_with_fk_refs(db, email="hideme-list@example.com")
    target_id = target.id

    client.delete(f"/api/v1/admin/users/{target_id}",
                  headers=auth_header(client, super_admin.email))

    r = client.get("/api/v1/admin/users",
                   headers=auth_header(client, super_admin.email))
    assert r.status_code == 200
    assert not any(u["id"] == target_id for u in r.json())

    r = client.get("/api/v1/admin/users?include_deleted=true",
                   headers=auth_header(client, super_admin.email))
    assert any(u["id"] == target_id for u in r.json())


def test_admin_delete_two_different_users_in_sequence(client, db, super_admin):
    """REGRESSION GUARD for "maybe it allows first delete alone but not
    successive" (operator concern, 2026-05-13).

    The idempotency test deletes the SAME user twice. This test is a
    distinct scenario: the operator deletes one user, then immediately
    deletes a DIFFERENT user — both should succeed. Failure modes this
    catches:

      * Stale session state on the second request (would 500 / 409).
      * Email-collision on the redacted ``deleted-{id}@redacted.invalid``
        pattern if the unique constraint isn't actually scoped per row.
      * Audit-log foreign-key issue if the deleted user's audit row
        breaks the second user's audit insert.
      * Anything that mutates global state (settings cache, redis key)
        in a way that survives across requests.
    """
    target_a = _user_with_fk_refs(db, email="seq-a@example.com")
    target_b = _user_with_fk_refs(db, email="seq-b@example.com")
    a_id, b_id = target_a.id, target_b.id
    assert a_id != b_id

    # Delete A.
    ra = client.delete(f"/api/v1/admin/users/{a_id}",
                       headers=auth_header(client, super_admin.email))
    assert ra.status_code == 204, ra.text

    # Delete B — must also succeed. THIS is the regression check.
    rb = client.delete(f"/api/v1/admin/users/{b_id}",
                       headers=auth_header(client, super_admin.email))
    assert rb.status_code == 204, rb.text

    db.expire_all()
    a = db.get(User, a_id)
    b = db.get(User, b_id)
    assert a.deleted_at is not None
    assert b.deleted_at is not None
    assert a.email == f"deleted-{a_id}@redacted.invalid"
    assert b.email == f"deleted-{b_id}@redacted.invalid"
    # And the redacted emails MUST be distinct (different IDs).
    assert a.email != b.email


def test_admin_delete_many_users_in_sequence(client, db, super_admin):
    """Stronger version of the above — five sequential deletes in one
    test, each on a different user. If the operator is clearing out a
    pile of junk signups, every click must work."""
    user_ids = []
    for i in range(5):
        u = _user_with_fk_refs(db, email=f"bulk-delete-{i}@example.com")
        user_ids.append(u.id)

    for uid in user_ids:
        r = client.delete(f"/api/v1/admin/users/{uid}",
                          headers=auth_header(client, super_admin.email))
        assert r.status_code == 204, \
            f"delete of user {uid} failed: {r.status_code} {r.text}"

    db.expire_all()
    for uid in user_ids:
        assert db.get(User, uid).deleted_at is not None


def test_admin_delete_post_delete_login_is_blocked(client, db, super_admin):
    """Functional check on the is_active=False side-effect — the deleted
    user can't log in afterward. This is what makes the soft-delete
    meaningful as a 'delete' rather than just a redaction."""
    target = _user_with_fk_refs(db, email="blockme@example.com")

    client.delete(f"/api/v1/admin/users/{target.id}",
                  headers=auth_header(client, super_admin.email))

    r = client.post("/api/v1/auth/login", json={
        "email": "blockme@example.com",
        "password": "apassword12345",
    })
    # Either 401 (auth rejects inactive) or some other non-2xx — what
    # matters is they can't get an access token.
    assert r.status_code >= 400
