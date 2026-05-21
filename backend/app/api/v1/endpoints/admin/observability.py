"""Admin observability endpoints — disk usage gauge + reclaim hints.

The backend container runs inside docker and can only see its own
mounts directly. That's fine for the things that ACTUALLY matter to
this application:

  * the host filesystem stats (visible through any mount path on it),
  * the cpmai-uploads volume's contents (mounted at /app/uploads),
  * the backend logs dir (mounted at /app/logs via prod overlay).

For VPS-level reclaim targets the backend can't reach (docker
dangling images, builder cache, /var/backups/cpmai-prep), we return
the SSH commands the operator should run instead — that keeps this
endpoint useful without bind-mounting the entire host into the
container, which would defeat the security boundary.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter


router = APIRouter()


# Paths the backend can see directly. Everything else lives in
# "reclaim suggestions" returned as host commands.
_UPLOAD_ROOT = Path(os.environ.get("UPLOAD_ROOT", "/app/uploads"))
_LOG_ROOT = Path("/app/logs")


def _du_bytes(path: Path, max_entries: int = 100_000) -> int:
    """Sum of file sizes under `path`, recursively. Safe on missing
    paths (returns 0). Caps at `max_entries` files to avoid a runaway
    on weird filesystems — beyond that point the operator should be
    using disk-usage tools directly.
    """
    if not path.exists():
        return 0
    total = 0
    count = 0
    try:
        for root, _dirs, files in os.walk(path):
            for fname in files:
                fp = Path(root) / fname
                try:
                    total += fp.stat().st_size
                except OSError:
                    # Symlink to nowhere, permission denied, etc. Skip.
                    pass
                count += 1
                if count >= max_entries:
                    return total
    except OSError:
        pass
    return total


def _filesystem_snapshot(path: Path) -> dict[str, Any]:
    """``shutil.disk_usage`` runs against the underlying filesystem.
    Because /app/uploads is a docker volume mounted from the host,
    this gives us the HOST's disk stats — exactly what an operator
    needs to see "how full is the VPS"."""
    try:
        usage = shutil.disk_usage(str(path))
    except FileNotFoundError:
        usage = shutil.disk_usage("/")
    return {
        "path": str(path),
        "total_bytes": usage.total,
        "free_bytes": usage.free,
        "used_bytes": usage.used,
        "used_percent": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
    }


@router.get("/disk")
def disk_usage() -> dict[str, Any]:
    """Disk gauge + per-application breakdown + reclaim hints.

    Output shape:

        {
          "filesystem": { path, total/free/used/used_percent },
          "application": {
              "uploads_volume": { path, size_bytes, file_count? },
              "logs_dir":       { path, size_bytes, file_count? },
              "total_bytes":    sum of the above
          },
          "reclaimable": [
              { id, label, bytes?, count?, where, command, notes? }, ...
          ]
        }

    The "reclaimable" list is informational — the backend cannot
    execute these commands (it's in a sandboxed container), but the
    operator can SSH and run them. UI surfaces each one with the
    command so it's a one-copy-paste reclaim.
    """
    # Filesystem gauge — anchored at /app/uploads so we get the host
    # disk that holds the named volume (which is what the VPS operator
    # actually wants to know about).
    fs = _filesystem_snapshot(_UPLOAD_ROOT if _UPLOAD_ROOT.exists() else Path("/"))

    uploads_bytes = _du_bytes(_UPLOAD_ROOT)
    logs_bytes = _du_bytes(_LOG_ROOT)

    application = {
        "uploads_volume": {
            "path": str(_UPLOAD_ROOT),
            "size_bytes": uploads_bytes,
        },
        "logs_dir": {
            "path": str(_LOG_ROOT),
            "size_bytes": logs_bytes,
        },
        "total_bytes": uploads_bytes + logs_bytes,
    }

    # Reclaim hints. None of these run on the backend — they're
    # operator-side SSH commands. We label each one with the safety
    # impact so the UI can sort "safe to delete" vs "needs review".
    reclaimable: list[dict[str, Any]] = [
        {
            "id": "old_daily_backups",
            "label": "Daily backups beyond the 30-day retention",
            "where": "/var/backups/cpmai-prep/",
            "command": "find /var/backups/cpmai-prep -name '*__daily.*' -mtime +30 -delete",
            "safety": "safe",
            "notes": "backup.sh already does this on the daily cron. "
                     "Manual run is safe — protected backups (pre-deploy, "
                     "pre-restore) match a different filename pattern.",
        },
        {
            "id": "old_pre_deploy_backups",
            "label": "Pre-deploy backups beyond 14 days",
            "where": "/var/backups/cpmai-prep/",
            "command": "find /var/backups/cpmai-prep -name '*__pre-deploy-*' -mtime +14 -delete",
            "safety": "safe",
            "notes": "Pre-deploy snapshots protect the rollback window. "
                     "After 14 days they're no longer needed (deploy.sh "
                     "already moved on).",
        },
        {
            "id": "docker_dangling_images",
            "label": "Dangling docker images (overwritten :latest tags)",
            "where": "/var/lib/docker",
            "command": "docker image prune -af --filter 'until=72h'",
            "safety": "safe",
            "notes": "Each ``compose build`` orphans the previous "
                     ":latest tag. The 72h filter keeps 3 days of "
                     "manual-rollback headroom (the :previous TAG is "
                     "always preserved separately, never at risk). "
                     "deploy.sh runs this automatically post-deploy.",
        },
        {
            "id": "docker_builder_cache",
            "label": "Docker BuildKit cache",
            "where": "/var/lib/docker/buildkit",
            "command": "docker builder prune -af --filter 'until=24h'",
            "safety": "safe",
            "notes": "Build cache has no rollback value; only speeds "
                     "up the next build. 24h is plenty for a busy "
                     "VPS — reclaims 20-40 GB on a system with "
                     "multiple deploys per day.",
        },
        {
            "id": "rotated_caddy_logs",
            "label": "Rotated Caddy access logs",
            "where": "/var/log/caddy/",
            "command": "find /var/log/caddy -name '*.log.*' -mtime +14 -delete",
            "safety": "safe",
            "notes": "Caddy rotates at 100MB + keeps 5 historical files. "
                     "Anything older than 14 days is past the operational "
                     "investigation window.",
        },
        {
            "id": "rotated_backend_logs",
            "label": "Rotated backend JSONL logs",
            "where": "/opt/cpmai-prep/backend/logs/",
            "command": "find /opt/cpmai-prep/backend/logs -name '*.log.*' -mtime +14 -delete",
            "safety": "safe",
            "notes": "JSONL request/error logs. Recent ones (≤14 days) "
                     "are useful for incident review.",
        },
        {
            "id": "apt_archives",
            "label": "Cached apt packages (host OS only)",
            "where": "/var/cache/apt/archives/",
            "command": "sudo apt-get clean",
            "safety": "safe",
            "notes": "Just package downloads, not installed software. "
                     "apt re-downloads on next upgrade if needed.",
        },
        {
            "id": "stopped_containers",
            "label": "Stopped (exited) docker containers",
            "where": "/var/lib/docker/containers",
            "command": "docker container prune -f",
            "safety": "review",
            "notes": "Removes ALL stopped containers. SAFE only if "
                     "you don't have a debug container you want to "
                     "exec back into. Running containers are never "
                     "touched.",
        },
    ]

    return {
        "filesystem": fs,
        "application": application,
        "reclaimable": reclaimable,
    }
