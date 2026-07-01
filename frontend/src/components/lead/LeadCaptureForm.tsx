"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";

interface Props {
  source: "landing_hero" | "newsletter" | "exit_intent" | "gated_download" |
          "pricing_page" | "exam_preview" | "demo_request";
  cta?: string;
  fields?: Array<
    "name" | "phone" | "whatsapp" | "linkedin" | "company" | "role" | "target_exam_date"
  >;
  /** Helper copy under the LinkedIn field — admin-configurable via landing content. */
  linkedinReason?: string;
  /**
   * Where to send the visitor after a successful submit.
   * If null, the form just shows a "thanks" message in place.
   */
  postSubmitRoute?: string | null;
}

// Default reason shown under the LinkedIn field when landing content doesn't override it.
const LINKEDIN_REASON_DEFAULT =
  "So we can serve you better and share relevant prep documents";

const INPUT_CLS =
  "w-full px-4 py-3 text-base border border-slate-300 rounded-lg " +
  "focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 " +
  "outline-none transition placeholder:text-slate-400";

// Common dialing codes — extend as the audience grows.
const COUNTRY_CODES: Array<{ value: string; label: string }> = [
  { value: "+91",  label: "🇮🇳 India (+91)" },
  { value: "+1",   label: "🇺🇸 US / Canada (+1)" },
  { value: "+44",  label: "🇬🇧 UK (+44)" },
  { value: "+61",  label: "🇦🇺 Australia (+61)" },
  { value: "+65",  label: "🇸🇬 Singapore (+65)" },
  { value: "+971", label: "🇦🇪 UAE (+971)" },
  { value: "+49",  label: "🇩🇪 Germany (+49)" },
  { value: "+33",  label: "🇫🇷 France (+33)" },
  { value: "+81",  label: "🇯🇵 Japan (+81)" },
  { value: "+86",  label: "🇨🇳 China (+86)" },
  { value: "+27",  label: "🇿🇦 South Africa (+27)" },
];

export function LeadCaptureForm({
  source, cta = "Get started", fields = [], linkedinReason, postSubmitRoute,
}: Props) {
  const router = useRouter();
  const [state, setState] = useState<"idle" | "submitting" | "ok" | "err">("idle");
  const [form, setForm] = useState({
    email: "", name: "", phone: "",
    country_code: "+91",   // sensible default for the primary audience
    whatsapp_number: "",
    linkedin_id: "",
    company: "", role: "",
    target_exam_date: "", consent_marketing: false,
  });
  const [errMsg, setErrMsg] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setState("submitting");
    setErrMsg(null);
    const utm = readUtmFromUrl();
    // Strip empty-string optional fields so the backend's date / phone
    // validators don't 422 on them.
    const cleaned: Record<string, unknown> = { source, utm };
    for (const [k, v] of Object.entries(form)) {
      if (v === "" || v == null) continue;
      cleaned[k] = v;
    }
    cleaned.consent_marketing = form.consent_marketing;
    cleaned.landing_url = typeof window !== "undefined" ? window.location.href : "";
    try {
      const r = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/leads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(cleaned),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => null);
        setErrMsg(body?.error?.message ?? `HTTP ${r.status}`);
        setState("err");
        return;
      }
      setState("ok");
      // Route to the configured destination after a brief moment so the
      // user can read the confirmation. postSubmitRoute=null skips this.
      if (postSubmitRoute) {
        const dest = postSubmitRoute;
        setTimeout(() => { router.push(dest); }, 800);
      }
    } catch (e: unknown) {
      setErrMsg((e as Error)?.message ?? "Network error");
      setState("err");
    }
  }

  if (state === "ok") {
    return (
      <div role="status"
           className="p-4 bg-emerald-50 border border-emerald-200
                      rounded-lg text-emerald-800 text-sm">
        Thanks — {postSubmitRoute
          ? "taking you to the free practice now…"
          : "we'll be in touch shortly."}
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3" noValidate>
      <input
        required
        type="email"
        inputMode="email"
        autoComplete="email"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        placeholder="you@company.com"
        value={form.email}
        onChange={(e) => setForm({ ...form, email: e.target.value })}
        className={INPUT_CLS}
        aria-label="Email address"
      />
      {fields.includes("name") && (
        <input
          autoComplete="name"
          autoCapitalize="words"
          placeholder="Your name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          className={INPUT_CLS}
          aria-label="Your name"
        />
      )}
      {fields.includes("whatsapp") && (
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            WhatsApp number{" "}
            <span className="text-slate-500 font-normal">
              (join our community for prep tips)
            </span>
          </label>
          <div className="flex gap-2">
            <select
              value={form.country_code}
              onChange={(e) => setForm({ ...form, country_code: e.target.value })}
              className="px-3 py-3 text-base border border-slate-300 rounded-lg
                         focus:ring-2 focus:ring-indigo-500 outline-none w-40"
              aria-label="Country code"
            >
              {COUNTRY_CODES.map(c => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
            <input
              type="tel"
              inputMode="tel"
              autoComplete="tel-national"
              placeholder="98xxxxxxxx"
              value={form.whatsapp_number}
              onChange={(e) => setForm({ ...form, whatsapp_number: e.target.value })}
              className={INPUT_CLS + " flex-1"}
              aria-label="WhatsApp number"
            />
          </div>
        </div>
      )}
      {fields.includes("linkedin") && (
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            LinkedIn ID{" "}
            <span className="text-slate-500 font-normal">
              ({linkedinReason || LINKEDIN_REASON_DEFAULT})
            </span>
          </label>
          <input
            type="text"
            inputMode="url"
            autoComplete="off"
            placeholder="linkedin.com/in/your-id"
            value={form.linkedin_id}
            onChange={(e) => setForm({ ...form, linkedin_id: e.target.value })}
            className={INPUT_CLS}
            aria-label="LinkedIn ID"
          />
        </div>
      )}
      {fields.includes("phone") && (
        <input
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          placeholder="+91 98xxxxxxxx"
          value={form.phone}
          onChange={(e) => setForm({ ...form, phone: e.target.value })}
          className={INPUT_CLS}
          aria-label="Phone number"
        />
      )}
      {fields.includes("company") && (
        <input
          autoComplete="organization"
          placeholder="Company"
          value={form.company}
          onChange={(e) => setForm({ ...form, company: e.target.value })}
          className={INPUT_CLS}
          aria-label="Company"
        />
      )}
      {fields.includes("role") && (
        <input
          autoComplete="organization-title"
          placeholder="Role / job title"
          value={form.role}
          onChange={(e) => setForm({ ...form, role: e.target.value })}
          className={INPUT_CLS}
          aria-label="Role"
        />
      )}
      {fields.includes("target_exam_date") && (
        <div>
          <label htmlFor="target_exam_date"
                 className="block text-sm font-medium text-slate-600 mb-1">
            Target exam date (optional)
          </label>
          <input
            id="target_exam_date"
            type="date"
            value={form.target_exam_date}
            onChange={(e) => setForm({ ...form, target_exam_date: e.target.value })}
            className={INPUT_CLS}
          />
        </div>
      )}
      <label className="flex items-start gap-2 text-sm text-slate-600 cursor-pointer
                        py-1 select-none">
        <input
          type="checkbox"
          required
          checked={form.consent_marketing}
          onChange={(e) => setForm({ ...form, consent_marketing: e.target.checked })}
          className="mt-1 w-4 h-4 rounded border-slate-300
                     text-indigo-600 focus:ring-indigo-500"
        />
        <span className="leading-snug">
          I agree to receive product updates by email. We will never sell your data.
        </span>
      </label>
      <button
        type="submit"
        data-track="cta:lead_capture_submit"
        disabled={state === "submitting"}
        className="w-full min-h-[48px] bg-indigo-600 text-white px-6 py-3
                   text-base font-semibold rounded-lg
                   hover:bg-indigo-700 active:bg-indigo-800
                   disabled:opacity-60 disabled:cursor-not-allowed
                   transition-colors
                   focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500
                   focus-visible:ring-offset-2"
      >
        {state === "submitting" ? "Sending…" : cta}
      </button>
      {state === "err" && (
        <p role="alert" className="text-sm text-rose-600">
          {errMsg ?? "Something went wrong. Please try again."}
        </p>
      )}
    </form>
  );
}

function readUtmFromUrl() {
  if (typeof window === "undefined") return null;
  const p = new URLSearchParams(window.location.search);
  const utm = {
    source: p.get("utm_source"), medium: p.get("utm_medium"),
    campaign: p.get("utm_campaign"), term: p.get("utm_term"),
    content: p.get("utm_content"),
  };
  return Object.values(utm).some(Boolean) ? utm : null;
}
