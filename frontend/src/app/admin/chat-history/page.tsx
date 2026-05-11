"use client";
import { useEffect, useState } from "react";
import { admin, errMsg } from "@/lib/api";

type UserRow = {
  user_id: number | null;
  email: string | null;
  name: string | null;
  turns: number;
  last_active: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
};

type Turn = {
  id: number;
  created_at: string;
  intent: string | null;
  intent_confidence: number | null;
  provider: string | null;
  model: string | null;
  input: string | null;
  response_preview: string | null;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
};

export default function ChatHistoryPage() {
  const [users, setUsers] = useState<UserRow[] | null>(null);
  const [selected, setSelected] = useState<UserRow | null>(null);
  const [turns, setTurns] = useState<Turn[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    admin.chatHistory.listUsers({ limit: 100 })
      .then(r => setUsers(r.users))
      .catch(e => { console.error("[admin/chat-history]", e); setErr(errMsg(e)); });
  }, []);

  async function openUser(u: UserRow) {
    setSelected(u); setTurns(null);
    if (u.user_id == null) return;
    try {
      const r = await admin.chatHistory.userTranscript(u.user_id, { limit: 200 });
      setTurns(r.turns);
    } catch (e) {
      console.error("[admin/chat-history] transcript", e);
      setErr(errMsg(e));
    }
  }

  return (
    <div className="p-8 max-w-6xl">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Chat History</h1>
        <p className="text-slate-600 mt-1 text-sm">
          Per-user transcripts of assistant conversations. PII-redacted at
          capture; intent, provider, tokens and cost are tracked for audit.
        </p>
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}

      <div className="grid lg:grid-cols-[24rem_1fr] gap-4">
        <aside className="bg-white border border-slate-200 rounded-xl p-4 max-h-[80vh] overflow-y-auto">
          <h2 className="font-semibold text-slate-900 mb-3 text-sm">Users</h2>
          {!users ? <div className="text-slate-500 text-sm">Loading…</div>
           : users.length === 0 ? (
              <div className="text-slate-500 text-sm">No chat activity yet.</div>
            ) : (
              <ul className="space-y-1">
                {users.map(u => {
                  const isSel = selected?.user_id === u.user_id;
                  return (
                    <li key={String(u.user_id)}>
                      <button onClick={() => openUser(u)}
                        className={`w-full text-left px-3 py-2 rounded-lg text-sm ${
                          isSel ? "bg-indigo-50 border border-indigo-200"
                                : "hover:bg-slate-50 border border-transparent"
                        }`}>
                        <div className="font-medium text-slate-900 truncate">
                          {u.name || u.email || "(anonymous)"}
                        </div>
                        <div className="text-xs text-slate-500 mt-0.5">
                          {u.turns} turns · ${u.cost_usd.toFixed(4)} ·
                          {" "}{new Date(u.last_active).toLocaleDateString()}
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
        </aside>

        <main className="bg-white border border-slate-200 rounded-xl p-5 max-h-[80vh] overflow-y-auto">
          {!selected ? (
            <div className="text-slate-500 text-sm">
              Select a user to see their transcript.
            </div>
          ) : selected.user_id == null ? (
            <div className="text-slate-500 text-sm">
              Anonymous chat — not linkable to a single user.
            </div>
          ) : !turns ? (
            <div className="text-slate-500 text-sm">Loading transcript…</div>
          ) : (
            <>
              <div className="mb-4 pb-3 border-b border-slate-100">
                <div className="font-semibold text-slate-900">
                  {selected.name || selected.email}
                </div>
                <div className="text-xs text-slate-500 mt-0.5">
                  {selected.turns} turns ·
                  {" "}{selected.tokens_in.toLocaleString()} in /
                  {" "}{selected.tokens_out.toLocaleString()} out ·
                  {" "}${selected.cost_usd.toFixed(4)} total
                </div>
              </div>
              <ol className="space-y-4">
                {turns.map(t => (
                  <li key={t.id} className="border-l-2 border-slate-200 pl-3">
                    <div className="text-xs text-slate-500 mb-1">
                      {new Date(t.created_at).toLocaleString()} ·
                      {t.intent ? ` ${t.intent}` : ""}
                      {t.provider ? ` · ${t.provider}/${t.model}` : ""}
                      {" "}· {t.tokens_in}↓/{t.tokens_out}↑
                    </div>
                    {t.input && (
                      <div className="text-sm text-slate-700 bg-slate-50 rounded p-2 mb-1">
                        <div className="text-[10px] uppercase text-slate-400 mb-1">user</div>
                        {t.input}
                      </div>
                    )}
                    {t.response_preview && (
                      <div className="text-sm text-slate-700 bg-indigo-50 rounded p-2">
                        <div className="text-[10px] uppercase text-slate-400 mb-1">assistant</div>
                        {t.response_preview}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
