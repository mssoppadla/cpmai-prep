def test_signup_then_login(client):
    r = client.post("/api/v1/auth/signup", json={
        "email": "new@example.com", "password": "longenough12",
        "name": "New User",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["email"] == "new@example.com"
    assert body["user"]["role"] == "user"
    assert body["access"] and body["refresh"]


def test_login_with_wrong_password_fails(client, user):
    r = client.post("/api/v1/auth/login",
                    json={"email": user.email, "password": "WRONG"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


def test_login_response_shape_matches_contract(client, user):
    r = client.post("/api/v1/auth/login",
                    json={"email": user.email, "password": "password123"})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"access", "refresh", "user"}
    assert set(body["user"].keys()) >= {"id", "email", "name", "role", "created_at"}


def test_lockout_after_repeated_failures(client, user, db):
    for _ in range(5):
        client.post("/api/v1/auth/login",
                    json={"email": user.email, "password": "WRONG"})
    r = client.post("/api/v1/auth/login",
                    json={"email": user.email, "password": "password123"})
    assert r.status_code in (401, 423)
    if r.status_code == 423:
        assert r.json()["error"]["code"] == "account_locked"


def test_user_enumeration_resistance(client):
    """Same error for unknown email and wrong password — no enumeration."""
    r1 = client.post("/api/v1/auth/login",
                     json={"email": "missing@example.com", "password": "x"})
    r2 = client.post("/api/v1/auth/login",
                     json={"email": "alice@example.com", "password": "x"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["error"]["code"] == r2.json()["error"]["code"]
