"use client";
/**
 * Live-class banner admin — a purpose-built editor for the
 * landing.live_banner_* runtime settings (the generic /admin/settings
 * page can edit the same keys, but raw JSON inputs are hostile for
 * color/font/animation knobs). Includes a live preview rendered with
 * the exact same component the public landing page uses.
 */
import { useEffect, useState } from "react";
import { admin, errMsg } from "@/lib/api";
import { LiveClassBanner } from "@/components/landing/LiveClassBanner";

const KEYS = {
  enabled:    "landing.live_banner_enabled",
  text:       "landing.live_banner_text",
  link_url:   "landing.live_banner_link_url",
  link_label: "landing.live_banner_link_label",
  font_size:  "landing.live_banner_font_size",
  font_style: "landing.live_banner_font_style",
  font_color: "landing.live_banner_font_color",
  bg_color:   "landing.live_banner_bg_color",
  animation:  "landing.live_banner_animation",
  link_enabled:        "landing.live_banner_link_enabled",
  link_bg_color:       "landing.live_banner_link_bg_color",
  link_text_color:     "landing.live_banner_link_text_color",
  ondemand_enabled:    "landing.live_banner_ondemand_enabled",
  ondemand_label:      "landing.live_banner_ondemand_label",
  ondemand_url:        "landing.live_banner_ondemand_url",
  ondemand_bg_color:   "landing.live_banner_ondemand_bg_color",
  ondemand_text_color: "landing.live_banner_ondemand_text_color",
} as const;

type BannerForm = {
  enabled: boolean;
  text: string;
  link_url: string;
  link_label: string;
  font_size: number;
  font_style: "normal" | "italic" | "bold" | "bold-italic";
  font_color: string;
  bg_color: string;
  animation: "none" | "pulse" | "blink";
  link_enabled: boolean;
  /** Empty string = automatic color pairing. */
  link_bg_color: string;
  link_text_color: string;
  ondemand_enabled: boolean;
  ondemand_label: string;
  ondemand_url: string;
  ondemand_bg_color: string;
  ondemand_text_color: string;
};

const DEFAULTS: BannerForm = {
  enabled: false,
  text: "Live CPMAI exam-prep classes are open — reserve your seat!",
  link_url: "",
  link_label: "Register now",
  font_size: 16,
  font_style: "normal",
  font_color: "#312e81",
  bg_color: "#e0e7ff",
  animation: "none",
  link_enabled: true,
  link_bg_color: "",
  link_text_color: "",
  ondemand_enabled: false,
  ondemand_label: "Request on-demand training",
  ondemand_url: "",
  ondemand_bg_color: "",
  ondemand_text_color: "",
};

export default function LandingBannerAdminPage() {
  const [form, setForm] = useState<BannerForm | null>(null);
  const [initial, setInitial] = useState<BannerForm | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const rows = await admin.settings.list();
        const byKey = new Map(rows.map(r => [r.key, r.value]));
        const loaded: BannerForm = {
          enabled:    typeof byKey.get(KEYS.enabled) === "boolean"
                        ? byKey.get(KEYS.enabled) as boolean : DEFAULTS.enabled,
          text:       str(byKey.get(KEYS.text), DEFAULTS.text),
          link_url:   str(byKey.get(KEYS.link_url), DEFAULTS.link_url),
          link_label: str(byKey.get(KEYS.link_label), DEFAULTS.link_label),
          font_size:  num(byKey.get(KEYS.font_size), DEFAULTS.font_size),
          font_style: pick(byKey.get(KEYS.font_style),
                           ["normal", "italic", "bold", "bold-italic"] as const,
                           DEFAULTS.font_style),
          font_color: str(byKey.get(KEYS.font_color), DEFAULTS.font_color),
          bg_color:   str(byKey.get(KEYS.bg_color), DEFAULTS.bg_color),
          animation:  pick(byKey.get(KEYS.animation),
                           ["none", "pulse", "blink"] as const,
                           DEFAULTS.animation),
          link_enabled: typeof byKey.get(KEYS.link_enabled) === "boolean"
                          ? byKey.get(KEYS.link_enabled) as boolean
                          : DEFAULTS.link_enabled,
          link_bg_color:   str(byKey.get(KEYS.link_bg_color), DEFAULTS.link_bg_color),
          link_text_color: str(byKey.get(KEYS.link_text_color), DEFAULTS.link_text_color),
          ondemand_enabled: typeof byKey.get(KEYS.ondemand_enabled) === "boolean"
                              ? byKey.get(KEYS.ondemand_enabled) as boolean
                              : DEFAULTS.ondemand_enabled,
          ondemand_label: str(byKey.get(KEYS.ondemand_label), DEFAULTS.ondemand_label),
          ondemand_url:   str(byKey.get(KEYS.ondemand_url), DEFAULTS.ondemand_url),
          ondemand_bg_color:   str(byKey.get(KEYS.ondemand_bg_color), DEFAULTS.ondemand_bg_color),
          ondemand_text_color: str(byKey.get(KEYS.ondemand_text_color), DEFAULTS.ondemand_text_color),
        };
        setForm(loaded); setInitial(loaded);
      } catch (e) {
        console.error("[admin/landing-banner] load", e);
        setErr(errMsg(e));
        setForm({ ...DEFAULTS }); setInitial(null);
      }
    })();
  }, []);

  async function save() {
    if (!form) return;
    setBusy(true); setErr(null); setSavedAt(null);
    const values: Record<keyof BannerForm, unknown> = {
      enabled: form.enabled,
      text: form.text.trim(),
      link_url: form.link_url.trim(),
      link_label: form.link_label.trim(),
      font_size: clamp(form.font_size, 10, 48),
      font_style: form.font_style,
      font_color: form.font_color,
      bg_color: form.bg_color,
      animation: form.animation,
      link_enabled: form.link_enabled,
      link_bg_color: form.link_bg_color,
      link_text_color: form.link_text_color,
      ondemand_enabled: form.ondemand_enabled,
      ondemand_label: form.ondemand_label.trim() || DEFAULTS.ondemand_label,
      ondemand_url: form.ondemand_url.trim(),
      ondemand_bg_color: form.ondemand_bg_color,
      ondemand_text_color: form.ondemand_text_color,
    };
    try {
      for (const field of Object.keys(KEYS) as Array<keyof BannerForm>) {
        // Only PATCH what changed — keeps the audit log readable.
        if (initial && values[field] === initial[field]) continue;
        await admin.settings.update(KEYS[field], values[field]);
      }
      const saved = values as BannerForm;
      setInitial(saved); setForm(saved);
      setSavedAt(Date.now());
    } catch (e) {
      console.error("[admin/landing-banner] save", e);
      setErr(errMsg(e));
    } finally { setBusy(false); }
  }

  if (!form) return <div className="p-8 text-slate-500">Loading…</div>;

  return (
    <div className="p-8 max-w-3xl">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Live Class Banner</h1>
        <p className="text-slate-600 mt-1 text-sm">
          Announcement shown on the landing page directly under the hero
          subtitle — point aspirants at your live-class registration link
          (calendar invite / Zoom registration).
        </p>
      </header>

      {err && (
        <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}

      {/* Live preview — same component the public page renders. */}
      <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 mb-6">
        <div className="text-xs font-medium text-slate-500 mb-1">
          Preview{!form.enabled && " (banner is currently disabled on the site)"}
        </div>
        <LiveClassBanner landing={{
          live_banner_enabled: true,
          live_banner_text: form.text || DEFAULTS.text,
          live_banner_link_url: form.link_url,
          live_banner_link_label: form.link_label,
          live_banner_font_size: form.font_size,
          live_banner_font_style: form.font_style,
          live_banner_font_color: form.font_color,
          live_banner_bg_color: form.bg_color,
          live_banner_animation: form.animation,
          live_banner_link_enabled: form.link_enabled,
          live_banner_link_bg_color: form.link_bg_color,
          live_banner_link_text_color: form.link_text_color,
          live_banner_ondemand_enabled: form.ondemand_enabled,
          live_banner_ondemand_label: form.ondemand_label,
          live_banner_ondemand_url: form.ondemand_url,
          live_banner_ondemand_bg_color: form.ondemand_bg_color,
          live_banner_ondemand_text_color: form.ondemand_text_color,
        }} />
      </div>

      <div className="bg-white rounded-xl border border-slate-200 p-6 space-y-4">
        <label className="flex items-center gap-2 text-sm font-medium text-slate-800">
          <input type="checkbox" checked={form.enabled}
                 onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
          Show the banner on the landing page
        </label>

        <Field label="Announcement text">
          <textarea value={form.text} rows={2} maxLength={300}
                    onChange={(e) => setForm({ ...form, text: e.target.value })}
                    className={cls} />
        </Field>

        {/* ── Button 1: live-class registration ─────────────────── */}
        <div className="border border-slate-200 rounded-lg p-4 space-y-3">
          <label className="flex items-center gap-2 text-sm font-medium text-slate-800">
            <input type="checkbox" checked={form.link_enabled}
                   onChange={(e) => setForm({ ...form, link_enabled: e.target.checked })} />
            Show the registration button
          </label>
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Registration link (calendar / Zoom URL)">
              <input value={form.link_url} placeholder="https://zoom.us/meeting/register/…"
                     onChange={(e) => setForm({ ...form, link_url: e.target.value })}
                     className={cls} />
            </Field>
            <Field label="Button label">
              <input value={form.link_label} maxLength={60}
                     onChange={(e) => setForm({ ...form, link_label: e.target.value })}
                     className={cls} />
            </Field>
          </div>
          <AutoColorPair
            bg={form.link_bg_color} text={form.link_text_color}
            autoHint="Automatic = banner text color as background, banner background as label — always readable."
            onChange={(bg, text) => setForm({ ...form, link_bg_color: bg, link_text_color: text })} />
        </div>

        {/* ── Button 2: on-demand training request ──────────────── */}
        <div className="border border-slate-200 rounded-lg p-4 space-y-3">
          <label className="flex items-center gap-2 text-sm font-medium text-slate-800">
            <input type="checkbox" checked={form.ondemand_enabled}
                   onChange={(e) => setForm({ ...form, ondemand_enabled: e.target.checked })} />
            Show an on-demand training request button
          </label>
          <p className="text-xs text-slate-500 -mt-1">
            Second button for aspirants who want custom training — point it
            at a Google Form that collects their requirements.
          </p>
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Request form link (Google Form URL)">
              <input value={form.ondemand_url} placeholder="https://forms.gle/…"
                     onChange={(e) => setForm({ ...form, ondemand_url: e.target.value })}
                     className={cls} />
            </Field>
            <Field label="Button label">
              <input value={form.ondemand_label} maxLength={60}
                     onChange={(e) => setForm({ ...form, ondemand_label: e.target.value })}
                     className={cls} />
            </Field>
          </div>
          <AutoColorPair
            bg={form.ondemand_bg_color} text={form.ondemand_text_color}
            autoHint="Automatic = white background with the banner text color as label + border (outline style)."
            onChange={(bg, text) => setForm({ ...form, ondemand_bg_color: bg, ondemand_text_color: text })} />
        </div>

        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Font size (px)">
            <div className="flex items-center gap-2">
              <button type="button" aria-label="Decrease font size"
                      onClick={() => setForm({ ...form, font_size: clamp(form.font_size - 1, 10, 48) })}
                      className={stepBtn}>−</button>
              <input type="number" min={10} max={48} value={form.font_size}
                     onChange={(e) => setForm({ ...form, font_size: clamp(Number(e.target.value) || 16, 10, 48) })}
                     className={`${cls} text-center`} />
              <button type="button" aria-label="Increase font size"
                      onClick={() => setForm({ ...form, font_size: clamp(form.font_size + 1, 10, 48) })}
                      className={stepBtn}>+</button>
            </div>
          </Field>
          <Field label="Font style">
            <select value={form.font_style}
                    onChange={(e) => setForm({ ...form, font_style: e.target.value as BannerForm["font_style"] })}
                    className={cls}>
              <option value="normal">Normal</option>
              <option value="bold">Bold</option>
              <option value="italic">Italic</option>
              <option value="bold-italic">Bold italic</option>
            </select>
          </Field>
        </div>

        <div className="grid sm:grid-cols-2 gap-4">
          <ColorField label="Text color" value={form.font_color}
                      onChange={(v) => setForm({ ...form, font_color: v })} />
          <ColorField label="Background color" value={form.bg_color}
                      onChange={(v) => setForm({ ...form, bg_color: v })} />
        </div>

        <Field label="Attention animation">
          <select value={form.animation}
                  onChange={(e) => setForm({ ...form, animation: e.target.value as BannerForm["animation"] })}
                  className={cls}>
            <option value="none">None</option>
            <option value="pulse">Pulse (gentle fade)</option>
            <option value="blink">Blink (hard on/off)</option>
          </select>
          <p className="text-xs text-slate-500 mt-1">
            Visitors with &ldquo;reduce motion&rdquo; enabled in their OS never
            see the animation.
          </p>
        </Field>

        <div className="flex items-center gap-3 pt-2">
          <button onClick={save} disabled={busy}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50">
            {busy ? "Saving…" : "Save banner"}
          </button>
          {savedAt && <span className="text-sm text-emerald-600">Saved ✓</span>}
        </div>
      </div>
    </div>
  );
}

// ----------------------------------------------------------- helpers

function str(v: unknown, fallback: string): string {
  return typeof v === "string" ? v : fallback;
}
function num(v: unknown, fallback: number): number {
  return typeof v === "number" && Number.isFinite(v) ? v : fallback;
}
function pick<T extends string>(v: unknown, options: readonly T[], fallback: T): T {
  return options.includes(v as T) ? (v as T) : fallback;
}
function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, Math.round(v)));
}

const cls = "w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none";
const stepBtn = "w-9 h-9 flex-shrink-0 grid place-items-center border border-slate-300 rounded-lg text-slate-700 hover:bg-slate-50 text-lg font-medium";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-600 mb-1">{label}</label>
      {children}
    </div>
  );
}

/** Button color pair with an "automatic" mode (stored as empty
 *  strings — the banner derives a contrasting pairing itself). */
function AutoColorPair({ bg, text, autoHint, onChange }: {
  bg: string; text: string; autoHint: string;
  onChange: (bg: string, text: string) => void;
}) {
  const isAuto = bg === "" && text === "";
  return (
    <div>
      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input type="checkbox" checked={isAuto}
               onChange={(e) => onChange(
                 e.target.checked ? "" : "#312e81",
                 e.target.checked ? "" : "#ffffff")} />
        Automatic button colors
      </label>
      <p className="text-xs text-slate-500 mt-0.5">{autoHint}</p>
      {!isAuto && (
        <div className="grid sm:grid-cols-2 gap-4 mt-2">
          <ColorField label="Button background" value={bg || "#312e81"}
                      onChange={(v) => onChange(v, text || "#ffffff")} />
          <ColorField label="Button label color" value={text || "#ffffff"}
                      onChange={(v) => onChange(bg || "#312e81", v)} />
        </div>
      )}
    </div>
  );
}

function ColorField({ label, value, onChange }: {
  label: string; value: string; onChange: (v: string) => void;
}) {
  return (
    <Field label={label}>
      <div className="flex items-center gap-2">
        <input type="color" value={normalizeHex(value)}
               onChange={(e) => onChange(e.target.value)}
               aria-label={`${label} picker`}
               className="w-10 h-9 p-0.5 border border-slate-300 rounded-lg cursor-pointer" />
        <input value={value} maxLength={7} placeholder="#312e81"
               onChange={(e) => onChange(e.target.value)}
               className={cls} />
      </div>
    </Field>
  );
}

/** <input type="color"> only accepts #RRGGBB — expand #RGB shorthand. */
function normalizeHex(v: string): string {
  if (/^#[0-9a-fA-F]{3}$/.test(v)) {
    return "#" + v.slice(1).split("").map(c => c + c).join("");
  }
  return /^#[0-9a-fA-F]{6}$/.test(v) ? v : "#000000";
}
