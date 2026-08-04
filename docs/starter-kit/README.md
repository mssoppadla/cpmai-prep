# CPMAI-Prep Starter Kit — build a production exam-prep SaaS with Claude

This kit teaches you to build, with Claude as your pair, a production-grade
product like **cpmaiexamprep.com**: mock-exam engine, AI tutor with
guardrails, payments, CMS/LMS, admin console, and a real VPS deployment
with CI gates. It is written for CPMAI candidates learning how modern
software + AI systems are actually built and operated.

## What's in the kit

| File | Purpose |
|---|---|
| `CONTEXT.md` | The product + architecture brief Claude works from — stack, domain model, conventions. **Upload first, always.** |
| `SKILL.md` | Claude's working agreement: the build loop, quality gates, verification workflow, credential rules. |
| `BUILD-PLAYBOOK.md` | Ten phases from empty repo to production, each with a copy-paste prompt, definition of done, and verify commands. |
| `AI-INTEGRATION.md` | The AI teaching core: provider registry, RAG, guardrails, drift monitoring, AI metrics. |
| `CREDENTIALS.md` | Every secret the project needs, where to get it, and the rules that keep it out of the repo and the chat. |
| `DEPLOYMENT.md` | VPS provisioning → CI deploy gates → rollback → the distilled production lessons. |

## How to use it (three modes)

**Mode A — Claude Code (recommended).** Create an empty GitHub repo, clone
it, drop this `starter-kit/` folder in, open Claude Code in the repo and say:

> Read docs/starter-kit/CONTEXT.md and SKILL.md fully, then start
> BUILD-PLAYBOOK.md Phase 0. Follow the skill's loop for every phase:
> implement → test → verify in browser → commit → push. Stop at each
> phase boundary and show me what was built.

**Mode B — claude.ai Project.** Create a Project, upload all six files as
project knowledge, and drive the build conversationally. Use Claude Code
for the hands-on-keyboard parts.

**Mode C — customize an existing build.** Keep the kit in `docs/starter-kit/`
of your running project. When you want a change, tell Claude: *"Per the
starter kit conventions, add <feature>"* — the kit is the shared context
that kills back-and-forth.

## The no-back-and-forth contract

Back-and-forth happens when Claude lacks context or you lack decisions.
This kit eliminates both sides:

1. **Claude's side** is covered by `CONTEXT.md` (what to build, how it's
   shaped) and `SKILL.md` (how to work). Don't summarize them to Claude —
   have Claude read them.
2. **Your side**: each playbook phase starts with a **Decisions box** —
   3–6 choices only you can make (product name, domains, providers,
   pricing). Fill them into the prompt before sending. Everything else is
   pre-decided by the kit.

## Data & credential safety (read before teaching with real accounts)

- The kit contains **zero real credentials, zero personal data**. All
  examples use placeholders.
- Secrets live only in local `.env` files (gitignored) and GitHub Actions
  secrets. Claude reads them from the environment when needed (e.g.
  `grep BOOTSTRAP_ADMIN_PASSWORD .env` piped into a curl login) and must
  **never print, commit, or restate them** — this rule is enforced in
  `SKILL.md` and is a good guardrails lesson in itself.
- GitHub access: `gh auth login` once on the student's machine; Claude
  then uses the `gh` CLI for pushes/PRs without ever seeing a token.
- Students should use **their own** sandbox accounts (Razorpay test mode,
  PayPal sandbox, their own OpenAI/Anthropic key) — see `CREDENTIALS.md`.

## What your students will learn, mapped to CPMAI

- **Business understanding (D-II/BU):** each phase's Decisions box is a
  scoping exercise — what's the MVP, what's deferred.
- **Data (D-III/DU-DP):** question-bank modeling, bulk Excel round-trips,
  data canonicalization and migration discipline.
- **Model development & evaluation (D-IV):** the AI tutor's intent
  classifier, RAG retrieval quality, and the evaluation loops in
  `AI-INTEGRATION.md`.
- **Trustworthy AI (D-I):** guardrails, quotas, drift monitoring, PII
  handling, auditability.
- **Operationalization (D-V):** CI gates, migrations, deploy + rollback,
  monitoring, incident debugging (`DEPLOYMENT.md` lessons are real
  production incidents).
