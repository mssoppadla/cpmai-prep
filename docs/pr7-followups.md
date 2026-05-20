# PR #7 (LMS foundation) — follow-ups

Snapshot of work that surfaced during PR #7 audit but didn't ship with
the foundation commit. Conventions mirror `backlog.md`:

- `[DONE]` — already shipped on `feat/phase1-lms-foundation`
- `[BUG]` — broken behaviour that must ship before merge
- `[FEATURE]` — net-new functionality
- `[REFACTOR]` — code-quality clean-up, no behaviour change
- `[INFRA]` — deploy / ops / observability gap
- `[FOLLOW-UP]` — known gap, scheduled for a later PR

Last updated: 2026-05-20 (during the operator-readiness audit).

---

## In-flight in this PR (bundled with the silent-fail audit fix)

### [DONE] CI test-gate `PermissionError: '/app'`
`backend/app/main.py` did `mkdir(/app/uploads)` at module-import time.
GitHub Actions runner can't create `/app` at filesystem root → ~80 tests
errored on collection. Wrapped in `try/except`, env-gated: tolerate
silently when `APP_ENV=test`, re-raise everywhere else so dev/staging/
prod fail loudly and trip auto-rollback.

### [DONE] Prod uploads volume ownership
Docker initializes named volumes from the image's contents at the mount
path. If `/app/uploads` doesn't exist in the image, the volume is
created as `root:root` and the non-root `app` (UID 999) container user
gets `EACCES` on every upload. `Dockerfile` now pre-creates the dir
with `app:app` ownership before `USER app`.

### [DONE] Five silent-failure surfaces
- `admin/lessons/[id]` file-list 500 → empty Files panel → admin re-uploads existing files silently. Now surfaces a banner.
- `courses/page.tsx` categories load → no filter chips, no log. Now `console.error`.
- `courses/[slug]/lessons/[lid]` × 3 (started ping, throttled progress write, note load) → completion / resume / pre-existing notes vanished. Now labelled `console.error`s.

### [DONE] Quiz builder shows existing options on load
Previously the admin could ADD options but never SEE ones already stored
(no GET endpoint, no hydration on load). Backend: new
`GET /admin/quiz-questions/{id}/options`. Frontend: hydrates
`optionsByQ` in parallel after questions load, with per-option delete
button.

### [DONE] Lesson-file delete unlinks on-disk file
`DELETE /admin/lesson-files/{id}` was deleting the DB row but leaving
the file on disk → unbounded growth in `/app/uploads`. Now resolves the
URL against `UPLOAD_ROOT`, refuses external URLs (Vimeo/S3), enforces
`relative_to(UPLOAD_ROOT)` to defeat path traversal, then `unlink`s.

### [DONE] Tests pinning the new behaviours
4 new integration tests in `test_lms.py`:
`test_admin_list_quiz_options`,
`test_admin_list_quiz_options_unknown_question`,
`test_lesson_file_delete_unlinks_local_file`,
`test_lesson_file_delete_preserves_external_url`,
`test_lesson_file_delete_path_traversal_blocked`.

### [DONE] GitHub Actions Node-20 deprecation pre-emptively addressed
GitHub announced Node 20 actions are deprecated:
- **June 2, 2026**: runner forces Node 24 default
- **September 16, 2026**: Node 20 binary removed from runners (hard deadline)

Bumped all 4 workflow files ahead of forced Node 24:
- `actions/checkout` v4 → v6 (used 6× across deploy/backend-ci/frontend-ci/security-scan)
- `actions/setup-python` v5 → v6 (used 4×)
- `actions/setup-node` v4 → v6 (used 3×)

Bumps verified as drop-in compatible — same input names, same outputs.
YAML parses cleanly. Deploy gate remains intact.

---

## Bucket B — small/medium follow-ups bundled into this same push

### [INFRA] `chmod 0600` on uploads tarball in `backup.sh`
Env tar gets 0600 in `backup.sh` but the new uploads tarball is
world-readable. Uploaded content can contain PII (signed PDFs,
screenshots with personal data). One-line fix.

### [FEATURE] Allow SVG image uploads
`image/svg+xml` not in `ALLOWED_MIMES`. Admins want to attach
diagrams/illustrations. One-line addition.

### [FEATURE] 1 GB upload cap (was 100 MB)
1-hour lesson videos at "good professional quality" land at
700 MB–1.2 GB. Cap had to grow. Plus add a UI hint of the limit so
admins know before they fail.

### [FEATURE] Image thumbnail in admin file picker
Currently `FileAttachmentsSection` shows filename + delete only.
Image rows now render a thumbnail (`/uploads/...` is same-origin from
the backend; `absoluteUploadUrl()` handles cross-origin).

### [FEATURE] Course categories: `display_order` + drag-reorder
Categories appeared in DB-insert order. Added an additive migration
(0030), schema field, admin reorder endpoint, and a drag UI.

### [FEATURE] Public course detail shows enrollment count
"247 students enrolled" social proof. Read-side: count enrollments per
course in the public detail payload.

### [FEATURE] Disk-usage observability + reclaimable items
New `/api/v1/admin/observability/disk` returns:
- Total VPS disk + free
- Application directory size
- Per-volume size (`cpmai-uploads`, `pgdata`, etc.)
- Backups dir size + retention status
- **Reclaimable**: items the operator can safely remove (old backups
  beyond the retention window, dangling docker images, builder cache,
  rotated log files).

Admin UI surfaces this on the existing `/admin/observability` page with
a "Reclaim" link that runs the corresponding cleanup.

### [FEATURE] Video upload: in-browser compression preview
The 1 GB cap is generous but bandwidth + storage cost still matter.
Added a MediaRecorder-based "Compress before upload" step:
- Per-resolution + per-bitrate presets (1080p, 720p, 480p × low/med/high)
- Real-time stats: source bitrate, predicted output size + duration
- Quality recommendation based on duration (e.g., "1 hr lecture →
  720p / 2.5 Mbps recommended → ~1.1 GB")
- Side-by-side preview (first 10s of each)
- Admin can skip compression and upload the original at any time

---

## Bucket C — medium, deferred to a follow-up PR

### [REFACTOR] Replace browser `prompt()` dialogs
8 sites across `admin/lessons/[id]` and `admin/courses/[id]` use
`prompt()` / `confirm()` for chapter/lesson/announcement/question/option
titles. `prompt()` breaks on mobile, has no validation, no rich text.
Replace with inline `<input> + Save` panels.

### [FEATURE] "Post a review" UI on course detail page
Backend endpoint and public list already exist. Just missing the form
on `/courses/[slug]`. Wire it.

### [REFACTOR] Soft-delete cascade for files
This PR adds disk-unlink for `DELETE /admin/lesson-files/{id}` but
`Course.is_deleted = True` / `Lesson.is_deleted = True` don't touch the
files. A nightly GC cron (in this same operations PR) should sweep
orphan files for soft-deleted parents older than N days.

---

## Bucket D — separate, larger PRs

### [FOLLOW-UP] PR #9 — R2/S3 storage backend
`LessonFile.file_object_key` field is in place (currently `NULL` for
all rows). Swap `admin/uploads.py` to also POST to R2-compatible
storage and store the key; the public renderer prefers `file_object_key`
when set. Reuses the same `file_url` for backwards-compat.

### [FOLLOW-UP] Razorpay → enrollment auto-grant
Paid courses currently have to be manually enrolled. The payment
webhook handler needs a "course or course-bundle" branch that calls
`grant_enrollment` after a successful charge. Belongs to the
payments-touching PR.

### [FOLLOW-UP] Course completion certificates
Generate a PDF on completion (using the existing PDF-gen path from
the assistant). Out of scope here.

### [FOLLOW-UP] Discussion thread inline integration
`discussion_url` is currently a plain link. Inline Discord widget /
embed is a UX upgrade, not a foundation requirement.

### [FOLLOW-UP] Captions upload + transcription flow
`Lesson.captions_url` exists, no upload UI, no auto-generation.

### [FOLLOW-UP] Quiz: image-in-question support
Schema is text-only. Adding an `image_url` column + admin upload flow
+ public renderer is a follow-up feature.

---

## Bucket E — operational, no code

### [INFRA] Wire `console.error` calls to a log aggregator
The silent-fail audit added 4 `console.error` calls. They currently
only surface in browser devtools. Wire to Sentry / Logflare / similar
so ops sees them in aggregate.

### [INFRA] Disk-usage alert thresholds
Once the new `/admin/observability/disk` endpoint lands, set up a cron
that fires a webhook when `cpmai-uploads` volume hits 80% of its
provisioned size, or when `/var/backups/cpmai-prep` exceeds 50 GB.
