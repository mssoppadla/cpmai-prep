"use client";
/**
 * Page metadata side panel — slug, title, nav visibility, publish state.
 *
 * Mirrors the API's PATCH-able fields exactly. The editor page debounces
 * changes from this panel together with block-content changes and POSTs
 * once with the combined diff.
 */
import type { NavVisibility } from "@/types/api";

interface PageMetadata {
  slug: string;
  title: string;
  nav_visibility: NavVisibility;
  nav_label: string | null;
  nav_order: number;
  is_published: boolean;
}

interface PageMetadataPanelProps {
  meta: PageMetadata;
  onChange: (patch: Partial<PageMetadata>) => void;
  /** Original slug at load — used to warn about URL breakage. */
  originalSlug: string;
}

const VISIBILITY_OPTIONS: { value: NavVisibility; label: string; help: string }[] = [
  { value: "always",        label: "Always visible",
    help: "Shown in the nav for everyone, including signed-out visitors." },
  { value: "authenticated", label: "Logged-in users only",
    help: "Shown in the nav only for users who are signed in." },
  { value: "subscribed",    label: "Paid subscribers only",
    help: "Shown in the nav only for users with an active subscription." },
  { value: "hidden",        label: "Hidden from nav",
    help: "Not in the nav. Page is still accessible by direct URL when published." },
];

export default function PageMetadataPanel({
  meta, onChange, originalSlug,
}: PageMetadataPanelProps) {
  const slugChanged = meta.slug !== originalSlug;
  return (
    <aside className="w-80 shrink-0 bg-white border border-slate-200 rounded-xl p-5 space-y-5">
      <div>
        <h2 className="text-sm font-semibold text-slate-900">Page details</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Saved automatically. Public URLs update when you change the slug.
        </p>
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-700 mb-1">Title</label>
        <input
          value={meta.title}
          onChange={(e) => onChange({ title: e.target.value })}
          className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
                     focus:outline-none focus:ring-2 focus:ring-indigo-500" />
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-700 mb-1">Slug</label>
        <input
          value={meta.slug}
          onChange={(e) => onChange({ slug: e.target.value })}
          className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono
                     focus:outline-none focus:ring-2 focus:ring-indigo-500" />
        {slugChanged && (
          <p className="text-xs text-amber-700 mt-1 bg-amber-50 px-2 py-1 rounded">
            Changing the slug breaks any external links to <code>/{originalSlug}</code>.
          </p>
        )}
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-700 mb-1">
          Nav label override
        </label>
        <input
          value={meta.nav_label ?? ""}
          onChange={(e) => onChange({ nav_label: e.target.value || null })}
          placeholder={`(defaults to: ${meta.title})`}
          className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
                     focus:outline-none focus:ring-2 focus:ring-indigo-500" />
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-700 mb-1">
          Nav order (lower = earlier)
        </label>
        <input
          type="number"
          value={meta.nav_order}
          onChange={(e) => onChange({ nav_order: Number(e.target.value) || 0 })}
          className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
                     focus:outline-none focus:ring-2 focus:ring-indigo-500" />
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-700 mb-2">
          Nav visibility
        </label>
        <div className="space-y-2">
          {VISIBILITY_OPTIONS.map((opt) => (
            <label key={opt.value}
                   className="flex gap-2 items-start cursor-pointer
                              hover:bg-slate-50 -mx-2 px-2 py-1 rounded">
              <input
                type="radio"
                name="nav_visibility"
                value={opt.value}
                checked={meta.nav_visibility === opt.value}
                onChange={() => onChange({ nav_visibility: opt.value })}
                className="mt-0.5" />
              <div>
                <div className="text-sm text-slate-800">{opt.label}</div>
                <div className="text-xs text-slate-500">{opt.help}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      <div className="pt-4 border-t border-slate-100">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={meta.is_published}
            onChange={(e) => onChange({ is_published: e.target.checked })} />
          <span className="text-sm font-medium text-slate-800">
            Published
          </span>
        </label>
        <p className="text-xs text-slate-500 mt-1 ml-6">
          Drafts (unchecked) are admin-visible only. Once checked, the page
          is live at its public URL.
        </p>
      </div>
    </aside>
  );
}
