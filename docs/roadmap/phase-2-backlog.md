# Phase 2 Backlog (TovaiTech SaaS Launch)

**Status**: living document — items added/removed as priorities shift
**Trigger**: only enter execution if validation gates pass (see
`validation-gates.md`)
**Related**: `docs/roadmap/phase-1-scope.md`, `docs/contracts/multi-tenancy-and-saas-integration.md`

## How to use this file

When validation passes and Phase 2 starts:

1. Re-read this document
2. Add anything new learned from Phase 1 (see "Discovered during Phase 1"
   section at the bottom)
3. Prioritise the backlog (M = must-have for launch, S = should-have,
   C = could-have)
4. Build in priority order

If validation FAILS: this document stays here as a record of what was
considered but not pursued. CPMAI Prep keeps its Phase 1 enhancements
regardless.

## Estimated Phase 2 effort

Approximately **3 weeks of focused build** for the must-have (M) items
to ship a public SaaS launch. Should-have (S) items add another 2-3
weeks. Could-have (C) items are open-ended.

## Backlog items (initial seed from Phase 1 out-of-scope list)

### M — Must-have for TovaiTech SaaS launch

| ID | Item | Approx effort | Notes |
|---|---|---|---|
| M-1 | Tenant signup flow + email verification | 3 days | Standard SaaS signup. Email verification via Resend/Postmark |
| M-2 | Multi-tenant routing middleware | 2 days | JWT-primary tenant resolution (per contract V1). Subdomain/custom-domain secondary |
| M-3 | `get_current_tenant_id()` Phase 2 implementation | 1 day | Replace stub with real logic. All Phase 1 code automatically respects it |
| M-4 | Marketing site at tovaitech.in | 4 days | Landing, features, pricing, blog. Static Next.js. Separate small repo |
| M-5 | Tenant billing (Razorpay + Stripe Connect) | 5 days | Monthly subscription. Webhook handling. Failed-payment dunning |
| M-6 | Plan tiers with feature gating | 2 days | Starter ₹1,999, Growth ₹4,999, Pro ₹14,999 (revised from ₹9,999 per margin analysis), Enterprise. Per contract I-7 + F-2 |
| M-7 | Per-tenant settings UI (workspace, branding) | 3 days | Each tenant configures their own |
| M-8 | Per-tenant payment gateway connection UI | 2 days | Tenant brings own Razorpay/Stripe keys (per contract P-1) |
| M-9 | Per-tenant Zoom account connection | 1 day | OAuth flow with Zoom |
| M-10 | Per-tenant social account connections (YouTube/LinkedIn via Buffer) | 2 days | OAuth flows |
| M-11 | Team members + roles (owner/admin/editor/viewer) | 3 days | Invite via email, role-based permissions |
| M-12 | Per-tenant AI quota enforcement | 2 days | Hard cap at plan limit, alert at 80% |
| M-13 | Per-tenant audit log scoping | 1 day | Tenant admin sees only own events |
| M-14 | Super-admin tenant management dashboard | 3 days | List tenants, comp credits, suspend, view-as |

**M total estimate**: ~34 days ≈ **~7 weeks** of full-time focused work
(or compressed if some items run in parallel).

### S — Should-have post-launch

| ID | Item | Approx effort | Notes |
|---|---|---|---|
| S-1 | Custom domain mapping per tenant (DNS + SSL) | 3 days | Pro tier feature. Caddy auto-SSL |
| S-2 | BYOK option for OpenAI (tenant brings own key) | 1 day | Encrypted at rest. Per contract P-2 pattern |
| S-3 | Webhook system (TovaiTech → tenant systems) | 3 days | HMAC-signed payloads. Standard events: page.published, recording.ready, etc. |
| S-4 | API keys for tenants (programmatic access) | 2 days | Create/revoke/scope. Last-used tracking |
| S-5 | Image-to-page AI feature | 5 days | GPT-4o vision → block JSON. Most-asked-about feature pre-launch |
| S-6 | RAG-grounded content generation | 3 days | Reuse existing agentic tools. Per-tenant knowledge base |
| S-7 | LMS certificates (PDF generation + signing) | 3 days | Customisable template |
| S-8 | LMS drip schedule | 2 days | Release modules on calendar |
| S-9 | LMS sequential unlocking | 2 days | Module 2 locks until Module 1 80% done |
| S-10 | Tab-to-complete in BlockNote | 3 days | Inline ghost text via OpenAI |
| S-11 | Page quality score | 2 days | AI evaluation with breakdown |
| S-12 | Cross-tenant analytics for super-admin | 3 days | MRR, churn, AI cost by tenant |

### C — Could-have (deferred indefinitely)

| ID | Item | Notes |
|---|---|---|
| C-1 | Native video generation (replace OpusClip dependency) | GPU infrastructure required; high cost. Only if OpusClip becomes a bottleneck |
| C-2 | Visual workflow builder for tenants | Replace fixed templates with drag-drop. Significant UI work |
| C-3 | Mobile native app | iOS + Android. PWA might suffice |
| C-4 | Multi-language UI | Hindi + regional languages. Translation pipeline + i18n framework |
| C-5 | White-label theming (custom CSS per tenant) | Beyond colour tokens — full CSS override |
| C-6 | Marketplace for content templates | Tenants sell templates to other tenants |
| C-7 | Affiliate / referral program | Tenant referral tracking + commission payouts |
| C-8 | Discussion forum per lesson | Per-course community. Significant moderation work |
| C-9 | Assignment uploads + grading | Beyond quizzes — file submissions + rubric grading |
| C-10 | Live cohort management | Batches, roll-overs, cohort-specific schedules |

## Pricing model (locked from contract decisions)

Phase 2 launches with these tiers (subject to revision based on
validation feedback):

| Plan | ₹/mo | Target customer | Features |
|---|---|---|---|
| Starter | 1,999 | Solo coach / small institute | CMS + LMS basics, 100 students, basic AI text features |
| Growth | 4,999 | Established institute, ₹50K+ MRR | + Live sessions (Zoom SDK), 500 students, AI video clipping, social automation (1 channel) |
| Pro | 14,999 | Multi-instructor or 1000+ students | + Unlimited students, white-label, custom domain, image-to-page AI, RAG grounding, 3 social channels |
| Enterprise | 25K+ | Schools, corporate L&D, multi-branch | Custom integrations, SLA, dedicated support |

**Margin analysis** (per `phase-1-scope.md` Section 14 risk register):

- Starter ₹1,999: ~₹165 variable cost → ~92% margin
- Growth ₹4,999: ~₹2,165 variable cost → ~57% margin
- Pro ₹14,999: ~₹9,665 variable cost → ~36% margin
- BYOK tenants (own OpenAI/Buffer/Zoom): margins jump to 90%+

**Transaction fees**: TovaiTech does NOT take transaction fees on
end-customer course sales (tenant's own Razorpay flow handles those).
This is differentiation vs Teachable/Kajabi which charge 5–10%.

## Discovered during Phase 1 (populated as Phase 1 unfolds)

(blank — items added here as we build Phase 1)

### Format for entries

```
- 2026-MM-DD: [discovery] description and proposed handling
```

Example entries (illustrative):

```
- 2026-06-03: BlockNote doesn't have a native "math equation" block.
  Proposal: add as a custom block in Phase 2 polish. Tenants asking
  for it can use code blocks with LaTeX syntax for now.

- 2026-06-15: Pictory API rate limits hit during testing (5 concurrent
  generations max). Proposal: implement queue + retry in Phase 1 (cost
  ~0.5 day); was assumed simpler in scope.
```

## Decision log for Phase 2 entry

When validation gates pass (or fail), record the decision here:

```
### Phase 2 entry decision — TBD

Validation period ended: TBD
Prospects interviewed: TBD / 15
Decision: TBD (Strong Pass / Weak Pass / Fail)
Decision rationale: TBD
Backlog items adjusted: TBD
Next action: TBD
```
