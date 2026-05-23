"use client";
/**
 * /admin/campaigns — manage AI-content automation workflows.
 *
 * Two views: list (table of campaigns) and editor (inline panel
 * that creates/edits one).
 *
 * Workflow types come from GET /admin/campaigns/workflows so adding
 * a new runner on the backend (registered in WORKFLOWS) makes it
 * available here without a frontend code change.
 *
 * config_json fields render based on the workflow's config_schema —
 * the v1 renderer handles `string`, `number`, `select`, and
 * `course_picker` field types.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { admin, errMsg } from "@/lib/api";
import type {
  CampaignCreateIn, CampaignOut, CampaignRunOut,
  CourseOut, WorkflowMetaOut, WorkflowType,
} from "@/types/api";


// Common cron presets for non-cron-savvy admins.
const CRON_PRESETS = [
  { label: "Daily 9am UTC",  cron: "0 9 * * *" },
  { label: "Daily 6pm UTC",  cron: "0 18 * * *" },
  { label: "Weekly Mon 10am UTC", cron: "0 10 * * 1" },
  { label: "Weekly Fri 4pm UTC",  cron: "0 16 * * 5" },
  { label: "Hourly",         cron: "0 * * * *" },
  { label: "Manual only (no schedule)", cron: "" },
];


function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "short", timeStyle: "short",
  });
}

function statusBadge(active: boolean) {
  return active
    ? <span className="px-2 py-0.5 text-xs rounded border bg-emerald-50 text-emerald-700 border-emerald-200">active</span>
    : <span className="px-2 py-0.5 text-xs rounded border bg-slate-100 text-slate-700 border-slate-200">paused</span>;
}

function workflowLabel(type: WorkflowType, workflows: WorkflowMetaOut[]): string {
  const meta = workflows.find((w) => w.workflow_type === type);
  return meta?.label ?? type;
}


interface DraftForm {
  id?: number;
  name: string;
  description: string;
  workflow_type: WorkflowType;
  schedule_cron: string;
  config_json: Record<string, unknown>;
  active: boolean;
}


function emptyForm(workflows: WorkflowMetaOut[]): DraftForm {
  // Default to first workflow + populate defaults from its schema.
  const w = workflows[0];
  return {
    name: "",
    description: "",
    workflow_type: w?.workflow_type ?? "weekly_content",
    schedule_cron: "0 9 * * *",
    config_json: defaultsFromSchema(w?.config_schema),
    active: true,
  };
}


function defaultsFromSchema(schema: Record<string, unknown> | undefined): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (!schema) return out;
  for (const [key, def] of Object.entries(schema)) {
    if (typeof def === "object" && def !== null && "default" in (def as Record<string, unknown>)) {
      out[key] = (def as Record<string, unknown>).default;
    }
  }
  return out;
}


function rowToForm(c: CampaignOut): DraftForm {
  return {
    id: c.id,
    name: c.name,
    description: c.description ?? "",
    workflow_type: c.workflow_type,
    schedule_cron: c.schedule_cron ?? "",
    config_json: c.config_json ?? {},
    active: c.active,
  };
}


export default function AdminCampaignsPage() {
  const [rows, setRows] = useState<CampaignOut[] | null>(null);
  const [workflows, setWorkflows] = useState<WorkflowMetaOut[]>([]);
  const [courses, setCourses] = useState<CourseOut[]>([]);
  const [editing, setEditing] = useState<DraftForm | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try { setRows(await admin.social.listCampaigns()); }
    catch (e) { setErr(errMsg(e)); }
  }, []);
  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    admin.social.listWorkflows()
      .then(setWorkflows)
      .catch((e) => console.error("[campaigns] workflows load", e));
    admin.lms.listCourses(true)
      .then(setCourses)
      .catch((e) => console.error("[campaigns] courses load", e));
  }, []);

  async function save() {
    if (!editing) return;
    if (editing.name.trim().length < 2) {
      setErr("Name must be at least 2 characters."); return;
    }
    setBusy(true); setErr(null);
    const payload: CampaignCreateIn = {
      name: editing.name.trim(),
      description: editing.description.trim() || null,
      workflow_type: editing.workflow_type,
      schedule_cron: editing.schedule_cron.trim() || null,
      config_json: editing.config_json,
      active: editing.active,
    };
    try {
      if (editing.id) {
        await admin.social.updateCampaign(editing.id, payload);
      } else {
        await admin.social.createCampaign(payload);
      }
      setEditing(null);
      await reload();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  async function runNow(id: number) {
    setBusy(true); setErr(null);
    try {
      const run = await admin.social.runCampaignNow(id);
      // Show preview of generated content inline
      if (run.status === "done") {
        alert(`Generated content (preview):\n\n${run.generated_content?.slice(0, 500) || "(empty)"}`);
      } else {
        alert(`Run status: ${run.status}\n${run.error?.slice(0, 500) || ""}`);
      }
      await reload();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  async function remove(id: number) {
    if (!confirm("Delete this campaign? Past runs are preserved.")) return;
    try {
      await admin.social.deleteCampaign(id);
      await reload();
    } catch (e) { setErr(errMsg(e)); }
  }

  return (
    <div className="p-8 max-w-6xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Campaigns</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Schedule AI-generated content. Output lands in the{" "}
            <Link href="/admin/social-queue" className="text-indigo-600 hover:underline">
              social queue
            </Link>{" "}
            where you copy + paste to your platforms.
          </p>
        </div>
        {!editing && workflows.length > 0 && (
          <button onClick={() => setEditing(emptyForm(workflows))}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700">
            + New campaign
          </button>
        )}
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}

      {editing && (
        <CampaignEditor
          form={editing}
          workflows={workflows}
          courses={courses}
          busy={busy}
          onChange={setEditing}
          onSave={save}
          onCancel={() => { setEditing(null); setErr(null); }}
        />
      )}

      {rows === null ? (
        <div className="text-slate-500 text-sm">Loading…</div>
      ) : rows.length === 0 && !editing ? (
        <div className="bg-white border border-slate-200 rounded-xl p-8 text-center text-slate-500">
          No campaigns yet. Click <strong>+ New campaign</strong> to schedule your first AI-content workflow.
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-left">
              <tr>
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Workflow</th>
                <th className="px-4 py-3 font-medium">Schedule</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Updated</th>
                <th className="px-4 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{c.name}</div>
                    {c.description && (
                      <div className="text-xs text-slate-500 truncate max-w-xs">{c.description}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-700">{workflowLabel(c.workflow_type, workflows)}</td>
                  <td className="px-4 py-3">
                    {c.schedule_cron
                      ? <code className="text-xs bg-slate-100 px-1.5 py-0.5 rounded">{c.schedule_cron}</code>
                      : <span className="text-slate-400 text-xs">manual</span>}
                  </td>
                  <td className="px-4 py-3">{statusBadge(c.active)}</td>
                  <td className="px-4 py-3 text-slate-600 text-xs">{fmtDateTime(c.updated_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <button onClick={() => runNow(c.id)} disabled={busy}
                            className="text-emerald-700 hover:underline text-xs mr-3 disabled:opacity-50">
                      Run now
                    </button>
                    <button onClick={() => setEditing(rowToForm(c))}
                            className="text-indigo-600 hover:underline text-xs mr-3">
                      Edit
                    </button>
                    <button onClick={() => remove(c.id)}
                            className="text-rose-600 hover:underline text-xs">
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


// ──────────────────────────────────────────────────────────────────────
// CampaignEditor
// ──────────────────────────────────────────────────────────────────────
function CampaignEditor({
  form, workflows, courses, busy, onChange, onSave, onCancel,
}: {
  form: DraftForm;
  workflows: WorkflowMetaOut[];
  courses: CourseOut[];
  busy: boolean;
  onChange: (f: DraftForm) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const isExisting = form.id !== undefined;
  const upd = (patch: Partial<DraftForm>) => onChange({ ...form, ...patch });

  const currentWorkflow = workflows.find((w) => w.workflow_type === form.workflow_type);
  const schema = (currentWorkflow?.config_schema ?? {}) as Record<string, Record<string, unknown>>;

  return (
    <div className="bg-white rounded-xl border-2 border-indigo-200 p-6 mb-6 space-y-5">
      <h2 className="font-semibold text-slate-900 text-lg">
        {isExisting ? `Edit campaign #${form.id}` : "New campaign"}
      </h2>

      <div className="grid sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-slate-700 mb-1">
            Name <span className="text-rose-500">*</span>
          </label>
          <input value={form.name}
                 onChange={(e) => upd({ name: e.target.value })}
                 placeholder="Weekly LinkedIn post"
                 className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-700 mb-1">Workflow type</label>
          <select value={form.workflow_type}
                  onChange={(e) => {
                    const wt = e.target.value as WorkflowType;
                    const w = workflows.find((x) => x.workflow_type === wt);
                    upd({
                      workflow_type: wt,
                      config_json: defaultsFromSchema(w?.config_schema),
                    });
                  }}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white">
            {workflows.map((w) => (
              <option key={w.workflow_type} value={w.workflow_type}>{w.label}</option>
            ))}
          </select>
          {currentWorkflow && (
            <p className="text-xs text-slate-500 mt-1">{currentWorkflow.description}</p>
          )}
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-700 mb-1">Description (optional)</label>
        <textarea value={form.description} rows={2}
                  onChange={(e) => upd({ description: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
      </div>

      {/* Schedule */}
      <div>
        <label className="block text-xs font-medium text-slate-700 mb-1">Schedule</label>
        <div className="flex gap-2 flex-wrap mb-2">
          {CRON_PRESETS.map((p) => (
            <button key={p.label}
                    onClick={() => upd({ schedule_cron: p.cron })}
                    className={`px-2 py-1 text-xs rounded border ${
                      form.schedule_cron === p.cron
                        ? "bg-indigo-600 text-white border-indigo-600"
                        : "bg-white text-slate-700 border-slate-300 hover:bg-slate-50"
                    }`}>
              {p.label}
            </button>
          ))}
        </div>
        <input value={form.schedule_cron}
               onChange={(e) => upd({ schedule_cron: e.target.value })}
               placeholder="cron expression (or leave blank for manual-only)"
               className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono" />
        <p className="text-xs text-slate-500 mt-1">
          5-field cron in UTC. Blank = manual-run only (you trigger via the &ldquo;Run now&rdquo; button).
        </p>
      </div>

      {/* Workflow-specific config */}
      <div className="border-t border-slate-200 pt-4">
        <h3 className="font-semibold text-slate-900 mb-3">Workflow config</h3>
        <ConfigEditor
          schema={schema}
          value={form.config_json}
          courses={courses}
          onChange={(cfg) => upd({ config_json: cfg })}
        />
      </div>

      {/* Active toggle */}
      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input type="checkbox" checked={form.active}
               onChange={(e) => upd({ active: e.target.checked })} />
        Active (paused campaigns don&apos;t fire on schedule but can still &ldquo;Run now&rdquo;)
      </label>

      <div className="flex gap-2 pt-2">
        <button onClick={onSave} disabled={busy}
                className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:bg-slate-300">
          {busy ? "Saving…" : isExisting ? "Save changes" : "Create campaign"}
        </button>
        <button onClick={onCancel}
                className="px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50">
          Cancel
        </button>
      </div>
    </div>
  );
}


// ──────────────────────────────────────────────────────────────────────
// ConfigEditor — renders fields from a workflow's config_schema
// ──────────────────────────────────────────────────────────────────────
function ConfigEditor({
  schema, value, courses, onChange,
}: {
  schema: Record<string, Record<string, unknown>>;
  value: Record<string, unknown>;
  courses: CourseOut[];
  onChange: (v: Record<string, unknown>) => void;
}) {
  const set = (key: string, v: unknown) => onChange({ ...value, [key]: v });

  return (
    <div className="space-y-3">
      {Object.entries(schema).map(([key, def]) => {
        const type = String(def.type ?? "string");
        const required = !!def.required;
        const placeholder = String(def.placeholder ?? "");
        const cur = value[key];

        const labelEl = (
          <label className="block text-xs font-medium text-slate-700 mb-1">
            {key} {required && <span className="text-rose-500">*</span>}
          </label>
        );

        if (type === "number") {
          return (
            <div key={key}>
              {labelEl}
              <input type="number"
                     min={Number(def.min ?? -Infinity)}
                     max={Number(def.max ?? Infinity)}
                     value={typeof cur === "number" ? cur : (def.default as number) ?? 0}
                     onChange={(e) => set(key, Number(e.target.value))}
                     className="w-32 px-3 py-2 border border-slate-300 rounded-lg text-sm" />
            </div>
          );
        }
        if (type === "select") {
          const opts = (def.options as string[]) ?? [];
          return (
            <div key={key}>
              {labelEl}
              <select value={typeof cur === "string" ? cur : opts[0] ?? ""}
                      onChange={(e) => set(key, e.target.value)}
                      className="px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white">
                {opts.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
          );
        }
        if (type === "course_picker") {
          return (
            <div key={key}>
              {labelEl}
              <select value={typeof cur === "number" ? String(cur) : ""}
                      onChange={(e) => set(key, e.target.value ? Number(e.target.value) : null)}
                      className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white">
                <option value="">— Any course —</option>
                {courses.map((c) => (
                  <option key={c.id} value={c.id}>{c.title}</option>
                ))}
              </select>
            </div>
          );
        }
        // string fallback
        return (
          <div key={key}>
            {labelEl}
            <textarea value={typeof cur === "string" ? cur : ""}
                      onChange={(e) => set(key, e.target.value)}
                      placeholder={placeholder}
                      rows={key === "prompt" ? 3 : 1}
                      className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
          </div>
        );
      })}
    </div>
  );
}
