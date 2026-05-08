"""Admin CRUD for /admin/plans and /admin/offer-codes."""
import pytest
from app.models.plan import Plan, PlanExamSet
from app.models.exam_set import ExamSet
from app.models.offer import OfferCode
from tests.conftest import auth_header


# ============================================================== plans
def test_create_plan_minimal(client, admin):
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/plans", headers=h, json={
        "name": "Exam Bundle", "slug": "exam-bundle",
        "bundle_type": "exam_bundle",
        "base_price_paise": 99900,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "exam-bundle"
    assert body["base_price_paise"] == 99900
    assert body["duration_days"] == 365
    assert body["exam_sets"] == []


def test_create_plan_with_exam_sets(client, admin, db, sample_exam_set):
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/plans", headers=h, json={
        "name": "Bundle A", "slug": "bundle-a",
        "bundle_type": "exam_bundle", "base_price_paise": 50000,
        "exam_set_ids": [sample_exam_set.id],
    })
    assert r.status_code == 201
    body = r.json()
    assert len(body["exam_sets"]) == 1
    assert body["exam_sets"][0]["id"] == sample_exam_set.id


def test_discount_must_be_below_base_at_create(client, admin):
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/plans", headers=h, json={
        "name": "Bad Plan", "slug": "bad-plan",
        "bundle_type": "exam_bundle",
        "base_price_paise": 1000, "discount_price_paise": 1500,
    })
    assert r.status_code == 422


def test_duplicate_slug_rejected(client, admin):
    h = auth_header(client, admin.email)
    payload = {
        "name": "A", "slug": "dup", "bundle_type": "exam_bundle",
        "base_price_paise": 1000,
    }
    assert client.post("/api/v1/admin/plans", headers=h, json=payload).status_code == 201
    payload["name"] = "B"
    r = client.post("/api/v1/admin/plans", headers=h, json=payload)
    assert r.status_code == 409


def test_list_returns_in_display_order(client, admin):
    h = auth_header(client, admin.email)
    for i, slug in enumerate(["c", "a", "b"], start=1):
        client.post("/api/v1/admin/plans", headers=h, json={
            "name": f"Plan {slug}", "slug": slug,
            "bundle_type": "exam_bundle", "base_price_paise": 1000 + i,
            "display_order": (3 - i),
        })
    r = client.get("/api/v1/admin/plans", headers=h)
    assert r.status_code == 200
    slugs = [p["slug"] for p in r.json()]
    assert slugs == ["b", "a", "c"]


def test_update_plan_replaces_exam_sets(client, admin, db, sample_exam_set):
    h = auth_header(client, admin.email)
    other = ExamSet(name="Other", slug="other", time_limit_minutes=30,
                    passing_score=70, is_active=True, created_by=admin.id)
    db.add(other); db.commit(); db.refresh(other)

    r = client.post("/api/v1/admin/plans", headers=h, json={
        "name": "P", "slug": "p", "bundle_type": "exam_bundle",
        "base_price_paise": 1000,
        "exam_set_ids": [sample_exam_set.id],
    })
    pid = r.json()["id"]
    r2 = client.patch(f"/api/v1/admin/plans/{pid}", headers=h, json={
        "exam_set_ids": [other.id],
    })
    assert r2.status_code == 200
    assert [es["slug"] for es in r2.json()["exam_sets"]] == ["other"]


def test_update_unknown_exam_set_rejected(client, admin):
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/plans", headers=h, json={
        "name": "P2", "slug": "p2", "bundle_type": "exam_bundle",
        "base_price_paise": 1000,
    })
    pid = r.json()["id"]
    r2 = client.patch(f"/api/v1/admin/plans/{pid}", headers=h, json={
        "exam_set_ids": [999_999],
    })
    assert r2.status_code == 422


def test_delete_plan_with_no_payments(client, super_admin):
    h = auth_header(client, super_admin.email)
    r = client.post("/api/v1/admin/plans", headers=h, json={
        "name": "Tmp", "slug": "tmp", "bundle_type": "exam_bundle",
        "base_price_paise": 1000,
    })
    pid = r.json()["id"]
    r2 = client.delete(f"/api/v1/admin/plans/{pid}", headers=h)
    assert r2.status_code == 204


def test_only_super_admin_can_delete(client, admin):
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/plans", headers=h, json={
        "name": "Tmp", "slug": "tmp", "bundle_type": "exam_bundle",
        "base_price_paise": 1000,
    })
    pid = r.json()["id"]
    r2 = client.delete(f"/api/v1/admin/plans/{pid}", headers=h)
    assert r2.status_code in (401, 403)


# ============================================================ offers
def test_create_offer_code(client, admin):
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/offer-codes", headers=h, json={
        "code": "save10", "discount_type": "percent", "discount_value": 10,
    })
    assert r.status_code == 201
    body = r.json()
    assert body["code"] == "SAVE10"            # normalised


def test_offer_percent_must_be_0_to_100(client, admin):
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/offer-codes", headers=h, json={
        "code": "BAD", "discount_type": "percent", "discount_value": 150,
    })
    assert r.status_code == 422


def test_duplicate_offer_code_rejected(client, admin):
    h = auth_header(client, admin.email)
    payload = {"code": "DUP", "discount_type": "flat", "discount_value": 100}
    assert client.post("/api/v1/admin/offer-codes", headers=h, json=payload).status_code == 201
    r = client.post("/api/v1/admin/offer-codes", headers=h, json=payload)
    assert r.status_code == 409


def test_update_offer_code(client, admin):
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/offer-codes", headers=h, json={
        "code": "U1", "discount_type": "percent", "discount_value": 5,
    })
    cid = r.json()["id"]
    r2 = client.patch(f"/api/v1/admin/offer-codes/{cid}", headers=h, json={
        "discount_value": 15, "is_active": False,
    })
    assert r2.status_code == 200
    body = r2.json()
    assert body["discount_value"] == 15
    assert body["is_active"] is False
