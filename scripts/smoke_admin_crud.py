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
clean run, 1 if any step failed. Designed for fast regression checks
after any backend or schema change.

Usage:
    # backend + postgres + redis must be up (docker compose up -d)
    python scripts/smoke_admin_crud.py
    # or with custom creds / base URL:
    BASE_URL=http://localhost:8000/api/v1 \\
    ADMIN_EMAIL=admin@example.com \\
    ADMIN_PASSWORD=admin-dev-pass-change-me \\
    python scripts/smoke_admin_crud.py

Requires: only stdlib (uses urllib.request — no external deps).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request


BASE = os.environ.get("BASE_URL", "http://localhost:8000/api/v1")
EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin-dev-pass-change-me")

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
