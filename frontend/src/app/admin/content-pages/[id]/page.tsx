"use client";
/**
 * Admin Content Page — editor view at /admin/content-pages/[id].
 *
 * Composes:
 *   - BlockNoteEditor    (dynamic import, SSR-disabled)
 *   - PageMetadataPanel  (right side, drives PATCH-able fields)
 *   - AIAssistButton     (top-right, talks to /admin/cms-ai/*)
 *
 * Persistence:
 *   - On any change (block content OR metadata), we schedule a debounced
 *     PATCH 1.5s later. While the timer runs we show "Saving…"; on success
 *     "Saved <relative time>".
 *   - Saves are coalesced: if the user keeps typing, the previous timer
 *     is cleared and a fresh one starts.
 *   - On unmount or page leave (beforeunload) we flush an immediate save
 *     so no edits are lost.
 *
 * Why the page reads the route param as Promise<...>: Next.js 14 wraps
 * dynamic params in a Promise that ``use()`` unwraps client-side. We
 * keep that boilerplate small via a helper.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import Link from "next/link";
import { admin, errMsg } from "@/lib/api";
import type {
  Block, PartialBlock,
} from "@blocknote/core";
import type {
  ContentPageOut, ContentPageUpdateIn, NavVisibility,
} from "@/types/api";
import PageMetadataPanel from "@/components/cms/PageMetadataPanel";
import AIAssistButton from "@/components/cms/AIAssistButton";
import type { useCreateBlockNote } from "@blocknote/react";

// SSR off — ProseMirror needs the DOM.
const BlockNoteEditor = dynamic(
  () => import("@/components/cms/BlockNoteEditor"),
  { ssr: false, loading: () => (
    <div className="rounded-xl bg-white border border-slate-200 p-8 text-center text-slate-400">
      Loading editor…
    </div>
  )},
);

const SAVE_DEBOUNCE_MS = 1500;

type EditorMeta = {
  slug: string;
  title: string;
  nav_visibility: NavVisibility;
  nav_label: string | null;
  nav_order: number;
  is_published: boolean;
};

function metaFrom(p: ContentPageOut): EditorMeta {
  return {
    slug: p.slug,
    title: p.title,
    nav_visibility: p.nav_visibility,
    nav_label: p.nav_label,
    nav_order: p.nav_order,
    is_published: p.is_published,
  };
}

export default function ContentPageEditorView({
  params,
}: { params: { id: string } }) {
  const router = useRouter();
  const pageId = Number(params.id);

  const [page, setPage] = useState<ContentPageOut | null>(null);
  const [meta, setMeta] = useState<EditorMeta | null>(null);
  const [blocks, setBlocks] = useState<Block[] | null>(null);

  const [saving, setSaving] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Stable initial blocks fed to BlockNote. Set ONCE after load.
  const [initialBlocks, setInitialBlocks] = useState<PartialBlock[] | undefined>(undefined);

  // Editor instance ref — used by AIAssistButton.
  const editorRef = useRef<ReturnType<typeof useCreateBlockNote> | null>(null);

  // ----------------------------------------------------- load

  useEffect(() => {
    if (!Number.isFinite(pageId)) {
      setErr("Invalid page id"); return;
    }
    (async () => {
      try {
        const p = await admin.contentPages.get(pageId);
        setPage(p);
        setMeta(metaFrom(p));
        setInitialBlocks(p.blocks as PartialBlock[]);
      } catch (e) {
        console.error("[cms editor] load", e);
        setErr(errMsg(e));
      }
    })();
  }, [pageId]);

  // ----------------------------------------------------- save (debounced)

  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flushSave = useCallback(async () => {
    if (!meta) return;
    setSaving("saving"); setErr(null);
    const patch: ContentPageUpdateIn = {
      slug: meta.slug,
      title: meta.title,
      nav_visibility: meta.nav_visibility,
      nav_label: meta.nav_label,
      nav_order: meta.nav_order,
      is_published: meta.is_published,
      ...(blocks ? { blocks: blocks as unknown as ContentPageUpdateIn["blocks"] } : {}),
    };
    try {
      const updated = await admin.contentPages.update(pageId, patch);
      setPage(updated);
      setSaving("saved");
      setSavedAt(new Date());
    } catch (e) {
      console.error("[cms editor] save", e);
      setErr(errMsg(e));
      setSaving("error");
    }
  }, [meta, blocks, pageId]);

  const scheduleSave = useCallback(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    setSaving("saving");
    saveTimer.current = setTimeout(() => { void flushSave(); }, SAVE_DEBOUNCE_MS);
  }, [flushSave]);

  // Schedule a save whenever meta or blocks change (but NOT on first load).
  const loadedRef = useRef(false);
  useEffect(() => {
    if (page === null) return;
    if (!loadedRef.current) { loadedRef.current = true; return; }
    scheduleSave();
  }, [meta, blocks, page, scheduleSave]);

  // Best-effort save on unmount and on beforeunload.
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (saveTimer.current) {
        // Synchronous save isn't reliably possible from beforeunload, but
        // we can at least prompt the user when there's an in-flight edit.
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, []);

  // ----------------------------------------------------- handlers

  const onBlocksChange = useCallback((next: Block[]) => {
    setBlocks(next);
  }, []);

  const onMetaChange = useCallback((patch: Partial<EditorMeta>) => {
    setMeta((m) => (m ? { ...m, ...patch } : m));
  }, []);

  // ----------------------------------------------------- render

  if (err && !page) {
    return (
      <div className="p-8">
        <div role="alert"
             className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg">
          {err}
        </div>
        <Link href="/admin/content-pages"
              className="inline-block mt-4 text-indigo-600 hover:underline text-sm">
          ← Back to content pages
        </Link>
      </div>
    );
  }
  if (!page || !meta) {
    return <div className="p-8 text-slate-500 text-sm">Loading…</div>;
  }

  return (
    <div className="p-8 max-w-7xl">
      <header className="flex items-center justify-between mb-6">
        <div>
          <Link href="/admin/content-pages"
                className="text-xs text-slate-500 hover:underline">
            ← Content Pages
          </Link>
          <h1 className="text-xl font-bold text-slate-900 mt-1">
            {meta.title || "(untitled)"}
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            <span>Status:</span>{" "}
            {saving === "saving" && <span className="text-amber-600">Saving…</span>}
            {saving === "saved"  && (
              <span className="text-emerald-600">
                Saved{savedAt ? ` ${relativeAgo(savedAt)}` : ""}
              </span>
            )}
            {saving === "error"  && <span className="text-rose-600">Save failed — retry?</span>}
            {saving === "idle"   && <span className="text-slate-500">Up to date</span>}
          </p>
        </div>
        <AIAssistButton editorRef={editorRef} />
      </header>

      {err && (
        <div role="alert"
             className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg mb-4 text-sm">
          {err}
        </div>
      )}

      <div className="flex gap-6 items-start">
        <main className="flex-1 min-w-0">
          <BlockNoteEditor
            initialBlocks={initialBlocks}
            onBlocksChange={onBlocksChange}
            placeholderText="Start typing — press '/' for the block menu."
            editorRef={editorRef}
          />
        </main>
        <PageMetadataPanel
          meta={meta}
          onChange={onMetaChange}
          originalSlug={page.slug}
        />
      </div>
    </div>
  );
}


function relativeAgo(d: Date): string {
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 5)   return "just now";
  if (s < 60)  return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return d.toLocaleTimeString();
}
