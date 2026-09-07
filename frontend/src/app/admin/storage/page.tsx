"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { absoluteUploadUrl, admin, errMsg } from "@/lib/api";
import type {
  MediaTrashOut, StorageFileOut, StorageLinkRef, StorageOverviewOut,
} from "@/types/api";

/**
 * /admin/storage — every uploaded file, with where it is used.
 *
 * Safety model (mirrors the backend, which is authoritative):
 *   - only status=unlinked rows are selectable; linked/held/system/
 *     candidate checkboxes don't exist
 *   - the server RE-VERIFIES links at trash time; anything that became
 *     linked after this page loaded comes back in `skipped` with proof
 *   - trash is a move; disk is freed only by Empty trash, which must
 *     echo the exact byte total (409 when trash changed underneath)
 */

const TABS = [
  { key: "all", label: "All" },
  { key: "linked", label: "Linked" },
  { key: "unlinked", label: "Unlinked" },
  { key: "candidate", label: "Compressed candidates" },
  { key: "system", label: "System" },
] as const;

function fmtBytes(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(0)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${n} B`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN",
    { day: "2-digit", month: "short", year: "numeric" });
}

function refText(r: StorageLinkRef): string {
  const path = [r.course_title, r.section_title].filter(Boolean).join(" → ");
  return path ? `${r.label} — ${path}` : r.label;
}

function LinkChips({ links }: { links: StorageLinkRef[] }) {
  if (!links.length) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {links.map((r, i) => (
        <a key={i} href={r.admin_href || "#"}
           className="inline-flex items-center rounded-md border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 hover:bg-emerald-100"
           title={refText(r)}>
          {refText(r)}
        </a>
      ))}
    </div>
  );
}

const STATUS_CHIP: Record<StorageFileOut["status"], { cls: string; text: string }> = {
  linked:    { cls: "border-emerald-200 bg-emerald-50 text-emerald-700", text: "Linked" },
  unlinked:  { cls: "border-amber-200 bg-amber-50 text-amber-700", text: "Unlinked — nothing references this file" },
  held:      { cls: "border-sky-200 bg-sky-50 text-sky-700", text: "Held — uploaded under 24h ago; excluded from deletion while you may still be attaching it" },
  candidate: { cls: "border-indigo-200 bg-indigo-50 text-indigo-700", text: "Compressed candidate" },
  system:    { cls: "border-sky-200 bg-sky-50 text-sky-700", text: "System — invoices, recordings & RAG files are never deletable here" },
};

export default function AdminStoragePage() {
  const [overview, setOverview] = useState<StorageOverviewOut | null>(null);
  const [rows, setRows] = useState<StorageFileOut[]>([]);
  const [trash, setTrash] = useState<MediaTrashOut[]>([]);
  const [tab, setTab] = useState<string>("all");
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [detail, setDetail] = useState<StorageFileOut | null>(null);
  const [emptyOpen, setEmptyOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    try {
      const [o, f, t] = await Promise.all([
        admin.storage.overview(),
        admin.storage.files(),
        admin.storage.trashItems(),
      ]);
      setOverview(o); setRows(f); setTrash(t);
      setSelected(new Set());
    } catch (e) { setErr(errMsg(e)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const visible = useMemo(() => {
    let list = rows;
    if (tab !== "all") {
      list = list.filter((r) => tab === "unlinked"
        ? r.status === "unlinked" || r.status === "held"
        : r.status === tab);
    }
    if (q.trim()) {
      const needle = q.trim().toLowerCase();
      list = list.filter((r) => r.name.toLowerCase().includes(needle)
        || r.path.toLowerCase().includes(needle));
    }
    return list;
  }, [rows, tab, q]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: rows.length };
    for (const t of TABS.slice(1)) {
      c[t.key] = rows.filter((r) => t.key === "unlinked"
        ? r.status === "unlinked" || r.status === "held"
        : r.status === t.key).length;
    }
    return c;
  }, [rows]);

  const selectedBytes = useMemo(
    () => rows.filter((r) => selected.has(r.path))
      .reduce((a, r) => a + r.size_bytes, 0),
    [rows, selected]);

  const trashBytes = trash.reduce((a, t) => a + t.size_bytes, 0);

  const toggle = (path: string) => setSelected((s) => {
    const next = new Set(s);
    if (next.has(path)) next.delete(path); else next.add(path);
    return next;
  });

  const doTrash = async (paths: string[]) => {
    setBusy(true); setErr(null); setNotice(null);
    try {
      const res = await admin.storage.trash(paths);
      const skippedLinked = res.skipped.filter((s) => s.reason === "linked");
      let msg = `Moved ${res.trashed.length} file(s) to trash.`;
      if (skippedLinked.length) {
        msg += ` Skipped ${skippedLinked.length} — the server found them`
          + ` linked (${skippedLinked.map((s) =>
            s.links?.[0] ? refText(s.links[0] as StorageLinkRef) : s.path).join("; ")}).`;
      }
      const other = res.skipped.filter((s) => s.reason !== "linked");
      if (other.length) {
        msg += ` Skipped ${other.length} (${other.map((s) => s.reason).join(", ")}).`;
      }
      setNotice(msg);
      await load();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  };

  const doRestore = async (t: MediaTrashOut, revert: boolean) => {
    setBusy(true); setErr(null); setNotice(null);
    try {
      const res = await admin.storage.restore(t.id, revert);
      setNotice(res.notice
        ?? (res.reverted_lesson
          ? "Restored and the lesson now serves the original again."
          : `Restored to ${res.restored_path} (listed as Unlinked — attach it wherever you need).`));
      await load();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  };

  const doEmpty = async () => {
    setBusy(true); setErr(null); setNotice(null);
    try {
      const res = await admin.storage.emptyTrash(trashBytes);
      setNotice(`Trash emptied — ${res.deleted} file(s) deleted, ${fmtBytes(res.freed_bytes)} freed.`);
      setEmptyOpen(false); setConfirmText("");
      await load();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  };

  const decide = async (candidateId: number, action: "keep" | "discard") => {
    setBusy(true); setErr(null); setNotice(null);
    try {
      const res = await admin.storage.decideCandidate(candidateId, action);
      setNotice(action === "keep"
        ? "Lesson now serves the compressed file. The original is in trash — restore it any time to revert."
        : "Candidate discarded; the original stays in place.");
      void res;
      setDetail(null);
      await load();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  };

  const confirmTarget = fmtBytes(trashBytes);

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Storage</h1>
        <p className="text-sm text-slate-500 max-w-3xl">
          Every uploaded file on the server, with where it is used. Only files
          the server verifies as unlinked can be trashed — linkage is
          re-checked at the moment you act, not from this listing.
        </p>
      </div>

      {err && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{err}</div>}
      {notice && <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">{notice}</div>}

      {overview && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
            <div className="text-[11px] uppercase tracking-wide text-slate-400">Disk used (uploads)</div>
            <div className="text-xl font-semibold tabular-nums text-slate-900">{fmtBytes(overview.disk_used_bytes)}</div>
            <div className="text-xs text-slate-500">
              {fmtBytes(overview.linked_bytes)} linked · {fmtBytes(overview.unlinked_bytes)} unlinked · {fmtBytes(overview.trash_bytes)} trash
            </div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
            <div className="text-[11px] uppercase tracking-wide text-slate-400">Linked files</div>
            <div className="text-xl font-semibold tabular-nums text-slate-900">{overview.counts.linked}</div>
            <div className="text-xs text-slate-500">used by courses, lessons & pages</div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
            <div className="text-[11px] uppercase tracking-wide text-slate-400">Unlinked (reclaimable)</div>
            <div className="text-xl font-semibold tabular-nums text-amber-600">{fmtBytes(overview.unlinked_bytes)}</div>
            <div className="text-xs text-slate-500">{overview.counts.unlinked} file(s), nothing references them</div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
            <div className="text-[11px] uppercase tracking-wide text-slate-400">In trash</div>
            <div className="text-xl font-semibold tabular-nums text-slate-900">{fmtBytes(overview.trash_bytes)}</div>
            <div className="text-xs text-slate-500">{overview.counts.trash} file(s) · restorable until emptied</div>
          </div>
        </div>
      )}

      <div className="border-b border-slate-200">
        <nav className="-mb-px flex gap-1">
          {TABS.map((t) => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`border-b-2 px-3 py-2 text-sm ${tab === t.key
                ? "border-indigo-600 font-semibold text-indigo-600"
                : "border-transparent text-slate-500 hover:text-slate-700"}`}>
              {t.label}
              <span className={`ml-1 rounded-full px-2 py-0.5 text-[11px] tabular-nums ${
                tab === t.key ? "bg-indigo-50 text-indigo-600" : "bg-slate-100 text-slate-500"}`}>
                {counts[t.key] ?? 0}
              </span>
            </button>
          ))}
        </nav>
      </div>

      <div className="flex items-center gap-3">
        <input value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Search file name or path…"
          className="w-full max-w-sm rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" />
        <span className="text-xs text-slate-400">Sorted by size · largest first</span>
        <button onClick={() => void load()} disabled={loading}
          className="ml-auto rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-50">
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm">
          <span><b className="tabular-nums">{selected.size}</b> unlinked file(s) selected · <b>{fmtBytes(selectedBytes)}</b></span>
          <button onClick={() => void doTrash([...selected])} disabled={busy}
            className="rounded-lg border border-red-200 bg-white px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50">
            Move to trash
          </button>
          <button onClick={() => setSelected(new Set())}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50">
            Clear
          </button>
          <span className="text-xs text-slate-500">Trash is reversible — files stay restorable until you empty the trash.</span>
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-400">
              <th className="w-8 px-3 py-2"></th>
              <th className="px-3 py-2">File</th>
              <th className="px-3 py-2">Used by</th>
              <th className="px-3 py-2">Size</th>
              <th className="px-3 py-2">Uploaded</th>
              <th className="px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.path} className="border-b border-slate-100 align-top last:border-0">
                <td className="px-3 py-2.5">
                  <input type="checkbox" disabled={r.status !== "unlinked"}
                    checked={selected.has(r.path)}
                    onChange={() => toggle(r.path)}
                    className="h-4 w-4 accent-indigo-600 disabled:opacity-30"
                    aria-label={`Select ${r.name}`} />
                </td>
                <td className="px-3 py-2.5">
                  <div className="font-medium text-slate-900">{r.name}</div>
                  <div className="break-all font-mono text-[11px] text-slate-400">{r.path}</div>
                </td>
                <td className="px-3 py-2.5">
                  {r.status === "candidate" && r.candidate ? (
                    <div className="space-y-1">
                      <span className={`inline-flex rounded-md border px-2 py-0.5 text-xs font-medium ${STATUS_CHIP.candidate.cls}`}>
                        Compressed candidate · −{r.candidate.savings_pct}% vs original
                      </span>
                      <div className="text-xs text-slate-500">
                        Original: <span className="font-mono text-[11px]">{r.candidate.parent_path.split("/").pop()}</span>
                      </div>
                      <LinkChips links={r.candidate.parent_links} />
                    </div>
                  ) : r.links.length ? (
                    <LinkChips links={r.links} />
                  ) : (
                    <span className={`inline-flex rounded-md border px-2 py-0.5 text-xs font-medium ${STATUS_CHIP[r.status].cls}`}>
                      {STATUS_CHIP[r.status].text}
                    </span>
                  )}
                </td>
                <td className="whitespace-nowrap px-3 py-2.5 tabular-nums text-slate-600">{fmtBytes(r.size_bytes)}</td>
                <td className="whitespace-nowrap px-3 py-2.5 tabular-nums text-slate-600">{fmtDate(r.uploaded_at)}</td>
                <td className="px-3 py-2.5">
                  <div className="flex flex-col items-start gap-1 text-sm">
                    <button onClick={() => setDetail(r)} className="text-indigo-600 hover:underline">Details</button>
                    <a href={absoluteUploadUrl(r.download_url)} download
                       className="text-indigo-600 hover:underline">Download</a>
                    {r.status === "unlinked" && (
                      <button onClick={() => void doTrash([r.path])} disabled={busy}
                        className="text-red-600 hover:underline disabled:opacity-50">Trash</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {!visible.length && !loading && (
              <tr><td colSpan={6} className="px-3 py-8 text-center text-sm text-slate-400">No files in this view.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Trash */}
      <div className="space-y-3 pt-4">
        <div className="flex items-end justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Trash</h2>
            <p className="text-sm text-slate-500 max-w-3xl">
              Files here no longer serve on the site but still occupy disk.
              Restore puts a file back at its original path; Empty trash
              permanently deletes and frees the space.
            </p>
          </div>
          {trash.length > 0 && (
            <button onClick={() => { setEmptyOpen(true); setConfirmText(""); }}
              className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700">
              Empty trash ({fmtBytes(trashBytes)})…
            </button>
          )}
        </div>
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-400">
                <th className="px-3 py-2">File</th>
                <th className="px-3 py-2">Was linked to</th>
                <th className="px-3 py-2">Size</th>
                <th className="px-3 py-2">Trashed</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {trash.map((t) => (
                <tr key={t.id} className="border-b border-slate-100 align-top last:border-0">
                  <td className="px-3 py-2.5">
                    <div className="font-medium text-slate-900">{t.name}
                      {t.is_kept_candidate_original && (
                        <span className="ml-2 rounded-md border border-slate-200 bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                          original of a kept candidate
                        </span>
                      )}
                    </div>
                    <div className="break-all font-mono text-[11px] text-slate-400">was {t.original_path}</div>
                  </td>
                  <td className="px-3 py-2.5">
                    {t.was_links.length
                      ? <LinkChips links={t.was_links} />
                      : <span className="text-xs text-slate-400">Nothing (was unlinked)</span>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 tabular-nums text-slate-600">{fmtBytes(t.size_bytes)}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-slate-600">
                    {fmtDate(t.trashed_at)}{t.trashed_by_email ? ` · ${t.trashed_by_email}` : ""}
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-col items-start gap-1 text-sm">
                      <button onClick={() => void doRestore(t, false)} disabled={busy}
                        className="text-indigo-600 hover:underline disabled:opacity-50">Restore</button>
                      {t.is_kept_candidate_original && (
                        <button onClick={() => void doRestore(t, true)} disabled={busy}
                          className="text-indigo-600 hover:underline disabled:opacity-50">
                          Restore & revert lesson to original
                        </button>
                      )}
                      <a href={absoluteUploadUrl(t.download_url)} download
                         className="text-indigo-600 hover:underline">Download</a>
                    </div>
                  </td>
                </tr>
              ))}
              {!trash.length && (
                <tr><td colSpan={5} className="px-3 py-6 text-center text-sm text-slate-400">Trash is empty.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Details drawer */}
      {detail && (
        <div className="fixed inset-0 z-40" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-slate-900/40" onClick={() => setDetail(null)} />
          <aside className="absolute inset-y-0 right-0 flex w-[420px] max-w-[94vw] flex-col overflow-y-auto border-l border-slate-200 bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
              <h3 className="text-sm font-semibold text-slate-900">{detail.name}</h3>
              <button onClick={() => setDetail(null)}
                className="rounded-lg border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50">Close</button>
            </div>
            <div className="space-y-4 px-5 py-4">
              {detail.mime?.startsWith("video/") ? (
                <video controls preload="metadata" className="w-full rounded-lg bg-slate-900"
                  src={absoluteUploadUrl(detail.download_url)} />
              ) : detail.mime?.startsWith("image/") ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img alt={detail.name} className="w-full rounded-lg border border-slate-200"
                  src={absoluteUploadUrl(detail.download_url)} />
              ) : null}
              <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1.5 text-sm">
                <dt className="text-slate-400">Size</dt><dd className="tabular-nums">{fmtBytes(detail.size_bytes)}</dd>
                <dt className="text-slate-400">Type</dt><dd>{detail.mime ?? "unknown"}</dd>
                <dt className="text-slate-400">Uploaded</dt><dd>{fmtDate(detail.uploaded_at)}</dd>
                <dt className="text-slate-400">Path</dt>
                <dd className="break-all font-mono text-[11px]">{detail.path}</dd>
                <dt className="text-slate-400">Status</dt>
                <dd><span className={`inline-flex rounded-md border px-2 py-0.5 text-xs font-medium ${STATUS_CHIP[detail.status].cls}`}>
                  {detail.status}</span></dd>
              </dl>
              {(detail.links.length > 0) && (
                <div className="space-y-2">
                  {detail.links.map((r, i) => (
                    <div key={i} className="rounded-lg border border-slate-200 px-3 py-2">
                      <div className="text-sm font-medium text-slate-900">{r.label}</div>
                      {(r.course_title || r.section_title) && (
                        <div className="text-xs text-slate-500">
                          {[r.course_title, r.section_title].filter(Boolean).join(" → ")}
                        </div>
                      )}
                      {r.admin_href && (
                        <a href={r.admin_href} className="text-xs text-indigo-600 hover:underline">Open in admin →</a>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {detail.candidate && (
                <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2">
                  <div className="text-sm font-medium text-slate-900">
                    Compressed candidate · −{detail.candidate.savings_pct}% vs original
                  </div>
                  <div className="text-xs text-slate-500">
                    Original: <span className="font-mono">{detail.candidate.parent_path.split("/").pop()}</span>
                  </div>
                  <div className="mt-1"><LinkChips links={detail.candidate.parent_links} /></div>
                  <div className="mt-2 flex gap-2">
                    <button onClick={() => void decide(detail.candidate!.id, "keep")} disabled={busy}
                      className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
                      Switch lesson to compressed
                    </button>
                    <button onClick={() => void decide(detail.candidate!.id, "discard")} disabled={busy}
                      className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs hover:bg-slate-50 disabled:opacity-50">
                      Keep original (discard candidate)
                    </button>
                  </div>
                  <p className="mt-1 text-[11px] text-slate-500">
                    Switching moves the original to trash — restorable (with a
                    revert-lesson option) until trash is emptied.
                  </p>
                </div>
              )}
            </div>
            <div className="mt-auto flex gap-2 border-t border-slate-200 px-5 py-3">
              <a href={absoluteUploadUrl(detail.download_url)} download
                 className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700">
                Download
              </a>
            </div>
          </aside>
        </div>
      )}

      {/* Empty-trash confirm */}
      {emptyOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-slate-900/50" onClick={() => setEmptyOpen(false)} />
          <div className="relative w-full max-w-md rounded-xl bg-white p-6 shadow-2xl">
            <h3 className="text-base font-semibold text-slate-900">
              Permanently delete {trash.length} file(s) ({confirmTarget})?
            </h3>
            <p className="mt-1 text-sm text-slate-500">
              This frees the space on the server and cannot be undone.
              {trash.some((t) => t.is_kept_candidate_original) &&
                " Lessons switched to compressed copies will lose their revert-to-original option."}
              {" "}Type <b>{confirmTarget}</b> to confirm.
            </p>
            <input value={confirmText} onChange={(e) => setConfirmText(e.target.value)}
              placeholder={confirmTarget}
              className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm"
              aria-label="Type the size to confirm" />
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setEmptyOpen(false)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50">Cancel</button>
              <button onClick={() => void doEmpty()}
                disabled={busy || confirmText.trim() !== confirmTarget}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-40">
                Empty trash
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
