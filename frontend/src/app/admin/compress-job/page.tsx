"use client";
/**
 * /admin/compress-job — popup window for re-compressing an EXISTING
 * uploaded video (Option 1.A, chosen 2026-09).
 *
 * Opened from the lesson editor's "Compress…" link with
 * ?lesson_id=&path=. Runs the browser encoder in its own window so the
 * admin keeps working in the main tab (encoding runs at ~1× playback
 * speed — an hour-long lecture takes about an hour; this window must
 * stay open).
 *
 * The output NEVER replaces the original automatically: it is uploaded
 * and registered as a pending CANDIDATE. The keep/discard decision
 * (side-by-side compare) lives in /admin/storage; keeping it switches
 * the lesson and moves the original to restorable trash.
 */
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { absoluteUploadUrl, admin, errMsg } from "@/lib/api";
import VideoCompressDialog from "@/components/lms/VideoCompressDialog";

function CompressJobInner() {
  const params = useSearchParams();
  const lessonId = Number(params.get("lesson_id") || "");
  const path = params.get("path") || "";

  const [file, setFile] = useState<File | null>(null);
  const [state, setState] = useState<"loading" | "encoding" | "uploading" | "done" | "error" | "cancelled">("loading");
  const [err, setErr] = useState<string | null>(null);
  const [candidateId, setCandidateId] = useState<number | null>(null);

  useEffect(() => {
    if (!path.startsWith("/uploads/")) {
      setErr("Missing or invalid video path."); setState("error"); return;
    }
    (async () => {
      try {
        const r = await fetch(absoluteUploadUrl(path));
        if (!r.ok) throw new Error(`Could not fetch the stored video (HTTP ${r.status})`);
        const blob = await r.blob();
        const name = (path.split("/").pop() ?? "video").split("?")[0];
        setFile(new File([blob], name, { type: blob.type || "video/mp4" }));
        setState("encoding");
      } catch (e) { setErr(errMsg(e)); setState("error"); }
    })();
  }, [path]);

  async function onCompressed(f: File) {
    setState("uploading"); setErr(null);
    try {
      const uploaded = await admin.uploads.file(f);
      const res = await admin.storage.createCandidate({
        parent_path: path,
        candidate_path: uploaded.url,
        lesson_id: Number.isFinite(lessonId) && lessonId > 0 ? lessonId : null,
      });
      setCandidateId(res.id);
      setState("done");
    } catch (e) { setErr(errMsg(e)); setState("error"); }
  }

  return (
    <div className="min-h-screen bg-slate-50 p-6">
      <div className="mx-auto max-w-3xl space-y-4">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Re-compress video</h1>
          <p className="text-sm text-slate-500">
            <code className="font-mono text-xs">{path.split("/").pop()}</code> —
            keep this window open until encoding finishes; you can keep working
            in the main tab. The result becomes a candidate — nothing switches
            until you compare and decide in Storage.
          </p>
        </div>

        {state === "loading" && (
          <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
            Fetching the stored video…
          </div>
        )}
        {state === "uploading" && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-8 text-center text-sm text-amber-800">
            Uploading the compressed candidate…
          </div>
        )}
        {state === "done" && (
          <div className="space-y-3 rounded-xl border border-emerald-200 bg-emerald-50 p-6 text-sm text-emerald-900">
            <p className="font-medium">✓ Candidate created — the lesson still serves the original.</p>
            <p>
              Compare both versions and choose which one the lesson serves
              from the Storage dashboard. Switching moves the original to
              restorable trash.
            </p>
            <div className="flex gap-2">
              <a href="/admin/storage"
                 className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700">
                Open Storage → Compressed candidates
              </a>
              <button onClick={() => window.close()}
                      className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm hover:bg-slate-50">
                Close window
              </button>
            </div>
            {candidateId != null && (
              <p className="text-xs text-emerald-700">Candidate #{candidateId}</p>
            )}
          </div>
        )}
        {state === "cancelled" && (
          <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
            Compression cancelled — nothing was changed. You can close this window.
          </div>
        )}
        {err && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{err}</div>
        )}

        {state === "encoding" && file && (
          <VideoCompressDialog
            file={file}
            titleOverride="Re-compress existing video"
            onUseCompressed={(f) => void onCompressed(f)}
            onUseOriginal={() => setState("cancelled")}
            onCancel={() => setState("cancelled")}
          />
        )}
      </div>
    </div>
  );
}

export default function CompressJobPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-slate-500">Loading…</div>}>
      <CompressJobInner />
    </Suspense>
  );
}
