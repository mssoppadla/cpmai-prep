"use client";
/**
 * /admin/questions/bulk — upload many questions from an Excel sheet.
 *
 * Flow:
 *   1. Admin clicks "Download template" → fetches the canonical .xlsx
 *      with column headers, 3 example rows, and dropdown validations.
 *   2. Admin fills it in offline.
 *   3. Admin uploads the filled sheet here. Backend parses + validates
 *      per row, commits valid ones, returns errors for the rest.
 *   4. We surface created count + a per-row error table so the admin
 *      can fix only the broken rows in their sheet and re-upload.
 *
 * The single-question /admin/questions/new path is unchanged and still
 * the right tool for one-off authoring; this page is for batch import.
 */
import { useRef, useState } from "react";
import Link from "next/link";
import { admin, errMsg } from "@/lib/api";

interface UploadResult {
  created: number;
  created_ids: number[];
  errors: Array<{ row: number; field: string; message: string }>;
}

export default function BulkUploadQuestionsPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState<"download" | "upload" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);

  async function downloadTemplate() {
    setBusy("download"); setErr(null);
    try {
      const blob = await admin.questions.downloadBulkTemplate();
      // Trigger a browser save-as without leaving the page.
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "cpmai-questions-template.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("[bulk] template download", e); setErr(errMsg(e));
    } finally { setBusy(null); }
  }

  async function upload() {
    if (!file) return;
    setBusy("upload"); setErr(null); setResult(null);
    try {
      const r = await admin.questions.bulkUpload(file);
      setResult(r);
      // Reset the file input so re-uploading the same filename re-triggers change.
      if (fileInputRef.current) fileInputRef.current.value = "";
      setFile(null);
    } catch (e) {
      console.error("[bulk] upload", e); setErr(errMsg(e));
    } finally { setBusy(null); }
  }

  return (
    <div className="p-8 max-w-4xl">
      <Link href="/admin/questions"
            className="text-sm text-slate-500 hover:text-indigo-600">
        ← Back to questions
      </Link>
      <header className="mt-2 mb-6">
        <h1 className="text-2xl font-bold text-slate-900">
          Bulk upload questions
        </h1>
        <p className="text-slate-600 mt-1 text-sm">
          Import many questions at once from an Excel file. Per-row
          validation is identical to the single-question editor — failing
          rows come back with a row number + reason; valid rows are
          created. No partial-state risk: each row is its own savepoint.
        </p>
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}

      {/* Step 1 — template */}
      <section className="bg-white rounded-xl border border-slate-200 p-6 mb-4">
        <h2 className="font-semibold text-slate-900 mb-1">1. Download the template</h2>
        <p className="text-sm text-slate-600 mb-3">
          Fresh template with column headers, three pre-filled example
          rows (single-choice, multi-choice, minimal), and dropdown
          validations on{" "}
          <code className="bg-slate-100 px-1 rounded text-xs">topic_code</code>,{" "}
          <code className="bg-slate-100 px-1 rounded text-xs">difficulty</code>,{" "}
          <code className="bg-slate-100 px-1 rounded text-xs">question_type</code>,
          and every <code className="bg-slate-100 px-1 rounded text-xs">option_*_is_correct</code>.
        </p>
        <button onClick={downloadTemplate} disabled={busy !== null}
                className="px-4 py-2 bg-slate-700 text-white text-sm font-medium rounded-lg hover:bg-slate-800 disabled:opacity-50">
          {busy === "download" ? "Preparing…" : "Download template (.xlsx)"}
        </button>
      </section>

      {/* Step 2 — guidance */}
      <section className="bg-white rounded-xl border border-slate-200 p-6 mb-4">
        <h2 className="font-semibold text-slate-900 mb-2">2. Fill it in</h2>
        <ul className="text-sm text-slate-700 space-y-1.5 list-disc list-inside">
          <li><strong>One question per row.</strong> Headers are in row 1; first data row is row 2.</li>
          <li><strong>Required cells:</strong>{" "}
            <code className="text-xs bg-slate-100 px-1 rounded">stem</code>,{" "}
            <code className="text-xs bg-slate-100 px-1 rounded">topic_code</code> (BU, DU, DP, MD, EV, DE),{" "}
            <code className="text-xs bg-slate-100 px-1 rounded">difficulty</code> (easy / medium / hard),{" "}
            and at least <code className="text-xs bg-slate-100 px-1 rounded">option_a_*</code> +{" "}
            <code className="text-xs bg-slate-100 px-1 rounded">option_b_*</code>.
          </li>
          <li><strong>Correct answers:</strong> use the
            <code className="text-xs bg-slate-100 px-1 mx-1 rounded">option_X_is_correct</code>
            column for each option (true / false). Reasoning goes next to it.
          </li>
          <li><strong>Single-choice:</strong> exactly one option must be{" "}
            <code className="text-xs bg-slate-100 px-1 rounded">true</code>.{" "}
            <strong>Multi-choice:</strong> at least two must be true AND at least one false.
          </li>
          <li><strong>Limits:</strong> 5 MB file size, 500 rows per upload. Split larger imports into multiple files.</li>
        </ul>
      </section>

      {/* Step 3 — upload */}
      <section className="bg-white rounded-xl border border-slate-200 p-6 mb-4">
        <h2 className="font-semibold text-slate-900 mb-1">3. Upload the filled file</h2>
        <p className="text-sm text-slate-600 mb-3">
          Valid rows commit immediately. Failing rows come back with a
          row number and reason — fix in your sheet and re-upload.
        </p>
        <div className="flex flex-wrap gap-3 items-center">
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm"
          />
          <button onClick={upload}
                  disabled={!file || busy !== null}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50">
            {busy === "upload" ? "Uploading…" : "Upload"}
          </button>
        </div>
      </section>

      {/* Result */}
      {result && (
        <section className="bg-white rounded-xl border border-slate-200 p-6">
          <h2 className="font-semibold text-slate-900 mb-3">Result</h2>
          <div className="flex flex-wrap gap-3 mb-4">
            <span className="px-3 py-1 rounded-full text-sm font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
              ✓ {result.created} created
            </span>
            <span className={`px-3 py-1 rounded-full text-sm font-medium border ${
              result.errors.length === 0
                ? "bg-slate-50 text-slate-500 border-slate-200"
                : "bg-amber-50 text-amber-800 border-amber-300"
            }`}>
              {result.errors.length === 0 ? "no errors" : `${result.errors.length} error${result.errors.length === 1 ? "" : "s"}`}
            </span>
          </div>
          {result.created > 0 && (
            <p className="text-xs text-slate-500 mb-3">
              Created question IDs: <code className="text-xs">{result.created_ids.join(", ")}</code>
            </p>
          )}
          {result.errors.length > 0 && (
            <div className="border border-amber-200 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-amber-50 text-amber-800 text-xs uppercase">
                  <tr>
                    <th className="px-3 py-2 text-left">Row</th>
                    <th className="px-3 py-2 text-left">Field</th>
                    <th className="px-3 py-2 text-left">Message</th>
                  </tr>
                </thead>
                <tbody>
                  {result.errors.map((e, i) => (
                    <tr key={i} className="border-t border-amber-100">
                      <td className="px-3 py-2 font-mono text-slate-900">{e.row}</td>
                      <td className="px-3 py-2 text-slate-600">{e.field}</td>
                      <td className="px-3 py-2 text-slate-700">{e.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
