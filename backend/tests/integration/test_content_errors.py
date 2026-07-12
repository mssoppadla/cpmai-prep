"""Public /content/errors — admin-editable 404/error-page copy.

Pins the default copy, the show_help_links toggle round-trip, and that
the endpoint is anonymous (error pages render for logged-out visitors).
"""
from tests.conftest import auth_header


def test_errors_copy_defaults_anonymous(client):
    r = client.get("/api/v1/content/errors")   # no auth on purpose
    assert r.status_code == 200
    body = r.json()
    assert body["not_found_title"] == "Uh oh! You seem to have lost your way."
    assert body["not_found_body"] == "Let us help you find what you were looking for:"
    assert body["server_error_title"] == "Something went wrong on our end"
    assert isinstance(body["server_error_body"], str)
    assert body["show_help_links"] is True


def test_errors_copy_reflects_admin_edits(client, admin):
    h = auth_header(client, admin.email)
    r1 = client.patch("/api/v1/admin/settings/errors.not_found_title",
                      headers=h, json={"value": "Page missing!"})
    assert r1.status_code == 200
    r2 = client.patch("/api/v1/admin/settings/errors.show_help_links",
                      headers=h, json={"value": False})
    assert r2.status_code == 200

    body = client.get("/api/v1/content/errors").json()
    assert body["not_found_title"] == "Page missing!"
    assert body["show_help_links"] is False
