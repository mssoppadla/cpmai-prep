# AI INTEGRATION — assistant, guardrails, and metrics (the teaching core)

This is the CPMAI-in-practice document: how a production AI feature is
structured so it is useful, bounded, observable, and improvable. Build it
in the order presented — each layer is a lesson.

## 1. Provider registry (never hardcode a vendor)

- `llm_provider_configs` table: provider type (openai/anthropic/stub),
  model name, API key (encrypted at rest with a Fernet key from env),
  active flag, purpose tags (chat, embeddings, classifier).
- A registry resolves "give me the chat provider" at call time from the
  DB — swapping vendors or models is an admin action, not a deploy.
- A **stub provider** returns canned deterministic responses: CI and all
  tests run with zero API cost and zero flakiness. This is the single
  most important testing decision in the AI subsystem.
- Admin page: provider CRUD + a "Test" button that makes one real call
  and surfaces the raw error on failure (never swallow SDK errors into
  generic strings — a real incident lesson).

## 2. Intent classification → handlers (don't build one mega-prompt)

- First hop classifies the user turn: `site_question | exam_insights |
  pricing | live_sessions | out_of_scope | smalltalk`.
- Each intent has a handler with its OWN narrow prompt and data access:
  - **site_question** → RAG over the site corpus (below).
  - **exam_insights** → deterministic SQL over the asking user's own
    attempts (their scores, weak domains) formatted by the LLM. The LLM
    never queries the DB; code fetches, LLM phrases.
  - **pricing / live_sessions** → structured data from settings/DB.
- Teaching point: routing + narrow contexts beat one huge prompt on
  cost, latency, safety, and debuggability.

## 3. RAG pipeline (pgvector)

- **Corpus sources**: FAQs, question explanations, CMS pages, uploaded
  reference docs. Each has a `(source_type, source_id)` identity.
- **Ingestion**: chunk (~500 tokens, overlap), embed, store in
  `rag_chunks` (vector column). CRUD endpoints call
  `reindex_quietly(db, source_type, id)` after commit — fire-and-forget
  (a rate-limited embed API must never fail a user's save), logged on
  failure, with an admin "reindex all" button as the recovery path.
  Deletes purge chunks — orphaned corpus entries are a real leak class.
- **Retrieval**: embed query → top-k by cosine similarity → similarity
  floor → pass chunks WITH their sources into the answer prompt →
  answer must cite; if retrieval is empty, say "I don't have that" —
  never let the model freestyle.

## 4. Guardrails (Trustworthy AI, D-I, in code)

1. **Scope prompt**: system prompt pins the assistant to the site's
   subject matter and its retrieved context; explicit refusal
   instruction for everything else (medical/legal/general chat).
   Retrieved content is DATA, not instructions — say so in the prompt
   (prompt-injection posture) and test it with an adversarial fixture.
2. **Quotas**: Redis daily counters — separate anon vs authenticated
   limits from settings, per-user admin override column (0 = blocked).
   Quota headers returned so the UI can show remaining count.
3. **PII**: chat logs store user ids, not emails, in prompts; secrets
   never enter prompts; uploaded docs are the operator's responsibility
   (document this for students).
4. **Auditability**: EVERY turn persisted (user text, intent, handler,
   retrieved sources, response, token counts, latency, request id).
   Admin chat-history browser + per-turn flagging ("wrong", "off-scope",
   "hallucination") feeding the eval set.
5. **Fail-soft**: provider errors → apologetic canned response + logged
   error; the site never 500s because a vendor hiccupped.

## 5. AI metrics (what "is it working?" means, measurably)

**Operational (every turn, aggregated daily):**
- volume, unique users, tokens in/out, **cost** (price table per model),
  p50/p95 latency, provider error rate, quota-hit rate.

**Quality:**
- **Flag rate** (human signal) per intent and per week.
- **Deflection**: share of sessions where the user did NOT proceed to a
  human-contact action after asking.
- **Retrieval health**: mean top-1 similarity; % of turns answered with
  empty retrieval (should be near zero for in-scope intents).
- **Drift evals**: a stored golden set of (question → expected key
  points/intent). A scheduled job replays it and scores intent accuracy
  + keyword/similarity of answers; the admin drift page trends it.
  Alert when accuracy drops N points — that's your signal a model
  update or corpus change moved behavior (CPMAI monitoring in action).
- **LLM-as-judge (advanced)**: sample real flagged/unflagged turns, have
  a second model grade groundedness against the retrieved chunks;
  trend the score. Teach its failure modes: bias to verbosity,
  same-model blind spots — always keep the human flag loop.

**Where it lives:** an admin Observability page (request/error/latency
panels) + Assistant Drift page (evals) + Chat History (raw turns).
Rule for students: if you can't see it in admin, it isn't monitored.

## 6. Test strategy for AI features

- Unit-test the classifier prompt-adapter, chunker, and cost math with
  the stub provider.
- Integration-test the full turn (route → handler → RAG → response)
  against stub + seeded corpus; assert citations and refusals.
- One adversarial test file: injection attempts inside corpus documents,
  out-of-scope prompts, quota exhaustion, provider-down path.
- Never let a test hit a paid API. If a student's CI bill isn't zero,
  the architecture is wrong.
