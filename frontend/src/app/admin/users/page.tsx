"use client";
import { Fragment, useEffect, useMemo, useState } from "react";
import { admin, errMsg } from "@/lib/api";
import type { EmailAutomationOut, UserAdminOut, UserRole } from "@/types/api";
import { countryAndCity, countryFlag } from "@/lib/country-flag";
import { UserSubscriptionsPanel } from "@/components/admin/UserSubscriptionsPanel";
import { linkedinHref } from "@/lib/linkedin";
import { ActivityWindowFilter, toIsoUtc } from "@/components/admin/ActivityWindowFilter";

/**
 * Admin user list — filterable view of every user (Google + password).
 *
 * Columns: name/email, login methods, role, subscription, last login, joined.
 * Filters: free-text search (email/name), role, login method, paid plan.
 * Super-admin can change roles inline.
 *
 * Bulk email (R9 — docs/contracts/email-automation.md §7): filter, tick
 * users, "Send email" → pick a mail type → one PERSONALIZED mail per
 * selected user is queued (each rendered with that user's own name and
 * details, never a generic blast). Results land in
 * /admin/email-automations → Activity.
 */
export default function AdminUsersPage() {
  const [rows, setRows] = useState<UserAdminOut[] | null>(null);
  const [me, setMe] = useState<{ role: UserRole } | null>(null);
  const [filter, setFilter] = useState<{
    q: string; role: string; method: "" | "google" | "password" | "both";
    active_from: string; active_to: string;
  }>({ q: "", role: "", method: "", active_from: "", active_to: "" });
  // Client-side paid/free narrowing — rows already carry
  // has_active_subscription, no extra backend round-trip needed.
  const [planFilter, setPlanFilter] = useState<"" | "paid" | "free">("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Bulk-email selection (R9).
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [sendOpen, setSendOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // Inline subscription panel — only one user expanded at a time so the
  // table doesn't sprawl. Click "Subscriptions" on a row to toggle.
  const [expandedSubsUserId, setExpandedSubsUserId] = useState<number | null>(null);

  async function reload() {
    setBusy(true);
    setErr(null);
    try {
      const params: Record<string, string | number> = {};
      if (filter.q) params.q = filter.q;
      if (filter.role) params.role = filter.role;
      if (filter.method) params.method = filter.method;
      const af = toIsoUtc(filter.active_from); if (af) params.active_from = af;
      const at = toIsoUtc(filter.active_to);   if (at) params.active_to = at;
      const data = await admin.users.list(params as any);
      setRows(data);
    } catch (e) {
      console.error("[admin/users] list", e);
      setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    // Fetch own role to gate the "change role" controls.
    import("@/lib/api").then(({ auth }) => auth.me().then((u) => setMe(u))
                                                   .catch(() => setMe(null)));
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function changeRole(u: UserAdminOut, role: UserRole) {
    if (!confirm(`Change ${u.email}'s role from "${u.role}" to "${role}"?`)) return;
    try {
      await admin.users.changeRole(u.id, role);
      await reload();
    } catch (e) {
      console.error("[admin/users] changeRole", e);
      setErr(errMsg(e));
    }
  }

  async function setChatLimit(u: UserAdminOut) {
    const current = u.daily_chat_limit_override;
    const prompt = current == null
      ? `Set a per-user daily chat-message cap for ${u.email}.\n\n` +
        `Currently using the global default. Enter a number to override ` +
        `it (e.g. 100), or leave blank to keep the default.`
      : `Override the daily chat-message cap for ${u.email}.\n\n` +
        `Current override: ${current} messages/day.\n` +
        `Enter a new number, "0" to block chat entirely, or leave blank to ` +
        `clear the override and fall back to the global default.`;
    const ans = window.prompt(prompt, current?.toString() ?? "");
    if (ans === null) return; // cancelled
    let override: number | null;
    if (ans.trim() === "") {
      override = null;
    } else {
      const n = Number(ans);
      if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) {
        setErr("Chat limit must be a non-negative whole number.");
        return;
      }
      override = n;
    }
    try {
      await admin.users.setChatLimitOverride(u.id, override);
      await reload();
    } catch (e) {
      console.error("[admin/users] setChatLimit", e);
      setErr(errMsg(e));
    }
  }

  async function resetPassword(u: UserAdminOut) {
    const pw = window.prompt(
      `Set a new password for ${u.email}.\n\n` +
      `Type or paste it below — it will not be echoed back. ` +
      `Hand the new password to the user out of band (no email is sent).`,
      "",
    );
    if (pw == null) return;          // cancelled
    if (pw.length < 8) {
      setErr("New password must be at least 8 characters.");
      return;
    }
    try {
      await admin.users.resetPassword(u.id, pw);
      // Don't echo it back. Just confirm.
      window.alert(`Password reset for ${u.email}. Pass the new value to them directly.`);
      await reload();
    } catch (e) {
      console.error("[admin/users] resetPassword", e);
      setErr(errMsg(e));
    }
  }

  const totals = useMemo(() => {
    if (!rows) return null;
    return {
      total: rows.length,
      google: rows.filter(r => r.has_google).length,
      paid: rows.filter(r => r.has_active_subscription).length,
    };
  }, [rows]);

  // Rows actually shown = server-filtered rows + client paid/free filter.
  const visibleRows = useMemo(() => {
    if (!rows) return null;
    if (planFilter === "paid") return rows.filter(r => r.has_active_subscription);
    if (planFilter === "free") return rows.filter(r => !r.has_active_subscription);
    return rows;
  }, [rows, planFilter]);

  const visibleIds = useMemo(
    () => new Set((visibleRows ?? []).map(r => r.id)), [visibleRows]);
  const allVisibleSelected = visibleRows != null && visibleRows.length > 0
    && visibleRows.every(r => selected.has(r.id));

  function toggleSelect(id: number) {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelected(prev => {
      if (allVisibleSelected) {
        const next = new Set(prev);
        for (const id of visibleIds) next.delete(id);
        return next;
      }
      return new Set([...prev, ...visibleIds]);
    });
  }

  return (
    <div className="p-4 sm:p-8 max-w-6xl">
      <header className="flex items-end justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Users</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Everyone who has signed in or signed up.
            {totals && (
              <span className="ml-2 text-slate-500">
                · {totals.total} total · {totals.google} via Google · {totals.paid} on a paid plan
              </span>
            )}
          </p>
        </div>
      </header>

      <div className="bg-white border border-slate-200 rounded-xl p-3 mb-4 flex flex-wrap gap-2">
        <input
          value={filter.q}
          onChange={(e) => setFilter({ ...filter, q: e.target.value })}
          placeholder="Search email or name…"
          className="flex-1 min-w-[180px] px-3 py-1.5 text-sm border border-slate-300 rounded"
        />
        <select
          value={filter.role}
          onChange={(e) => setFilter({ ...filter, role: e.target.value })}
          className="px-3 py-1.5 text-sm border border-slate-300 rounded"
        >
          <option value="">All roles</option>
          <option value="user">User</option>
          <option value="admin">Admin</option>
          <option value="super_admin">Super admin</option>
        </select>
        <select
          value={filter.method}
          onChange={(e) => setFilter({ ...filter, method: e.target.value as any })}
          className="px-3 py-1.5 text-sm border border-slate-300 rounded"
        >
          <option value="">Any login method</option>
          <option value="google">Google linked</option>
          <option value="password">Password set</option>
          <option value="both">Both</option>
        </select>
        <select
          value={planFilter}
          onChange={(e) => setPlanFilter(e.target.value as any)}
          className="px-3 py-1.5 text-sm border border-slate-300 rounded"
        >
          <option value="">Any plan status</option>
          <option value="paid">Paid (active subscription)</option>
          <option value="free">Free (no payment)</option>
        </select>
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

      {selected.size > 0 && (
        <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-3 mb-4
                        flex flex-wrap items-center gap-3">
          <span className="text-sm text-indigo-900 font-medium">
            {selected.size} user{selected.size > 1 ? "s" : ""} selected
          </span>
          <button
            onClick={() => setSendOpen(true)}
            className="px-4 py-1.5 bg-indigo-600 text-white text-sm rounded
                       hover:bg-indigo-700"
          >
            Send email…
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="text-xs text-indigo-700 hover:underline"
          >
            Clear selection
          </button>
          <span className="text-xs text-indigo-700">
            Each recipient gets a personalized mail (their own name/details).
          </span>
        </div>
      )}

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}
      {notice && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800
                        p-3 rounded-lg mb-4 text-sm">
          {notice}
        </div>
      )}

      {!visibleRows ? (
        <div className="text-slate-500">Loading…</div>
      ) : visibleRows.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200 p-12 text-center text-slate-500">
          No users match the filter.
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 overflow-x-auto">
          <table className="w-full min-w-[800px]">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                <th className="px-4 py-3 w-8">
                  <input type="checkbox" checked={allVisibleSelected}
                         onChange={toggleSelectAll}
                         title="Select all visible users" />
                </th>
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Login methods</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Subscription</th>
                <th className="px-4 py-3">Chat limit</th>
                {/* GeoIP enrichment (PR-A). Shows signup country flag + city.
                    Hover the Last-login cell to see the IP/country at last login. */}
                <th className="px-4 py-3">Location</th>
                <th className="px-4 py-3">Last login</th>
                <th className="px-4 py-3">Joined</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {visibleRows.map((u) => (
                <Fragment key={u.id}>
                <tr className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <input type="checkbox" checked={selected.has(u.id)}
                           onChange={() => toggleSelect(u.id)} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-sm font-medium text-slate-900">
                      {u.name || <span className="italic text-slate-400">no name</span>}
                    </div>
                    <div className="text-xs text-slate-500">{u.email}</div>
                    {u.alt_emails?.map((e) => (
                      <div key={e} className="text-xs text-slate-500" title="Also used this email on a landing form">
                        alt: {e}
                      </div>
                    ))}
                    {u.linkedin_id && (
                      <div className="text-xs text-slate-500 mt-0.5">
                        in:{" "}
                        <a href={linkedinHref(u.linkedin_id)} target="_blank" rel="noopener noreferrer"
                           className="text-indigo-600 hover:underline break-all">{u.linkedin_id}</a>
                      </div>
                    )}
                    {u.whatsapp && (
                      <div className="text-xs text-slate-500">wa: {u.whatsapp}</div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {u.has_google && <Badge color="blue">Google</Badge>}
                      {u.has_password && <Badge color="slate">Password</Badge>}
                      {!u.has_google && !u.has_password && (
                        <span className="text-xs text-slate-400">—</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <RoleBadge role={u.role} />
                  </td>
                  <td className="px-4 py-3">
                    {u.has_active_subscription ? (
                      <Badge color="emerald">{u.subscription_plan ?? "active"}</Badge>
                    ) : (
                      <Badge color="slate">free</Badge>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {u.daily_chat_limit_override == null ? (
                      <span className="text-xs text-slate-400">default</span>
                    ) : u.daily_chat_limit_override === 0 ? (
                      <Badge color="slate">blocked</Badge>
                    ) : (
                      <Badge color="indigo">
                        {u.daily_chat_limit_override}/day
                      </Badge>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-700">
                    {/* Signup-time snapshot. Doesn't change on subsequent
                        logins — see Last-login tooltip for current. */}
                    {countryAndCity(u.country, u.city)}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {u.last_login_at ? (
                      <span
                        title={
                          u.last_login_ip
                            ? `Last login from ${u.last_login_ip}` +
                              (u.last_login_country
                                ? ` (${u.last_login_country})` : "")
                            : "IP not captured"
                        }
                      >
                        {u.last_login_country &&
                          <span className="mr-1">{countryFlag(u.last_login_country)}</span>}
                        {new Date(u.last_login_at).toLocaleString()}
                      </span>
                    ) : (
                      <span className="italic">never</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {new Date(u.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex flex-col items-end gap-1">
                      {/* Subscriptions panel toggle — available to any admin
                          (super_admin OR admin) since the user's confirmed
                          design grants both roles the ability to resolve
                          stuck-payment cases. */}
                      <button
                        onClick={() =>
                          setExpandedSubsUserId((curr) =>
                            curr === u.id ? null : u.id)
                        }
                        className="text-xs px-2 py-1 border border-slate-300 rounded text-slate-700 hover:bg-slate-50"
                        title="Show subscriptions; grant / extend / revoke a paid plan for this user"
                      >
                        {expandedSubsUserId === u.id
                          ? "Hide subscriptions"
                          : "Subscriptions"}
                      </button>
                      {me?.role === "super_admin" && (
                        <>
                          {u.role !== "super_admin" && (
                            <select
                              defaultValue=""
                              onChange={(e) => {
                                if (e.target.value) {
                                  changeRole(u, e.target.value as UserRole);
                                  e.target.value = "";
                                }
                              }}
                              className="text-xs border border-slate-300 rounded px-2 py-1"
                            >
                              <option value="">Change role…</option>
                              {u.role !== "user" && <option value="user">→ user</option>}
                              {u.role !== "admin" && <option value="admin">→ admin</option>}
                              <option value="super_admin">→ super admin</option>
                            </select>
                          )}
                          <button
                            onClick={() => resetPassword(u)}
                            className="text-xs px-2 py-1 border border-slate-300 rounded text-slate-700 hover:bg-slate-50"
                            title="Force-reset this user's password"
                          >
                            Reset password
                          </button>
                          <button
                            onClick={() => setChatLimit(u)}
                            className="text-xs px-2 py-1 border border-slate-300 rounded text-slate-700 hover:bg-slate-50"
                            title="Override this user's daily chat-message cap"
                          >
                            {u.daily_chat_limit_override == null
                              ? "Set chat limit"
                              : "Edit chat limit"}
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
                {expandedSubsUserId === u.id && (
                  <tr className="bg-slate-50">
                    <td colSpan={10} className="p-0">
                      <UserSubscriptionsPanel
                        userId={u.id}
                        userEmail={u.email}
                      />
                    </td>
                  </tr>
                )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {sendOpen && (
        <SendEmailModal
          userIds={[...selected]}
          onClose={() => setSendOpen(false)}
          onSent={(msg) => {
            setSendOpen(false);
            setSelected(new Set());
            setNotice(msg);
          }}
        />
      )}
    </div>
  );
}

/** Bulk-send modal (R9): pick a mail type, confirm, queue one
 *  personalized mail per selected user. */
function SendEmailModal({ userIds, onClose, onSent }: {
  userIds: number[];
  onClose: () => void;
  onSent: (notice: string) => void;
}) {
  const [automations, setAutomations] = useState<EmailAutomationOut[] | null>(null);
  const [automationId, setAutomationId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    admin.emailAutomations.list()
      .then((rows) => {
        setAutomations(rows);
        if (rows.length > 0) setAutomationId(rows[0].id);
      })
      .catch((e) => setErr(errMsg(e)));
  }, []);

  const chosen = automations?.find((a) => a.id === automationId) ?? null;

  async function send() {
    if (!automationId) return;
    setBusy(true); setErr(null);
    try {
      const r = await admin.emailAutomations.bulkSend(automationId, userIds);
      const skippedNote = r.skipped.length
        ? ` (${r.skipped.length} skipped: ${r.skipped
            .map((s) => `#${s.user_id} ${s.reason}`).join(", ")})`
        : "";
      onSent(`Queued ${r.queued} personalized email${r.queued === 1 ? "" : "s"}` +
             `${skippedNote}. Track them in Email Automations → Activity.`);
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center
                    bg-slate-900/40 p-4"
         onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl max-w-lg w-full p-6"
           onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-bold text-slate-900 mb-1">
          Send email to {userIds.length} user{userIds.length > 1 ? "s" : ""}
        </h2>
        <p className="text-sm text-slate-600 mb-4">
          Each recipient gets the template rendered with <b>their own</b> name
          and details. Sends go out on the next dispatcher tick (within a
          minute) while the master switch is ON.
        </p>

        {err && (
          <div role="alert" className="bg-rose-50 border border-rose-200
                                       text-rose-700 p-3 rounded-lg mb-3 text-sm">
            {err}
          </div>
        )}

        {!automations ? (
          <div className="text-slate-500 text-sm">Loading mail types…</div>
        ) : automations.length === 0 ? (
          <div className="text-sm text-slate-600">
            No mail types exist yet — create one in{" "}
            <a href="/admin/email-automations"
               className="text-indigo-600 hover:underline">Email Automations</a>{" "}
            first.
          </div>
        ) : (
          <>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Mail type (template)
            </label>
            <select
              value={automationId ?? ""}
              onChange={(e) => setAutomationId(Number(e.target.value))}
              className="w-full px-3 py-2 text-sm border border-slate-300 rounded"
            >
              {automations.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}{a.attachments.length
                    ? ` (${a.attachments.length} attachment${a.attachments.length > 1 ? "s" : ""})`
                    : ""}
                </option>
              ))}
            </select>
            {chosen && (
              <p className="text-xs text-slate-500 mt-2">
                Subject: <i>{chosen.subject}</i>
                {!chosen.is_active && (
                  <span className="block text-amber-700 mt-1">
                    Note: this mail type is currently disabled for automatic
                    sends — manual sends like this one still go out.
                  </span>
                )}
              </p>
            )}
          </>
        )}

        <div className="mt-5 flex gap-2 justify-end">
          <button onClick={onClose}
                  className="px-4 py-2 bg-white text-slate-700 text-sm border
                             border-slate-300 rounded hover:bg-slate-50">
            Cancel
          </button>
          <button onClick={send}
                  disabled={busy || !automationId || !automations?.length}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm rounded
                             hover:bg-indigo-700 disabled:opacity-50">
            {busy ? "Queueing…" : `Send to ${userIds.length}`}
          </button>
        </div>
      </div>
    </div>
  );
}

function Badge({ color, children }: {
  color: "emerald" | "slate" | "blue" | "purple" | "indigo";
  children: React.ReactNode;
}) {
  const tones = {
    emerald: "bg-emerald-50 text-emerald-700 border-emerald-200",
    slate:   "bg-slate-100 text-slate-700 border-slate-200",
    blue:    "bg-blue-50 text-blue-700 border-blue-200",
    purple:  "bg-purple-50 text-purple-700 border-purple-200",
    indigo:  "bg-indigo-50 text-indigo-700 border-indigo-200",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${tones[color]}`}>
      {children}
    </span>
  );
}

function RoleBadge({ role }: { role: UserRole }) {
  if (role === "super_admin") return <Badge color="purple">super admin</Badge>;
  if (role === "admin") return <Badge color="indigo">admin</Badge>;
  return <Badge color="slate">user</Badge>;
}
