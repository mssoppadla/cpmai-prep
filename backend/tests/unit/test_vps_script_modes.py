"""Regression guard: VPS operational scripts keep their +x bit in git.

Incident (2026-07): fx_refresh.sh / install_fx_cron.sh were committed
as mode 100644. deploy.sh guarded the installer with ``[ -x ... ]``, so
the FX-refresh cron was silently skipped on EVERY deploy and prod ran
on 7-week-old FX rates. The geoip cron scripts had the same latent bug.

Windows checkouts don't materialise the executable bit on disk, so we
assert the GIT INDEX mode (100755), which is what the VPS checkout
receives. Skips when git/.git isn't available (e.g. the preflight's
ephemeral backend container mounts only backend/) — the CI test job
runs from a full checkout and is the enforcing gate.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

# Every script deploy.sh or a cron entry executes directly. Add new
# scripts/vps/*.sh entries here when they're wired into deploy/cron.
_MUST_BE_EXECUTABLE = [
    "scripts/vps/backup.sh",
    "scripts/vps/deploy.sh",
    "scripts/vps/fx_refresh.sh",
    "scripts/vps/geoip_refresh.sh",
    "scripts/vps/install_app.sh",
    "scripts/vps/install_fx_cron.sh",
    "scripts/vps/install_geoip.sh",
    "scripts/vps/install_geoip_cron.sh",
    "scripts/vps/provision.sh",
    "scripts/vps/restore.sh",
]


def _repo_root() -> Path | None:
    for parent in [Path(__file__).resolve()] + list(
            Path(__file__).resolve().parents):
        if (parent / ".git").exists() and (parent / "scripts" / "vps").is_dir():
            return parent
    return None


def test_vps_scripts_are_executable_in_git():
    root = _repo_root()
    if root is None or shutil.which("git") is None:
        pytest.skip("repo root / git unavailable (containerised run) — "
                    "enforced by the CI test job instead")
    out = subprocess.run(
        ["git", "ls-files", "-s", "--", "scripts/vps"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout
    modes = {}
    for line in out.splitlines():
        # "<mode> <object> <stage>\t<path>"
        meta, _, path = line.partition("\t")
        modes[path] = meta.split()[0]

    offenders = [
        f"{path} (mode {modes.get(path, 'MISSING')})"
        for path in _MUST_BE_EXECUTABLE
        if modes.get(path) != "100755"
    ]
    assert offenders == [], (
        "These scripts must be executable in git (100755) — deploy.sh/cron "
        "runs them directly and a lost +x bit silently disables prod "
        "automation:\n  " + "\n  ".join(offenders) +
        "\nFix: git update-index --chmod=+x <path>")
