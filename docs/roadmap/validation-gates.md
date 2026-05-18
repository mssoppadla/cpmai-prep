# Validation Gates — Phase 1 → Phase 2

**Status**: locked 2026-05-19
**Decision authority**: mssoppadla
**Related**: `docs/roadmap/phase-1-scope.md`, `docs/roadmap/phase-2-backlog.md`, `docs/contracts/multi-tenancy-and-saas-integration.md`

## Purpose

Define explicit, measurable criteria to decide whether TovaiTech becomes
a public SaaS or stays as an internal-only enhancement of CPMAI Prep.

Without these gates, "we'll see" turns into 6 months of building
features no one will buy.

## Gate timing

The validation period runs for **4 weeks immediately after Phase 1
acceptance is signed off** (see `phase-1-scope.md` "Acceptance Criteria").

During those 4 weeks:

- CPMAI Prep runs with all Phase 1 features
- You conduct customer discovery interviews
- No SaaS-specific code is written
- At the end of week 4, the gate decision is recorded in this document

## Gate criteria

### Primary criterion: prospect conversion intent

Target: **15 customer discovery interviews completed** with prospects
from adjacent verticals:

| Segment | Target count | Channel suggestions |
|---|---|---|
| Indian coaching institutes (UPSC/JEE/NEET/CAT) | 5 | LinkedIn outreach to founders; coaching-industry forums |
| Solo course creators currently using Wix + ChatGPT separately | 5 | YouTube/LinkedIn creator economy networks |
| Corporate training / B2B content teams | 5 | LinkedIn outreach to L&D managers |

Each prospect is shown:

1. A live demo of CPMAI Prep with all Phase 1 features (Study Guide
   editing, course building, Zoom session scheduling, social campaign
   automation)
2. A mockup of the TovaiTech SaaS signup flow (designed in Figma — does
   NOT require building the actual signup flow)
3. The proposed pricing tiers (₹1,999 / ₹4,999 / ₹14,999)

Each prospect is asked:

> "At what monthly price would this feel like an obvious yes for your
> business?"

Document each answer in `phase-2-backlog.md` "Discovered during Phase 1"
section.

### Pass thresholds

**STRONG PASS** (commit to Phase 2 immediately):

- 8+ prospects say ≥₹3,000/mo would be an obvious yes
- 3+ prospects offer to be design partners (no payment expected, just
  feedback)
- 1+ prospect commits to paying once Phase 2 ships

**WEAK PASS** (proceed with Phase 2 but pivot pricing/positioning):

- 5–7 prospects say ≥₹3,000/mo
- Most feedback clusters around 1–2 specific complaints (fixable)

**FAIL** (do NOT proceed with Phase 2):

- <5 prospects say ≥₹3,000/mo
- Feedback indicates fundamentally wrong product/market fit
- Or fewer than 10 prospects could be reached at all

## Secondary criteria (sanity checks)

- [ ] CPMAI Prep itself has shown positive value from Phase 1 features
      (e.g. users actually use the Study Guide page, students watch
      course videos)
- [ ] Phase 1 features have run for 4 weeks without production incidents
- [ ] Cost of running Phase 1 (₹6,400–6,900/mo) is sustainable for CPMAI
- [ ] No PRs deviated from the contract without explicit update

## What happens at each outcome

### Strong pass

- Commit to Phase 2 (estimated 3-7 weeks for SaaS shell — see
  `phase-2-backlog.md` for breakdown)
- Update Phase 2 backlog priorities based on prospect feedback
- Begin Phase 2 work
- Set 90-day target: ship marketing site + 5 paying tenants

### Weak pass

- Pause for 2 weeks
- Iterate on Phase 1 features OR adjust pricing based on feedback
- Re-run abbreviated validation with 5 of the original 15 prospects
- If they re-confirm: proceed to Phase 2
- If they don't: declare fail

### Fail

- TovaiTech SaaS is shelved (not killed — preserved in this doc + the
  Phase 2 backlog for future revisit)
- CPMAI Prep keeps Phase 1 features (they're valuable regardless)
- Reassess in 6 months whether market conditions changed
- Cost: Phase 1 build effort (₹4.8L of time) is sunk but CPMAI got the
  full value of those features

## Conducting customer discovery interviews

### Format

- 30 minutes per call (Zoom/Google Meet)
- Record (with permission) for later analysis
- Same structure for every prospect

### Suggested script

```
1. Intro (2 min)
   - Introduce yourself + TovaiTech
   - Confirm prospect's role + business

2. Discovery (10 min)
   - What's your current setup for [their use case]?
   - What's the most painful part of that setup?
   - How much time/money do you spend on it monthly?
   - What have you tried that didn't work?

3. Demo (10 min)
   - Walk through CPMAI Prep with Phase 1 features
   - Specifically show: Study Guide editing, course building,
     session scheduling, social automation
   - Don't pitch — just show

4. Reaction (5 min)
   - What's missing for your business?
   - What stood out as valuable?
   - At what monthly price would this feel like an obvious yes?

5. Close (3 min)
   - Would you be willing to be a design partner if we ship this?
   - Can I follow up in 4 weeks with progress?
```

### Disqualifying questions

If any of these are true, the prospect is NOT a useful signal:

- They're not the decision-maker for tool spend
- Their business is <6 months old (still iterating on offering)
- They're not currently selling courses or content (no need for the tool)
- They expect free / freemium-only pricing

Stop the call politely and don't count them in the 15.

## Sign-off section (filled in at decision time)

**Validation period start**: TBD (after Phase 1 acceptance)
**Validation period end**: TBD
**Prospects interviewed**: TBD / 15
**Prospects converted to design partners**: TBD
**Decision**: TBD (Strong Pass / Weak Pass / Fail)
**Decision date**: TBD
**Decision rationale**: TBD
**Next action**: TBD

## Lessons learned (post-decision)

After the decision is made, document what worked and what didn't in
the validation process. This informs future Phase N validation gates.

```
- TBD
```
