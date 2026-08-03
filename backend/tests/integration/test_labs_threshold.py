"""Threshold Explorer lab: public config endpoint + admin editor."""
from tests.conftest import auth_header


def test_public_config_serves_default_demo(client, db):
    r = client.get("/api/v1/content/labs/threshold-explorer")
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["mode"] == "cases"
    assert len(cfg["cases"]) >= 10
    labels = {c["actual"] for c in cfg["cases"]}
    assert labels == {0, 1}          # demo must have both classes
    assert 0.01 <= cfg["threshold"] <= 0.99


def test_admin_save_roundtrips_to_public(client, admin, db):
    headers = auth_header(client, admin.email)
    payload = {
        "mode": "cases", "threshold": 0.4,
        "cases": [{"score": 0.2, "actual": 0}, {"score": 0.9, "actual": 1},
                  {"score": 0.55, "actual": 1}],
        "tp": 0, "fp": 0, "fn": 0, "tn": 0,
    }
    r = client.put("/api/v1/admin/labs/threshold-explorer",
                   headers=headers, json=payload)
    assert r.status_code == 200, r.text

    pub = client.get("/api/v1/content/labs/threshold-explorer").json()
    assert pub["threshold"] == 0.4
    assert len(pub["cases"]) == 3

    # Snapshot mode round-trips too.
    r = client.put("/api/v1/admin/labs/threshold-explorer", headers=headers,
                   json={"mode": "counts", "threshold": 0.5, "cases": [],
                         "tp": 10, "fp": 3, "fn": 2, "tn": 15})
    assert r.status_code == 200, r.text
    pub = client.get("/api/v1/content/labs/threshold-explorer").json()
    assert pub["mode"] == "counts" and pub["tp"] == 10 and pub["tn"] == 15


def test_admin_save_rejects_degenerate_configs(client, admin, db):
    headers = auth_header(client, admin.email)
    base = {"threshold": 0.5, "tp": 0, "fp": 0, "fn": 0, "tn": 0}
    # cases mode with a single class → curves undefined → rejected
    r = client.put("/api/v1/admin/labs/threshold-explorer", headers=headers,
                   json={**base, "mode": "cases",
                         "cases": [{"score": 0.2, "actual": 1},
                                   {"score": 0.8, "actual": 1}]})
    assert r.status_code == 422, r.text
    # too few cases
    r = client.put("/api/v1/admin/labs/threshold-explorer", headers=headers,
                   json={**base, "mode": "cases",
                         "cases": [{"score": 0.5, "actual": 1}]})
    assert r.status_code == 422, r.text
    # counts mode with all-zero counts
    r = client.put("/api/v1/admin/labs/threshold-explorer", headers=headers,
                   json={**base, "mode": "counts", "cases": []})
    assert r.status_code == 422, r.text
    # out-of-range score is caught by the schema
    r = client.put("/api/v1/admin/labs/threshold-explorer", headers=headers,
                   json={**base, "mode": "cases",
                         "cases": [{"score": 1.4, "actual": 1},
                                   {"score": 0.2, "actual": 0}]})
    assert r.status_code == 422, r.text


def test_admin_endpoints_require_admin(client, user, db):
    headers = auth_header(client, user.email)
    assert client.get("/api/v1/admin/labs/threshold-explorer",
                      headers=headers).status_code in (401, 403)
    assert client.put("/api/v1/admin/labs/threshold-explorer", headers=headers,
                      json={"mode": "counts", "threshold": 0.5, "cases": [],
                            "tp": 1, "fp": 0, "fn": 0, "tn": 0}
                      ).status_code in (401, 403)
