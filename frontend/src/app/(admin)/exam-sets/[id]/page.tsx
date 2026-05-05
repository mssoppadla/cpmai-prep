"use client";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { admin, content as contentApi, ApiError } from "@/lib/api";
import type {
  ExamSetSummaryOut, QuestionAdminOut,
} from "@/types/api";

export default function ExamSetEditorPage() {
  const { id } = useParams<{ id: string }>();
  const setId = Number(id);

  const [set, setSet] = useState<ExamSetSummaryOut | null>(null);
  const [linked, setLinked] = useState<QuestionAdminOut[] | null>(null);
  const [allQ, setAllQ] = useState<QuestionAdminOut[]>([]);
  const [topics, setTopics] = useState<Array<{id:number;code:string;name:string}>>([]);
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [err, setErr] = useState<string | null>(null);

  // The "linked" list isn't directly exposed by an admin endpoint; we derive
  // it by listing all questions and filtering by exam_set membership via
  // the user-facing GET /exam-sets/{slug} which returns question_count only.
  // So we mirror the server's link via the /admin/questions list and a
  // server-side helper. For simplicity in this first iteration, we list
  // ALL questions and rely on a heuristic: a future admin endpoint
  // /admin/exam-sets/{id}/questions would return the linked subset directly.
  //
  // Until that endpoint exists, this page focuses on the ADD/REMOVE flow
  // by the IDs the admin selects — the API guarantees idempotency.

  async function reload() {
    try {
      const [sets, qs, ts] = await Promise.all([
        admin.examSets.list(), admin.questions.list({ limit: 200 }),
        contentApi.topics(),
      ]);
      const me = sets.find(s => s.id === setId);
      if (!me) { setErr("Exam set not found"); return; }
      setSet(me);
      setAllQ(qs);
      setTopics(ts);
      // Linked detection: hit the public GET /exam-sets/{slug}/start would
      // require enrollment. Instead expose a simple admin helper later.
      // For now, we treat `linked` as null and rely on the picker UX.
      setLinked([]);
    } catch (e) { setErr((e as ApiError).body.message); }
  }
  useEffect(() => { reload(); }, [setId]);

  function topicCode(qid: number): string {
    const q = allQ.find(x => x.id === qid);
    if (!q) return "";
    return topics.find(t => t.id === q.topic_id)?.code ?? "";
  }

  const filtered = useMemo(() => {
    const s = search.toLowerCase().trim();
    return allQ.filter(q => !s || q.stem.toLowerCase().includes(s));
  }, [allQ, search]);

  async function addPicked() {
    if (picked.size === 0) return;
    try {
      await admin.examSets.addQuestions(setId, Array.from(picked));
      setPicked(new Set());
      alert(`Added ${picked.size} question(s) to the set.`);
    } catch (e) { setErr((e as ApiError).body.message); }
  }

  async function removeOne(qid: number) {
    if (!confirm("Remove this question from the set?")) return;
    try {
      await admin.examSets.removeQuestion(setId, qid);
      alert("Removed.");
    } catch (e) { setErr((e as ApiError).body.message); }
  }

  if (err) {
    return <div className="p-8"><div className="bg-rose-50 border border-rose-200
            text-rose-700 p-4 rounded-lg">{err}</div></div>;
  }
  if (!set) return <div className="p-8 text-slate-500">Loading…</div>;

  return (
    <div className="p-8 max-w-5xl">
      <Link href="/admin/exam-sets"
            className="text-sm text-slate-500 hover:text-indigo-600">
        ← All exam sets
      </Link>
      <header className="mt-2 mb-6">
        <h1 className="text-2xl font-bold text-slate-900">{set.name}</h1>
        <div className="text-sm text-slate-600 mt-1">
          <code className="bg-slate-100 px-1.5 py-0.5 rounded text-xs">{set.slug}</code>
          {" · "}{set.question_count} question{set.question_count === 1 ? "" : "s"}
          {" · "}{set.time_limit_minutes} min · pass {set.passing_score}%
          {set.is_premium && " · ⭐ premium"}
        </div>
      </header>

      <section className="bg-white rounded-xl border border-slate-200 p-6 mb-6">
        <h2 className="font-semibold text-slate-900 mb-4">Add questions</h2>
        <p className="text-sm text-slate-600 mb-3">
          Pick from the question bank. Already-linked questions are silently skipped
          on add. To remove a question, use the row action below.
        </p>
        <input value={search}
               onChange={(e) => setSearch(e.target.value)}
               placeholder="Search question stem…"
               className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg
                          focus:ring-2 focus:ring-indigo-500 outline-none mb-3" />
        <div className="border border-slate-200 rounded-lg max-h-96 overflow-y-auto">
          {filtered.length === 0 ? (
            <div className="p-6 text-center text-slate-500 text-sm">No matches.</div>
          ) : (
            <ul className="divide-y divide-slate-100">
              {filtered.map(q => {
                const sel = picked.has(q.id);
                return (
                  <li key={q.id} className="flex items-start gap-3 p-3 hover:bg-slate-50">
                    <input type="checkbox" checked={sel}
                           onChange={() => {
                             const n = new Set(picked);
                             sel ? n.delete(q.id) : n.add(q.id);
                             setPicked(n);
                           }}
                           className="mt-1" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-slate-900 line-clamp-2">{q.stem}</div>
                      <div className="text-xs text-slate-500 mt-0.5">
                        {topicCode(q.id)}{q.domain ? ` · ${q.domain}` : ""}
                        {" · "}<span className="capitalize">{q.difficulty}</span>
                      </div>
                    </div>
                    <button onClick={() => removeOne(q.id)}
                            className="text-xs text-rose-600 hover:underline">
                      Unlink
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <div className="flex items-center justify-between mt-4">
          <div className="text-sm text-slate-600">
            {picked.size} selected
          </div>
          <button onClick={addPicked} disabled={picked.size === 0}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium
                             rounded-lg hover:bg-indigo-700 disabled:opacity-50">
            Add selected to set
          </button>
        </div>
      </section>
    </div>
  );
}
