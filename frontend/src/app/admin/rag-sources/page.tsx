"use client";
import { useEffect, useRef, useState } from "react";
import { admin, errMsg, type RagDocumentOut } from "@/lib/api";

const ALLOWED = ".txt,.md,.pdf,.docx,.xlsx";

export default function RagSourcesPage() {
  const [docs, setDocs] = useState<RagDocumentOut[] | null>(null);
  const [status, setStatus] = useState<Record<string, {
    chunks: number; last_indexed: string | null;
    provider: string | null; model: string | null;
  }> | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function reload() {
    try {
      const [s, list] = await Promise.all([
        admin.rag.status(),
        admin.rag.listUploads(),
      ]);
      setStatus(s.sources);
      setDocs(list.documents);
    } catch (e) {
      console.error("[admin/rag] reload", e);
      setErr(errMsg(e));
    }
  }
  useEffect(() => { reload(); }, []);

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setBusy(true); setErr(null); setInfo(null);
    try {
      const doc = await admin.rag.upload(f);
      setInfo(`Indexed ${doc.filename} → ${doc.chunk_count} chunks.`);
      await reload();
    } catch (ex) {
      console.error("[admin/rag] upload", ex);
      setErr(errMsg(ex));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function onDelete(id: number, name: string) {
    if (!confirm(`Delete "${name}" and its chunks?`)) return;
    try {
      await admin.rag.deleteUpload(id);
      await reload();
    } catch (e) {
      console.error("[admin/rag] delete", e);
      setErr(errMsg(e));
    }
  }

  async function onReindex() {
    if (!confirm("Re-embed every indexed source? This calls the embedding provider.")) return;
    setBusy(true); setErr(null); setInfo(null);
    try {
      const r = await admin.rag.reindex();
      const total = Object.values(r.counts).reduce((a, b) => a + b, 0);
      setInfo(`Reindex complete — ${total} chunks across ${Object.keys(r.counts).length} sources.`);
      await reload();
    } catch (e) {
      console.error("[admin/rag] reindex", e);
      setErr(errMsg(e));
    } finally { setBusy(false); }
  }

  return (
    <div className="p-8 max-w-4xl">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">RAG Sources</h1>
        <p className="text-slate-600 mt-1 text-sm">
          Upload reference documents the assistant retrieves from. Files
          are parsed, chunked, and embedded immediately. The raw file
          isn&apos;t kept — to update content, re-upload.
        </p>
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}
      {info && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 p-3 rounded-lg mb-4 text-sm">
          {info}
        </div>
      )}

      <section className="bg-white border border-slate-200 rounded-xl p-5 mb-6">
        <h2 className="font-semibold text-slate-900 mb-3">Index status</h2>
        {!status ? <div className="text-slate-500 text-sm">Loading…</div> : (
          <div className="grid sm:grid-cols-2 gap-3 text-sm">
            {Object.entries(status).map(([src, s]) => (
              <div key={src} className="border border-slate-200 rounded-lg p-3">
                <div className="font-medium text-slate-900">{src}</div>
                <div className="text-slate-600 mt-1">
                  {s.chunks} chunks
                  {s.model ? ` · ${s.provider}/${s.model}` : ""}
                </div>
                <div className="text-xs text-slate-500 mt-1">
                  {s.last_indexed
                    ? `last indexed ${new Date(s.last_indexed).toLocaleString()}`
                    : "not indexed yet"}
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="mt-4">
          <button onClick={onReindex} disabled={busy}
            className="px-3 py-2 bg-slate-900 text-white text-sm font-medium rounded-lg hover:bg-slate-800 disabled:opacity-50">
            {busy ? "Working…" : "Reindex all sources"}
          </button>
        </div>
      </section>

      <section className="bg-white border border-slate-200 rounded-xl p-5 mb-6">
        <h2 className="font-semibold text-slate-900 mb-1">Upload a document</h2>
        <p className="text-xs text-slate-500 mb-3">
          Supported: .txt, .md, .pdf, .docx, .xlsx. Max 20 MB. Scanned-image
          PDFs without OCR text won&apos;t produce any chunks.
        </p>
        <input ref={fileRef} type="file" accept={ALLOWED}
               disabled={busy} onChange={onUpload}
               className="block text-sm" />
      </section>

      <section>
        <h2 className="font-semibold text-slate-900 mb-3">Uploaded documents</h2>
        {!docs ? <div className="text-slate-500 text-sm">Loading…</div>
         : docs.length === 0 ? (
            <div className="bg-white rounded-xl border border-slate-200 p-12 text-center text-slate-500 text-sm">
              No uploads yet.
            </div>
          ) : (
            <ul className="space-y-2">
              {docs.map(d => (
                <li key={d.id}
                    className="bg-white rounded-xl border border-slate-200 p-4 flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-slate-900 truncate">
                      {d.filename}
                    </div>
                    <div className="text-xs text-slate-500 mt-1">
                      {(d.size_bytes / 1024).toFixed(1)} KB ·
                      {" "}{d.chunk_count} chunks ·
                      {" "}{new Date(d.created_at).toLocaleString()}
                    </div>
                  </div>
                  <button onClick={() => onDelete(d.id, d.filename)}
                    className="text-xs text-rose-600 hover:underline flex-shrink-0">
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          )}
      </section>
    </div>
  );
}
