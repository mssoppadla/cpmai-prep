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
      { href: "/admin/landing-banner", label: "Live Class Banner", badge: "NEW" },
      { href: "/admin/testimonials",  label: "Testimonials", badge: "NEW" },
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
      { href: "/admin/user-insights",          label: "User Insights", badge: "NEW" },
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
      { href: "/admin/payments",    label: "Payments", badge: "NEW" },
      { href: "/admin/offer-codes", label: "Offer Codes" },
      { href: "/admin/pricing",     label: "Pricing & FX" },
    ],
  },
  {
    key: "marketing",
    label: "Marketing",
    icon: "📣",
    defaultExpanded: false,
    items: [
      { href: "/admin/campaigns",       label: "Campaigns", badge: "NEW" },
      { href: "/admin/social-queue",    label: "Social queue", badge: "NEW" },
      { href: "/admin/email-automations", label: "Email Automations", badge: "NEW" },
      { href: "/admin/email-templates", label: "Email Templates" },
      { href: "/admin/leads",           label: "Contacts (also in People)", indent: true },
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
  // Mobile nav drawer. The sidebar is a persistent rail on desktop (lg+)
  // but an off-canvas drawer on phones/tablets so the content gets the
  // full width instead of being squeezed (which clipped wide tables).
  const [navOpen, setNavOpen] = useState(false);

  // Close the drawer whenever the route changes, so tapping a nav item
  // navigates AND dismisses the overlay in one go.
  useEffect(() => { setNavOpen(false); }, [pathname]);

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
      {/* Mobile top bar — only on < lg. Holds the hamburger so the nav
          drawer can be opened; the persistent sidebar is hidden here. */}
      <div className="lg:hidden fixed top-0 inset-x-0 z-30 h-14 bg-white border-b border-slate-200 flex items-center gap-2 px-3">
        <button
          onClick={() => setNavOpen(true)}
          aria-label="Open admin menu"
          className="p-2 rounded-md text-slate-700 hover:bg-slate-100"
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               strokeWidth="2" strokeLinecap="round">
            <line x1="4" y1="7" x2="20" y2="7" /><line x1="4" y1="12" x2="20" y2="12" /><line x1="4" y1="17" x2="20" y2="17" />
          </svg>
        </button>
        <span className="font-bold text-slate-900">CPMAI Prep</span>
        <span className="text-xs text-slate-400">Admin</span>
      </div>

      {/* Backdrop behind the drawer (mobile only, when open). */}
      {navOpen && (
        <div className="lg:hidden fixed inset-0 z-40 bg-slate-900/50"
             onClick={() => setNavOpen(false)} aria-hidden />
      )}

      <aside className={`bg-white border-r border-slate-200 flex flex-col
                         fixed inset-y-0 left-0 z-50 w-64 transform transition-transform duration-200
                         lg:static lg:z-auto lg:w-60 lg:flex-shrink-0 lg:translate-x-0
                         ${navOpen ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="p-4 border-b border-slate-200 flex items-center justify-between">
          <div>
            <div className="font-bold text-slate-900">CPMAI Prep</div>
            <div className="text-xs text-slate-500">Admin Console</div>
          </div>
          {/* Close button — drawer only (mobile). */}
          <button
            onClick={() => setNavOpen(false)}
            aria-label="Close menu"
            className="lg:hidden p-1.5 rounded-md text-slate-500 hover:bg-slate-100"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth="2" strokeLinecap="round">
              <line x1="6" y1="6" x2="18" y2="18" /><line x1="6" y1="18" x2="18" y2="6" />
            </svg>
          </button>
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
      {/* pt-14 clears the fixed mobile top bar; min-w-0 lets wide tables
          shrink/scroll inside instead of forcing the layout wider. */}
      <main className="flex-1 min-w-0 overflow-auto pt-14 lg:pt-0">{children}</main>
    </div>
  );
}
