"use client";
/**
 * Media library picker — choose an ALREADY-UPLOADED file (video or any
 * attachment) for a lesson instead of uploading it again.
 *
 * Picking shares the same server file: no copy is made, so a video used
 * by three lessons costs one upload of disk. The storage dashboard's
 * link scan sees every lesson that references the path, so the file
 * stays "linked" (never trashable) while any lesson uses it.
 *
 * Data comes from /admin/storage/files (the same listing the storage
 * dashboard uses) filtered by kind server-side; search, "unused only"
 * and the preview are client-side.
 */
import { useEffect, useMemo, useState } from "react";
import { admin, errMsg } from "@/lib/api";
import type { StorageFileOut } from "@/types/api";

export type MediaKind = "video" | "image" | "document" | "any";

function fmtBytes(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${n} B`;
}

/** "Course › Lesson" for every place the file is used, deduped. */
export function usedIn(f: StorageFileOut): string[] {
  const seen = new Set<string>();
  for (const l of f.links) {
    const where = [l.course_title, l.section_title, l.label].filter(Boolean).join(" › ");
    if (where) seen.add(where);
  }
  return Array.from(seen);
}

export function MediaLibraryPicker({
  kind, title, onPick, onClose, excludePath,
}: {
  kind: MediaKind;
  title?: string;
  onPick: (file: StorageFileOut) => void;
  onClose: () => void;
  /** Hide the file currently attached (already in use here). */
  excludePath?: string | null;
}) {
  const [items, setItems] = useState<StorageFileOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [unusedOnly, setUnusedOnly] = useState(false);
  const [preview, setPreview] = useState<StorageFileOut | null>(null);

  useEffect(() => {
    let alive = true;
    admin.storage.files({ kind: kind === "any" ? undefined : kind })
      .then((rows) => { if (alive) setItems(rows); })
      .catch((e) => { if (alive) setErr(errMsg(e)); });
    return () => { alive = false; };
  }, [kind]);

  const rows = useMemo(() => {
    if (!items) return [];
    const needle = q.trim().toLowerCase();
    return items
      .filter((f) => f.status !== "system" && f.status !== "candidate")
      .filter((f) => !excludePath || f.path !== excludePath)
      .filter((f) => !unusedOnly || f.links.length === 0)
      .filter((f) => !needle
        || f.name.toLowerCase().includes(needle)
        || usedIn(f).some((w) => w.toLowerCase().includes(needle)))
      .sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at));
  }, [items, q, unusedOnly, excludePath]);

  const heading = title ?? (kind === "video" ? "Choose a video from the library" : "Choose a file from the library");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={heading}>
      <div className="absolute inset-0 bg-slate-900/60" onClick={onClose} />
      <div className="relative w-full max-w-3xl rounded-xl bg-white p-5 flex flex-col gap-3 max-h-[85vh]">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-semibold text-slate-900">{heading}</h3>
          <button onClick={onClose}
                  className="px-3 py-1 text-sm border border-slate-300 rounded-lg hover:bg-slate-50">Close</button>
        </div>
        <p className="text-xs text-slate-500">
          Picking a file <strong>shares</strong> it with this lesson — nothing is copied,
          and it keeps working everywhere else it is used.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="Search by file name or course / lesson…"
                 aria-label="Search library"
                 className="flex-1 min-w-[200px] px-3 py-2 border border-slate-300 rounded-lg text-sm" />
          <label className="flex items-center gap-2 text-xs text-slate-700">
            <input type="checkbox" checked={unusedOnly} onChange={(e) => setUnusedOnly(e.target.checked)} />
            Unused only
          </label>
        </div>

        {err && <p className="text-xs text-rose-600">{err}</p>}
        <div className="overflow-y-auto -mx-1 px-1 min-h-[160px]">
          {items === null && !err ? (
            <p className="text-sm text-slate-500 py-8 text-center">Loading library…</p>
          ) : rows.length === 0 ? (
            <p className="text-sm text-slate-500 py-8 text-center">
              {items && items.length > 0 ? "No files match." : "No uploaded files yet."}
            </p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {rows.map((f) => {
                const where = usedIn(f);
                const isPreviewing = preview?.path === f.path;
                return (
                  <li key={f.path} className="py-2.5">
                    <div className="flex items-start gap-3">
                      {f.mime?.startsWith("image/") ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={f.download_url} alt="" className="w-14 h-10 object-cover rounded shrink-0 bg-slate-100" />
                      ) : (
                        <span className="w-14 h-10 rounded shrink-0 bg-slate-100 grid place-items-center text-slate-500 text-lg" aria-hidden="true">
                          {f.mime?.startsWith("video/") ? "▶" : "📄"}
                        </span>
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium text-slate-900 truncate" title={f.path}>{f.name}</div>
                        <div className="text-xs text-slate-500">
                          {fmtBytes(f.size_bytes)} · {new Date(f.uploaded_at).toLocaleDateString()}
                          {" · "}
                          {where.length === 0
                            ? <span className="text-amber-700">not used anywhere</span>
                            : <span>used in {where.length}: {where.slice(0, 2).join("; ")}{where.length > 2 ? "; …" : ""}</span>}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {(f.mime?.startsWith("video/") || f.mime?.startsWith("audio/") || f.mime === "application/pdf") && (
                          <button type="button"
                                  onClick={() => setPreview(isPreviewing ? null : f)}
                                  className="px-2 py-1 text-xs border border-slate-300 rounded-lg hover:bg-slate-50">
                            {isPreviewing ? "Hide" : "Preview"}
                          </button>
                        )}
                        <button type="button" onClick={() => onPick(f)}
                                className="px-3 py-1 text-xs font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700">
                          Use this file
                        </button>
                      </div>
                    </div>
                    {isPreviewing && (
                      <div className="mt-2 rounded-lg overflow-hidden bg-black">
                        {f.mime?.startsWith("video/") ? (
                          <video src={f.download_url} controls preload="metadata" className="w-full max-h-72" />
                        ) : f.mime?.startsWith("audio/") ? (
                          <audio src={f.download_url} controls preload="metadata" className="w-full bg-white" />
                        ) : (
                          <iframe src={f.download_url} title={f.name} className="w-full h-72 bg-white" />
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
