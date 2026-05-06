#!/usr/bin/env python3
"""Data-preservation guard — never lose users on a deploy.

Snapshots row counts for the tables you cannot afford to lose, then
either records the snapshot or compares against a previously-recorded
one and exits non-zero if any count went DOWN.

Designed for use around `scripts/upgrade.sh`:

    # before deploy
    python scripts/preserve_users_check.py snapshot

    # ... run alembic upgrade head, restart services, etc. ...

    # after deploy — refuses to exit 0 if any count decreased
    python scripts/preserve_users_check.py verify

The snapshot is JSON in /tmp by default — override with PRESERVE_SNAPSHOT_PATH.

Talks to the database by shelling out to psql (no psycopg2 dependency on
the host). The connection details come from PRESERVE_DB_CMD, defaulting
to `docker compose exec -T postgres psql -U cpmai -d cpmai_prep -At -c`,
which works in any environment that uses the project's docker-compose
stack. Override the env var if your prod DB lives elsewhere, e.g.:

    PRESERVE_DB_CMD='psql $DATABASE_URL -At -c' \\
    python scripts/preserve_users_check.py verify
"""
from __future__ import annotations

import json
import os
import pathlib
import shlex
import subprocess
import sys


# Tables whose rows must never decrease across a deploy. Add anything
# here that holds business data or auditable history.
GUARDED_TABLES = (
    "users",
    "exam_sessions",
    "exam_attempt_answers",
    "payments",
    "subscriptions",
    "leads",
    "audit_logs",
    "journey_events",
)

SNAPSHOT_PATH = pathlib.Path(
    os.environ.get("PRESERVE_SNAPSHOT_PATH",
                   str(pathlib.Path.home() / ".cpmai-preserve-snapshot.json"))
)

DB_CMD = os.environ.get(
    "PRESERVE_DB_CMD",
    "docker compose exec -T postgres psql -U cpmai -d cpmai_prep -At -c",
)


def _query_count(table: str) -> int:
    sql = f"SELECT count(*) FROM {table}"
    cmd = shlex.split(DB_CMD) + [sql]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        # Table missing on a fresh DB — treat as 0
        msg = (res.stderr or res.stdout or "").strip().splitlines()[-1:]
        print(f"  ! {table}: query failed — {msg} (treating as 0)",
              file=sys.stderr)
        return 0
    out = (res.stdout or "").strip().splitlines()
    if not out:
        return 0
    try:
        return int(out[-1])
    except ValueError:
        return 0


def snapshot() -> dict[str, int]:
    return {t: _query_count(t) for t in GUARDED_TABLES}


def cmd_snapshot() -> int:
    counts = snapshot()
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(counts, indent=2), encoding="utf-8")
    print(f"snapshot saved to {SNAPSHOT_PATH}:")
    for k, v in counts.items():
        print(f"  {k:>22s}: {v}")
    return 0


def cmd_verify() -> int:
    if not SNAPSHOT_PATH.is_file():
        print(f"ERROR: no snapshot at {SNAPSHOT_PATH}. "
              f"Run `preserve_users_check.py snapshot` first.", file=sys.stderr)
        return 2

    before = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    after = snapshot()

    failures: list[str] = []
    print(f"{'TABLE':>22s}  {'BEFORE':>8s}  {'AFTER':>8s}  {'DELTA':>7s}")
    for table in GUARDED_TABLES:
        b, a = before.get(table, 0), after.get(table, 0)
        delta = a - b
        marker = " "
        if delta < 0:
            marker = "!"
            failures.append(f"{table}: {b} -> {a}  (-{abs(delta)})")
        print(f"{marker} {table:>20s}  {b:>8}  {a:>8}  {delta:+7}")

    if failures:
        print()
        print("DEPLOY-SAFETY VIOLATION — row count DECREASED in:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print("\nRefusing to mark deploy successful. Restore from backup or "
              "investigate before retrying.", file=sys.stderr)
        return 1
    print("\nOK — every guarded table preserved or grew.")
    return 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("snapshot", "verify"):
        print(f"Usage: {sys.argv[0]} {{snapshot|verify}}", file=sys.stderr)
        return 2
    return cmd_snapshot() if sys.argv[1] == "snapshot" else cmd_verify()


if __name__ == "__main__":
    sys.exit(main())
