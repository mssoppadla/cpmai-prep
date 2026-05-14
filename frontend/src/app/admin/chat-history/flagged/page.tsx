"use client";
/**
 * Admin queue of flagged chat turns.
 *
 * Oldest-first by default (earliest flag = earliest reply). Each row
 * shows the original message + AI reply + user's note (if any), with a
 * reply textarea + Send button + Mark resolved button.
 *
 * State filtering:
 *   * default               → pending only (replied=hidden, resolved=hidden)
 *   * include_replied=true  → also shows replied-but-not-resolved
 *   * include_resolved=true → also shows resolved rows (audit view)
 *
 * Either side can close a flag (PR feat/flagged-turn-resolve):
 *   * user clicks "Resolved" in their chat widget    → status="resolved", is_self=true
 *   * admin clicks "Mark resolved" on this page      → status="resolved", is_self=false
 *
 * Resolution doesn't require a reply — admin can close a non-actionable
 * flag without writing one.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { admin, errMsg, type FlaggedTurnAdminRow } from "@/lib/api";


export default function FlaggedTurnsPage() {
  const [items, setItems] = useState<FlaggedTurnAdminRow[] | null>(null);
  const [includeReplied, setIncludeReplied] = useState(false);
  const [includeResolved, setIncludeResolved] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Per-row admin reply drafts, keyed by FLAG id. Critical: keyed by
  // flag.id (NOT log_id, NOT array index) so two flags rendered side
  // by side keep their drafts isolated. Regression guard against the
  // cross-row state-leak bug reported on 2026-05-14.
  const [replies, setReplies] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<Record<number, boolean>>({});

  async function load() {
    setItems(null); setErr(null);
    try {
      const r = await admin.chatHistory.listFlagged({
        include_replied: includeReplied,
        include_resolved: includeResolved,
        limit: 100,
      });
      setItems(r.items);
    } catch (e) {
      setErr(errMsg(e));
    }
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ },
            [includeReplied, includeResolved]);

  async function submitReply(flagId: number) {
    const reply = (replies[flagId] ?? "").trim();
    if (!reply) return;
    setBusy((b) => ({ ...b, [flagId]: true }));
    try {
      await admin.chatHistory.replyToFlagged(flagId, reply);
      // Drop the draft for this row. Other rows' drafts stay intact —
      // important for the data-isolation contract.
      setReplies((r) => { const { [flagId]: _drop, ...rest } = r; return rest; });
      // Refresh the queue. Replied-but-not-resolved rows still appear
      // when include_replied is on, with their admin_reply rendered.
      if (includeReplied || includeResolved) {
        await load();
      } else {
        setItems((cur) => cur?.filter((x) => x.id !== flagId) ?? null);
      }
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setBusy((b) => ({ ...b, [flagId]: false }));
    }
  }

  async function resolveFlag(flagId: number) {
    setBusy((b) => ({ ...b, [flagId]: true }));
    try {
      await admin.chatHistory.resolveFlagged(flagId);
      // Drop any in-flight draft for this row.
      setReplies((r) => { const { [flagId]: _drop, ...rest } = r; return rest; });
      // If resolved rows are hidden, drop this row from view. If
      // they're shown (audit mode), reload so the "Resolved by X"
      // header renders.
      if (includeResolved) {
        await load();
      } else {
        setItems((cur) => cur?.filter((x) => x.id !== flagId) ?? null);
      }
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setBusy((b) => ({ ...b, [flagId]: false }));
    }
  }

  return (
    <div className="p-8 max-w-5xl">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Flagged turns</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Chat turns users have flagged as unhelpful. Reply here; the
            user sees your reply in their chat widget on next open.
          </p>
        </div>
        <Link href="/admin/chat-history"
          className="shrink-0 text-sm text-indigo-600 hover:underline">
          ← All chat history
        </Link>
      </header>

      <div className="flex items-center gap-5 mb-4 text-sm text-slate-700">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={includeReplied}
                  onChange={(e) => setIncludeReplied(e.target.checked)} />
          Include already-replied turns
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={includeResolved}
                  onChange={(e) => setIncludeResolved(e.target.checked)} />
          Include resolved turns
        </label>
      </div>

      {err && (
        <div role="alert"
             className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}

      {!items ? (
        <div className="text-slate-500 text-sm">Loading…</div>
      ) : items.length === 0 ? (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 p-4 rounded-lg text-sm">
          No flagged turns — queue is clear.
        </div>
      ) : (
        <ol className="space-y-4">
          {items.map((r) => (
            <li key={r.id}
                className="bg-white border border-slate-200 rounded-xl p-5">
              <div className="text-xs text-slate-500 mb-2">
                {r.user.name || r.user.email || "(unknown user)"} ·
                {" "}flagged {new Date(r.flagged_at).toLocaleString()}
                {r.provider && r.model && (
                  <> · <span className="text-slate-400">{r.provider}/{r.model}</span></>
                )}
              </div>

              <div className="text-xs uppercase text-slate-400 mt-2">User asked</div>
              <div className="text-sm text-slate-800 bg-slate-50 rounded p-2 mt-1 whitespace-pre-wrap">
                {r.original_message}
              </div>

              <div className="text-xs uppercase text-slate-400 mt-3">AI replied</div>
              <div className="text-sm text-slate-800 bg-indigo-50 rounded p-2 mt-1 whitespace-pre-wrap">
                {r.original_reply}
              </div>

              {r.flag_note && (
                <>
                  <div className="text-xs uppercase text-slate-400 mt-3">User's note</div>
                  <div className="text-sm text-slate-800 bg-amber-50 border border-amber-200 rounded p-2 mt-1 whitespace-pre-wrap">
                    {r.flag_note}
                  </div>
                </>
              )}

              {r.admin_reply && (
                <>
                  <div className="text-xs uppercase text-emerald-700 mt-3">
                    Replied {r.replied_at && new Date(r.replied_at).toLocaleString()}
                    {r.replied_by?.name && ` by ${r.replied_by.name}`}
                  </div>
                  <div className="text-sm text-slate-800 bg-emerald-50 border border-emerald-200 rounded p-2 mt-1 whitespace-pre-wrap">
                    {r.admin_reply}
                  </div>
                </>
              )}

              {r.status === "resolved" ? (
                /* Resolved rows show a closed-status footer instead of
                   the reply / mark-resolved controls. Tells the admin
                   WHO closed it (user-self vs admin) so they can tell
                   "withdrew it themselves" apart from "we closed it
                   without a reply". */
                <div className="mt-3 text-xs bg-slate-100 border border-slate-200
                                  rounded p-2 text-slate-700">
                  <span className="font-medium">Resolved</span>{" "}
                  {r.resolved_at && new Date(r.resolved_at).toLocaleString()}
                  {r.resolved_by && (
                    <>
                      {" "}· {r.resolved_by.is_self
                        ? <em>by the user (withdrawn / acknowledged)</em>
                        : <em>by admin {r.resolved_by.name ?? r.resolved_by.email ?? ""}</em>}
                    </>
                  )}
                </div>
              ) : (
                /* Open row — show reply textarea (unless already replied)
                   AND the Mark resolved button. Resolution is independent
                   of reply: admin can resolve without replying for
                   non-actionable flags. */
                <>
                  {!r.admin_reply && (
                    <div className="mt-4">
                      <label className="block text-xs uppercase text-slate-400 mb-1">
                        Your reply
                      </label>
                      <textarea
                        rows={3} maxLength={4000}
                        value={replies[r.id] ?? ""}
                        onChange={(e) => setReplies((m) => ({ ...m, [r.id]: e.target.value }))}
                        disabled={!!busy[r.id]}
                        placeholder="A clarifying answer for the user…"
                        className="w-full text-sm border border-slate-300 rounded
                                   px-2 py-1.5 focus:outline-none focus:ring-2
                                   focus:ring-indigo-400 disabled:bg-slate-50"
                      />
                    </div>
                  )}
                  <div className="flex justify-end gap-2 mt-2">
                    <button
                      type="button"
                      onClick={() => resolveFlag(r.id)}
                      disabled={!!busy[r.id]}
                      title={r.admin_reply
                        ? "Close this row out of the queue."
                        : "Close without replying (e.g. non-actionable flag)."}
                      className="px-3 py-1.5 text-sm bg-white text-slate-700
                                 border border-slate-300 rounded-md
                                 hover:bg-slate-50 disabled:opacity-50
                                 disabled:cursor-not-allowed">
                      Mark resolved
                    </button>
                    {!r.admin_reply && (
                      <button
                        type="button"
                        onClick={() => submitReply(r.id)}
                        disabled={!(replies[r.id]?.trim()) || !!busy[r.id]}
                        className="px-3 py-1.5 text-sm bg-indigo-600 text-white
                                   rounded-md hover:bg-indigo-700 disabled:opacity-50
                                   disabled:cursor-not-allowed">
                        {busy[r.id] ? "Sending…" : "Send reply"}
                      </button>
                    )}
                  </div>
                </>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
