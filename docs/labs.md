# Labs & visual walkthroughs — how access works and how to add one

Everything about a lab lives in ONE registry:
`backend/app/core/labs_registry.py`. The admin Labs screen, the plan
checkboxes, the `/labs` index, the SEO metadata, the settings validators
and the access endpoint all derive from it.

## Access model

Per lab (Admin → Labs & Walkthroughs, or Settings → `labs.<key>_access`):

| mode      | who gets the full page                                    |
|-----------|-----------------------------------------------------------|
| `free`    | everyone (launch default for every lab)                   |
| `signin`  | any logged-in account; plans are ignored                  |
| `preview` | plan members; everyone else sees sections up to `labs.<key>_free_upto`, then blurred placeholders + the lock panel |
| `plan`    | plan members; everyone else sees the header + lock panel  |

**Plan member** = a live subscription (active, not revoked, not expired)
whose plan lists the lab slug in `Plan.perks["labs"]` — ticked under
Admin → Plans → *Labs & walkthroughs*. Legacy subscriptions with no
`plan_id` unlock everything (same rule as exam sets). Ticking a lab on a
plan unlocks it for every existing subscriber of that plan on their next
page load; un-ticking, revoking or expiry removes it. Course enrolments
on their own (admin_grant without a subscription) do **not** unlock
labs — grant the plan.

Policy is decided in one place, `backend/app/services/labs_access.py`
(`resolve_access`). The frontend never re-derives it.

## Request flow

1. `/labs/<slug>` (server component) reads `/content/labs` for titles,
   sections and SEO, renders the page chrome + a crawlable section
   outline, and mounts `LabEmbedClient`.
2. The client calls `/content/labs/<slug>/access` with the Bearer token
   (if any) and receives the decision plus a 6-hour **embed token**
   (JWT, `type:"lab"`, carries only what the visitor proved: `anon` /
   `user` / `plan`).
3. The iframe loads `/labs/embed/<slug>?t=<embed token>`. That Next
   route handler (`frontend/src/app/labs/embed/[slug]/route.ts`) reads
   `frontend/labs-assets/<slug>.html` (NOT under `/public`, so it can't
   be fetched directly), asks the backend to re-check the token against
   the CURRENT settings, and serves the asset **cut at the decision**
   (`frontend/src/lib/labs.ts::truncateLabHtml`). Locked sections never
   leave the server; the blur below the cut is a placeholder.
4. The lock panel (× to dismiss → a slim bar with "Show options") links
   to `/pricing` and `/login?next=…` in the parent window, names the
   active plans that tick the lab, and posts a `lab-lock` message so the
   page records a `cta.click` journey event (`lab_lock_shown`).

Backend unreachable → the embed route answers 503 with a friendly
message (fail-closed on purpose; the labs index and pages themselves
still fail open as before).

## Adding a lab

1. Build the page as a self-contained HTML document. Put **section
   markers** in it, in top-to-bottom order:
   * HTML section: `<!--LABSEC id="s7"-->` right before the section.
   * Section inside an `<svg>`: `<!--LABSEC id="sec4" y="1530" close="</svg></figure>"-->`
     — `y` is the viewBox height to cut to, `close` closes whatever is
     open at that point.
   * `<!--LABSEC:END-->` once, before the trailing scripts.
   * A height reporter that watches `document.body` (inside an iframe the
     `<html>` box never resizes) and posts
     `{type:"lab-height", h: documentElement.scrollHeight}` — copy the
     snippet from any existing asset. Only needed for `frame="content"`.
   * Site links (`href="/..."`) need `target="_top"`; copy the small
     link-target script from an existing asset. Do NOT use
     `<base target="_top">` — it retargets `#section` links too and they
     then open the embed document in the top window.
   * Pick the frame mode in the registry: `frame="content"` (frame grows
     with the document, page scrolls — infographics) or
     `frame="viewport"` (frame fills the viewport, document scrolls
     inside — anything with a sticky rail, fixed buttons or popovers).
2. Save it as `frontend/labs-assets/<slug>.html`.
3. Add a `LabDef` to `LABS` in `backend/app/core/labs_registry.py` with
   the same `slug`, its `sections` (ids matching the markers, in order),
   `asset="<slug>.html"`, group, domain, blurb, minutes, teaches.
4. Add the four seeds to `backend/seeds/default_settings.json`
   (`labs.<key>_enabled/_title/_access/_free_upto`) and their happy-path
   values in `tests/integration/test_settings_editable.py`.

That's it: `/labs/<slug>` renders, the admin screen shows the row, the
plan form shows the checkbox, the access modes work.

The mock → asset conversion for the current three pages is scripted in
the session scratchpad (`sync_assets.py`); the markers it inserts are
the ones listed above.

## Backlog

- **"Try it live" stops in the Walkthrough** are rendered as disabled
  "Upcoming" chips (`sync`: `.play .btn.soon`). The Simulator cannot yet
  open at a given stage; add a `?stage=<slug>` (or hash) handler to
  `labs-assets/data-pipeline-navigator.html`, point each stop at its
  stage, then re-enable the chips as links.
