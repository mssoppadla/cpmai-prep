"use client";
/**
 * Testimonials admin — CRUD for the landing-page carousel cards plus
 * the section-level knobs (show/hide, heading, rotation speed) that
 * live in runtime settings.
 *
 * Photo upload reuses the shared /admin/uploads endpoint (same as
 * lesson/course media); the stored photo_url is the relative
 * /uploads/... URL it returns.
 */
import { useEffect, useState } from "react";
import { admin, errMsg, absoluteUploadUrl } from "@/lib/api";
import type { TestimonialAdminOut, TestimonialIn } from "@/types/api";

const blank: TestimonialIn = {
  name: "", role: "", quote: "", photo_url: null, link_url: null,
  display_order: 100, is_active: true,
};

const SECTION_KEYS = {
  enabled:  "landing.testimonials_enabled",
  heading:  "landing.testimonials_heading",
  interval: "landing.testimonials_interval_ms",
} as const;

export default function TestimonialsAdminPage() {
  const [rows, setRows] = useState<TestimonialAdminOut[] | null>(null);
  const [editing, setEditing] = useState<TestimonialAdminOut | null>(null);
  const [form, setForm] = useState<TestimonialIn | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  // Section settings (runtime settings, saved separately from cards).
  const [section, setSection] = useState<{ enabled: boolean; heading: string; intervalSec: number } | null>(null);
  const [sectionBusy, setSectionBusy] = useState(false);
  const [sectionSaved, setSectionSaved] = useState(false);

  async function reload() {
    try { setRows(await admin.testimonials.list()); }
    catch (e) { console.error("[admin/testimonials] list", e); setErr(errMsg(e)); }
  }
  useEffect(() => {
    reload();
    (async () => {
      try {
        const all = await admin.settings.list();
        const byKey = new Map(all.map(r => [r.key, r.value]));
        const enabled = byKey.get(SECTION_KEYS.enabled);
        const heading = byKey.get(SECTION_KEYS.heading);
        const interval = byKey.get(SECTION_KEYS.interval);
        setSection({
          enabled: typeof enabled === "boolean" ? enabled : true,
          heading: typeof heading === "string" ? heading : "What our aspirants say",
          intervalSec: typeof interval === "number" ? Math.round(interval / 1000) : 6,
        });
      } catch (e) {
        console.error("[admin/testimonials] settings", e);
        // Card CRUD still works without the section card — leave it hidden.
      }
    })();
  }, []);

  async function saveSection() {
    if (!section) return;
    setSectionBusy(true); setSectionSaved(false); setErr(null);
    try {
      const intervalMs = Math.min(60, Math.max(2, Math.round(section.intervalSec))) * 1000;
      await admin.settings.update(SECTION_KEYS.enabled, section.enabled);
      await admin.settings.update(SECTION_KEYS.heading, section.heading.trim() || "What our aspirants say");
      await admin.settings.update(SECTION_KEYS.interval, intervalMs);
      setSection({ ...section, intervalSec: intervalMs / 1000 });
      setSectionSaved(true);
    } catch (e) { console.error("[admin/testimonials] section save", e); setErr(errMsg(e)); }
    finally { setSectionBusy(false); }
  }

  function startEdit(t: TestimonialAdminOut) {
    setEditing(t);
    setForm({
      name: t.name, role: t.role ?? "", quote: t.quote,
      photo_url: t.photo_url, link_url: t.link_url,
      display_order: t.display_order, is_active: t.is_active,
    });
  }
  function startNew() { setEditing(null); setForm({ ...blank }); }
  function cancel()   { setEditing(null); setForm(null); }

  async function uploadPhoto(file: File) {
    if (!form) return;
    setUploading(true); setErr(null);
    try {
      const uploaded = await admin.uploads.file(file);
      setForm({ ...form, photo_url: uploaded.url });
    } catch (e) { console.error("[admin/testimonials] upload", e); setErr(errMsg(e)); }
    finally { setUploading(false); }
  }

  async function save() {
    if (!form) return;
    setBusy(true); setErr(null);
    const payload: TestimonialIn = {
      ...form,
      role: form.role?.trim() ? form.role.trim() : null,
      link_url: form.link_url?.trim() ? form.link_url.trim() : null,
      photo_url: form.photo_url || null,
    };
    try {
      if (editing) await admin.testimonials.update(editing.id, payload);
      else         await admin.testimonials.create(payload);
      cancel(); await reload();
    } catch (e) { console.error("[admin/testimonials] save", e); setErr(errMsg(e)); }
    finally { setBusy(false); }
  }

  async function remove(id: number) {
    if (!confirm("Delete this testimonial?")) return;
    try { await admin.testimonials.delete(id); await reload(); }
    catch (e) { console.error("[admin/testimonials] delete", e); setErr(errMsg(e)); }
  }

  return (
    <div className="p-8 max-w-4xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Testimonials</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Cards in the landing-page carousel. Disabled rows are hidden
            but kept for history.
          </p>
        </div>
        {!form && (
          <button onClick={startNew}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700">
            + New testimonial
          </button>
        )}
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}

      {section && (
        <div className="bg-white rounded-xl border border-slate-200 p-5 mb-6">
          <h2 className="font-semibold text-slate-900 mb-3">Section settings</h2>
          <div className="grid sm:grid-cols-3 gap-4 items-end">
            <Field label="Heading">
              <input value={section.heading} maxLength={120}
                     onChange={(e) => setSection({ ...section, heading: e.target.value })}
                     className={cls} />
            </Field>
            <Field label="Auto-rotate every (seconds, 2–60)">
              <input type="number" min={2} max={60} value={section.intervalSec}
                     onChange={(e) => setSection({ ...section, intervalSec: Number(e.target.value) || 6 })}
                     className={cls} />
            </Field>
            <label className="flex items-center gap-2 text-sm text-slate-700 pb-2.5">
              <input type="checkbox" checked={section.enabled}
                     onChange={(e) => setSection({ ...section, enabled: e.target.checked })} />
              Show section on landing page
            </label>
          </div>
          <div className="flex items-center gap-3 mt-4">
            <button onClick={saveSection} disabled={sectionBusy}
              className="px-4 py-2 bg-white text-slate-700 text-sm font-medium border border-slate-300 rounded-lg hover:bg-slate-50 disabled:opacity-50">
              {sectionBusy ? "Saving…" : "Save section settings"}
            </button>
            {sectionSaved && <span className="text-sm text-emerald-600">Saved ✓</span>}
          </div>
        </div>
      )}

      {form && (
        <div className="bg-white rounded-xl border-2 border-indigo-200 p-6 mb-6">
          <h2 className="font-semibold text-slate-900 mb-4">
            {editing ? `Edit testimonial #${editing.id}` : "New testimonial"}
          </h2>

          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Name">
              <input value={form.name} maxLength={120}
                     onChange={(e) => setForm({ ...form, name: e.target.value })}
                     className={cls} placeholder="Sarah T." />
            </Field>
            <Field label="Role / title (optional)">
              <input value={form.role ?? ""} maxLength={160}
                     onChange={(e) => setForm({ ...form, role: e.target.value })}
                     className={cls} placeholder="AI Project Manager" />
            </Field>
          </div>
          <div className="mt-3" />
          <Field label="Quote">
            <textarea value={form.quote} rows={4} maxLength={2000}
                      onChange={(e) => setForm({ ...form, quote: e.target.value })}
                      className={cls} />
          </Field>
          <div className="mt-3" />
          <Field label="Proof link (LinkedIn recommendation, review site — optional)">
            <input value={form.link_url ?? ""} maxLength={1000}
                   onChange={(e) => setForm({ ...form, link_url: e.target.value })}
                   className={cls} placeholder="https://www.linkedin.com/in/…" />
          </Field>

          <div className="mt-3" />
          <Field label="Photo (optional)">
            {form.photo_url ? (
              <div className="flex items-center gap-3">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={absoluteUploadUrl(form.photo_url)} alt="Testimonial photo preview"
                     className="w-16 h-16 rounded-lg object-cover border border-slate-200" />
                <button type="button" onClick={() => setForm({ ...form, photo_url: null })}
                        className="text-xs text-rose-600 hover:underline">
                  Remove photo
                </button>
              </div>
            ) : (
              <label className="block border-2 border-dashed border-slate-300 rounded-lg p-4
                                text-center cursor-pointer text-sm text-slate-500
                                hover:border-indigo-400 hover:text-indigo-600 transition">
                <input type="file" accept="image/*" className="hidden"
                       onChange={(e) => {
                         const f = e.target.files?.[0];
                         if (f) void uploadPhoto(f);
                         e.target.value = "";
                       }} />
                {uploading ? "Uploading…" : "Click to upload a photo (JPG/PNG/WebP)"}
              </label>
            )}
          </Field>

          <div className="grid sm:grid-cols-2 gap-4 mt-3">
            <Field label="Display order (lower = earlier)">
              <input type="number" value={form.display_order}
                     onChange={(e) => setForm({ ...form, display_order: Number(e.target.value) })}
                     className={cls} />
            </Field>
            <label className="flex items-center gap-2 text-sm text-slate-700 mt-6">
              <input type="checkbox" checked={form.is_active}
                     onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
              Active (visible to public)
            </label>
          </div>

          <div className="flex items-center gap-3 mt-5">
            <button onClick={save} disabled={busy || uploading || !form.name.trim() || !form.quote.trim()}
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50">
              {busy ? "Saving…" : (editing ? "Save changes" : "Create")}
            </button>
            <button onClick={cancel}
              className="px-4 py-2 bg-white text-slate-700 text-sm font-medium border border-slate-300 rounded-lg hover:bg-slate-50">
              Cancel
            </button>
          </div>
        </div>
      )}

      {!rows ? <div className="text-slate-500">Loading…</div>
       : rows.length === 0 ? (
         <div className="bg-white rounded-xl border border-slate-200 p-12 text-center text-slate-500">
           No testimonials yet — click &quot;+ New testimonial&quot;.
         </div>
       ) : (
        <ul className="space-y-2">
          {rows.map(t => (
            <li key={t.id} className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="flex items-start gap-3">
                {t.photo_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={absoluteUploadUrl(t.photo_url)} alt=""
                       className="w-12 h-12 rounded-lg object-cover border border-slate-200 flex-shrink-0" />
                ) : (
                  <div className="w-12 h-12 rounded-lg bg-indigo-50 text-indigo-400 grid
                                  place-items-center font-bold flex-shrink-0">
                    {t.name.trim().charAt(0).toUpperCase()}
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-xs text-slate-500">#{t.display_order}</span>
                    {!t.is_active && (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">
                        hidden
                      </span>
                    )}
                  </div>
                  <div className="font-semibold text-slate-900">
                    {t.name}
                    {t.role && <span className="ml-2 text-xs font-normal text-indigo-600">{t.role}</span>}
                  </div>
                  <div className="text-sm text-slate-600 mt-1 line-clamp-2">{t.quote}</div>
                  {t.link_url && (
                    <a href={t.link_url} target="_blank" rel="noopener noreferrer"
                       className="text-xs text-indigo-600 hover:underline break-all">
                      {t.link_url}
                    </a>
                  )}
                </div>
                <div className="flex flex-col gap-1 flex-shrink-0">
                  <button onClick={() => startEdit(t)}
                    className="text-xs text-slate-700 hover:underline">Edit</button>
                  <button onClick={() => remove(t.id)}
                    className="text-xs text-rose-600 hover:underline">Delete</button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const cls = "w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none";
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-600 mb-1">{label}</label>
      {children}
    </div>
  );
}
