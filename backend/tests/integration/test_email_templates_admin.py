"""Admin CRUD for lead → auto-offer email templates."""
from tests.conftest import auth_header


def test_create_list_update_delete(client, admin):
    h = auth_header(client, admin.email)

    # create a default (source omitted → null) template
    r = client.post("/api/v1/admin/email-templates", headers=h, json={
        "subject": "Welcome {{name}}", "html_body": "<p>Hi {{name}}</p>",
    })
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert r.json()["source"] is None

    # list
    r = client.get("/api/v1/admin/email-templates", headers=h)
    assert r.status_code == 200
    assert any(t["id"] == tid for t in r.json())

    # update subject + attach a source
    r = client.patch(f"/api/v1/admin/email-templates/{tid}", headers=h,
                     json={"subject": "Hey {{name}}", "source": "landing_hero"})
    assert r.status_code == 200
    assert r.json()["subject"] == "Hey {{name}}"
    assert r.json()["source"] == "landing_hero"

    # delete
    r = client.delete(f"/api/v1/admin/email-templates/{tid}", headers=h)
    assert r.status_code == 204


def test_empty_source_normalises_to_default(client, admin):
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/email-templates", headers=h, json={
        "source": "   ", "subject": "s", "html_body": "<p>x</p>",
    })
    assert r.status_code == 201
    assert r.json()["source"] is None


def test_test_send_unconfigured_reports_not_sent(client, admin):
    h = auth_header(client, admin.email)
    r = client.post("/api/v1/admin/email-templates", headers=h, json={
        "subject": "s", "html_body": "<p>x</p>",
    })
    tid = r.json()["id"]
    # No SMTP configured → send_email fail-soft returns False, endpoint 200.
    r = client.post(f"/api/v1/admin/email-templates/{tid}/test",
                    headers=h, json={"to": "me@x.test"})
    assert r.status_code == 200
    assert r.json()["sent"] is False
    assert r.json()["to"] == "me@x.test"


def test_requires_admin(client, user):
    h = auth_header(client, user.email)
    r = client.get("/api/v1/admin/email-templates", headers=h)
    assert r.status_code in (401, 403)
