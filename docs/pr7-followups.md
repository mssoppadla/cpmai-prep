# PR #7 (LMS foundation) — follow-ups

Snapshot of work that surfaced during PR #7 audit but didn't ship with
the foundation commit. Conventions mirror `backlog.md`:

- `[DONE]` — already shipped on `feat/phase1-lms-foundation`
- `[BUG]` — broken behaviour that must ship before merge
- `[FEATURE]` — net-new functionality
- `[REFACTOR]` — code-quality clean-up, no behaviour change
- `[INFRA]` — deploy / ops / observability gap
- `[FOLLOW-UP]` — known gap, scheduled for a later PR

Last updated: 2026-05-26 (Visitor Insights v2 — local build, awaiting preflight + PR).

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

---

## PR #8 follow-ups — captured from 2026-05-24 operator session

After the Zoom + Social PR (#77) reached prod, the operator surfaced
a set of requirements that don't fit the v1 scope but should land in
the next PR. Captured here so they don't get lost.

### [FEATURE] SEO foundations — crawling, indexing, rich snippets
Comprehensive SEO pass:
  * `robots.txt` admin-editable (allow/disallow rules per path)
  * `sitemap.xml` auto-generated from active courses/pages/lessons
    (drops drafts + paywalled bodies)
  * Per-page Open Graph + Twitter Card admin controls (title, desc,
    og:image override)
  * Rich-snippet preview UI: "what Google will show" for the page
    being edited (Google's search-snippet renderer + character counters)
  * Schema.org JSON-LD per content type: Article for blog/study guide,
    Course for /courses, Person for instructor bios
  * Indexing controls: noindex toggle per CMS page; canonical URL
    override per page; meta keywords if useful for niche SEO

### [FEATURE] Campaign content sources — idea library + sheet sync
Move beyond the "single prompt per campaign" model.
  * New `campaign_ideas` table: id, tenant_id, idea_text, target_date,
    target_platforms JSONB, tone (informational/question/opinion/insight),
    engagement_hook (CTA template), status (queued/used/skipped), created_at
  * Admin UI at `/admin/content-ideas` to add/edit/import ideas
  * Optional Google Sheets two-way sync (Sheets API + OAuth) — admin
    points the integration at a sheet; rows = ideas; cron syncs both
    directions
  * Campaign runner picks the next-due idea from the library
    (where target_date <= today AND status='queued'), generates the
    post, marks idea as 'used' on success
  * Tone selector at the IDEA level (not the campaign level) so the
    same campaign produces varied output

### [FEATURE] Per-workflow LLM provider picker
Each campaign workflow + each idea can specify its LLM:
  * `weekly_content` → text-only → existing LLMRegistry provider
    (OpenAI/Anthropic)
  * `image_post` (new) → text + image → OpenAI DALL-E for images,
    text from a separate provider
  * `video_post` (new — see below) → text + video, separate providers
  * Schema: Campaign.config_json gains `llm_provider_id` (FK to
    llm_providers); falls back to "active" if not set
  * Admin form: dropdown of registered LLM providers per campaign,
    with hint text "use [provider X] for this workflow"

### [FEATURE] Centralised hashtag library
Define hashtags once; reuse across campaigns + posts.
  * New `hashtag_sets` table: id, tenant_id, name, hashtags TEXT[],
    description, created_at
  * Admin UI at `/admin/hashtags` — CRUD on named sets
    ("evergreen", "exam-prep", "ai-news", "platform-specific:linkedin")
  * Campaign config_json gains `hashtag_set_ids` (list of FKs)
  * Runner appends the configured sets' hashtags to generated content
    (deduped, capped at platform limits)

### [FEATURE] AI-generated voiceover for course videos (multi-language, cached)
Operator request — give learners a toggle on the video player:
"Human voice" (default, the original recording) vs "AI voice
(English)" vs "AI voice (Hindi/Tamil/Telugu/…)". First-click
generation, then cached forever for reuse.

**User-facing flow:**
  * Video lesson player shows a small dropdown / segmented control
    above the player: `Voice: [Human ▼]` with options for every
    pre-generated track plus "Generate AI voice (English)" /
    "Generate AI voice (Hindi)" / etc.
  * Selecting an existing track swaps the `<audio>` element instantly
    (the video stays muted; we play the chosen track in sync via
    `currentTime` binding). Subtitles continue to render from the
    SRT.
  * Selecting "Generate AI voice (Lang)" for the first time on a
    given (lesson, language) pair queues a background job; the player
    falls back to the human track until the job finishes (admin
    notification + in-player toast).
  * Every learner thereafter who picks "AI voice (Lang)" on this
    lesson streams the cached MP3 — zero TTS cost per replay.

**Admin-facing flow:**
  * Lesson editor for video-type lessons gains an "SRT subtitles" tab
    next to "Attached files". Admin can paste SRT, upload `.srt`
    file, or drag-drop. Live preview shows the SRT parsed into
    timed cues so they can spot bad timestamps before publishing.
  * Admin can pre-generate any (lesson, language) MP3 from this tab
    so the first-learner experience isn't a "generating…" wait.
  * Admin can delete a cached AI track (e.g. updated the SRT and
    needs a re-render) — confirms with row count of users who'd
    re-use it.

**Backend architecture:**
  * New table `lesson_voiceovers`:
       id, tenant_id, lesson_id, language, voice_provider, voice_id,
       audio_url (object_key on R2 when we swap), duration_ms,
       srt_hash, generated_at, generated_by, generation_cost_usd,
       play_count
    `UNIQUE(lesson_id, language, voice_id)` — at most one cached
    track per (lesson × language × voice). srt_hash lets the player
    invalidate stale tracks when the admin updates the SRT.
  * New service `app/services/voiceover/` with:
       * `srt_parser.py` — parse + validate SRT (drop overlaps,
         normalise newlines, cap each cue at N seconds)
       * `tts_registry.py` — pluggable TTS provider just like
         LLMRegistry (`OpenAITTS`, `ElevenLabsTTS`, `AzureTTS`,
         `StubTTS` for tests)
       * `voiceover_generator.py` — main pipeline:
         SRT → per-cue chunks → TTS calls → ffmpeg concat with
         silent-pad to match each cue's start/end → final MP3 →
         persist row + write to uploads volume (or R2 once PR #9 lands)
  * APScheduler queue (in-process today, swappable to RQ/Celery
    later) handles generation jobs so the HTTP request that triggered
    "Generate" returns immediately with a job_id.
  * `POST /api/v1/lessons/{id}/voiceover/generate` (auth required,
    rate-limited per user) — queues a job, returns `{job_id, status}`.
  * `GET  /api/v1/lessons/{id}/voiceover` — list available tracks
    (cached + in-progress) for the player dropdown.
  * `GET  /api/v1/voiceover/jobs/{job_id}` — poll for progress
    (status, percent_complete, eta_seconds).
  * Admin endpoints under `/admin/voiceover/*` for SRT CRUD + delete-
    cached-track.

**Cost + scale guards (Day-1):**
  * Hard cap per tenant per day on TTS cost (settings_store key
    `voiceover.daily_cost_cap_usd`, default $20). Job manager checks
    cap before enqueuing.
  * Per-user rate limit (1 generation job per lesson per 10 min) so
    a refresh-loop can't drain budget.
  * `voiceover.allowed_languages` setting — comma-separated ISO
    codes, default "en,hi". Admin enables Tamil/Telugu/etc. when
    they're ready to QC the output.
  * Audit log + dashboard tile under `/admin/observability`: per-day
    generation count, total cost, cache hit rate (plays of cached
    tracks ÷ total plays).

**SRT handling:**
  * If a video has no SRT, "Generate AI voice" is disabled with a
    tooltip: "Add subtitles in the lesson editor first."
  * If SRT has gaps, we generate silence to fill (so the AI voice
    stays in sync with the video timeline).
  * If SRT has overlapping cues (multi-speaker captions), we
    sequentialise them with a 300ms pause — operator gets a warning
    banner in the editor.
  * `Lesson.captions_url` (already in schema, see Bucket D) is the
    SRT source of truth; voiceover service reads from there.

**Multi-language nuance:**
  * Captions can be uploaded per language (`lesson_captions` table:
    lesson_id + language + url). The AI voice track for "hi" reads
    from the `hi` captions row, not the English one — a separate
    translation step is the admin's responsibility (we don't
    auto-translate captions; that's a separate AI feature).
  * Player UI groups available tracks by language with native-name
    labels (हिन्दी / தமிழ் / etc.) using the existing country-flag
    util pattern.

**Trade-off acknowledged:**
  * Cached MP3s grow `cpmai-uploads` linearly with (lessons ×
    languages). At ~3MB per 10-min lesson × 5 languages × 200
    lessons = ~3 GB total — comfortable for v1, justifies the R2
    swap by year 2.
  * Cold-start latency for first-learner is unavoidable; we mitigate
    with admin pre-generation + an inline "generating, ~30s"
    progress bar that doesn't block playback.

**Why this is its own PR (not bundled with Visitor Insights v2):**
  * Touches lesson schema, lesson editor UI, video player UI, a new
    service layer, an external TTS provider with real costs — large
    surface, deserves dedicated review.
  * Provider selection (OpenAI TTS vs ElevenLabs vs Azure) is its
    own evaluation — different voice quality, different per-1k-char
    pricing, different language support.
  * Belongs after PR #9 (R2 storage) so cached MP3s don't pin disk
    on the VPS. If R2 slips, fallback to local-uploads volume with
    the daily cap acting as the guardrail.

### [FEATURE] Video generation (real, not stub)
The current `auto_clip` workflow returns a placeholder. Real options
(in order of cost/quality trade-off):
  * **Free**: OpenAI Sora-2 if pricing makes sense + slide-deck-to-video
    pipeline (HTML/Canvas slides + OpenAI TTS narration via ffmpeg)
  * **Paid**: Pictory / InVideo / Pika — admin enters API key in
    `/admin/settings`, runner POSTs the script + waits for callback
  * Either way: campaign runner writes the generated MP4 to the
    uploads volume (same path as Zoom recordings); admin queue surfaces
    a video preview alongside the text caption

### [DONE locally — Visitor Insights v2] Page-level analytics + funnel + drilldown
Replaces the narrow /admin/anonymous-traffic widget (which only knew
about chat-bubble opens) with a full /admin/insights dashboard
covering both anonymous visitors AND signed-in users. Three PRs
bundled per operator request:

* **Capture (PR-A)** — Migration `0032_visitor_insights` extends
  `journey_events` with tenant_id + path + referrer + UTM +
  device/browser/os + GeoIP + duration_ms + scroll_pct. Backend
  endpoint `POST /api/v1/track` accepts batched events (≤50/batch,
  120 batches/min/IP). Frontend tracker (`src/lib/tracker.ts` +
  `TrackerMount` in root layout) emits page.view / page.heartbeat /
  page.exit / scroll.depth / cta.click / session.start / session.end
  with `sendBeacon` on pagehide. Respects Do-Not-Track + per-batch
  sampling.

* **Dashboard (PR-B)** — `/admin/insights` page with KPI strip
  (sessions, visitors, avg duration, pages/session, bounce%,
  conversion%), top-pages table (views + avg active time + bounce% +
  exit%), funnel viz (landing → signup → first lesson → payment),
  session-timeline drilldown (paste anon_id, see ordered events).
  Backed by 4 admin endpoints + 1 GDPR action.

* **Scale prep (PR-C)** — `visitor_insights_daily` rollup table +
  nightly APScheduler job (gated by `tracking.rollup_enabled`,
  default off). Three live levers: `tracking.enabled`, `sample_rate`,
  `rollup_enabled` — all in `EDITABLE` + seed + drift test.

Tests added: `test_tracking.py` (HTTP surface, kill switches, PII
strip, path normalisation), `test_tracking_ua_parser.py` (device/
browser/OS bucketing), `test_visitor_insights.py` (RBAC + each
endpoint's aggregation logic + GDPR anonymise).

Local Python syntax check + JSON validity green. Pending: full
`scripts/preflight.sh` run + PR + deploy.

### [DONE in prod — PR #79] Zoom + new site.* settings visible in /admin/settings
The admin settings page is whitelisted by key in the EDITABLE dict
at `backend/app/api/v1/endpoints/admin/settings.py:441`. The new
zoom.* keys (SDK, OAuth, webhook) + site.* keys (instagram_url,
facebook_url, threads_url, tiktok_url, github_url, privacy_email,
contact_phone) + uploads.max_mb were missing from EDITABLE so they
didn't render. Validators added, seeded with empty defaults,
drift-test extended. Zoom secrets (sdk_secret, oauth_client_secret,
webhook_secret_token) added to SECRET_KEYS so GET masks them to
last-4 only. Admins can now rotate all credentials live without a
redeploy — uploads.max_mb takes effect on the next POST because
`/admin/uploads.py::_max_upload_bytes()` reads settings_store per
request. **Deployed to prod 2026-05-25.**
