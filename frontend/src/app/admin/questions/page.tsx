"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { admin, content as contentApi, errMsg } from "@/lib/api";
import type { QuestionAdminOut } from "@/types/api";

export default function QuestionsListPage() {
  const [rows, setRows] = useState<QuestionAdminOut[] | null>(null);
  const [topics, setTopics] = useState<Array<{id:number;code:string;name:string}>>([]);
  const [filter, setFilter] = useState<{
    q: string; topic_id: string; tagged: "" | "any" | "none";
  }>({ q: "", topic_id: "", tagged: "" });
  const [err, setErr] = useState<string | null>(null);

  async function reload() {
    try {
      const params: Record<string, unknown> = {};
      if (filter.q) params.q = filter.q;
      if (filter.topic_id) params.topic_id = Number(filter.topic_id);
      if (filter.tagged) params.tagged = filter.tagged;
      setRows(await admin.questions.list(params));
    } catch (e) { console.error("[admin/questions] list", e); setErr(errMsg(e)); }
  }
  useEffect(() => {
    contentApi.topics().then(setTopics).catch(() => {});
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function topicCode(id: number): string {
    return topics.find(t => t.id === id)?.code ?? `#${id}`;
  }

  async function remove(id: number) {
    if (!confirm("Delete this question? It will also be removed from any exam set it belongs to.")) return;
    try { await admin.questions.delete(id); await reload(); }
    catch (e) { console.error("[admin/questions] delete", e); setErr(errMsg(e)); }
  }

  return (
    <div className="p-8">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Questions</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Author the question bank. Each option carries its own correctness flag
            and reasoning — shown to learners only after they submit.
          </p>
        </div>
        <Link href="/admin/questions/new"
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium
                         rounded-lg hover:bg-indigo-700">
          + New Question
        </Link>
      </header>

      <div className="bg-white border border-slate-200 rounded-xl p-3 mb-4 flex gap-2 flex-wrap">
        <input value={filter.q}
               onChange={(e) => setFilter({ ...filter, q: e.target.value })}
               placeholder="Search stem…"
               className="flex-1 min-w-[200px] px-3 py-1.5 text-sm border border-slate-300 rounded" />
        <select value={filter.topic_id}
                onChange={(e) => setFilter({ ...filter, topic_id: e.target.value })}
                className="px-3 py-1.5 text-sm border border-slate-300 rounded">
          <option value="">All phases</option>
          {topics.map(t => (
            <option key={t.id} value={t.id}>{t.code} — {t.name}</option>
          ))}
        </select>
        <select value={filter.tagged}
                onChange={(e) => setFilter({ ...filter, tagged: e.target.value as "" | "any" | "none" })}
                className="px-3 py-1.5 text-sm border border-slate-300 rounded"
                title="Filter by whether the question is tagged into any exam set">
          <option value="">Any tag-state</option>
          <option value="any">Tagged in ≥1 set</option>
          <option value="none">Untagged (orphan)</option>
        </select>
        <button onClick={reload}
                className="px-4 py-1.5 bg-slate-700 text-white text-sm rounded
                           hover:bg-slate-800">
          Filter
        </button>
      </div>

      {err && <div className="bg-rose-50 border border-rose-200 text-rose-700
                              p-3 rounded-lg mb-4 text-sm">{err}</div>}
      {!rows ? <div className="text-slate-500">Loading…</div>
       : rows.length === 0 ? (
         <div className="bg-white rounded-xl border border-slate-200 p-12 text-center
                         text-slate-500">
           No questions match. <Link href="/admin/questions/new" className="text-indigo-600">
           Create the first one</Link>.
         </div>
       ) : (
        <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <table className="w-full">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-left text-xs font-medium text-slate-500 uppercase">
                <th className="px-4 py-3">Stem</th>
                <th className="px-4 py-3">Phase</th>
                <th className="px-4 py-3">Difficulty</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map(q => (
                <tr key={q.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="text-sm text-slate-900 line-clamp-2 max-w-xl">
                      {q.stem}
                    </div>
                    {q.domain && (
                      <div className="text-xs text-slate-500 mt-1">{q.domain}</div>
                    )}
                    {/* Cross-set visibility — admin can see at a glance
                        which sets a question already lives in. Empty
                        list = unattached (omit the row entirely). */}
                    {q.in_sets && q.in_sets.length > 0 && (
                      <div className="text-xs text-slate-500 mt-1">
                        In:{" "}
                        {q.in_sets.map(s => (
                          <span key={s.id}
                                className="inline-block bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded mr-1">
                            {s.name}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-600">
                    {topicCode(q.topic_id)}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-600 capitalize">
                    {q.difficulty}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${
                      q.is_active
                        ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                        : "bg-slate-100 text-slate-600 border-slate-200"
                    }`}>
                      {q.is_active ? "active" : "draft"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link href={`/admin/questions/${q.id}`}
                          className="text-xs text-indigo-600 hover:underline mr-3">
                      Edit
                    </Link>
                    <button onClick={() => remove(q.id)}
                            className="text-xs text-rose-600 hover:underline">
                      Delete
                    </button>
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
