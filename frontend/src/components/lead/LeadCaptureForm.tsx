"use client";
import { useState } from "react";

interface Props {
  source: "landing_hero" | "newsletter" | "exit_intent" | "gated_download" |
          "pricing_page" | "exam_preview" | "demo_request";
  cta?: string;
  fields?: Array<"name" | "phone" | "company" | "role" | "target_exam_date">;
}

// All inputs use these classes — text-base = 16px on mobile (no iOS zoom),
// py-3 = 48px touch height on Android, well over Apple's 44px minimum.
const INPUT_CLS =
  "w-full px-4 py-3 text-base border border-slate-300 rounded-lg " +
  "focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 " +
  "outline-none transition placeholder:text-slate-400";

export function LeadCaptureForm({ source, cta = "Get started", fields = [] }: Props) {
  const [state, setState] = useState<"idle" | "submitting" | "ok" | "err">("idle");
  const [form, setForm] = useState({
    email: "", name: "", phone: "", company: "", role: "",
    target_exam_date: "", consent_marketing: false,
  });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setState("submitting");
    const utm = readUtmFromUrl();
    try {
      const r = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/leads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          ...form, source, utm,
          landing_url: typeof window !== "undefined" ? window.location.href : "",
        }),
      });
      setState(r.ok ? "ok" : "err");
    } catch {
      setState("err");
    }
  }

  if (state === "ok") {
    return (
      <div role="status"
           className="p-4 bg-emerald-50 border border-emerald-200
                      rounded-lg text-emerald-800 text-sm">
        Thanks — we'll be in touch shortly.
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
          Something went wrong. Please try again.
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
