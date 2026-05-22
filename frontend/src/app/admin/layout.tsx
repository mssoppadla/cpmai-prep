"use client";
import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { auth, ApiError } from "@/lib/api";
import type { UserOut } from "@/types/api";
import { SidebarGroup, type NavItem, itemIsActive } from "@/components/admin/SidebarGroup";

/**
 * Admin sidebar — grouped navigation.
 *
 * Layout rationale:
 * - Dashboard sits above all groups (always one click away)
 * - Three "daily-use" groups (Content, Learning, People) are expanded
 *   by default; less-used groups (Commerce, Assistant, System) start
 *   collapsed
 * - Expand/collapse state persists per-group to localStorage
 * - The group containing the currently-active URL force-expands so
 *   the user can always see where they are
 *
 * Phase 1 additions (not yet in this PR — will be added by their
 * respective feature PRs):
 * - Content group gains "Study Guide" (badge: NEW)
 * - Learning group gains "Courses" + "Live Sessions" (badge: NEW)
 * - A new "Marketing" group will appear with "Campaigns" + "Anonymous
 *   Traffic" when the Phase 1 Campaigns PR lands. Anonymous Traffic
 *   currently lives as a widget on the Contacts page; it gets its
 *   own sidebar entry only if/when it becomes a dedicated page.
 */

type NavGroupDef = {
  key: string;
  label: string;
  icon: string;
  defaultExpanded: boolean;
  items: NavItem[];
};

const DASHBOARD: NavItem = { href: "/admin", label: "Dashboard" };

const GROUPS: NavGroupDef[] = [
  {
    key: "content",
    label: "Content",
    icon: "📚",
    defaultExpanded: true,
    items: [
      { href: "/admin/content-pages", label: "Content Pages", badge: "NEW" },
      { href: "/admin/faqs",          label: "FAQs" },
      { href: "/admin/rag-sources",   label: "RAG Sources" },
    ],
  },
  {
    key: "learning",
    label: "Learning",
    icon: "🎓",
    defaultExpanded: true,
    items: [
      { href: "/admin/courses",        label: "Courses", badge: "NEW" },
      { href: "/admin/course-categories", label: "Course Categories" },
      { href: "/admin/sessions",       label: "Live Sessions", badge: "NEW" },
      { href: "/admin/exam-sets",      label: "Exam Sets" },
      { href: "/admin/questions",      label: "Questions" },
    ],
  },
  {
    key: "people",
    label: "People",
    icon: "👥",
    defaultExpanded: true,
    items: [
      { href: "/admin/users",                  label: "Users" },
      { href: "/admin/leads",                  label: "Contacts" },
      { href: "/admin/chat-history",           label: "Chat History" },
      { href: "/admin/chat-history/flagged",   label: "Flagged Turns", indent: true },
    ],
  },
  {
    key: "commerce",
    label: "Commerce",
    icon: "💰",
    defaultExpanded: false,
    items: [
      { href: "/admin/plans",       label: "Plans" },
      { href: "/admin/offer-codes", label: "Offer Codes" },
      { href: "/admin/pricing",     label: "Pricing & FX" },
    ],
  },
  {
    key: "assistant",
    label: "Assistant",
    icon: "🤖",
    defaultExpanded: false,
    items: [
      { href: "/admin/assistant-flow",  label: "Assistant Flow" },
      { href: "/admin/assistant-drift", label: "Assistant Drift" },
    ],
  },
  {
    key: "system",
    label: "System",
    icon: "⚙️",
    defaultExpanded: false,
    items: [
      { href: "/admin/settings",          label: "Runtime Settings" },
      { href: "/admin/llm-providers",     label: "LLM Providers" },
      { href: "/admin/payment-providers", label: "Payment Providers" },
      { href: "/admin/geoip",             label: "GeoIP" },
      { href: "/admin/observability",     label: "Observability", badge: "NEW" },
    ],
  },
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

  const dashboardActive = itemIsActive(DASHBOARD, pathname);

  return (
    <div className="min-h-screen flex bg-slate-50">
      <aside className="w-60 bg-white border-r border-slate-200 flex flex-col flex-shrink-0">
        <div className="p-4 border-b border-slate-200">
          <div className="font-bold text-slate-900">CPMAI Prep</div>
          <div className="text-xs text-slate-500">Admin Console</div>
        </div>
        <nav className="flex-1 p-2 space-y-1 overflow-y-auto">
          {/* Dashboard sits above groups — always one click away. */}
          <Link
            href={DASHBOARD.href}
            className={`block px-3 py-2 rounded text-sm ${
              dashboardActive
                ? "bg-indigo-50 text-indigo-700 font-medium"
                : "text-slate-600 hover:bg-slate-50"
            }`}
          >
            📊  {DASHBOARD.label}
          </Link>
          <div className="border-t border-slate-100 my-2" />
          {GROUPS.map((g) => (
            <SidebarGroup
              key={g.key}
              groupKey={g.key}
              label={g.label}
              icon={g.icon}
              items={g.items}
              pathname={pathname}
              defaultExpanded={g.defaultExpanded}
            />
          ))}
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
