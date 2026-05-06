"use client";
import { useEffect, useMemo, useState } from "react";
import { admin, errMsg } from "@/lib/api";
import type { UserAdminOut, UserRole } from "@/types/api";

/**
 * Admin user list — filterable view of every user (Google + password).
 *
 * Columns: name/email, login methods, role, subscription, last login, joined.
 * Filters: free-text search (email/name), role, login method.
 * Super-admin can change roles inline.
 */
export default function AdminUsersPage() {
  const [rows, setRows] = useState<UserAdminOut[] | null>(null);
  const [me, setMe] = useState<{ role: UserRole } | null>(null);
  const [filter, setFilter] = useState<{
    q: string; role: string; method: "" | "google" | "password" | "both";
  }>({ q: "", role: "", method: "" });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function reload() {
    setBusy(true);
    setErr(null);
    try {
      const params: Record<string, string | number> = {};
      if (filter.q) params.q = filter.q;
      if (filter.role) params.role = filter.role;
      if (filter.method) params.method = filter.method;
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

  const totals = useMemo(() => {
    if (!rows) return null;
    return {
      total: rows.length,
      google: rows.filter(r => r.has_google).length,
      paid: rows.filter(r => r.has_active_subscription).length,
    };
  }, [rows]);

  return (
    <div className="p-8 max-w-6xl">
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

      {!rows ? (
        <div className="text-slate-500">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200 p-12 text-center text-slate-500">
          No users match the filter.
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <table className="w-full">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider">
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Login methods</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Subscription</th>
                <th className="px-4 py-3">Last login</th>
                <th className="px-4 py-3">Joined</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((u) => (
                <tr key={u.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="text-sm font-medium text-slate-900">
                      {u.name || <span className="italic text-slate-400">no name</span>}
                    </div>
                    <div className="text-xs text-slate-500">{u.email}</div>
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
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {u.last_login_at
                      ? new Date(u.last_login_at).toLocaleString()
                      : <span className="italic">never</span>}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {new Date(u.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {me?.role === "super_admin" && u.role !== "super_admin" && (
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
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
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
