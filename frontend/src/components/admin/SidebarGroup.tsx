"use client";

/**
 * SidebarGroup — collapsible group of navigation items for the admin sidebar.
 *
 * Behavioural contract:
 * - Expanded state is persisted to localStorage per group key
 * - If any item in the group is active (URL match), the group force-expands
 *   regardless of saved state (so the user can always see where they are)
 * - Manual user toggle wins for subsequent navigation within the same group
 * - First render uses `defaultExpanded` if no localStorage value exists
 *
 * This component is intentionally dumb about routing — the parent layout
 * passes in the current `pathname` and the items; this component renders
 * + manages collapse state.
 */
import { useEffect, useState } from "react";
import Link from "next/link";

export type NavItem = {
  href: string;
  label: string;
  /** Visual badge shown next to label (e.g. "NEW"). Optional. */
  badge?: string;
  /** If true, item is rendered indented (used for hierarchical sub-items
   *  like Flagged Turns under Chat History). */
  indent?: boolean;
};

export type SidebarGroupProps = {
  /** Stable identifier — used as the localStorage key for expand state.
   *  Must be unique across all sidebar groups. */
  groupKey: string;
  label: string;
  icon: string;
  items: NavItem[];
  /** Current page pathname (passed from parent to avoid each group
   *  calling usePathname independently). */
  pathname: string;
  /** Used as initial state on first render if no localStorage value exists. */
  defaultExpanded: boolean;
};

const STORAGE_PREFIX = "admin.sidebar.";

function loadExpanded(groupKey: string, fallback: boolean): boolean {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + groupKey);
    if (raw === null) return fallback;
    return raw === "1";
  } catch {
    return fallback;
  }
}

function saveExpanded(groupKey: string, expanded: boolean) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_PREFIX + groupKey, expanded ? "1" : "0");
  } catch {
    // localStorage might be disabled (private browsing) — fail silently
  }
}

export function SidebarGroup({
  groupKey, label, icon, items, pathname, defaultExpanded,
}: SidebarGroupProps) {
  // Compute "any item in this group is currently active" up-front so we
  // can force-expand at first paint without flicker.
  const hasActive = items.some((item) => itemIsActive(item, pathname));

  // Initial state: persisted value OR defaultExpanded. If a group has an
  // active item, force-expand on mount (regardless of saved state).
  const [expanded, setExpanded] = useState<boolean>(() =>
    hasActive ? true : loadExpanded(groupKey, defaultExpanded)
  );

  // When the URL changes and an active item lands in this group,
  // auto-expand it. Doesn't override subsequent manual collapses on
  // pages WITHOUT an active item — those preserve the saved state.
  useEffect(() => {
    if (hasActive && !expanded) {
      setExpanded(true);
    }
    // We intentionally omit `expanded` from deps — adding it would cause
    // re-expansion on manual collapse-during-active. The user can collapse
    // an active group; we don't fight them.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasActive]);

  function toggle() {
    const next = !expanded;
    setExpanded(next);
    saveExpanded(groupKey, next);
  }

  return (
    <div className="mb-1">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={expanded}
        aria-controls={`sidebar-group-${groupKey}`}
        className="w-full flex items-center justify-between px-3 py-2 rounded
                   text-xs font-semibold uppercase tracking-wide text-slate-500
                   hover:bg-slate-50 hover:text-slate-700 transition"
      >
        <span className="flex items-center gap-2">
          <span aria-hidden>{icon}</span>
          <span>{label}</span>
        </span>
        <span aria-hidden className="text-slate-400 text-sm">
          {expanded ? "▾" : "▸"}
        </span>
      </button>
      {expanded && (
        <ul
          id={`sidebar-group-${groupKey}`}
          className="mt-0.5 space-y-0.5"
        >
          {items.map((item) => {
            const active = itemIsActive(item, pathname);
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={`flex items-center justify-between px-3 py-1.5 rounded
                              text-sm ${item.indent ? "ml-4" : ""} ${
                    active
                      ? "bg-indigo-50 text-indigo-700 font-medium"
                      : "text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  <span>{item.label}</span>
                  {item.badge && (
                    <span className="text-[10px] font-bold tracking-wide
                                     uppercase bg-emerald-100 text-emerald-700
                                     px-1.5 py-0.5 rounded">
                      {item.badge}
                    </span>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** Active means: URL is exactly this item's href, OR URL starts with
 *  href + "/" (e.g. /admin/questions/123 is active for /admin/questions).
 *  /admin matches only when pathname is exactly /admin (avoid every
 *  admin page matching the Dashboard link). */
export function itemIsActive(item: NavItem, pathname: string): boolean {
  if (item.href === "/admin") return pathname === "/admin";
  return pathname === item.href || pathname.startsWith(item.href + "/");
}
