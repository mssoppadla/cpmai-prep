# Backlog — features queued for future sessions

Items intentionally **not** implemented in the current PR cycle, with enough
context that future-you (or future-Claude) can pick them up cold.

---

## Anonymous exam attempts on free sets

**Ask**: A visitor lands on `/exams`, picks a free set (e.g. "Set 1 — Foundations"
or "Set 3 — Phase Drill"), and can attempt it without signing in. Submission
shows the result on screen but doesn't save against any account. Premium sets
still require login + active subscription.

**Currently**: All `/exams/{slug}/start` calls require an authenticated user
(`get_current_user` dependency on the endpoint). Free vs. premium only changes
the paywall path, not the auth requirement.

**What it takes**:

1. **Migration** (additive): `exam_sessions.user_id` → nullable. New
   migration revision under `backend/migrations/versions/`.
2. **Anonymous identity** via signed cookie. Pick a name like
   `cpmai_anon_session`, contains a random uuid, set HttpOnly + Secure.
   `app.core.deps.get_optional_user_or_anon` returns either a `User` or an
   `AnonSession(token=...)` shape. Service-layer methods accept either.
3. **Backend changes** in `app/services/exam_service.py`:
   - `start_attempt(actor, slug)` — accepts user OR anon session token,
     creates `ExamSession(user_id=None, anon_token=token)` on the anon path.
     Premium check still gates premium sets (anon → 401, with a clear
     "subscription required, sign in first" payload).
   - `save_answer`, `submit`, `get_attempt` — auth check matches either the
     `user_id` (logged-in path) or the cookie token (anon path).
4. **Frontend** `/exams/[slug]/page.tsx` — don't redirect on 401 if the
   call succeeds anonymously. Show a banner: "You're not signed in. Your
   result will be visible after submit but not saved. Sign in to save."
5. **Smoke test** — extend with an anonymous flow probe.
6. **Pruning** — anon sessions older than 7 days dropped by a cron, since
   they're tied only to a cookie that may not come back.

**Estimate**: ~200 LOC across model + migration + service + endpoint +
frontend + smoke. ~2 hours including local testing.

**Decision needed first**: do anonymous users get the AI tutor on each
question? (Probably no — quota would explode. Show "Sign in to use the
AI tutor for explanations" inline.)

---

## Super-admin password reset from `/admin/users`

**Ask**: Open `/admin/users`, find a user (including yourself), click a row
action to set a new password. Currently the only path is to manually edit
the `users.password_hash` column via psql, or to delete and re-create the
account.

**What it takes**:

1. **Backend endpoint**: `PATCH /admin/users/{user_id}/password` — body
   `{ "new_password": "..." }`. Same permissions as the existing role-change
   endpoint (super-admin only). Re-uses `app.core.security.hash_password()`.
   Audit log entry: `user.password_reset_by_admin`.
2. **Frontend** `/admin/users/page.tsx` — add a row action button "Reset
   password" that opens a small inline form (or modal). Show the new
   password to the operating admin in a one-time display so they can pass
   it to the user out of band; do NOT email it.
3. **Smoke** — extend the smoke to cover the password-reset flow.

**Edge cases**:
- If the target user has Google sign-in only (no `password_hash`), the
  reset still works; they can choose to use the password OR keep using
  Google going forward (since `users.password_hash` and `google_id` are
  independent columns).
- Don't allow resetting a super-admin's password via this UI unless the
  operator is also a super-admin (already enforced by the existing
  role-based dependency, but double-check).

**Estimate**: ~80 LOC. ~30–45 min including local test.

---

## How to pick these up

Both are independent of each other and of the prod deploy automation. Order
of value if both are scheduled:

1. **Password reset** first — small, mechanical, unblocks operational tasks
   immediately (rotating the bootstrap super-admin password is currently a
   psql edit).
2. **Anonymous attempts** second — bigger product change, needs a migration,
   should be tested against a clone of the prod DB before going live.

Both should ride through the standard `deploy.sh` path with no special
handling.
