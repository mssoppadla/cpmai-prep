"use client";
/**
 * Admin queue of flagged chat turns.
 *
 * Oldest-first by default (earliest flag = earliest reply). Each row
 * shows the original message + AI reply + user's note (if any), with a
 * reply textarea and a Send button. After reply the row disappears
 * from the pending queue; toggle "Include replied" to audit history.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { admin, errMsg } from "@/lib/api";

type FlaggedRow = {
  id: number;
  assistant_log_id: number;
  user: { id: number | null; email: string | null; name: string | null };
  original_message: string;
  original_reply: string;
  provider: string | null;
  model: string | null;
  flag_note: string | null;
  flagged_at: string;
  admin_reply: string | null;
  replied_at: string | null;
  replied_by: { id: number | null; name: string | null;
                email: string | null } | null;
};

export default function FlaggedTurnsPage() {
  const [items, setItems] = useState<FlaggedRow[] | null>(null);
  const [includeReplied, setIncludeReplied] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [replies, setReplies] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<Record<number, boolean>>({});

  async function load() {
    setItems(null); setErr(null);
    try {
      const r = await admin.chatHistory.listFlagged({
        include_replied: includeReplied, limit: 100,
      });
      setItems(r.items);
    } catch (e) {
      setErr(errMsg(e));
    }
  }
  useEffect(() => { load(); }, [includeReplied]);

  async function submitReply(flagId: number) {
    const reply = (replies[flagId] ?? "").trim();
    if (!reply) return;
    setBusy((b) => ({ ...b, [flagId]: true }));
    try {
      await admin.chatHistory.replyToFlagged(flagId, reply);
      // Drop from view + clear textarea (or reload if showing replied).
      setReplies((r) => { const { [flagId]: _, ...rest } = r; return rest; });
      if (includeReplied) {
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

      <label className="flex items-center gap-2 mb-4 text-sm text-slate-700">
        <input type="checkbox" checked={includeReplied}
               onChange={(e) => setIncludeReplied(e.target.checked)} />
        Include already-replied turns
      </label>

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

              {r.admin_reply ? (
                <>
                  <div className="text-xs uppercase text-emerald-700 mt-3">
                    Replied {r.replied_at && new Date(r.replied_at).toLocaleString()}
                    {r.replied_by?.name && ` by ${r.replied_by.name}`}
                  </div>
                  <div className="text-sm text-slate-800 bg-emerald-50 border border-emerald-200 rounded p-2 mt-1 whitespace-pre-wrap">
                    {r.admin_reply}
                  </div>
                </>
              ) : (
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
                  <div className="flex justify-end mt-2">
                    <button
                      type="button"
                      onClick={() => submitReply(r.id)}
                      disabled={!(replies[r.id]?.trim()) || !!busy[r.id]}
                      className="px-3 py-1.5 text-sm bg-indigo-600 text-white
                                 rounded-md hover:bg-indigo-700 disabled:opacity-50
                                 disabled:cursor-not-allowed">
                      {busy[r.id] ? "Sending…" : "Send reply"}
                    </button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
