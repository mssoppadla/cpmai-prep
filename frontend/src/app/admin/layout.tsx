"use client";
import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { auth, ApiError } from "@/lib/api";
import type { UserOut } from "@/types/api";

const NAV = [
  { href: "/admin",                    label: "Dashboard" },
  { href: "/admin/users",              label: "Users" },
  { href: "/admin/questions",          label: "Questions" },
  { href: "/admin/exam-sets",          label: "Exam Sets" },
  { href: "/admin/plans",              label: "Plans" },
  { href: "/admin/offer-codes",        label: "Offer Codes" },
  { href: "/admin/leads",              label: "Contacts" },
  { href: "/admin/faqs",               label: "FAQs" },
  { href: "/admin/settings",           label: "Runtime Settings" },
  { href: "/admin/llm-providers",      label: "LLM Providers" },
  { href: "/admin/payment-providers",  label: "Payment Providers" },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<UserOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await auth.me();
        if (cancelled) return;
        if (!["admin", "super_admin"].includes(me.role)) {
          // Regular users get bounced to their own dashboard, not the
          // marketing landing page.
          router.replace("/dashboard");
          return;
        }
        setUser(me);
      } catch (e) {
        if (cancelled) return;
        // Try refreshing the token first
        const ok = await auth.refresh();
        if (ok) {
          try { setUser(await auth.me()); return; } catch {}
        }
        setError((e as ApiError)?.body?.message ?? "Sign in required");
        setTimeout(() => router.replace("/login"), 800);
      }
    })();
    return () => { cancelled = true; };
  }, [router]);

  if (error) {
    return <div className="p-8 text-rose-600">{error}</div>;
  }
  if (!user) {
    return <div className="p-8 text-slate-500">Checking access…</div>;
  }

  return (
    <div className="min-h-screen flex bg-slate-50">
      <aside className="w-60 bg-white border-r border-slate-200 flex flex-col flex-shrink-0">
        <div className="p-4 border-b border-slate-200">
          <div className="font-bold text-slate-900">CPMAI Prep</div>
          <div className="text-xs text-slate-500">Admin Console</div>
        </div>
        <nav className="flex-1 p-2 space-y-0.5 overflow-y-auto">
          {NAV.map(n => {
            const active = pathname === n.href ||
                           (n.href !== "/admin" && pathname.startsWith(n.href));
            return (
              <Link key={n.href} href={n.href}
                    className={`block px-3 py-2 rounded text-sm ${
                      active ? "bg-indigo-50 text-indigo-700 font-medium"
                             : "text-slate-600 hover:bg-slate-50"}`}>
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="p-3 border-t border-slate-200 text-xs text-slate-500">
          <div className="font-medium text-slate-700 truncate">{user.email}</div>
          <div className="capitalize">{user.role.replace("_", " ")}</div>
          <button onClick={async () => { await auth.logout(); router.push("/"); }}
                  className="mt-2 text-indigo-600 hover:underline">
            Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  );
}
