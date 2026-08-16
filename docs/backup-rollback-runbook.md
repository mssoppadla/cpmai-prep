# Backup & Rollback Runbook

The one page to open when something goes wrong. Every command is
copy-paste ready for the VPS (`ssh deploy@<host>`, `cd /opt/cpmai-prep`).

## What gets backed up, when, automatically

| Artifact | Contains | When |
|---|---|---|
| `<ts>__<tag>.sql.gz` | **Every table** (full pg_dump, plain SQL) | nightly 02:30 cron · before every deploy · manual |
| `<ts>__<tag>.dump` | Same data, custom format → **single-table restore capable** | same schedule |
| `<ts>__<tag>.counts.txt` | Row count of every table at backup time | same schedule |
| `<ts>__<tag>.env.tar.gz` | backend/.env + frontend/.env.local | same schedule |
| `<ts>__<tag>.uploads.tar.gz` | All CMS/LMS file uploads | same schedule |

All in `/var/backups/cpmai-prep/`. Every backup **self-verifies**
(gzip integrity + size sanity) at creation — a corrupt backup fails
loudly the night it's made, not the day it's needed.

Retention: 30 daily sql/dump/manifest · 7 daily uploads tarballs ·
pre-deploy sets 14 days (uploads capped at 5) · manual tags 30 days.

Manual backup before anything risky:
```bash
./scripts/vps/backup.sh "before-<what-you-are-about-to-do>"
```

## Scenario A — a deploy broke things
Usually nothing to do: deploy.sh auto-rolls-back (previous images +
pre-deploy DB restore) when the health check, data-preservation guard,
or smoke test fails. If you must revert a deploy that PASSED its checks
but is behaviorally wrong:
```bash
ls -lt /var/backups/cpmai-prep/*pre-deploy*.sql.gz | head -3   # pick the right one
./scripts/vps/restore.sh /var/backups/cpmai-prep/<file>.sql.gz
```
restore.sh asks for confirmation, takes its own pre-restore backup
first (so even a wrong restore is reversible), restores DB + uploads
(stage→verify→swap; a bad archive is a no-op), migrates, restarts,
health-checks.

## Scenario A2 — rolling back a deploy DAYS later (data must survive)
The Scenario-A restore path is for MINUTES-old deploys. If the bad
deploy has been live for hours or days, users have signed up, taken
exams, and paid since — a DB restore would erase all of it. The rule:

**Late rollback = CODE-ONLY rollback. Never restore the DB.**

```bash
git log --oneline -5                      # find the last good commit
git checkout <good-sha> && ./scripts/vps/deploy.sh   # redeploy old code
# (or: docker tag cpmai-prep-backend:previous cpmai-prep-backend:latest
#      + docker compose up -d, if the images are still on disk)
```

Why this is safe: migrations here are ADDITIVE-ONLY by policy (new
columns/tables, never renames/drops in the same release) — old code
runs fine against the newer schema, so reverting code does not require
reverting the database. New-user signups, exam results, and payments
taken during the bad period are all retained.

- deploy.sh's AUTOMATIC rollback (which does restore the pre-deploy
  backup) only fires during the deploy itself — minutes of exposure,
  before real user activity accumulates. It never runs later.
- If the bad deploy also CORRUPTED data, don't full-restore: fix the
  damaged rows with Scenario-C (single table) or targeted SQL, keeping
  everything created since.
- If a migration in the bad release was NOT additive (schema the old
  code can't run on), roll FORWARD with a fixing commit instead of
  rolling back.

## Scenario B — bad data change / accidental damage, no deploy involved
Same as A but pick the newest backup from BEFORE the damage:
```bash
ls -lt /var/backups/cpmai-prep/*.sql.gz | head -5
./scripts/vps/restore.sh /var/backups/cpmai-prep/<chosen>.sql.gz
```
Everything after that timestamp is lost — check the `.counts.txt`
manifest next to it to see what state you're returning to.

## Scenario C — one table damaged, everything else fine
Full restore would discard unrelated new data. Use the custom-format
`.dump` to surgically restore a single table. (This exact sequence was
drill-tested 2026-08-16: table wiped to 0 rows → restored to full.)
```bash
# 1. ALWAYS snapshot current state first
./scripts/vps/backup.sh "before-table-restore"
# 2. Copy the dump INTO the container (restore from a file path —
#    piping binary dumps over stdin is fragile across shells)
docker cp /var/backups/cpmai-prep/<file>.dump cpmai-prep-postgres-1:/tmp/restore.dump
# 3. Restore ONE table (example: faq_items) — --clean drops+recreates
#    just that table from the backup
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
  pg_restore -U cpmai -d cpmai_prep --clean --if-exists --no-owner \
  --table=faq_items /tmp/restore.dump
# 4. Verify counts vs the manifest, then clean up
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres \
  psql -U cpmai -d cpmai_prep -At -c "SELECT count(*) FROM faq_items"
grep faq_items /var/backups/cpmai-prep/<file>.counts.txt
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres rm /tmp/restore.dump
```
Drill-learned caveats:
- **Works on the live DB only** — a `--table` restore into an EMPTY
  database fails on enum-typed columns (types aren't included). For
  scratch-DB drills, full-restore first, then practice the table step.
- **FK-referenced tables** (users, plans, …): the `--clean` drop can be
  blocked by foreign keys pointing at the table. If you hit FK errors,
  fall back to a full Scenario-B restore rather than fighting
  constraints by hand.
- ⚠️ Guarded tables (users, payments, subscriptions, exam data…): a
  single-table restore REPLACES current rows with backup rows —
  anything created since the backup is lost for that table. Prefer a
  full Scenario-B restore or targeted SQL for those.

## Scenario D — uploads (images/videos/PDFs) missing, DB fine
```bash
ls -lt /var/backups/cpmai-prep/*.uploads.tar.gz | head -5   # pick a FULL-SIZE one (~2G, never ~100 bytes)
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backend \
  tar -xzf - -C /app/uploads < /var/backups/cpmai-prep/<file>.uploads.tar.gz
curl -s -o /dev/null -w "%{http_code}\n" https://api.cpmaiexamprep.com/uploads/<known-file>   # expect 200
```

## Scenario E — health check of the backup system itself (monthly habit)
```bash
ls -lt /var/backups/cpmai-prep/ | head -8          # fresh files? sane sizes?
gunzip -t /var/backups/cpmai-prep/$(ls -t /var/backups/cpmai-prep/*.sql.gz | head -1 | xargs basename)  && echo "latest dump OK"
df -h /                                            # disk headroom
```

## Scenario F — off-server copies (DECISION PENDING)
Everything above lives on the VPS disk. A disk failure or account
loss takes the backups with it. Options (operator to choose):
1. Hostinger's VPS backup/snapshot add-on — zero maintenance
2. rclone nightly sync of /var/backups to object storage
   (Backblaze B2 ≈ $6/TB/mo, or S3) — needs an account + keys
3. Minimum viable: periodic manual `scp` of the newest set to a local
   machine
Until one is in place, treat the VPS disk as a single point of failure.

## The three rules
1. **Before anything risky: take a tagged backup** (one command).
2. **Never restore over damage without the automatic pre-restore
   backup** (restore.sh does this for you — don't bypass it).
3. **A ~100-byte archive is a warning, not a backup** — full-size or
   it doesn't count.
