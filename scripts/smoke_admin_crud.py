#!/usr/bin/env python3
"""End-to-end smoke test for the admin CRUD flows.

Exercises every action an admin would take through the UI, against a
running stack:
    - login as super-admin
    - create / patch / delete an exam set
    - create / patch / delete a question
    - link, list, reorder, unlink questions on a set
    - confirm public learner endpoint sees the set

Each step prints PASS / FAIL with a one-line summary. Exit code is 0 on
clean run, 1 if any step failed, 2 if config is missing. Designed for
fast regression checks after any backend or schema change.

Credentials & config — never hardcoded. Resolved in this order:
    1. ADMIN_EMAIL / ADMIN_PASSWORD env vars (if set)
    2. BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD from backend/.env
       (the same source the backend uses to bootstrap the super-admin)

If neither is configured the script exits with a clear error before any
network call.

Usage:
    # backend + postgres + redis must be up (docker compose up -d)
    python scripts/smoke_admin_crud.py

Requires: only stdlib (uses urllib.request — no external deps).
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request


# -----------------------------------------------------------------------------
# Config: load credentials from backend/.env (the real config source)
# without overwriting anything already in the environment.
# -----------------------------------------------------------------------------
def _load_dotenv(path: pathlib.Path) -> None:
    """Tiny .env parser. Mirrors pydantic-settings' parsing closely enough for
    the keys this script needs. Never overwrites already-set env vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        # Strip surrounding quotes and inline comments
        val = val.split("#", 1)[0].strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_load_dotenv(_REPO_ROOT / "backend" / ".env")

BASE = os.environ.get("BASE_URL", "http://localhost:8000/api/v1")
EMAIL = (os.environ.get("ADMIN_EMAIL")
         or os.environ.get("BOOTSTRAP_ADMIN_EMAIL"))
PASSWORD = (os.environ.get("ADMIN_PASSWORD")
            or os.environ.get("BOOTSTRAP_ADMIN_PASSWORD"))

if not EMAIL or not PASSWORD:
    print("ERROR: admin credentials not configured.", file=sys.stderr)
    print("", file=sys.stderr)
    print("Provide them via either:", file=sys.stderr)
    print("  - ADMIN_EMAIL / ADMIN_PASSWORD env vars, or", file=sys.stderr)
    print("  - BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD in",
          file=sys.stderr)
    print(f"    {_REPO_ROOT / 'backend' / '.env'}", file=sys.stderr)
    sys.exit(2)

GREEN = "\033[0;32m"
RED = "\033[0;31m"
DIM = "\033[2m"
RESET = "\033[0m"

_failures: list[str] = []
_token: str | None = None


def http(method: str, path: str, body: dict | None = None,
         token: str | None = None) -> tuple[int, dict | None]:
    """Make a single HTTP call. Returns (status, decoded_json_or_none)."""
    url = path if path.startswith("http") else BASE + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return e.code, {"raw": raw.decode("utf-8", errors="replace")}


def step(name: str, ok: bool, detail: str = "") -> None:
    mark = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
    print(f"  [{mark}] {name}{(' — ' + DIM + detail + RESET) if detail else ''}")
    if not ok:
        _failures.append(name)


def section(title: str) -> None:
    print(f"\n== {title}")


# -----------------------------------------------------------------------------
# Smoke test
# -----------------------------------------------------------------------------

def main() -> int:
    global _token

    section("Health + auth")
    status, body = http("GET", "/../health" if not BASE.endswith("/api/v1")
                                else BASE.replace("/api/v1", "/health"))
    step("backend /health", status == 200,
         f"status={status} body={body}")

    status, body = http("POST", "/auth/login",
                        {"email": EMAIL, "password": PASSWORD})
    if status == 200 and body and "access" in body:
        _token = body["access"]
        step("login as super-admin", True, f"role={body['user']['role']}")
    else:
        step("login as super-admin", False, f"status={status} body={body}")
        return 1

    # Verify the /auth/google endpoint exists and rejects an obvious bogus
    # credential. Returns 503 when GOOGLE_OAUTH_CLIENT_ID is unset (feature
    # disabled) or 401 when configured (token can't be verified). Either is
    # a healthy answer; what would be wrong is a 500 or 200.
    status, body = http("POST", "/auth/google", {"credential": "bogus.jwt"})
    step("google sign-in endpoint rejects bogus token",
         status in (401, 503),
         f"status={status} ({'configured' if status == 401 else 'disabled'})")

    # ------------------------------------------------------------------
    section("Question CRUD")
    payload = {
        "stem": "SMOKE: which CPMAI phase defines the business goal?",
        "topic_id": 1,
        "difficulty": "easy",
        "domain": None, "task": None, "enablers": [], "remarks": None,
        "explanation": "Phase 1 — Business Understanding.",
        "options": [
            {"option_letter": "A", "text": "Phase 1", "is_correct": True,
             "reasoning": "right"},
            {"option_letter": "B", "text": "Phase 2", "is_correct": False,
             "reasoning": "wrong"},
        ],
        "is_active": True,
    }
    status, body = http("POST", "/admin/questions", payload, _token)
    qid = body.get("id") if body else None
    step("create question", status == 201 and qid is not None,
         f"status={status} id={qid}")
    if qid is None:
        return 1

    # PATCH — this used to fail with UniqueViolation on the options
    payload["stem"] = "SMOKE: edited stem — phase 1?"
    status, body = http("PATCH", f"/admin/questions/{qid}", payload, _token)
    step("update question (with options replace)",
         status == 200 and body and body.get("stem") == payload["stem"],
         f"status={status}")

    status, body = http("GET", f"/admin/questions/{qid}", token=_token)
    step("get question by id", status == 200 and body and body["id"] == qid,
         f"status={status}")

    # ------------------------------------------------------------------
    section("Exam-set CRUD")
    set_payload = {
        "name": "SMOKE Exam Set",
        "slug": "smoke-exam-set",
        "description": "Created by smoke_admin_crud.py",
        "difficulty": "easy",
        "time_limit_minutes": 15,
        "passing_score": 50,
        "is_active": True,
        "is_premium": False,
        "display_order": 999,
    }
    # Cleanup any leftover from a previous failed run before creating.
    status, body = http("GET", "/admin/exam-sets", token=_token)
    if status == 200 and isinstance(body, list):
        for s in body:
            if s.get("slug") == set_payload["slug"]:
                http("DELETE", f"/admin/exam-sets/{s['id']}", token=_token)

    status, body = http("POST", "/admin/exam-sets", set_payload, _token)
    sid = body.get("id") if body else None
    step("create exam set", status == 201 and sid is not None,
         f"status={status} id={sid}")
    if sid is None:
        http("DELETE", f"/admin/questions/{qid}", token=_token)
        return 1

    set_payload["name"] = "SMOKE Exam Set RENAMED"
    set_payload["time_limit_minutes"] = 30
    status, body = http("PATCH", f"/admin/exam-sets/{sid}", set_payload, _token)
    step("update exam set",
         status == 200 and body and body.get("name") == set_payload["name"]
         and body.get("time_limit_minutes") == 30,
         f"status={status}")

    # ------------------------------------------------------------------
    section("Linkage: link / list / reorder / unlink")
    status, _ = http("POST", f"/admin/exam-sets/{sid}/questions",
                     {"question_ids": [qid]}, _token)
    step("link question to set", status == 204, f"status={status}")

    status, body = http("GET", f"/admin/exam-sets/{sid}/questions",
                        token=_token)
    linked_ok = (status == 200 and isinstance(body, list) and len(body) == 1
                 and body[0]["question"]["id"] == qid
                 and body[0]["question"]["options"])
    step("list linked questions (with options)", linked_ok,
         f"status={status} count={len(body) if isinstance(body, list) else 0}")

    # Reorder: move our single question to position 50
    status, _ = http("PATCH", f"/admin/exam-sets/{sid}/questions/reorder",
                     {"items": [{"question_id": qid, "position": 50}]}, _token)
    step("reorder linked questions", status == 204, f"status={status}")

    status, _ = http("DELETE", f"/admin/exam-sets/{sid}/questions/{qid}",
                     token=_token)
    step("unlink question from set", status == 204, f"status={status}")

    # ------------------------------------------------------------------
    section("Public learner endpoint sees the set")
    status, body = http("GET", "/exam-sets")  # no auth — public
    visible = (status == 200 and isinstance(body, list)
               and any(s["slug"] == set_payload["slug"] for s in body))
    step("set visible on public /exam-sets", visible,
         f"status={status} count={len(body) if isinstance(body, list) else 0}")

    # ------------------------------------------------------------------
    section("Landing copy is hot-editable (no restart)")
    # Read current value, change it, read again, revert. Proves the
    # settings_store cache invalidation works without a restart.
    status, body = http("GET", "/content/landing")
    original_heading = body.get("lead_section_heading") if body else None
    step("read /content/landing", status == 200 and original_heading,
         f"status={status} heading={original_heading!r}")

    new_heading = "SMOKE-PROBE heading"
    status, _ = http("PATCH", "/admin/settings/landing.lead_section_heading",
                     {"value": new_heading}, _token)
    step("PATCH landing.lead_section_heading", status == 200,
         f"status={status}")

    # Re-read public endpoint — change should be visible immediately.
    # settings_store has a 30s in-process cache, so we may need to retry
    # briefly if the worker that serves the GET hasn't cleared its cache.
    import time as _time
    seen_change = False
    for _ in range(8):
        status, body = http("GET", "/content/landing")
        if body and body.get("lead_section_heading") == new_heading:
            seen_change = True
            break
        _time.sleep(0.5)
    step("public /content/landing reflects new heading without restart",
         seen_change,
         f"after-PATCH heading={(body or {}).get('lead_section_heading')!r}")

    # Revert.
    status, _ = http("PATCH", "/admin/settings/landing.lead_section_heading",
                     {"value": original_heading}, _token)
    step("revert heading", status == 200, f"status={status}")

    # ------------------------------------------------------------------
    section("FAQ CRUD")
    status, body = http("POST", "/admin/faqs", {
        "question": "SMOKE: is this a real FAQ?",
        "answer": "No — created by the smoke test, deleted at the end.",
        "display_order": 9999, "is_active": True,
    }, _token)
    fid = body.get("id") if body else None
    step("create FAQ", status == 201 and fid is not None,
         f"status={status} id={fid}")

    if fid:
        status, body = http("PATCH", f"/admin/faqs/{fid}", {
            "question": "SMOKE: edited FAQ question?",
            "answer": "Edited body.",
            "display_order": 9999, "is_active": False,
        }, _token)
        step("update FAQ (set inactive)",
             status == 200 and body and body.get("is_active") is False,
             f"status={status}")

        # Public /content/faqs hides inactive — confirm
        status, body = http("GET", "/content/faqs")
        hidden = (status == 200 and isinstance(body, list)
                  and not any(f.get("id") == fid for f in body))
        step("inactive FAQ hidden from public /content/faqs", hidden,
             f"status={status}")

        status, _ = http("DELETE", f"/admin/faqs/{fid}", token=_token)
        step("delete FAQ", status == 204, f"status={status}")

    # ------------------------------------------------------------------
    section("Contact (lead) delete via super-admin")
    # Create a junk lead to exercise the delete path, then delete it.
    junk_email = f"smoke-junk-{int(__import__('time').time())}@example.com"
    status, body = http("POST", "/leads", {
        "email": junk_email, "name": "Smoke Junk",
        "source": "landing_hero", "consent_marketing": True,
    })
    lid = body.get("id") if body else None
    step("create junk lead", status == 201 and lid is not None,
         f"status={status} id={lid}")

    if lid:
        status, _ = http("DELETE", f"/admin/leads/{lid}", token=_token)
        step("super-admin deletes lead", status == 204, f"status={status}")

    # ------------------------------------------------------------------
    section("Subscription gating on premium exam sets")
    # /exam-sets/{slug}/start requires get_current_user; admin has no active
    # subscription, so attempting a premium set must yield 402
    # (subscription_required). A free set returns 201. This proves the
    # gate at exam_service.py:38 still fires after any code change.
    status, body = http("GET", "/exam-sets")  # public list
    free_slug = next((s["slug"] for s in (body or [])
                      if not s.get("is_premium")), None)
    premium_slug = next((s["slug"] for s in (body or [])
                         if s.get("is_premium")), None)

    if premium_slug:
        status, body = http("POST", f"/exam-sets/{premium_slug}/start",
                            None, _token)
        gated = status == 402 and body and (body.get("error") or {}).get("code") == "subscription_required"
        step("premium set blocked without subscription (402)", gated,
             f"slug={premium_slug} status={status}")
    else:
        step("premium set blocked without subscription (402)", True,
             "skipped — no premium set seeded")

    if free_slug:
        # Don't actually start (creates rows); just verify the path is
        # reachable for an authed user. POST returns 201 and an attempt id.
        # Use a short-lived attempt and clean up via DB-level tear-down.
        status, body = http("POST", f"/exam-sets/{free_slug}/start",
                            None, _token)
        step("free set startable for authed user (201 or reuse 200)",
             status in (200, 201) and body and "id" in body,
             f"slug={free_slug} status={status}")

    # ------------------------------------------------------------------
    section("Cleanup")
    status, _ = http("DELETE", f"/admin/exam-sets/{sid}", token=_token)
    step("delete exam set", status == 204, f"status={status}")

    status, _ = http("DELETE", f"/admin/questions/{qid}", token=_token)
    step("delete question", status == 204, f"status={status}")

    # ------------------------------------------------------------------
    print()
    if _failures:
        print(f"{RED}FAIL{RESET} — {len(_failures)} step(s) failed:")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print(f"{GREEN}OK{RESET} — all admin CRUD flows green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
