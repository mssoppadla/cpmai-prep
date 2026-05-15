# Known limitations + workarounds

Honest about what the platform doesn't do today and how we work around
it at the current scale. Each entry includes:

- **What's limited** — the constraint
- **Why it's OK for now** — why we accept the limitation at our scale
- **Workaround** — what to do if it bites today
- **When we'd fix it** — the trigger that justifies the engineering cost

---

## Infrastructure

### 1. Single VPS — no horizontal autoscaling

**Limitation**: Backend runs as a single container on one Hostinger VPS.
Spikes above the box's RAM / CPU cause queuing or 502s. No
fail-over if the VPS goes down.

**Why OK now**: Current scale is ~100 active users and ~10 chat turns / hour.
The box is ~10% utilised at peak. A reboot or maintenance window is
minutes, not hours.

**Workaround**:

- Vertical scaling — bump the VPS plan (single click in Hostinger panel) to
  add RAM / vCPU
- For planned downtime, put up a static maintenance page via Caddy
- Backups via `scripts/vps/backup.sh` (daily cron, restore via `restore.sh`)

**When we'd fix it**: when sustained traffic hits ~10+ concurrent chat
turns / sec or the VPS plan tops out. Path: migrate Postgres to managed
service (e.g. Hostinger / DigitalOcean managed Postgres), put the backend
behind a load balancer with 2+ replicas. ~3 days work; cost ~3x current.

### 2. Single Postgres instance — no read replicas

**Limitation**: All reads and writes go to one Postgres instance.
Long-running admin queries (e.g. the drift dashboard over a 30-day
window) compete with user traffic.

**Why OK now**: Query volume is well within a single box. Indexes on
`(created_at, action)` make most admin queries millisecond-fast.

**Workaround**:

- Run heavy admin queries during low-traffic hours
- Window queries down (default 7d; rarely need 30d)

**When we'd fix it**: when admin queries start showing > 1s p95 latency.
Add a read replica + route the drift / leads / chat-history admin queries
there.

### 3. No object storage — uploaded docs are discarded after chunking

**Limitation**: When an admin uploads a PDF/DOCX to `/admin/rag-sources`,
the file is chunked, embedded, stored in `rag_chunks`, and the raw bytes
are dropped. You can't re-download the source.

**Why OK now**: The chunked text is what the chat assistant needs. Admins
keep their source files locally / in shared drives.

**Workaround**: Keep the original source files outside the platform.

**When we'd fix it**: if admins start asking "where's the original PDF I
uploaded last month?" — add S3-compatible object storage (e.g. Hostinger
Object Storage, MinIO) and persist the raw bytes alongside the chunks.

---

## Auth & sessions

### 4. JWT — no revocation list

**Limitation**: A stolen access token works until expiry. There's no
denylist; we can't force-logout a specific user.

**Why OK now**: Access tokens expire in 120 minutes on prod (15 min default
in code). Sensitive admin actions are gated by role and would require the
attacker to also compromise an admin's refresh token. We log every
auth-related event in `audit_logs` for forensics.

**Workaround**:

- Reduce `ACCESS_TOKEN_EXPIRE_MINUTES` to 15 if a compromise is suspected
  (next chat turn forces a token refresh)
- Rotate `SECRET_KEY` to invalidate ALL outstanding JWTs (forces all users
  to re-login)

**When we'd fix it**: if we add high-stakes actions (e.g. user-initiated
money transfers, mass-emailing functionality). Add a JWT-id (`jti`)
column on `users` or a separate `revoked_tokens` table + check on every
request.

### 5. Refresh token max 7 days

**Limitation**: Users who don't log in for >7 days must sign in again.

**Why OK now**: This is the standard security trade-off — a 7-day refresh
balances "don't make me log in every day" with "don't keep a stolen
device authenticated forever".

**Workaround**: Power users can use the Google one-tap on next visit
(zero-friction re-auth).

**When we'd fix it**: if we add a "remember me for 30 days" checkbox.
Trade-off documented in [design-decisions.md](design-decisions.md#auth).

---

## Chat assistant

### 6. Agentic flow uses only OpenAI for tool calling

**Limitation**: `complete_with_tools()` is implemented on the OpenAI
provider only. The Anthropic provider exists but raises
`NotImplementedError` for the agentic path. Switching active LLM provider
to Anthropic with `assistant.flow=agentic` would crash every chat turn.

**Why OK now**: We're standardised on `gpt-4o` for prod. Vendor lock-in is
real but the abstraction in `providers/base.py` makes the Anthropic
implementation a localised job (not a refactor).

**Workaround**: Stay on OpenAI for agentic. If OpenAI is down, flip
`assistant.flow=legacy` (legacy works on any provider that supports
`complete()`).

**When we'd fix it**: when we want a non-OpenAI fallback or are
cost-comparing Anthropic. ~1 day of implementation; pin via tests in
`test_agentic_orchestrator.py`.

### 7. Shadow mode is synchronous

**Limitation**: When `assistant.flow=shadow`, the agentic side runs in the
SAME request thread as legacy. The user waits for both → ~2× chat-turn
latency on sampled requests.

**Why OK now**: Shadow mode is gated by `shadow_sampling_rate=0.0` by
default. An admin who turns it on knows the latency cost. Useful for
collecting A/B data without committing to a cohort rollout.

**Workaround**: Keep `shadow_sampling_rate` low (0.05–0.1) when shadow is
on; turn it off once enough data is collected.

**When we'd fix it**: if shadow mode becomes a long-running observation
state. Move to FastAPI `BackgroundTasks` — fires after the response is
sent. ~1 hour to implement; doesn't change the response path.

### 8. One re-plan iteration max

**Limitation**: If the router picks tools that all return EMPTY, we
re-plan once. If THAT also fails, we go to synthesis with no evidence.
We don't loop further.

**Why OK now**: Two-round retrieval handles >95% of recoverable cases.
Capping iterations prevents runaway LLM cost.

**Workaround**: Tune the router system prompt for known failure patterns
(via `assistant.agentic.router_system` setting).

**When we'd fix it**: if drift dashboard shows `refused_with_context`
events on agentic that a second re-plan would have caught. Bump
`tools_max_calls` and loosen the re-plan condition.

### 9. Tools execute sequentially within an iteration

**Limitation**: If the router picks 3 tools, they run one after another
even though they're independent. Adds ~50–100ms × N tools to chat
latency.

**Why OK now**: Most agentic turns call 1–2 tools. The latency overhead is
modest.

**Workaround**: None needed at current volume.

**When we'd fix it**: if multi-tool turns become common AND latency
budgets tighten. Parallelise tool exec with `asyncio.gather` (each tool
is async-safe — they're pure functions). ~half-day work + tests.

### 10. Drift detector heuristics, not ML

**Limitation**: Four hand-coded rules. Misses subtle drift modes
(factually wrong answer that doesn't trigger any rule).

**Why OK now**: Operator-actionable signal from day one, no training data
needed.

**Workaround**: Use the rule output as a sample to manually audit.

**When we'd fix it**: when we have ~1000 labelled (question, response,
drift?) tuples — train a classifier, deploy alongside the rules. See
[design-decisions.md](design-decisions.md#drift-detector-with-heuristic-rules-not-ml).

---

## Frontend

### 11. No 401 auto-refresh — user sees session timeout mid-action

**Limitation**: The frontend's `request()` function doesn't auto-retry on
401 with `auth.refresh()`. A user whose access token expired mid-action
sees an error and has to re-login.

**Why OK now**: We bumped `ACCESS_TOKEN_EXPIRE_MINUTES` to 120 on prod;
the chance of an expiry mid-action is low.

**Workaround**: Refresh the page (top-level page loads call `auth.me()`
which auto-refreshes if needed).

**When we'd fix it**: bundled into the next bug-fix PR (~30 LOC + tests).
See backlog.

### 12. No real-time admin notifications

**Limitation**: When a user flags a turn or submits a callback, the admin
has to open `/admin/chat-history/flagged` or `/admin/leads` to see it.
No push notification.

**Why OK now**: Admins check the dashboards as part of daily ops.

**Workaround**: Open dashboards in a tab and refresh; or watch `audit_logs`
table via SQL if monitoring closely.

**When we'd fix it**: when flag volume justifies the integration. Slack
webhook or email alert on every flagged-turn write. ~1 hour.

### 13. Anonymous chat is sign-in-gated

**Limitation**: Anonymous visitors see the chat bubble and a "please sign
in" panel, but they can't actually chat without signing in.

**Why OK now**: Forcing auth keeps the LLM cost-shielded from drive-by
visitors and lets us attribute every chat turn to a user.

**Workaround**: None needed — this is by design.

**When we'd fix it**: if onboarding friction is hurting conversion enough
to justify the cost-exposure trade-off. Solution: rate-limited anonymous
chat with stricter quotas.

---

## Operations

### 14. Manual `.env` edits require care

**Limitation**: Editing `backend/.env` on the VPS, if done with `sudo`,
changes ownership to root and breaks the container's ability to read it
(when source-bind-mounted via the dev override).

**Why OK now**: We documented the safe pattern in
[vps-deployment-lessons.md](vps-deployment-lessons.md). Always edit as
the `deploy` user, never with `sudo`.

**Workaround**:
- Use the deploy user's editor: `nano backend/.env` (no sudo)
- After edit, restart with prod overlay flags:
  `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d backend`
- A wrapper script `scripts/vps/restart.sh` is on the backlog that sources
  `.deploy.conf` + applies the right flags automatically.

**When we'd fix it**: ship the wrapper script. ~10 LOC. Backlog.

### 15. Settings cache invalidation is best-effort

**Limitation**: When an admin saves a setting via `/admin/settings`, the
local in-process cache is invalidated via Redis pubsub. If the pubsub
delivery fails (Redis hiccup), the local cache serves stale values for
up to 30 seconds (the TTL).

**Why OK now**: Worst case is 30 seconds of stale config. The system is
designed to be eventually consistent — every reader has a fallback path.

**Workaround**: For urgent flips, restart the backend container after
saving (forces all caches to drop):
`docker compose -f docker-compose.yml -f docker-compose.prod.yml restart backend`.

**When we'd fix it**: not planned — 30s eventual consistency is
acceptable.

### 16. No multi-tenancy

**Limitation**: The platform serves a single tenant (CPMAI Prep). The
schema has `tenant_id` columns on `rag_chunks` (always NULL today) but
no tenant-aware routing or per-tenant config.

**Why OK now**: We're not selling the platform white-label.

**Workaround**: None applicable.

**When we'd fix it**: if a white-label opportunity arises. Would need:
domain-based tenant resolution, tenant-aware settings_store, tenant-scoped
admin auth, tenant-scoped audit logs. ~2 weeks work.

---

## Demo-time things that look like limitations but aren't

These come up in demos — worth pre-empting:

| Question | Honest answer |
|---|---|
| "Why does the agentic flow cost 2× more LLM calls?" | One extra router decision per turn. In return: multi-topic answers, semantic routing, user-state tools, escalation. Cheaper than the alternative of forcing users to ask twice. |
| "What if OpenAI goes down?" | Active provider is switchable at runtime via `/admin/llm-providers` (e.g., flip to Anthropic for legacy; agentic needs OpenAI today). If both go down, `StubProvider` returns a friendly "AI tutor is being set up" message — chat doesn't 500. |
| "How do you handle prompt injection?" | Layered: pre-LLM regex catches obvious patterns (`ignore previous instructions`, `<system>` tags). Output regex catches secret leakage (`sk-…`, `BEGIN PRIVATE KEY`). Plus per-turn audit logging for forensics. Not bulletproof — no chat assistant is — but the layers raise the cost of an attack. |
| "Why not LangChain / LangGraph / CrewAI?" | We chose plain Python for the 3-node state machine. Less abstraction, simpler debugging, no version-churn dependency. Adoption deferred until we hit a complexity that needs it. |
| "Where's the test coverage report?" | ~360 backend tests + 25 frontend tests, all passing on every push. Coverage tool isn't wired up; we focus on contract tests (does this PR break existing behaviour?) rather than line coverage. |
