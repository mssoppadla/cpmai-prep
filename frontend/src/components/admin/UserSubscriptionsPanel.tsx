"use client";

/**
 * UserSubscriptionsPanel — admin-only inline panel showing one user's
 * subscriptions plus grant / extend / revoke controls.
 *
 * Mounted as an expandable row underneath an /admin/users table row;
 * the parent owns the open/close state and passes ``userId`` when the
 * panel should mount.
 *
 * Operational context: this is the backstop for stuck-payment cases —
 * a user paid via PayPal, the payment got held PENDING, our system
 * never received a successful capture, the user shows "no active sub"
 * despite having been debited. Admin opens this panel, clicks Grant,
 * fills in plan + period + reason, user is unblocked immediately.
 * Every action also writes an audit_logs row server-side.
 */
import { useEffect, useState } from "react";
import { admin, errMsg, type SubscriptionAdminOut } from "@/lib/api";
import type { PlanAdminOut } from "@/types/api";

export function UserSubscriptionsPanel({
  userId,
  userEmail,
}: {
  userId: number;
  userEmail: string;
}) {
  const [subs, setSubs] = useState<SubscriptionAdminOut[] | null>(null);
  const [plans, setPlans] = useState<PlanAdminOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Grant-form state. Hidden by default — admin clicks "Grant a plan"
  // to reveal it. Keeping it inline (not a modal) keeps the user's
  // identity visible right above the form, which is the whole point
  // of doing this on /admin/users/[user].
  const [showGrantForm, setShowGrantForm] = useState(false);
  const [grant, setGrant] = useState({
    plan_id: 0,
    period_days: 30,
    reason: "",
    source: "manual_admin_grant" as
      "manual_admin_grant" | "comp" | "refund_reversed",
  });

  async function reload() {
    setBusy(true); setErr(null);
    try {
      const [s, p] = await Promise.all([
        admin.subscriptions.listForUser(userId),
        admin.plans.list(),
      ]);
      setSubs(s);
      setPlans(p);
      // Default grant_form plan to the first plan if none picked.
      if (p.length > 0 && grant.plan_id === 0) {
        setGrant((g) => ({ ...g, plan_id: p[0].id }));
      }
    } catch (e) {
      console.error("[UserSubscriptionsPanel] reload", e);
      setErr(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  async function submitGrant() {
    if (!grant.plan_id) { setErr("Pick a plan."); return; }
    if (grant.reason.trim().length < 3) {
      setErr("Reason is required (min 3 characters).");
      return;
    }
    try {
      await admin.subscriptions.grant(userId, grant);
      setShowGrantForm(false);
      setGrant((g) => ({ ...g, reason: "" }));
      await reload();
    } catch (e) {
      console.error("[UserSubscriptionsPanel] grant", e);
      setErr(errMsg(e));
    }
  }

  async function extendSub(sub: SubscriptionAdminOut) {
    const ans = window.prompt(
      `Extend subscription #${sub.id} (${sub.plan}) by how many days?\n\n` +
      `Current expires_at: ${sub.expires_at ?? "(none)"}\n\n` +
      `Enter a positive number.`,
      "30",
    );
    if (ans == null) return;
    const days = Number(ans);
    if (!Number.isInteger(days) || days < 1 || days > 365) {
      setErr("Days must be a whole number between 1 and 365.");
      return;
    }
    const reason = window.prompt(
      "Reason for the extension (required, ≥3 chars):",
      "",
    );
    if (reason == null || reason.trim().length < 3) {
      setErr("Reason is required.");
      return;
    }
    try {
      await admin.subscriptions.extend(sub.id, { days, reason });
      await reload();
    } catch (e) {
      console.error("[UserSubscriptionsPanel] extend", e);
      setErr(errMsg(e));
    }
  }

  async function revokeSub(sub: SubscriptionAdminOut) {
    if (sub.revoked_at) return; // already revoked; idempotent server-side
    const reason = window.prompt(
      `Revoke subscription #${sub.id} (${sub.plan}) for ${userEmail}?\n\n` +
      `This sets revoked_at — the paywall will treat it as inactive ` +
      `from this moment regardless of expires_at. Cannot be undone via ` +
      `the UI (grant a new sub instead).\n\nReason (required, ≥3 chars):`,
      "",
    );
    if (reason == null || reason.trim().length < 3) {
      setErr("Revocation requires a reason.");
      return;
    }
    try {
      await admin.subscriptions.revoke(sub.id, { reason });
      await reload();
    } catch (e) {
      console.error("[UserSubscriptionsPanel] revoke", e);
      setErr(errMsg(e));
    }
  }

  return (
    <div className="bg-slate-50 border-t border-slate-200 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-700">
          Subscriptions for <span className="font-mono">{userEmail}</span>
        </h3>
        <button
          onClick={() => setShowGrantForm((v) => !v)}
          className="text-xs px-3 py-1.5 bg-emerald-600 text-white rounded hover:bg-emerald-700"
        >
          {showGrantForm ? "Cancel" : "+ Grant a plan"}
        </button>
      </div>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-2 rounded mb-3 text-xs">
          {err}
        </div>
      )}

      {showGrantForm && plans && (
        <div className="bg-white border border-emerald-200 rounded p-3 mb-3 space-y-2 text-sm">
          <div className="grid grid-cols-2 gap-2">
            <label className="block">
              <span className="text-xs text-slate-600">Plan</span>
              <select
                value={grant.plan_id}
                onChange={(e) =>
                  setGrant({ ...grant, plan_id: Number(e.target.value) })
                }
                className="w-full mt-0.5 px-2 py-1 border border-slate-300 rounded text-sm"
              >
                <option value={0}>— pick —</option>
                {plans.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.slug})
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-xs text-slate-600">Period (days)</span>
              <input
                type="number" min={1} max={3650}
                value={grant.period_days}
                onChange={(e) =>
                  setGrant({ ...grant, period_days: Number(e.target.value) })
                }
                className="w-full mt-0.5 px-2 py-1 border border-slate-300 rounded text-sm"
              />
            </label>
          </div>
          <label className="block">
            <span className="text-xs text-slate-600">Source</span>
            <select
              value={grant.source}
              onChange={(e) =>
                setGrant({ ...grant, source: e.target.value as typeof grant.source })
              }
              className="w-full mt-0.5 px-2 py-1 border border-slate-300 rounded text-sm"
            >
              <option value="manual_admin_grant">
                manual_admin_grant — stuck-payment unblock
              </option>
              <option value="comp">
                comp — free comp (no payment)
              </option>
              <option value="refund_reversed">
                refund_reversed — restoring access after refund reversal
              </option>
            </select>
          </label>
          <label className="block">
            <span className="text-xs text-slate-600">
              Reason (captured in subscription row + audit log)
            </span>
            <textarea
              rows={2}
              value={grant.reason}
              onChange={(e) => setGrant({ ...grant, reason: e.target.value })}
              placeholder="e.g. PayPal held the funds for 5 days; user has card statement showing debit on May 11"
              className="w-full mt-0.5 px-2 py-1 border border-slate-300 rounded text-sm"
            />
          </label>
          <div className="flex justify-end gap-2 pt-1">
            <button
              onClick={() => setShowGrantForm(false)}
              className="px-3 py-1 text-sm border border-slate-300 rounded hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              onClick={submitGrant}
              disabled={busy}
              className="px-3 py-1 text-sm bg-emerald-600 text-white rounded hover:bg-emerald-700 disabled:opacity-50"
            >
              Grant
            </button>
          </div>
        </div>
      )}

      {!subs ? (
        <div className="text-xs text-slate-500">Loading…</div>
      ) : subs.length === 0 ? (
        <div className="text-xs text-slate-500 italic">
          No subscriptions on record. Use “+ Grant a plan” above.
        </div>
      ) : (
        <div className="space-y-2">
          {subs.map((s) => (
            <div key={s.id}
                 className="bg-white border border-slate-200 rounded p-3 text-sm">
              <div className="flex items-start justify-between mb-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-900">
                    #{s.id} · {s.plan}
                  </span>
                  <SourceBadge source={s.source} />
                  <StatusBadge sub={s} />
                </div>
                <div className="flex gap-1">
                  {!s.revoked_at && (
                    <>
                      <button
                        onClick={() => extendSub(s)}
                        className="text-xs px-2 py-1 border border-slate-300 rounded hover:bg-slate-50"
                      >
                        Extend
                      </button>
                      <button
                        onClick={() => revokeSub(s)}
                        className="text-xs px-2 py-1 border border-rose-300 text-rose-700 rounded hover:bg-rose-50"
                      >
                        Revoke
                      </button>
                    </>
                  )}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-slate-600 mt-1">
                <div>
                  Expires: {s.expires_at
                    ? new Date(s.expires_at).toLocaleString()
                    : "(no expiry)"}
                </div>
                <div>
                  Created: {new Date(s.created_at).toLocaleDateString()}
                </div>
                {s.granted_by_email && (
                  <div className="col-span-2">
                    Granted by {s.granted_by_email}
                    {s.grant_reason && (
                      <span className="italic"> — “{s.grant_reason}”</span>
                    )}
                  </div>
                )}
                {s.revoked_at && (
                  <div className="col-span-2 text-rose-700">
                    Revoked {new Date(s.revoked_at).toLocaleString()}
                    {s.revoked_by_email && ` by ${s.revoked_by_email}`}
                    {s.revoke_reason && (
                      <span className="italic"> — “{s.revoke_reason}”</span>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SourceBadge({ source }: { source: string }) {
  const tone = source === "paid"
    ? "bg-blue-50 text-blue-700 border-blue-200"
    : source === "manual_admin_grant"
      ? "bg-amber-50 text-amber-700 border-amber-200"
      : source === "comp"
        ? "bg-purple-50 text-purple-700 border-purple-200"
        : "bg-slate-100 text-slate-700 border-slate-200";
  return (
    <span className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded border font-medium ${tone}`}>
      {source}
    </span>
  );
}

function StatusBadge({ sub }: { sub: SubscriptionAdminOut }) {
  if (sub.revoked_at) {
    return (
      <span className="text-xs px-2 py-0.5 rounded border bg-rose-50 text-rose-700 border-rose-200 font-medium">
        revoked
      </span>
    );
  }
  if (sub.is_active_now) {
    return (
      <span className="text-xs px-2 py-0.5 rounded border bg-emerald-50 text-emerald-700 border-emerald-200 font-medium">
        active
      </span>
    );
  }
  return (
    <span className="text-xs px-2 py-0.5 rounded border bg-slate-100 text-slate-700 border-slate-200 font-medium">
      inactive
    </span>
  );
}
