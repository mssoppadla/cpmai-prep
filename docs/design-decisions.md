# Key design decisions

Why each major architectural lever was chosen. Each decision below
sets the trade-off explicitly — what we got vs. what we gave up.
[Known limitations](known-limitations.md) covers the downsides in more
detail.

---

## Hosting

### Hostinger VPS over AWS / Azure / GCP

**Decision**: single Linux VPS on Hostinger, Docker Compose orchestration,
Caddy reverse proxy.

**Trade-off**:

- ✅ Predictable monthly cost (~$10/mo for current scale)
- ✅ No surprise charges from autoscaling or data egress
- ✅ Simpler ops surface — one server, one compose file, one SSH session
- ❌ No autoscaling (vertical scaling only — bigger VPS plan)
- ❌ Single point of failure (no built-in failover)
- ❌ Manual TLS / OS patching (Caddy handles TLS automatically; OS patches
  via `unattended-upgrades`)

**When we'd revisit**: traffic above ~10 concurrent chat turns or
~10k req/day sustained — at that point the autoscaling story makes
hyperscalers worth their cost premium.

---

## Runtime configuration

### `settings_store` for every operational knob

**Decision**: A `system_settings` table (Postgres) backed by a Redis cache
with 30-second TTL and pubsub-based invalidation, exposed via `/admin/settings`
and dedicated control pages.

**What's tunable at runtime** (no redeploy):

- Chat daily limits + cooldown
- Active LLM provider + active payment provider
- Classifier keywords (per intent)
- Handler system prompts (per intent)
- Banned topics + allowed exceptions
- Drift detection on/off
- Agentic flow toggle + cohort percent
- Shadow sampling rate
- Router/synthesis system prompts (agentic)
- PMI URLs (course, ECO)
- FAQ try-asking suggestions
- Landing page copy strings
- And ~50 more

**Trade-off**:

- ✅ Zero-downtime experimentation — flip a setting, next request uses it
- ✅ Operators can self-serve without engineering for ops changes
- ✅ Stale configs are bounded (30s worst-case if pubsub fails)
- ❌ Each `settings_store.get(...)` call costs a Redis round-trip on cache miss
  (negligible at our scale)
- ❌ A malformed admin-saved value can crash the chat path if not validated
  → mitigated by per-key validators in `admin/settings.py` AND defensive
  fallbacks in code (every reader falls back to a hardcoded default)

---

## Observability

### `audit_logs` as the universal event sink

**Decision**: One `audit_logs` table with a structured `action` column
(`auth.login.success`, `assistant.drift.refused_with_context`,
`assistant.agentic.turn`, etc.) and a JSONB `metadata_json` column.
All operator-visible events route through it.

**Trade-off**:

- ✅ One table to query for any event type — no per-feature audit tables
- ✅ Indexed on `(created_at, action)` → cheap window-based dashboard queries
- ✅ JSONB metadata is flexible without schema migrations per event
- ❌ Schema changes per event type aren't enforced at the DB level — relies
  on Python-side discipline (every event writer documents its `metadata_json`
  shape in its docstring)
- ❌ Volume grows linearly with traffic — at scale, would need partitioning
  by `created_at` month and a TTL job for old rows

### Drift detector with heuristic rules (not ML)

**Decision**: Four hand-coded heuristic rules (`refused_with_context`,
`empty_response`, `missing_citation`, `invented_citation`) that run on
every chat turn (when enabled) and write structured audit rows.

**Trade-off**:

- ✅ Operator-actionable signal from day one — no training data needed
- ✅ Each rule is independently testable + tunable
- ✅ False-positive rate is auditable (look at the drift events; if a class
  of legitimate answers is firing, edit the rule)
- ❌ Misses subtle drift modes (e.g., factually-wrong answers that don't
  trigger any of the four rules)
- ❌ Doesn't grade answer quality directly — needs a separate eval pipeline
  for that

**When we'd revisit**: when we have enough labelled examples for an
ML-classifier approach (rough threshold: ~1000 labelled (question,
response, drift?) tuples).

---

## Chat orchestration

### Two flows (legacy + agentic) coexisting

**Decision**: Keyword-classifier legacy flow stays alongside the agentic
LLM-tool-calling flow. Choice of flow is a runtime setting (`assistant.flow`)
with support for `legacy` / `agentic` / `percent:N` / `shadow` modes.

**Trade-off**:

- ✅ Risk-free rollout: deploy agentic code, leave `flow=legacy` (seed default),
  test in staging, gradually ramp `percent:N` on prod
- ✅ Legacy is cheaper (1 LLM call vs ~2 for agentic) and faster — use it for
  single-intent questions where keyword routing works
- ✅ Drift dashboard can show side-by-side performance during rollout
- ❌ Maintain two code paths long-term (both call the same RAG layer, so the
  duplication is shallow)
- ❌ Per-turn decision adds one settings read + one hash computation
  (sub-millisecond)

### Single-agent tool-using, not multi-agent

**Decision**: One router LLM picks tools; tools are deterministic functions
(some with their own LLM call for embedding); one synthesis LLM composes
the final answer.

**Trade-off**:

- ✅ One decision-maker = easier to reason about, debug, and tune
- ✅ No agent-to-agent coordination overhead
- ✅ Tools that don't need an LLM (PMI URL lookup, account state) are
  deterministic and cheap
- ❌ Can't do hand-off patterns (e.g., a research agent passing to a writer
  agent) — would need refactor to multi-agent if/when justified
- ❌ Re-plan loop is bounded to one extra iteration — complex queries that
  need 3+ tool rounds aren't supported (yet)

### Plain-Python state machine over LangGraph

**Decision**: The agentic orchestrator is ~150 lines of Python with three
explicit nodes (router → tool exec → synthesis). LangGraph is not a
dependency.

**Trade-off**:

- ✅ Fewer dependencies, smaller image, less abstraction to learn
- ✅ Every state transition visible in one function — easy to trace
- ❌ When we add complex patterns (parallel tools, sub-graphs, persistence,
  retries with backoff), LangGraph's runtime ergonomics may pay off
- ❌ No built-in tracing à la LangSmith

**When we'd revisit**: when re-plan / parallel-tool / shadow-async logic
makes the state machine non-linear enough to justify a graph runtime.

---

## RAG

### pgvector instead of a dedicated vector store

**Decision**: Embeddings live in a `vector(1536)` column on the existing
Postgres database. No Pinecone, Weaviate, or Qdrant.

**Trade-off**:

- ✅ One database to run, back up, and monitor
- ✅ Joins between embedded chunks and operational tables (faq_items,
  questions, plans) are trivial — same DB
- ✅ Bulk `IN`-clause filters by `source_type` use the existing B-tree index
- ❌ Index choice is HNSW or IVFFlat — pgvector's HNSW is younger than
  Pinecone's; specialised vector stores have more retrieval features
  (filtering by JSON metadata, hybrid search) out of the box
- ❌ Single-tenant model — multi-tenant would need a `tenant_id` filter on
  every retrieval query (the column exists but we don't expose it yet)

**When we'd revisit**: scale where pgvector retrieval > 100ms p95 starts
mattering. Current corpus (~1000 chunks) is well under that.

### Embedding model: `text-embedding-3-small`

**Decision**: OpenAI's `text-embedding-3-small` (1536 dim) for all chunk
embeddings + every query embedding.

**Trade-off**:

- ✅ Cheap (~$0.02 per 1M tokens) — entire corpus re-embed is pennies
- ✅ Strong quality for English retrieval; works fine for our domain
- ❌ Vendor lock-in on OpenAI for embeddings (provider abstraction exists in
  code; haven't implemented Anthropic / Cohere / local alternatives)
- ❌ Switching models requires a full corpus re-embed (vectors from different
  models live in different spaces — `provider+model` filter on retrieval
  enforces this)

---

## Auth

### JWT (access + refresh) over server-side sessions

**Decision**: Access token (15 min default, 120 min on prod) + refresh
token (7 days), both signed JWTs stored client-side in `localStorage`.

**Trade-off**:

- ✅ Stateless — backend doesn't store sessions, scales horizontally without
  a shared session store
- ✅ Mobile / SPA-friendly — Bearer header works everywhere
- ❌ Revocation is harder than server sessions — a stolen access token is
  valid until expiry (we don't run a denylist today)
- ❌ Refresh-token rotation isn't implemented (a fresh refresh is minted on
  each `/auth/refresh` call but the old one is still valid until its own
  expiry)

### Google Sign-In as the primary path

**Decision**: Google one-tap is the prominent sign-in option; password is
present but de-emphasised. The flow uses a tokenised ID token verified
server-side, then mints our own JWTs.

**Trade-off**:

- ✅ Lower signup friction — no password to remember
- ✅ Verified emails by default — no email-verification flow
- ❌ Dependent on Google availability (negligible risk in practice)
- ❌ Users who don't want Google must use password (still supported)

---

## HITL (human-in-the-loop)

### Either user OR admin can mark a flag resolved

**Decision**: Both `assistant_flagged_turns.resolved_at` / `resolved_by`
endpoints exist for users (their own flag) AND admins (any flag). UI
button on both surfaces.

**Trade-off**:

- ✅ Users get agency — withdraw a flag they made in error, or close a
  resolved thread themselves
- ✅ Admins aren't stuck waiting on users to acknowledge a reply — they
  can close the loop unilaterally
- ✅ Distinguishes "user-resolved" vs "admin-resolved" via
  `resolved_by == user_id` comparison, no extra column
- ❌ Adds two endpoints + one migration; slightly more state to track

### Reply lands on the user's chat (not email)

**Decision**: Admin reply to a flagged turn is fetched by the chat widget
on next open and rendered as a `SupportReplyBubble` at the top of the
message list.

**Trade-off**:

- ✅ In-context — user sees the reply right where they raised the issue
- ✅ No email infrastructure required
- ❌ User has to open the chat to see the reply (no push notification)
  — mitigated by the red-dot indicator on the chat bubble icon
---

## CI/CD

### Pre-push hook + GitHub Actions deploy

**Decision**: Local `./scripts/preflight.sh` runs the same test gate that
CI runs (vitest + backend pytest). A `pre-push` git hook calls it
automatically. CI deploys on push to `main` after tests pass.

**Trade-off**:

- ✅ Catch test breakages in 30s locally instead of after a 3-minute CI
  round-trip
- ✅ Tests run against a clean Docker environment (matches CI) — no "works
  on my machine" gap
- ❌ Tests must be hermetic (no real network) — we mock OpenAI; fakeredis
  replaces real Redis; SQLite replaces Postgres per-test (with a few caveats
  documented in `tests/conftest.py`)
- ❌ Hook is opt-in (`scripts/setup-hooks.sh` installs it) — a new contributor
  who skips that step doesn't get the pre-push guard


---

## Payments

### Two rails, auto-routed by currency

**Decision**: Razorpay for INR (Indian residents); PayPal for USD / EUR /
other currencies. The pricing service picks the rail by checkout currency.

**Trade-off**:

- ✅ Razorpay's INR + UPI support is best-in-class for Indian customers;
  PayPal's reach covers everywhere else
- ✅ Both runtime-configurable — admin can swap providers without redeploy
- ❌ Maintain two integrations (webhooks, signature verification, refund
  flow) — Stripe alone would be simpler but worse for INR
- ❌ Currency selector is admin-tunable — adding a new currency requires
  setting the FX rate in `/admin/pricing`

---

## Anonymous visitor tracking

### Cookie-bound `anon_id` + audit_log events

**Decision**: Anonymous visitors get a server-set `anon_id` cookie. Two
events get logged when the chat widget mounts and when the bubble is
clicked:

- `assistant.anon.page_view` — once per session (sessionStorage-deduped)
- `assistant.anon.bubble_open` — once per session

**Trade-off**:

- ✅ Aggregate funnel visibility (visitors → bubble-openers → signups)
  without per-visitor PII
- ✅ GeoIP enrichment (country / city) for the operator dashboard
- ❌ Cookie-based — users with strict ad-blockers or in private browsing
  with sessionStorage disabled aren't tracked
- ❌ No client-side analytics product integration (we don't ship Mixpanel /
  Amplitude / GA out of the box) — could be added if needed
