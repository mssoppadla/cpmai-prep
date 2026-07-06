"use client";
/**
 * Admin Content Pages — list view.
 *
 * Shows every non-deleted ContentPage for the current tenant. Admin
 * actions:
 *   • Create a new page — slug + title prompt → POST → redirect to editor
 *   • Click row → editor at /admin/content-pages/[id]
 *   • Delete (soft-delete in API) — confirmation dialog
 *
 * BlockNote-heavy work lives in the [id] editor route, NOT here, so
 * this page stays small and SSR-clean. No editor dependencies imported.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { admin, errMsg } from "@/lib/api";
import type { ContentPageOut, NavVisibility } from "@/types/api";

// Slug rule mirrors backend regex: lowercase alphanum + single dashes,
// no leading/trailing dash, no consecutive dashes.
const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function navVisibilityBadge(v: NavVisibility): string {
  switch (v) {
    case "always":        return "bg-emerald-100 text-emerald-800";
    case "authenticated": return "bg-sky-100 text-sky-800";
    case "subscribed":    return "bg-amber-100 text-amber-800";
    case "hidden":        return "bg-slate-200 text-slate-700";
  }
}

export default function ContentPagesAdminPage() {
  const [rows, setRows] = useState<ContentPageOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newSlug, setNewSlug] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function reload() {
    try { setRows(await admin.contentPages.list()); }
    catch (e) { console.error("[admin/content-pages] list", e); setErr(errMsg(e)); }
  }
  useEffect(() => { reload(); }, []);

  async function createPage() {
    // Trim BEFORE validation — accepting "  study-guide  " from the
    // user and then rejecting it for the leading spaces would be
    // confusing UX. The backend's slug regex requires the same shape
    // anyway, so we normalise here.
    const trimmedSlug = newSlug.trim();
    const trimmedTitle = newTitle.trim();
    if (!SLUG_RE.test(trimmedSlug)) {
      setErr("Slug must be lowercase alphanumeric with single dashes (e.g. 'study-guide')");
      return;
    }
    if (!trimmedTitle) {
      setErr("Title is required");
      return;
    }
    setBusy(true); setErr(null);
    try {
      const page = await admin.contentPages.create({
        slug: trimmedSlug, title: trimmedTitle,
      });
      // Hand off to the editor — operator can start authoring immediately
      router.push(`/admin/content-pages/${page.id}`);
    } catch (e) {
      console.error("[admin/content-pages] create", e);
      setErr(errMsg(e));
    } finally { setBusy(false); }
  }

  // Reorder a page by bumping its nav_order. Swaps with the adjacent
  // page in the sort so the user gets visible movement immediately.
  async function move(idx: number, direction: -1 | 1) {
    if (!rows) return;
    const target = rows[idx];
    const neighborIdx = idx + direction;
    if (neighborIdx < 0 || neighborIdx >= rows.length) return;
    const neighbor = rows[neighborIdx];
    // Optimistic UI: swap locally first, then PATCH both. If a PATCH
    // fails we reload to recover.
    const a = target.nav_order;
    const b = neighbor.nav_order;
    const newOrderA = a === b ? a - direction : b;
    const newOrderB = a === b ? a : a;
    const next = rows.slice();
    next[idx] = { ...target, nav_order: newOrderA };
    next[neighborIdx] = { ...neighbor, nav_order: newOrderB };
    setRows([...next].sort((p, q) => p.nav_order - q.nav_order || p.id - q.id));
    try {
      await Promise.all([
        admin.contentPages.update(target.id, { nav_order: newOrderA }),
        admin.contentPages.update(neighbor.id, { nav_order: newOrderB }),
      ]);
    } catch (e) {
      console.error("[admin/content-pages] reorder", e);
      setErr(errMsg(e));
      await reload();
    }
  }

  async function deletePage(id: number, slug: string) {
    const ok = confirm(
      `Delete page "${slug}"?\n\nThis soft-deletes the page — it stays in ` +
      `the database and can be recovered, but it disappears from this list ` +
      `and from your public site.`
    );
    if (!ok) return;
    try {
      await admin.contentPages.delete(id);
      await reload();
    } catch (e) {
      console.error("[admin/content-pages] delete", e);
      setErr(errMsg(e));
    }
  }

  return (
    <div className="p-8 max-w-5xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Content Pages</h1>
          <p className="text-slate-600 mt-1 text-sm">
            Admin-editable long-form pages. Each page is published to a slug
            URL (e.g. <code className="px-1 bg-slate-100 rounded">/pages/about</code>)
            and can be shown or hidden in the site nav per its visibility setting.
          </p>
        </div>
        {!creating && (
          <button
            onClick={() => { setCreating(true); setErr(null); }}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700">
            + New page
          </button>
        )}
      </header>

      {err && (
        <div role="alert"
             className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}

      {creating && (
        <div className="bg-white rounded-xl border-2 border-indigo-200 p-6 mb-6">
          <h2 className="font-semibold text-slate-900 mb-4">Create a new page</h2>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Slug (URL piece)
          </label>
          <input
            value={newSlug}
            onChange={(e) => setNewSlug(e.target.value)}
            placeholder="study-guide"
            className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
                       focus:outline-none focus:ring-2 focus:ring-indigo-500" />
          <p className="text-xs text-slate-500 mt-1">
            Lowercase letters, numbers, and single dashes only. This becomes
            the URL piece on the public site.
          </p>
          <label className="block text-sm font-medium text-slate-700 mb-1 mt-4">
            Title
          </label>
          <input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="CPMAI Study Guide"
            className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
                       focus:outline-none focus:ring-2 focus:ring-indigo-500" />
          <div className="flex gap-2 mt-5">
            <button
              onClick={createPage}
              disabled={busy}
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg
                         hover:bg-indigo-700 disabled:bg-slate-300">
              {busy ? "Creating…" : "Create and open editor"}
            </button>
            <button
              onClick={() => { setCreating(false); setNewSlug(""); setNewTitle(""); setErr(null); }}
              className="px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm
                         font-medium rounded-lg hover:bg-slate-50">
              Cancel
            </button>
          </div>
        </div>
      )}

      {rows === null ? (
        <div className="text-slate-500 text-sm">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl p-8 text-center text-slate-500">
          No content pages yet. Click <strong>+ New page</strong> to create your first one.
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-left">
              <tr>
                <th className="px-4 py-3 font-medium w-20">Order</th>
                <th className="px-4 py-3 font-medium">Title / Slug</th>
                <th className="px-4 py-3 font-medium">Visibility</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Updated</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => (
                <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-3 text-slate-600 text-xs">
                    <div className="flex flex-col gap-0.5 items-start">
                      <button onClick={() => move(idx, -1)}
                              disabled={idx === 0}
                              aria-label="Move up"
                              className="px-1.5 py-0.5 text-slate-500 hover:text-indigo-600 disabled:text-slate-300 disabled:cursor-not-allowed">
                        ▲
                      </button>
                      <span className="px-1.5 font-mono">{r.nav_order}</span>
                      <button onClick={() => move(idx, +1)}
                              disabled={idx === rows.length - 1}
                              aria-label="Move down"
                              className="px-1.5 py-0.5 text-slate-500 hover:text-indigo-600 disabled:text-slate-300 disabled:cursor-not-allowed">
                        ▼
                      </button>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Link href={`/admin/content-pages/${r.id}`}
                            className="font-medium text-indigo-700 hover:underline">
                        {r.title}
                      </Link>
                      {r.is_landing && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide
                                         bg-purple-100 text-purple-700"
                              title="This page is marked as the landing page. It takes effect when cms.use_cms_landing is enabled in settings.">
                          Landing
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-500 mt-0.5">
                      <code className="px-1 bg-slate-100 rounded">/{r.slug}</code>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${navVisibilityBadge(r.nav_visibility)}`}>
                      {r.nav_visibility}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {r.is_published ? (
                      <span className="text-emerald-700 text-xs font-medium">● Published</span>
                    ) : (
                      <span className="text-slate-500 text-xs font-medium">○ Draft</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-600 text-xs">
                    {new Date(r.updated_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => deletePage(r.id, r.slug)}
                      className="text-rose-600 hover:underline text-xs">
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
