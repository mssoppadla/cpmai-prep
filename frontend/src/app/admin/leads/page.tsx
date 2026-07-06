"use client";
/**
 * Contacts — unified feed of leads (landing-form submissions) + users
 * (signed up via password or Google).
 *
 * One row stream sorted by created_at desc. Filter by kind to focus on
 * just leads or just users. The internal-notes editor is available for
 * every row — leads AND signed-up users (notes persist to the matching
 * table via admin.leads.updateNotes / admin.users.updateNotes).
 */
import { useEffect, useMemo, useState } from "react";
import { admin, auth, errMsg } from "@/lib/api";
import { leadTier } from "@/types/api";
import type { ContactRow, LeadTier, UserOut } from "@/types/api";
import { countryAndCity } from "@/lib/country-flag";
import { linkedinHref } from "@/lib/linkedin";
import { ActivityWindowFilter, toIsoUtc } from "@/components/admin/ActivityWindowFilter";

export default function ContactsPage() {
  const [rows, setRows] = useState<ContactRow[] | null>(null);
  const [me, setMe] = useState<UserOut | null>(null);
  const [filter, setFilter] = useState<{
    kind: "" | "lead" | "user";
    q: string;
    // Off by default — operators almost always want active contacts.
    // Toggle on to investigate forensics / audit.
    includeDeleted: boolean;
    active_from: string; active_to: string;
  }>({ kind: "", q: "", includeDeleted: false, active_from: "", active_to: "" });
  // Client-side sort. "recent" preserves the API's created_at-desc
  // ordering. "score" surfaces warmest leads first (with scoreless
  // rows demoted to the bottom).
  const [sortBy, setSortBy] = useState<"recent" | "score">("recent");
  const [editing, setEditing] = useState<string | null>(null);  // `${kind}-${id}`
  const [notes, setNotes] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function reload() {
    setBusy(true);
    setErr(null);
    try {
      const params: Record<string, string | number | boolean> = { limit: 500 };
      if (filter.kind) params.kind = filter.kind;
      if (filter.q) params.q = filter.q;
      if (filter.includeDeleted) params.include_deleted = true;
      const af = toIsoUtc(filter.active_from); if (af) params.active_from = af;
      const at = toIsoUtc(filter.active_to);   if (at) params.active_to = at;
      setRows(await admin.contacts.list(params as any));
    } catch (e) {
      console.error("[admin/contacts] list", e);
      setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    reload();
    auth.me().then(setMe).catch(() => setMe(null));
    /* eslint-disable-next-line */
  }, [filter.includeDeleted]);

  // Client-side resort. Memoize so we don't re-sort on every render.
  // For score-sort: higher score first, NULL scores last, ties broken
  // by created_at desc (preserves the recent-first feel within a tier).
  const displayRows = useMemo<ContactRow[] | null>(() => {
    if (!rows) return null;
    if (sortBy === "recent") return rows;  // API already sorted this way
    return [...rows].sort((a, b) => {
      const sa = a.score ?? -1;
      const sb = b.score ?? -1;
      if (sa !== sb) return sb - sa;
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
  }, [rows, sortBy]);

  async function deleteRow(row: ContactRow) {
    const isUser = row.kind === "user";
    const msg = isUser
      ? `Delete user ${row.email}?\n\n` +
        "This is a SOFT delete — the account is marked inactive, " +
        "PII (name / password / Google link) is wiped, and the email " +
        "is replaced with 'deleted-{id}@redacted.invalid'. The row " +
        "stays so audit logs / payments / exam attempts referencing " +
        "this user remain valid (required for tax + compliance retention). " +
        "Login is blocked immediately. Use for junk signups."
      : `Permanently DELETE this lead (${row.email})?\n\n` +
        "Removes the landing-form submission. Cannot be undone.";
    if (!confirm(msg)) return;
    try {
      if (isUser) await admin.users.delete(row.id);
      else        await admin.leads.delete(row.id);
      await reload();
    } catch (e) {
      console.error(`[admin/contacts] delete ${row.kind}`, e);
      setErr(errMsg(e));
    }
  }

  async function saveNotes(row: ContactRow) {
    try {
      // Notes live on different tables for the two contact kinds —
      // route to the matching endpoint (both share the same {notes}
      // payload shape).
      if (row.kind === "user") await admin.users.updateNotes(row.id, notes);
      else                     await admin.leads.updateNotes(row.id, notes);
      setEditing(null);
      setNotes("");
      await reload();
    } catch (e) {
      console.error("[admin/contacts] save notes", e);
      setErr(errMsg(e));
    }
  }

  async function exportCsv() {
    const params: Record<string, string> = {};
    if (filter.q) params.q = filter.q;
    const qs = new URLSearchParams(params).toString();
    const url = `${process.env.NEXT_PUBLIC_API_URL}/admin/leads/export.csv${qs ? "?" + qs : ""}`;
    const token = typeof window !== "undefined"
      ? window.localStorage.getItem("cpmai.access") : null;
    try {
      const r = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const blob = await r.blob();
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objUrl;
      a.download = `leads-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(objUrl);
    } catch (e) {
      setErr(`Export failed: ${(e as Error).message}`);
    }
  }

  const totals = rows && {
    all: rows.length,
    leads: rows.filter(r => r.kind === "lead").length,
    users: rows.filter(r => r.kind === "user").length,
    google: rows.filter(r => r.kind === "user" && r.has_google).length,
    paid: rows.filter(r => r.kind === "user" && r.has_active_subscription).length,
  };

  return (
    <div className="p-8 max-w-6xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Contacts</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Everyone who showed interest — landing-form leads plus full sign-ups (password or Google).
          </p>
          {totals && (
            <p className="text-xs text-slate-500 mt-2">
              {totals.all} total · {totals.leads} leads · {totals.users} users
              {" · "}{totals.google} via Google · {totals.paid} on a paid plan
            </p>
          )}
        </div>
        <button
          onClick={exportCsv}
          className="px-4 py-2 bg-white text-slate-700 text-sm font-medium border border-slate-300 rounded-lg hover:bg-slate-50"
        >
          Export leads CSV
        </button>
      </header>

      {/* Unconverted-traffic rollup. Sits ABOVE the contacts table
          because operators usually open this page asking "who's
          showing up but not converting" — this answers it directly,
          and the contact stream below answers "of those who did
          convert, what are their details". */}
      <AnonymousTrafficSection />

      <div className="bg-white border border-slate-200 rounded-xl p-3 mb-4
                      flex gap-2 flex-wrap items-center">
        <input
          value={filter.q}
          onChange={(e) => setFilter({ ...filter, q: e.target.value })}
          placeholder="Search email or name…"
          className="flex-1 min-w-[200px] px-3 py-1.5 text-sm border border-slate-300 rounded"
        />
        <select
          value={filter.kind}
          onChange={(e) => setFilter({ ...filter, kind: e.target.value as any })}
          className="px-3 py-1.5 text-sm border border-slate-300 rounded"
        >
          <option value="">Both leads + users</option>
          <option value="lead">Leads only</option>
          <option value="user">Users only</option>
        </select>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as "recent" | "score")}
          className="px-3 py-1.5 text-sm border border-slate-300 rounded"
          title="Sort order"
        >
          <option value="recent">Sort: recent first</option>
          <option value="score">Sort: warmest leads first</option>
        </select>
        {/* Toggle: include soft-deleted users in the feed. Off by
            default — operators almost always want active contacts.
            Forensics / abuse investigation flip this on. */}
        <label className="flex items-center gap-1.5 px-2 py-1.5 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={filter.includeDeleted}
            onChange={(e) => setFilter({ ...filter, includeDeleted: e.target.checked })}
          />
          Show deleted users
        </label>
        <ActivityWindowFilter
          from={filter.active_from} to={filter.active_to}
          onChange={(from, to) => setFilter({ ...filter, active_from: from, active_to: to })}
        />
        <button
          onClick={reload}
          disabled={busy}
          className="px-4 py-1.5 bg-slate-700 text-white text-sm rounded hover:bg-slate-800 disabled:opacity-50"
        >
          {busy ? "Loading…" : "Filter"}
        </button>
      </div>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}

      {!displayRows ? (
        <div className="text-slate-500">Loading…</div>
      ) : displayRows.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200 p-12 text-center text-slate-500">
          No contacts match the filter.
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 overflow-x-auto">
          <table className="w-full">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-left text-xs font-medium text-slate-500 uppercase">
                <th className="px-4 py-3">Contact</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Source / role</th>
                {/* GeoIP-enriched country flag + city. NULL for users
                    and for leads from before the GeoIP feature shipped. */}
                <th className="px-4 py-3">Location</th>
                <th className="px-4 py-3">Score</th>
                <th className="px-4 py-3">Subscription</th>
                <th className="px-4 py-3">Last seen</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {displayRows.map(r => {
                const key = `${r.kind}-${r.id}`;
                const isOpen = editing === key;
                // Super-admin can delete anything except their own user row.
                // Admin can delete leads (junk landing-form entries) but not users.
                // Already-soft-deleted users get the button hidden — no second
                // delete pass is meaningful (the row is already redacted and
                // the soft-delete service is idempotent, but operators don't
                // need the visual noise).
                const canDelete = me
                  ? (r.kind === "lead"
                      ? (me.role === "super_admin" || me.role === "admin")
                      : (me.role === "super_admin"
                         && r.id !== me.id
                         && !r.deleted_at))
                  : false;
                return (
                  <Row
                    key={key}
                    row={r}
                    isOpen={isOpen}
                    notes={notes}
                    setNotes={setNotes}
                    canDelete={canDelete}
                    onToggle={() => {
                      if (isOpen) { setEditing(null); setNotes(""); return; }
                      // Internal notes apply to every contact (leads AND
                      // signed-up users) — expand any row to edit them.
                      setEditing(key);
                      setNotes(r.notes ?? "");
                    }}
                    onSaveNotes={() => saveNotes(r)}
                    onDelete={() => deleteRow(r)}
                    onCancel={() => { setEditing(null); setNotes(""); }}
                  />
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

interface RowProps {
  row: ContactRow;
  isOpen: boolean;
  notes: string;
  setNotes: (v: string) => void;
  canDelete: boolean;
  onToggle: () => void;
  onSaveNotes: () => void;
  onDelete: () => void;
  onCancel: () => void;
}
function Row({
  row, isOpen, notes, setNotes, canDelete,
  onToggle, onSaveNotes, onDelete, onCancel,
}: RowProps) {
  // Soft-deleted users: dim the whole row + replace the user badge with
  // a "deleted" badge so operators can tell at a glance which rows are
  // active accounts vs. tombstones.
  const isDeleted = row.kind === "user" && !!row.deleted_at;
  return (
    <>
      <tr
        className={`hover:bg-slate-50 cursor-pointer ${
          isDeleted ? "opacity-50" : ""
        }`}
        onClick={onToggle}
      >
        <td className="px-4 py-3">
          <div className={`text-sm font-medium text-slate-900 ${
            isDeleted ? "line-through" : ""
          }`}>{row.email}</div>
          {row.name && <div className="text-xs text-slate-500">{row.name}</div>}
          {row.kind === "user" && row.alt_emails?.map((e) => (
            <div key={e} className="text-xs text-slate-500" title="Also used this email on a landing form">
              alt: {e}
            </div>
          ))}
          {row.kind === "lead" && row.linkedin_id && (
            <div className="text-xs text-slate-500 mt-0.5">
              in:{" "}
              <a href={linkedinHref(row.linkedin_id)} target="_blank" rel="noopener noreferrer"
                 className="text-indigo-600 hover:underline break-all">{row.linkedin_id}</a>
            </div>
          )}
          {row.kind === "lead" && row.converted_user_id && (
            <span className="text-xs text-emerald-700 font-medium">✓ converted</span>
          )}
          {row.kind === "user" && !isDeleted && (
            <div className="flex flex-wrap gap-1 mt-1">
              {row.has_google && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200">
                  Google
                </span>
              )}
              {row.has_password && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200">
                  Password
                </span>
              )}
            </div>
          )}
        </td>
        <td className="px-4 py-3">
          {row.kind === "lead" ? (
            <span className="text-xs px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200 font-medium">
              lead
            </span>
          ) : isDeleted ? (
            <span className="text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-500 border border-slate-200 font-medium"
                  title={`Soft-deleted on ${row.deleted_at}`}>
              deleted
            </span>
          ) : (
            <span className="text-xs px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-medium">
              user
            </span>
          )}
        </td>
        <td className="px-4 py-3 text-sm text-slate-600">
          {row.kind === "lead" ? row.source : row.role}
          {row.kind === "lead" && row.utm_campaign && (
            <div className="text-xs text-slate-500">{row.utm_campaign}</div>
          )}
        </td>
        <td className="px-4 py-3 text-sm text-slate-700">
          {/* Location is set for BOTH kinds when available. Lead rows
              come from the GeoIP enrichment at form-submit time; user
              rows come from signup-time enrichment (or last-login if
              that's the only data we have). The countryAndCity helper
              renders "—" when nothing is set. */}
          {countryAndCity(row.country, row.city)}
        </td>
        <td className="px-4 py-3 text-sm">
          {row.kind === "lead" ? (
            <ScoreChip score={row.score ?? null} />
          ) : (
            <span className="text-xs text-slate-300">—</span>
          )}
        </td>
        <td className="px-4 py-3 text-sm">
          {row.kind === "user" ? (
            row.has_active_subscription
              ? <span className="text-emerald-700 font-medium">paid</span>
              : <span className="text-slate-500">free</span>
          ) : (
            row.consent_marketing
              ? <span className="text-emerald-700">✓ consent</span>
              : <span className="text-slate-500">no consent</span>
          )}
        </td>
        <td className="px-4 py-3 text-xs text-slate-500">
          {row.kind === "user"
            ? (row.last_login_at
                ? new Date(row.last_login_at).toLocaleString()
                : <span className="italic">never</span>)
            : (row.target_exam_date ? `target: ${row.target_exam_date}` : "—")}
        </td>
        <td className="px-4 py-3 text-xs text-slate-500">
          {new Date(row.created_at).toLocaleDateString()}
        </td>
        <td className="px-4 py-3 text-right">
          {canDelete && (
            <button
              onClick={(e) => { e.stopPropagation(); onDelete(); }}
              title={row.kind === "user"
                ? "Delete this user (super-admin only). Use for junk signups."
                : "Delete this lead. Use for junk landing-form submissions."}
              className="text-xs text-rose-600 hover:underline"
            >
              Delete
            </button>
          )}
        </td>
      </tr>
      {isOpen && (
        <tr className="bg-slate-50">
          <td colSpan={9} className="px-4 py-4">
            <div className="text-xs font-semibold text-slate-700 mb-2">
              Internal notes (admin-only)
              {row.kind === "user" && (
                <span className="ml-2 font-normal text-slate-400">
                  · {row.email}
                </span>
              )}
            </div>
            <textarea
              value={notes}
              rows={3}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Sales follow-up, qualifying details…"
              className="w-full px-3 py-2 text-sm border border-slate-300 rounded mb-2"
            />
            <div className="flex gap-2">
              <button
                onClick={onSaveNotes}
                className="px-3 py-1.5 bg-indigo-600 text-white text-xs rounded hover:bg-indigo-700"
              >
                Save notes
              </button>
              <button
                onClick={onCancel}
                className="px-3 py-1.5 bg-white text-slate-700 text-xs border border-slate-300 rounded hover:bg-slate-50"
              >
                Cancel
              </button>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/** Tier-colored chip for the lead Score column.
 *  HOT = score ≥ 70, WARM = 40-69, COLD = <40, neutral = unscored. */
function ScoreChip({ score }: { score: number | null }) {
  const tier: LeadTier = leadTier(score);
  if (tier === "unknown") {
    return <span className="text-xs text-slate-400 italic">unscored</span>;
  }
  const cls = (
    tier === "hot"  ? "bg-rose-50    text-rose-700    border-rose-200" :
    tier === "warm" ? "bg-amber-50   text-amber-700   border-amber-200" :
                      "bg-slate-100  text-slate-700   border-slate-200"
  );
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5
                  rounded border font-medium ${cls}`}
      title={`Rule-based lead score: ${score}/100`}
    >
      <span className="uppercase tracking-wide">{tier}</span>
      <span className="opacity-70">{score}</span>
    </span>
  );
}


// ============================================================================
// Anonymous traffic section — rollup of unconverted visitors.
//
// Sourced from `assistant.anon.*` audit_log events fired when an anon
// visitor opens the chat bubble. Three rollups so the operator can
// answer "where is unconverted traffic coming from?" without opening
// a SQL terminal:
//
//   • Headline: unique anonymous visitors + total events (the "events"
//     number surfaces multi-open anons separately from drive-by ones)
//   • By country: ranked, top-N
//   • By day: chronological bar-chart-style table
//
// Self-contained so the contacts page above stays focused on the
// per-contact stream. Re-fetches whenever the window selector changes.
// ============================================================================

type AnonWindow = "24h" | "7d" | "30d";

function AnonymousTrafficSection() {
  const [window, setWindow] = useState<AnonWindow>("7d");
  const [data, setData] = useState<Awaited<
    ReturnType<typeof admin.anonymousTraffic.summary>
  > | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    admin.anonymousTraffic.summary(window)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setErr(errMsg(e)); });
    return () => { cancelled = true; };
  }, [window]);

  const maxDayEvents = useMemo(() => {
    if (!data) return 0;
    return Math.max(0, ...data.by_day.map(d => d.events));
  }, [data]);

  return (
    <section className="bg-white border border-slate-200 rounded-xl mb-6">
      <header className="px-5 py-3 border-b border-slate-200
                          flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">
            Anonymous traffic
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Visitors who opened the chat without signing in. Where are
            they coming from, when did they show up?
          </p>
          {/* Bridge to Visitor Insights v2 — the broader dashboard
              that adds top-pages, funnel, and per-visitor timeline.
              The summary widget below remains the at-a-glance view
              for operators sitting on /admin/leads. */}
          <a href="/admin/insights"
              className="text-xs text-blue-600 hover:underline mt-1 inline-block">
            Open full Visitor Insights dashboard →
          </a>
        </div>
        <select value={window}
                onChange={(e) => setWindow(e.target.value as AnonWindow)}
                className="px-2 py-1 text-xs border border-slate-300 rounded">
          <option value="24h">Last 24 hours</option>
          <option value="7d">Last 7 days</option>
          <option value="30d">Last 30 days</option>
        </select>
      </header>

      {err && (
        <div className="px-5 py-3 text-sm text-rose-700 bg-rose-50">{err}</div>
      )}

      {!data ? (
        <div className="px-5 py-6 text-sm text-slate-500">Loading…</div>
      ) : data.totals.events === 0 ? (
        <div className="px-5 py-6 text-sm text-slate-500">
          No anonymous traffic recorded in this window.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-0 divide-y
                          md:divide-y-0 md:divide-x divide-slate-100">
          {/* Column 1: headline */}
          <div className="px-5 py-4">
            <div className="text-xs text-slate-500 font-medium">
              Unique visitors
            </div>
            <div className="text-3xl font-bold text-slate-900 mt-1">
              {data.totals.unique_anons}
            </div>
            <div className="text-xs text-slate-500 mt-1">
              {/* "events" is the union of page_view + bubble_open anon
                  events. Older copy said "chat-bubble opens" — no
                  longer accurate since the widget-mount commit
                  started recording page views as separate events. */}
              {data.totals.events} total event{data.totals.events === 1 ? "" : "s"}
              <span className="text-slate-400 ml-1">
                (page views + bubble opens)
              </span>
            </div>
          </div>

          {/* Column 2: by region (country + city). Uses the same
              countryAndCity helper the leads table below renders for
              its Location column — so a row reads as "🇮🇳 Bengaluru"
              rather than "IN", consistent with the rest of the
              admin surface. Rows with neither country nor city
              (unresolved IPs — datacenter / proxy / private) get
              the "unresolved" label so they stay visible. */}
          <div className="px-5 py-4">
            <div className="text-xs text-slate-500 font-medium mb-2">
              Top regions
            </div>
            {data.by_region.length === 0 ? (
              <div className="text-xs text-slate-400">No data</div>
            ) : (
              <ul className="space-y-1 text-xs">
                {data.by_region.slice(0, 6).map((c, i) => {
                  const label = countryAndCity(c.country, c.city);
                  const unresolved = !c.country && !c.city;
                  return (
                    <li key={i} className="flex items-center justify-between
                                            text-slate-700">
                      <span>
                        {unresolved
                          ? <em className="text-slate-400">unresolved</em>
                          : label}
                      </span>
                      <span>
                        <strong>{c.unique_anons}</strong>
                        <span className="text-slate-400 ml-1">
                          ({c.events} open{c.events === 1 ? "" : "s"})
                        </span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {/* Column 3: by day — minimal text "bar chart" */}
          <div className="px-5 py-4">
            <div className="text-xs text-slate-500 font-medium mb-2">
              Daily breakdown
            </div>
            <ul className="space-y-1 text-xs">
              {data.by_day.slice(-7).map((d) => {
                // Width as percentage of the max-day count, so the
                // longest bar fills the column and others scale down.
                // Cleanest no-dep visualisation — Tailwind + flexbox.
                const widthPct = maxDayEvents > 0
                  ? Math.max(2, Math.round((d.events / maxDayEvents) * 100))
                  : 0;
                return (
                  <li key={d.day} className="flex items-center gap-2
                                              text-slate-700">
                    <span className="font-mono text-slate-500 w-16
                                       flex-shrink-0">
                      {d.day.slice(5)}
                    </span>
                    <div className="flex-1 relative h-4 bg-slate-50 rounded
                                       overflow-hidden">
                      <div className="absolute inset-y-0 left-0 bg-indigo-200"
                           style={{ width: `${widthPct}%` }} />
                      <span className="absolute inset-0 flex items-center
                                         px-1.5 text-[10px] text-slate-700">
                        {d.events > 0 ? d.events : ""}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      )}
    </section>
  );
}
