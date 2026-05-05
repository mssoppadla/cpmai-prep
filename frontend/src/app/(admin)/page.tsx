"use client";
import Link from "next/link";

const CARDS = [
  { href: "/admin/questions",         title: "Questions",
    desc: "Author and edit the question bank with per-option reasoning." },
  { href: "/admin/exam-sets",         title: "Exam Sets",
    desc: "Curate sets and link questions for learners to attempt." },
  { href: "/admin/leads",             title: "Leads",
    desc: "View, annotate, and export marketing leads with UTM context." },
  { href: "/admin/settings",          title: "Runtime Settings",
    desc: "Daily chat limits, lockout thresholds, cache TTLs — no redeploy." },
  { href: "/admin/llm-providers",     title: "LLM Providers",
    desc: "Add or rotate AI model providers with encrypted API keys." },
  { href: "/admin/payment-providers", title: "Payment Providers",
    desc: "Configure Razorpay (or future gateways) at runtime — no redeploy." },
];

export default function AdminDashboard() {
  return (
    <div className="p-8">
      <header className="mb-8">
        <h1 className="text-2xl font-bold text-slate-900">Admin Console</h1>
        <p className="text-slate-600 mt-1 text-sm">
          Configure the platform without redeploying.
        </p>
      </header>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {CARDS.map(c => (
          <Link key={c.href} href={c.href}
                className="block bg-white border border-slate-200 rounded-xl p-5
                           hover:border-indigo-300 hover:shadow-sm transition">
            <div className="font-semibold text-slate-900">{c.title}</div>
            <div className="text-sm text-slate-600 mt-1">{c.desc}</div>
            <div className="mt-3 text-xs text-indigo-600 font-medium">Open →</div>
          </Link>
        ))}
      </div>
    </div>
  );
}
