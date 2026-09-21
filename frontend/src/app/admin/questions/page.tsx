"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { admin, content as contentApi, errMsg } from "@/lib/api";
import { QuestionEditorForm, type QuestionEditorHandle } from "@/components/admin/QuestionEditorForm";
import type { DomainOut, QuestionAdminOut } from "@/types/api";

// One page of questions. The list endpoint is offset/limit paged; we fetch
// PAGE_SIZE rows at a time and infer "there's a next page" from a full page.
const PAGE_SIZE = 50;

export default function QuestionsListPage() {
  const [rows, setRows] = useState<QuestionAdminOut[] | null>(null);
  const [topics, setTopics] = useState<Array<{id:number;code:string;name:string}>>([]);
  const [domains, setDomains] = useState<DomainOut[]>([]);
  const [sets, setSets] = useState<Array<{id:number;name:string}>>([]);
  const [filter, setFilter] = useState<{
    q: string; topic_id: string; domain: string;
    exam_set_id: string; tagged: "" | "any" | "none";
  }>({ q: "", topic_id: "", domain: "", exam_set_id: "", tagged: "" });
  const [page, setPage] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  // Bulk delete: ids ticked by the admin. Survives paging so "select
  // across pages" accumulates; any filter change clears it (the
  // selection was made against a different result set).
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);

  // Side-panel editor. Editing happens next to the list so the filters
  // and page stay exactly as they are (previously every edit bounced to
  // /admin/questions/[id] and back, losing the filter each time).
  const [openId, setOpenId] = useState<number | "new" | null>(null);
  const [dirty, setDirty] = useState(false);
  const editorRef = useRef<QuestionEditorHandle>(null);
  // Pending navigation blocked by unsaved edits: what to open next.
  const [pending, setPending] = useState<number | "new" | null | undefined>(undefined);

  /** Open a question (or close with null); asks first when there are
   *  unsaved edits. */
  function requestOpen(next: number | "new" | null) {
    if (next === openId) return;
    if (dirty) { setPending(next); return; }
    setOpenId(next);
  }
  async function resolvePending(action: "save" | "discard" | "stay") {
    const next = pending;
    setPending(undefined);
    if (action === "stay" || next === undefined) return;
    if (action === "save") {
      const ok = await editorRef.current?.save();
      if (!ok) return;            // invalid / failed: stay on the question
    }
    setDirty(false);
    setOpenId(next);
  }
  // Tab close / hard navigation with edits.
  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  /** A save landed: refresh that row in place (keeps position + filter). */
  function onSaved(row: QuestionAdminOut, wasNew: boolean) {
    if (wasNew) {
      setOpenId(row.id);
      void load(page);
      return;
    }
    setRows(prev => prev ? prev.map(r => r.id === row.id
      ? { ...row, in_sets: row.in_sets?.length ? row.in_sets : r.in_sets } : r) : prev);
  }

  const load = useCallback(async (p: number) => {
    try {
      const params: Record<string, unknown> = { limit: PAGE_SIZE, offset: p * PAGE_SIZE };
      if (filter.q) params.q = filter.q;
      if (filter.topic_id) params.topic_id = Number(filter.topic_id);
      if (filter.domain) params.domain = filter.domain;
      if (filter.exam_set_id) params.exam_set_id = Number(filter.exam_set_id);
      if (filter.tagged) params.tagged = filter.tagged;
      setRows(await admin.questions.list(params));
      setPage(p);
    } catch (e) { console.error("[admin/questions] list", e); setErr(errMsg(e)); }
  }, [filter]);

  /** Current filter as list-endpoint params (no paging). */
  const filterParams = useCallback(() => {
    const params: {
      q?: string; topic_id?: number; domain?: string;
      exam_set_id?: number; tagged?: "any" | "none";
    } = {};
    if (filter.q) params.q = filter.q;
    if (filter.topic_id) params.topic_id = Number(filter.topic_id);
    if (filter.domain) params.domain = filter.domain;
    if (filter.exam_set_id) params.exam_set_id = Number(filter.exam_set_id);
    if (filter.tagged) params.tagged = filter.tagged;
    return params;
  }, [filter]);

  useEffect(() => {
    contentApi.topics().then(setTopics).catch(() => {});
    contentApi.domains().then(setDomains).catch(() => {});
    admin.examSets.list().then(setSets).catch(() => {});
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function topicCode(id: number): string {
    return topics.find(t => t.id === id)?.code ?? `#${id}`;
  }

  async function remove(id: number) {
    if (!confirm("Delete this question? It will also be removed from any exam set it belongs to. Already-submitted attempts keep their frozen review.")) return;
    try {
      await admin.questions.delete(id);
      if (openId === id) { setDirty(false); setOpenId(null); }
      setSelected(prev => { const n = new Set(prev); n.delete(id); return n; });
      await load(page);
    }
    catch (e) { console.error("[admin/questions] delete", e); setErr(errMsg(e)); }
  }

  function toggleOne(id: number) {
    setSelected(prev => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  }

  /** Header checkbox: tick/untick every row on the current page. */
  function togglePage() {
    if (!rows) return;
    const allOn = rows.every(r => selected.has(r.id));
    setSelected(prev => {
      const n = new Set(prev);
      for (const r of rows) { if (allOn) n.delete(r.id); else n.add(r.id); }
      return n;
    });
  }

  /** Select EVERY question matching the active filter, across all pages
   *  (the list endpoint caps at 1000/page, so walk until a short page). */
  async function selectAllFiltered() {
    setBusy(true);
    try {
      const ids: number[] = [];
      const LIMIT = 1000;
      for (let offset = 0; ; offset += LIMIT) {
        const batch = await admin.questions.list(
          { ...filterParams(), limit: LIMIT, offset });
        ids.push(...batch.map(q => q.id));
        if (batch.length < LIMIT) break;
      }
      setSelected(new Set(ids));
    } catch (e) { console.error("[admin/questions] select-all", e); setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  async function removeSelected() {
    const ids = Array.from(selected);
    if (ids.length === 0) return;
    if (!confirm(`Delete ${ids.length} question${ids.length === 1 ? "" : "s"}? They will also be removed from any exam sets. Already-submitted attempts keep their frozen review.`)) return;
    setBusy(true);
    try {
      const res = await admin.questions.bulkDelete(ids);
      setSelected(new Set());
      await load(0);
      if (res.missing.length > 0) {
        setErr(`${res.deleted} deleted; ${res.missing.length} were already gone (list refreshed).`);
      } else {
        setErr(null);
      }
    } catch (e) { console.error("[admin/questions] bulk delete", e); setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  // A full page means there are (probably) more rows beyond it.
  const hasNext = !!rows && rows.length === PAGE_SIZE;
  const hasPrev = page > 0;

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
        <div className="flex gap-2">
          <Link href="/admin/questions/bulk"
                className="px-4 py-2 bg-white text-slate-700 border border-slate-300
                           text-sm font-medium rounded-lg hover:bg-slate-50">
            ↥ Bulk upload
          </Link>
          <button type="button" onClick={() => requestOpen("new")}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium
                             rounded-lg hover:bg-indigo-700">
            + New Question
          </button>
        </div>
      </header>

      {/* Unsaved-changes prompt when switching questions */}
      {pending !== undefined && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="unsaved-title">
          <div className="absolute inset-0 bg-slate-900/50" onClick={() => void resolvePending("stay")} />
          <div className="relative w-full max-w-md rounded-xl bg-white p-5 shadow-xl">
            <h2 id="unsaved-title" className="font-semibold text-slate-900">Unsaved changes</h2>
            <p className="text-sm text-slate-600 mt-1">
              The question you are editing has unsaved edits. They will be lost if you
              {pending === null ? " close the editor" : " move to another question"} without saving.
            </p>
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <button type="button" onClick={() => void resolvePending("stay")}
                      className="px-3 py-2 text-sm border border-slate-300 rounded-lg hover:bg-slate-50">Stay here</button>
              <button type="button" onClick={() => void resolvePending("discard")}
                      className="px-3 py-2 text-sm border border-rose-300 text-rose-700 rounded-lg hover:bg-rose-50">
                Discard &amp; {pending === null ? "close" : "move"}
              </button>
              <button type="button" onClick={() => void resolvePending("save")}
                      className="px-3 py-2 text-sm font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700">
                Save &amp; {pending === null ? "close" : "move"}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-xl p-3 mb-4 flex gap-2 flex-wrap">
        <input value={filter.q}
               onChange={(e) => setFilter({ ...filter, q: e.target.value })}
               onKeyDown={(e) => { if (e.key === "Enter") { setSelected(new Set()); load(0); } }}
               placeholder="Search stem…"
               className="flex-1 min-w-[180px] px-3 py-1.5 text-sm border border-slate-300 rounded" />
        <select value={filter.exam_set_id}
                onChange={(e) => setFilter({ ...filter, exam_set_id: e.target.value })}
                className="px-3 py-1.5 text-sm border border-slate-300 rounded"
                title="Filter by exam set">
          <option value="">All sets</option>
          {sets.map(s => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
        <select value={filter.domain}
                onChange={(e) => setFilter({ ...filter, domain: e.target.value })}
                className="px-3 py-1.5 text-sm border border-slate-300 rounded"
                title="Filter by ECO domain">
          <option value="">All domains</option>
          {domains.map(d => (
            <option key={d.code} value={d.code}>{d.code} — {d.name}</option>
          ))}
        </select>
        <select value={filter.topic_id}
                onChange={(e) => setFilter({ ...filter, topic_id: e.target.value })}
                className="px-3 py-1.5 text-sm border border-slate-300 rounded"
                title="Filter by CPMAI phase">
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
        <button onClick={() => { setSelected(new Set()); load(0); }}
                className="px-4 py-1.5 bg-slate-700 text-white text-sm rounded
                           hover:bg-slate-800">
          Filter
        </button>
      </div>

      {err && <div className="bg-rose-50 border border-rose-200 text-rose-700
                              p-3 rounded-lg mb-4 text-sm">{err}</div>}
      <div className={openId !== null ? "grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(420px,44%)] items-start" : ""}>
      <div className="min-w-0">
      {!rows ? <div className="text-slate-500">Loading…</div>
       : rows.length === 0 ? (
         <div className="bg-white rounded-xl border border-slate-200 p-12 text-center
                         text-slate-500">
           No questions match. <button type="button" onClick={() => requestOpen("new")} className="text-indigo-600 hover:underline">
           Create the first one</button>.
         </div>
       ) : (
        <>
        {/* Selection toolbar — bulk delete over the ticked rows. */}
        <div className="flex items-center gap-3 mb-3 text-sm">
          <span className="text-slate-600">
            {selected.size} selected
          </span>
          <button onClick={selectAllFiltered} disabled={busy}
                  className="text-indigo-600 hover:underline disabled:opacity-40">
            Select all matching filter
          </button>
          {selected.size > 0 && (
            <>
              <button onClick={() => setSelected(new Set())} disabled={busy}
                      className="text-slate-500 hover:underline disabled:opacity-40">
                Clear selection
              </button>
              <button onClick={removeSelected} disabled={busy}
                      className="px-3 py-1.5 bg-rose-600 text-white rounded
                                 hover:bg-rose-700 disabled:opacity-40">
                {busy ? "Deleting…" : `Delete ${selected.size} selected`}
              </button>
            </>
          )}
        </div>
        <div className="bg-white rounded-xl border border-slate-200 overflow-x-auto">
          <table className="w-full">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-left text-xs font-medium text-slate-500 uppercase">
                <th className="px-4 py-3 w-8">
                  <input type="checkbox"
                         aria-label="Select all on this page"
                         checked={rows.length > 0 && rows.every(r => selected.has(r.id))}
                         onChange={togglePage} />
                </th>
                <th className="px-4 py-3">Stem</th>
                <th className={`px-4 py-3 ${openId !== null ? "hidden 2xl:table-cell" : ""}`}>Domain</th>
                <th className="px-4 py-3">Phase</th>
                <th className={`px-4 py-3 ${openId !== null ? "hidden 2xl:table-cell" : ""}`}>Difficulty</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map(q => (
                <tr key={q.id}
                    onClick={() => requestOpen(q.id)}
                    aria-selected={openId === q.id}
                    className={`cursor-pointer ${openId === q.id
                      ? "bg-indigo-50/70 ring-1 ring-inset ring-indigo-200"
                      : "hover:bg-slate-50"}`}>
                  <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox"
                           aria-label={`Select question ${q.id}`}
                           checked={selected.has(q.id)}
                           onChange={() => toggleOne(q.id)} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-sm text-slate-900 line-clamp-2 max-w-md">
                      {q.stem}
                    </div>
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
                  <td className={`px-4 py-3 text-sm text-slate-600 max-w-[16rem] ${openId !== null ? "hidden 2xl:table-cell" : ""}`}>
                    {q.domain
                      ? <span className="line-clamp-2">{q.domain}</span>
                      : <span className="text-slate-400 italic">Unassigned</span>}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-600">
                    {topicCode(q.topic_id)}
                  </td>
                  <td className={`px-4 py-3 text-sm text-slate-600 capitalize ${openId !== null ? "hidden 2xl:table-cell" : ""}`}>
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
                  <td className="px-4 py-3 text-right whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                    <button type="button" onClick={() => requestOpen(q.id)}
                            className="text-xs text-indigo-600 hover:underline mr-3">
                      {openId === q.id ? "Editing" : "Edit"}
                    </button>
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

        {/* Pager — the list endpoint is offset-paged, so we step a page at a
            time. We don't know the grand total, so "Next" is shown whenever
            the current page came back full. */}
        <div className="flex items-center justify-between mt-4 text-sm">
          <span className="text-slate-500">
            Page {page + 1} · showing {rows.length} question{rows.length === 1 ? "" : "s"}
            {hasNext ? " (more available)" : ""}
          </span>
          <div className="flex gap-2">
            <button onClick={() => load(page - 1)} disabled={!hasPrev}
                    className="px-3 py-1.5 border border-slate-300 rounded
                               disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-50">
              ← Prev
            </button>
            <button onClick={() => load(page + 1)} disabled={!hasNext}
                    className="px-3 py-1.5 border border-slate-300 rounded
                               disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-50">
              Next →
            </button>
          </div>
        </div>
        </>
      )}
      </div>

      {/* Right-hand editor panel (full-screen sheet below xl). */}
      {openId !== null && (
        <aside className="max-xl:fixed max-xl:inset-0 max-xl:z-40 max-xl:overflow-y-auto max-xl:bg-slate-900/40 max-xl:p-3 xl:sticky xl:top-4 xl:max-h-[calc(100vh-2rem)] xl:overflow-y-auto"
               aria-label="Question editor">
          <div className="max-xl:bg-slate-50 max-xl:rounded-xl max-xl:p-3 max-xl:min-h-full">
            <div className="flex items-center justify-between mb-2">
              <h2 className="font-semibold text-slate-900">
                {openId === "new" ? "New question" : `Edit question #${openId}`}
                {dirty && <span className="ml-2 text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5">unsaved</span>}
              </h2>
              <div className="flex items-center gap-3 text-xs">
                {openId !== "new" && (
                  <Link href={`/admin/questions/${openId}`} className="text-slate-500 hover:text-indigo-600"
                        onClick={(e) => { if (dirty) { e.preventDefault(); } }}>
                    Open full page ↗
                  </Link>
                )}
                <button type="button" onClick={() => requestOpen(null)}
                        className="text-slate-500 hover:text-slate-900" aria-label="Close editor">✕ Close</button>
              </div>
            </div>
            <QuestionEditorForm
              ref={editorRef}
              key={String(openId)}
              questionId={openId}
              compact
              onDirtyChange={setDirty}
              onSaved={onSaved}
              onCancel={() => requestOpen(null)}
            />
          </div>
        </aside>
      )}
      </div>
    </div>
  );
}
