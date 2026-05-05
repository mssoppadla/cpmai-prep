"use client";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { admin, content as contentApi, errMsg } from "@/lib/api";
import type {
  ExamSetSummaryOut, ExamSetLinkedQuestion, QuestionAdminOut,
} from "@/types/api";

export default function ExamSetEditorPage() {
  const { id } = useParams<{ id: string }>();
  const setId = Number(id);

  const [set, setSet] = useState<ExamSetSummaryOut | null>(null);
  const [linked, setLinked] = useState<ExamSetLinkedQuestion[] | null>(null);
  const [allQ, setAllQ] = useState<QuestionAdminOut[]>([]);
  const [topics, setTopics] = useState<Array<{ id: number; code: string; name: string }>>([]);
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [orderDirty, setOrderDirty] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);

  async function reload() {
    try {
      const [sets, qs, ts, ls] = await Promise.all([
        admin.examSets.list(),
        admin.questions.list({ limit: 500 }),
        contentApi.topics(),
        admin.examSets.listLinkedQuestions(setId),
      ]);
      const me = sets.find((s) => s.id === setId);
      if (!me) {
        setErr("Exam set not found");
        return;
      }
      setSet(me);
      setAllQ(qs);
      setTopics(ts);
      setLinked(ls);
      setOrderDirty(false);
    } catch (e) {
      console.error("[admin/exam-sets/edit] error", e); setErr(errMsg(e));
    }
  }
  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setId]);

  function topicCode(qid: number): string {
    const q = allQ.find((x) => x.id === qid);
    if (!q) return "";
    return topics.find((t) => t.id === q.topic_id)?.code ?? "";
  }

  // Available questions for the picker = all - already linked
  const linkedIds = useMemo(
    () => new Set(linked?.map((l) => l.question.id) ?? []),
    [linked],
  );
  const filtered = useMemo(() => {
    const s = search.toLowerCase().trim();
    return allQ.filter(
      (q) => !linkedIds.has(q.id) && (!s || q.stem.toLowerCase().includes(s)),
    );
  }, [allQ, search, linkedIds]);

  function moveUp(i: number) {
    if (!linked || i === 0) return;
    const next = [...linked];
    [next[i - 1], next[i]] = [next[i], next[i - 1]];
    setLinked(next);
    setOrderDirty(true);
  }

  function moveDown(i: number) {
    if (!linked || i === linked.length - 1) return;
    const next = [...linked];
    [next[i + 1], next[i]] = [next[i], next[i + 1]];
    setLinked(next);
    setOrderDirty(true);
  }

  async function saveOrder() {
    if (!linked || !orderDirty) return;
    setBusy("save-order");
    setErr(null);
    try {
      const items = linked.map((l, i) => ({
        question_id: l.question.id,
        position: (i + 1) * 10,
      }));
      await admin.examSets.reorderQuestions(setId, items);
      setOkMsg("Order saved.");
      setTimeout(() => setOkMsg(null), 2000);
      await reload();
    } catch (e) {
      console.error("[admin/exam-sets/edit] error", e); setErr(errMsg(e));
    } finally {
      setBusy(null);
    }
  }

  async function addPicked() {
    if (picked.size === 0) return;
    setBusy("add");
    setErr(null);
    try {
      await admin.examSets.addQuestions(setId, Array.from(picked));
      const n = picked.size;
      setPicked(new Set());
      setOkMsg(`Added ${n} question${n === 1 ? "" : "s"}.`);
      setTimeout(() => setOkMsg(null), 2000);
      await reload();
    } catch (e) {
      console.error("[admin/exam-sets/edit] error", e); setErr(errMsg(e));
    } finally {
      setBusy(null);
    }
  }

  async function removeOne(qid: number) {
    if (!confirm("Remove this question from the set?")) return;
    setBusy(`remove-${qid}`);
    setErr(null);
    try {
      await admin.examSets.removeQuestion(setId, qid);
      await reload();
    } catch (e) {
      console.error("[admin/exam-sets/edit] error", e); setErr(errMsg(e));
    } finally {
      setBusy(null);
    }
  }

  if (err && !set) {
    return (
      <div className="p-8">
        <div className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg">
          {err}
        </div>
      </div>
    );
  }
  if (!set || !linked) {
    return <div className="p-8 text-slate-500">Loading…</div>;
  }

  return (
    <div className="p-8 max-w-5xl">
      <Link
        href="/admin/exam-sets"
        className="text-sm text-slate-500 hover:text-indigo-600"
      >
        ← All exam sets
      </Link>
      <header className="mt-2 mb-6">
        <h1 className="text-2xl font-bold text-slate-900">{set.name}</h1>
        <div className="text-sm text-slate-600 mt-1">
          <code className="bg-slate-100 px-1.5 py-0.5 rounded text-xs">{set.slug}</code>
          {" · "}
          {linked.length} question{linked.length === 1 ? "" : "s"}
          {" · "}
          {set.time_limit_minutes} min · pass {set.passing_score}%
          {set.is_premium && " · ⭐ premium"}
        </div>
      </header>

      {err && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}
      {okMsg && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 p-3 rounded-lg mb-4 text-sm">
          {okMsg}
        </div>
      )}

      {/* Linked questions in display order */}
      <section className="bg-white rounded-xl border border-slate-200 p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="font-semibold text-slate-900">Linked questions</h2>
            <p className="text-sm text-slate-600">
              This is the order learners will see. Use ↑/↓ to reorder, then save.
            </p>
          </div>
          {orderDirty && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => reload()}
                className="px-3 py-2 bg-white text-slate-700 text-sm font-medium border border-slate-300 rounded-lg hover:bg-slate-50"
              >
                Discard
              </button>
              <button
                onClick={saveOrder}
                disabled={busy === "save-order"}
                className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50"
              >
                {busy === "save-order" ? "Saving…" : "Save order"}
              </button>
            </div>
          )}
        </div>
        {linked.length === 0 ? (
          <div className="text-center py-8 text-slate-500 text-sm">
            No questions linked yet. Add some from the picker below.
          </div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {linked.map((l, i) => (
              <li key={l.question.id} className="flex items-start gap-3 py-3">
                <div className="flex flex-col items-center w-8 select-none">
                  <button
                    onClick={() => moveUp(i)}
                    disabled={i === 0}
                    aria-label="Move up"
                    className="text-slate-400 hover:text-indigo-600 disabled:opacity-30 disabled:cursor-not-allowed text-sm leading-none"
                  >
                    ▲
                  </button>
                  <span className="text-xs text-slate-500 tabular-nums my-1">
                    {i + 1}
                  </span>
                  <button
                    onClick={() => moveDown(i)}
                    disabled={i === linked.length - 1}
                    aria-label="Move down"
                    className="text-slate-400 hover:text-indigo-600 disabled:opacity-30 disabled:cursor-not-allowed text-sm leading-none"
                  >
                    ▼
                  </button>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-slate-900 line-clamp-2">
                    {l.question.stem}
                  </div>
                  <div className="text-xs text-slate-500 mt-0.5 flex flex-wrap items-center gap-x-2">
                    <span className="font-medium">{topicCode(l.question.id)}</span>
                    {l.question.domain && (
                      <>
                        <span>·</span>
                        <span>{l.question.domain}</span>
                      </>
                    )}
                    <span>·</span>
                    <span className="capitalize">{l.question.difficulty}</span>
                    {!l.question.is_active && (
                      <>
                        <span>·</span>
                        <span className="text-amber-700">draft</span>
                      </>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <Link
                    href={`/admin/questions/${l.question.id}`}
                    className="text-xs text-indigo-600 hover:underline"
                  >
                    Edit
                  </Link>
                  <button
                    onClick={() => removeOne(l.question.id)}
                    disabled={busy === `remove-${l.question.id}`}
                    className="text-xs text-rose-600 hover:underline disabled:opacity-50"
                  >
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Add new questions (filtered to exclude already-linked) */}
      <section className="bg-white rounded-xl border border-slate-200 p-6">
        <h2 className="font-semibold text-slate-900 mb-1">Add questions</h2>
        <p className="text-sm text-slate-600 mb-3">
          Pick from the question bank. Already-linked questions are filtered out.
        </p>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search question stem…"
          className="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none mb-3"
        />
        <div className="border border-slate-200 rounded-lg max-h-96 overflow-y-auto">
          {filtered.length === 0 ? (
            <div className="p-6 text-center text-slate-500 text-sm">
              {allQ.length === 0
                ? "No questions in the bank yet."
                : linkedIds.size === allQ.length
                  ? "All questions are already linked to this set."
                  : "No unlinked questions match the search."}
            </div>
          ) : (
            <ul className="divide-y divide-slate-100">
              {filtered.map((q) => {
                const sel = picked.has(q.id);
                return (
                  <li
                    key={q.id}
                    className="flex items-start gap-3 p-3 hover:bg-slate-50 cursor-pointer"
                    onClick={() => {
                      const n = new Set(picked);
                      sel ? n.delete(q.id) : n.add(q.id);
                      setPicked(n);
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={sel}
                      onChange={() => {}}
                      className="mt-1 pointer-events-none"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm text-slate-900 line-clamp-2">
                        {q.stem}
                      </div>
                      <div className="text-xs text-slate-500 mt-0.5">
                        {topicCode(q.id)}
                        {q.domain ? ` · ${q.domain}` : ""}
                        {" · "}
                        <span className="capitalize">{q.difficulty}</span>
                      </div>
                    </div>
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
          <button
            onClick={addPicked}
            disabled={picked.size === 0 || busy === "add"}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50"
          >
            {busy === "add" ? "Adding…" : "Add selected"}
          </button>
        </div>
      </section>
    </div>
  );
}
