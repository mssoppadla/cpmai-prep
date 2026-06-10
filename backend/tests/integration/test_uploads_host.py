"""TrustedHost must allow the internal docker service name.

The frontend proxies /uploads/* to this service via a Next.js rewrite (so
StaticFiles-served lesson videos / CMS images are reachable behind the
"/"->frontend reverse proxy). That proxied request carries `Host: backend`
(the compose service name), so TrustedHostMiddleware has to allow it —
otherwise every upload 400s "Invalid host header". See app/main.py.
"""


def test_internal_docker_host_is_allowed(client):
    # Host the frontend uses when proxying /uploads to this backend.
    r = client.get("/health", headers={"host": "backend"})
    assert r.status_code == 200, r.text


def test_unknown_public_host_still_rejected(client):
    # The internal allowance must not open the door to arbitrary hosts.
    r = client.get("/health", headers={"host": "evil.example.com"})
    assert r.status_code == 400
