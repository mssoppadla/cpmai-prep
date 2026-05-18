<!--
This template is derived from docs/contracts/multi-tenancy-and-saas-integration.md
§17 (Pre-PR Checklist) and §18 (Mandatory Local Testing Gate).

Fill in every section. If a section doesn't apply, write "N/A" with
a one-line reason — don't delete it. PRs missing this template are
blocked from merge.
-->

## Summary

<!-- 1–3 sentences. What does this PR do? Why? -->

## Changes

<!-- Bulleted list of meaningful changes -->

-
-

## Contract alignment

<!--
Reference: docs/contracts/multi-tenancy-and-saas-integration.md

If this PR is documentation-only or doesn't touch the contract's
scope, write "N/A — docs/config only" and skip the boxes.
-->

- [ ] Adheres to invariants I-1..I-7
- [ ] If deviating from contract, contract document updated in this same commit
- [ ] No hardcoded `tenant_id=1` outside the `get_current_tenant_id()` stub
- [ ] Every new table has `tenant_id` (per I-1)
- [ ] Asset storage paths use `tenants/{id}/...` prefix (per S-1)
- [ ] New audit_log calls include current tenant_id (per A-2)

## Backward compatibility (BC-1..BC-6)

- [ ] No existing endpoint route changed
- [ ] No existing function signature changed (additive only — new params are optional)
- [ ] No existing JWT-decoding logic altered (old JWTs still work)
- [ ] No existing query changed to include tenant_id filter
- [ ] No existing migration revised (additive only per M-1)
- [ ] Existing admin URLs unchanged (per BC-5)

## Risk register references

<!--
List which risk IDs from §15 of the contract this PR touches, and how
the mitigation was applied.

Example:
- CR-1 (existing logins break) — mitigated by test `test_old_jwt_without_tenant_claim_still_works`
- HR-5 (BlockNote bundle size) — mitigated by lazy-loading on /admin/content-pages route only
-->

-

## Tests

- [ ] Preflight (`./scripts/preflight.sh`) green locally — paste end-of-output line
- [ ] New tests added for happy path
- [ ] New tests added for backward compat
- [ ] New tests added for tenant scope correctness
- [ ] Risk-specific tests added where applicable
- [ ] No existing test deleted, skipped, or weakened

**Preflight output**:

```
(paste the final "preflight green in Ns" line here)
```

## Local testing gate (§18)

Reference: contract §18.

### §18.1 Universal gates

- [ ] `./scripts/preflight.sh` passes locally
- [ ] All NEW tests pass
- [ ] Docker stack (postgres + redis) up + migration applied
- [ ] Frontend dev server builds without errors

### §18.2 UI gates (if frontend changes)

- [ ] Manually loaded the changed page in a real browser
- [ ] Works for an existing CPMAI user (no re-login required)
- [ ] Works for a brand-new user signing up
- [ ] Works on mobile viewport (DevTools responsive mode)
- [ ] Does NOT break adjacent existing pages
- [ ] No new console errors/warnings introduced

### §18.3 External API gates (if integration with Zoom/OpenAI/R2/Pictory/Buffer/ElevenLabs)

- [ ] Real API credentials configured in local `.env`
- [ ] Happy path tested end-to-end with real API (not just mocked)
- [ ] Error path tested by breaking credentials
- [ ] Webhook receivers tested with real webhook from provider's sandbox
- [ ] Rate limit / quota behaviour verified
- [ ] Cost of integration test documented below

**Integration test cost**: `<e.g. ₹3 of OpenAI credits>` or `N/A`

### §18.4 Migration gates (if Alembic migration included)

- [ ] `alembic upgrade head` runs cleanly on fresh empty DB
- [ ] `alembic upgrade head` runs cleanly on dev DB with seed data
- [ ] Smoke test against migrated DB: existing endpoints still work
- [ ] Affected row count documented below if migration backfills existing rows
- [ ] `downgrade()` raises NotImplementedError (per M-2)

**Affected rows on backfill**: `<count>` or `N/A`

### §18.5 Auth/security gates (if security.py, deps.py, tenant.py, JWT logic touched)

- [ ] Existing stored JWT still decodes correctly
- [ ] New JWT issued post-change has expected shape (manually decoded + verified)
- [ ] Admin user can still access admin routes
- [ ] Regular user CANNOT access admin routes (verified in real browser session)
- [ ] Tenant-scoping does NOT filter out CPMAI's existing data (manually queried DB)

### §18.6 Feature-specific manual scenarios

<!--
List 3–5 concrete manual scenarios that were clicked through end-to-end
locally. Be specific. Reviewer reads this to gauge confidence.

Example:
> 1. Created a new page in /admin/content-pages → added 5 blocks → published → loaded /study-guide → renders correctly
> 2. Edited a block → saved → reloaded → change persisted
-->

1.
2.
3.

## Deployment considerations

<!--
- New env vars required?
- New external services (Zoom, R2, etc.) need configuration?
- Migration impact on production data?
- Any operational steps after deploy?
-->

-

## Related

<!--
Links to:
- Contract sections this PR implements
- Phase 1 scope items this PR addresses
- Risk IDs from §15 of the contract
- Issues/discussions
-->

- Implements: <e.g. Phase 1 PR #N from `phase-1-scope.md`>
- Contract: <e.g. invariants I-1, I-4>
- Risks: <e.g. CR-1, HR-7>

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
