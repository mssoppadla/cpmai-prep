# Roadmap

Documents for **CPMAI Prep Phase 1 enhancements** and **TovaiTech SaaS
Phase 2 launch**.

## Reading order

1. **`phase-1-scope.md`** — what we're building, what we're explicitly
   not building, and the acceptance criteria for "Phase 1 done."

2. **`validation-gates.md`** — the criteria that decide whether
   TovaiTech becomes a public SaaS (Phase 2) or stays as an internal
   CPMAI enhancement only.

3. **`phase-2-backlog.md`** — the deferred items that move to execution
   only if validation gates pass. Living document — items added/removed
   as priorities shift during Phase 1 build.

## Companion documents (outside this folder)

- **`docs/contracts/multi-tenancy-and-saas-integration.md`** — the
  technical contract every Phase 1 PR must respect. Defines
  invariants, backward-compat guarantees, and risk mitigations.

- **`.github/PULL_REQUEST_TEMPLATE.md`** — auto-prefilled PR checklist
  derived from the contract's §17 and §18.

## Quick reference

| Question | See |
|---|---|
| What features are we building in Phase 1? | `phase-1-scope.md` "IN SCOPE" |
| What are we explicitly NOT building yet? | `phase-1-scope.md` "OUT OF SCOPE" |
| How do we know Phase 1 is done? | `phase-1-scope.md` "Acceptance Criteria" |
| When do we decide on Phase 2? | `validation-gates.md` "Gate timing" |
| What's in the Phase 2 backlog? | `phase-2-backlog.md` |
| What rules must every PR follow? | `docs/contracts/multi-tenancy-and-saas-integration.md` §17 |
| Local testing requirements? | `docs/contracts/multi-tenancy-and-saas-integration.md` §18 |

## Status (as of 2026-05-19)

- ✅ Contract drafted and locked
- ✅ Phase 1 scope locked
- ✅ Validation gates defined
- ⏳ Phase 1 build: not yet started (next PR will be migration 0023)
- ⏳ Validation period: after Phase 1 acceptance
- ⏳ Phase 2 build: only if validation passes
