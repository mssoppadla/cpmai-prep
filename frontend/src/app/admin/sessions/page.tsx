"use client";
/**
 * /admin/sessions — Zoom session scheduling for admins.
 *
 * Two views: list (table of sessions) and editor (inline panel that
 * either creates a new session or edits an existing one).
 *
 * Lifecycle context: when admin saves a session, the backend tries
 * to push it to Zoom immediately if Zoom credentials are configured
 * in /admin/settings. Otherwise it saves as "draft" and the admin
 * can click "Publish" later. The status column makes this state
 * visible at a glance.
 *
 * host_config field-by-field UX:
 *   * Toggles use a consistent two-column layout: left = label +
 *     short rationale ("learners can unmute their mic"), right = the
 *     toggle. Defaults are PERMISSIVE — admin flips restrictions.
 *   * chat_mode + screen_share_mode are radio groups (3 options each)
 *     rendered as buttons; the chosen one highlights.
 *
 * Course picker: optional. Pulls from existing admin.lms.listCourses.
 * Standalone sessions (course_id=null) are valid — they appear on
 * /sessions for any user with an active subscription.
 */
import { useCallback, useEffect, useState } from "react";
import { admin, errMsg } from "@/lib/api";
import type {
  ZoomSessionAdminOut, ZoomSessionCreateIn, HostConfig, CourseOut,
} from "@/types/api";
import { DEFAULT_HOST_CONFIG } from "@/types/api";


// ──────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────
function fmtDateTime(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    dateStyle: "medium", timeStyle: "short",
  });
}

/** Convert a JS Date to the value `<input type="datetime-local">` wants
 *  (YYYY-MM-DDTHH:MM in LOCAL time, no timezone). */
function toLocalInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function statusBadge(status: string) {
  const map: Record<string, string> = {
    draft:     "bg-slate-100 text-slate-700 border-slate-200",
    scheduled: "bg-indigo-50 text-indigo-700 border-indigo-200",
    live:      "bg-emerald-50 text-emerald-700 border-emerald-200",
    ended:     "bg-slate-100 text-slate-500 border-slate-200",
    cancelled: "bg-rose-50 text-rose-700 border-rose-200",
  };
  return (
    <span className={`px-2 py-0.5 text-xs rounded border ${map[status] ?? map.draft}`}>
      {status}
    </span>
  );
}

interface DraftForm {
  id?: number;
  title: string;
  description: string;
  scheduled_at_local: string;     // YYYY-MM-DDTHH:MM in local TZ
  duration_minutes: number;
  course_id: number | null;
  host_config: HostConfig;
}

function emptyForm(): DraftForm {
  // Default schedule = tomorrow 10:00 local
  const t = new Date();
  t.setDate(t.getDate() + 1);
  t.setHours(10, 0, 0, 0);
  return {
    title: "",
    description: "",
    scheduled_at_local: toLocalInputValue(t),
    duration_minutes: 60,
    course_id: null,
    host_config: { ...DEFAULT_HOST_CONFIG },
  };
}

function rowToForm(s: ZoomSessionAdminOut): DraftForm {
  return {
    id: s.id,
    title: s.title,
    description: s.description ?? "",
    scheduled_at_local: toLocalInputValue(new Date(s.scheduled_at)),
    duration_minutes: s.duration_minutes,
    course_id: s.course_id,
    host_config: { ...DEFAULT_HOST_CONFIG, ...s.host_config },
  };
}


// ──────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────
export default function AdminSessionsPage() {
  const [rows, setRows] = useState<ZoomSessionAdminOut[] | null>(null);
  const [courses, setCourses] = useState<CourseOut[]>([]);
  const [editing, setEditing] = useState<DraftForm | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try { setRows(await admin.zoom.listSessions({ limit: 200 })); }
    catch (e) { setErr(errMsg(e)); }
  }, []);
  useEffect(() => { void reload(); }, [reload]);
  // Courses for the picker — best-effort; if it fails we still let
  // admin save standalone sessions.
  useEffect(() => {
    admin.lms.listCourses(true)
      .then((cs) => setCourses(cs))
      .catch((e) => console.error("[sessions] courses load failed", e));
  }, []);

  async function save() {
    if (!editing) return;
    if (editing.title.trim().length < 2) {
      setErr("Title must be at least 2 characters."); return;
    }
    setBusy(true); setErr(null);
    // Convert local datetime string → ISO with TZ offset
    const scheduled_at = new Date(editing.scheduled_at_local).toISOString();
    const payload: ZoomSessionCreateIn = {
      title: editing.title.trim(),
      description: editing.description.trim() || null,
      scheduled_at,
      duration_minutes: editing.duration_minutes,
      course_id: editing.course_id,
      host_config: editing.host_config,
    };
    try {
      if (editing.id) {
        await admin.zoom.updateSession(editing.id, payload);
      } else {
        await admin.zoom.createSession(payload);
      }
      setEditing(null);
      await reload();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  async function publish(id: number) {
    setBusy(true); setErr(null);
    try {
      await admin.zoom.publishSession(id);
      await reload();
    } catch (e) { setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  async function remove(id: number) {
    if (!confirm("Cancel this session? Removes it from learners and from Zoom.")) return;
    try {
      await admin.zoom.deleteSession(id);
      await reload();
    } catch (e) { setErr(errMsg(e)); }
  }

  return (
    <div className="p-8 max-w-6xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Live Sessions</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Schedule and manage Zoom live sessions. Sessions in &ldquo;draft&rdquo;
            state need Zoom credentials configured in{" "}
            <a href="/admin/settings" className="text-indigo-600 hover:underline">
              /admin/settings
            </a>{" "}
            (keys: <code className="text-xs">zoom.sdk_key</code>,{" "}
            <code className="text-xs">zoom.sdk_secret</code>,{" "}
            <code className="text-xs">zoom.oauth_client_*</code>,{" "}
            <code className="text-xs">zoom.host_email</code>).
          </p>
        </div>
        {!editing && (
          <button onClick={() => setEditing(emptyForm())}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700">
            + New session
          </button>
        )}
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}

      {editing && (
        <SessionEditor
          form={editing}
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
          No sessions yet. Click <strong>+ New session</strong> to schedule one.
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-left">
              <tr>
                <th className="px-4 py-3 font-medium">Title</th>
                <th className="px-4 py-3 font-medium">When</th>
                <th className="px-4 py-3 font-medium">Duration</th>
                <th className="px-4 py-3 font-medium">Course</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const course = courses.find((c) => c.id === s.course_id);
                return (
                  <tr key={s.id} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-900">{s.title}</div>
                      {s.description && (
                        <div className="text-xs text-slate-500 truncate max-w-xs">{s.description}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-700">{fmtDateTime(s.scheduled_at)}</td>
                    <td className="px-4 py-3 text-slate-700">{s.duration_minutes}m</td>
                    <td className="px-4 py-3 text-slate-700">
                      {course ? course.title : <span className="text-slate-400">Standalone</span>}
                    </td>
                    <td className="px-4 py-3">{statusBadge(s.status)}</td>
                    <td className="px-4 py-3 text-right">
                      {s.status === "draft" && (
                        <button onClick={() => publish(s.id)} disabled={busy}
                                className="text-emerald-700 hover:underline text-xs mr-3">
                          Publish to Zoom
                        </button>
                      )}
                      <button onClick={() => setEditing(rowToForm(s))}
                              className="text-indigo-600 hover:underline text-xs mr-3">
                        Edit
                      </button>
                      <button onClick={() => remove(s.id)}
                              className="text-rose-600 hover:underline text-xs">
                        Cancel
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


// ──────────────────────────────────────────────────────────────────────
// SessionEditor — inline panel for create / edit
// ──────────────────────────────────────────────────────────────────────
function SessionEditor({
  form, courses, busy, onChange, onSave, onCancel,
}: {
  form: DraftForm;
  courses: CourseOut[];
  busy: boolean;
  onChange: (f: DraftForm) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const editingExisting = form.id !== undefined;
  const cfg = form.host_config;
  const upd = (patch: Partial<DraftForm>) => onChange({ ...form, ...patch });
  const updCfg = (patch: Partial<HostConfig>) =>
    onChange({ ...form, host_config: { ...cfg, ...patch } });

  return (
    <div className="bg-white rounded-xl border-2 border-indigo-200 p-6 mb-6 space-y-5">
      <h2 className="font-semibold text-slate-900 text-lg">
        {editingExisting ? `Edit session #${form.id}` : "Schedule a new session"}
      </h2>

      <div className="grid sm:grid-cols-2 gap-4">
        <Field label="Title" required>
          <input value={form.title}
                 onChange={(e) => upd({ title: e.target.value })}
                 placeholder="Week 1: Risk Frameworks"
                 className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
        </Field>
        <Field label="Course (optional)">
          <select value={form.course_id ?? ""}
                  onChange={(e) => upd({ course_id: e.target.value ? Number(e.target.value) : null })}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white">
            <option value="">— Standalone (any subscriber can join) —</option>
            {courses.map((c) => (
              <option key={c.id} value={c.id}>{c.title}</option>
            ))}
          </select>
        </Field>
      </div>

      <Field label="Description (optional)">
        <textarea value={form.description}
                  onChange={(e) => upd({ description: e.target.value })}
                  rows={2}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
      </Field>

      <div className="grid sm:grid-cols-2 gap-4">
        <Field label="Scheduled at" required>
          <input type="datetime-local"
                 value={form.scheduled_at_local}
                 onChange={(e) => upd({ scheduled_at_local: e.target.value })}
                 className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
        </Field>
        <Field label="Duration (minutes)" required>
          <input type="number" min={10} max={480}
                 value={form.duration_minutes}
                 onChange={(e) => upd({ duration_minutes: Number(e.target.value) })}
                 className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm" />
        </Field>
      </div>

      {/* ─────────────── Host config ─────────────── */}
      <div className="border-t border-slate-200 pt-4">
        <h3 className="font-semibold text-slate-900 mb-1">Participant controls</h3>
        <p className="text-xs text-slate-500 mb-4">
          These are enforced by the embedded Web SDK + Zoom server-side.
          Defaults are permissive — flip what you want to restrict.
        </p>

        <div className="space-y-3">
          <ToggleRow
            label="Mute all on entry"
            description="Everyone joins muted. Reduces echo at the start of the session."
            value={cfg.mute_on_entry}
            onChange={(v) => updCfg({ mute_on_entry: v })}
          />
          <ToggleRow
            label="Allow learners to unmute themselves"
            description="If off, only the host can unmute a learner — useful for strict lectures."
            value={cfg.allow_self_unmute}
            onChange={(v) => updCfg({ allow_self_unmute: v })}
          />
          <ToggleRow
            label="Allow learner camera toggle"
            description="If off, the camera button is disabled for learners. Useful for low-bandwidth lectures."
            value={cfg.allow_video_toggle}
            onChange={(v) => updCfg({ allow_video_toggle: v })}
          />
          <ToggleRow
            label="Waiting room"
            description="Hold learners in a waiting room until you admit them."
            value={cfg.waiting_room}
            onChange={(v) => updCfg({ waiting_room: v })}
          />
          <ToggleRow
            label="Auto-record to cloud"
            description="Zoom records to the cloud automatically; our system archives the MP4 once Zoom processes it."
            value={cfg.auto_record}
            onChange={(v) => updCfg({ auto_record: v })}
          />

          <div>
            <div className="text-sm font-medium text-slate-900 mb-1">Chat mode</div>
            <div className="flex gap-2">
              {(["open", "admin_only", "off"] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() => updCfg({ chat_mode: mode })}
                  className={`px-3 py-1.5 text-xs rounded-lg border ${
                    cfg.chat_mode === mode
                      ? "bg-indigo-600 text-white border-indigo-600"
                      : "bg-white text-slate-700 border-slate-300 hover:bg-slate-50"
                  }`}
                >
                  {mode === "open" ? "Open chat" :
                   mode === "admin_only" ? "Admin-only (DMs to host)" :
                   "Chat off"}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="text-sm font-medium text-slate-900 mb-1">Screen share</div>
            <div className="flex gap-2">
              {(["approval", "all_users", "host_only"] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() => updCfg({ screen_share_mode: mode })}
                  className={`px-3 py-1.5 text-xs rounded-lg border ${
                    cfg.screen_share_mode === mode
                      ? "bg-indigo-600 text-white border-indigo-600"
                      : "bg-white text-slate-700 border-slate-300 hover:bg-slate-50"
                  }`}
                >
                  {mode === "approval" ? "Learner requests, admin approves" :
                   mode === "all_users" ? "Anyone can share" :
                   "Host only"}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="flex gap-2 pt-2">
        <button onClick={onSave} disabled={busy}
                className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:bg-slate-300">
          {busy ? "Saving…" : editingExisting ? "Save changes" : "Schedule session"}
        </button>
        <button onClick={onCancel}
                className="px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50">
          Cancel
        </button>
      </div>
    </div>
  );
}

function Field({ label, required, children }: {
  label: string; required?: boolean; children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-700 mb-1">
        {label}{required && <span className="text-rose-500 ml-0.5">*</span>}
      </label>
      {children}
    </div>
  );
}

function ToggleRow({ label, description, value, onChange }: {
  label: string; description: string;
  value: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex-1">
        <div className="text-sm font-medium text-slate-900">{label}</div>
        <div className="text-xs text-slate-500">{description}</div>
      </div>
      <button
        type="button"
        onClick={() => onChange(!value)}
        className={`mt-1 inline-flex h-6 w-11 items-center rounded-full transition ${
          value ? "bg-indigo-600" : "bg-slate-300"
        }`}
        role="switch" aria-checked={value} aria-label={label}
      >
        <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition ${
          value ? "translate-x-6" : "translate-x-1"
        }`} />
      </button>
    </div>
  );
}
