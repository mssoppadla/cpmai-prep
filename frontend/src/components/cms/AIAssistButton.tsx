"use client";
/**
 * AI assist menu — three operations on the BlockNote editor.
 *
 *   1. Generate page from prompt   → fills the entire document
 *   2. Improve current selection   → rewrites the selected blocks in a tone
 *
 * "Fill block" from the original spec is reachable via the editor's own
 * slash menu by typing into an empty paragraph; we keep this widget
 * focused on the cross-cutting operations.
 *
 * Network calls go through the typed admin.cmsAi.* client. Errors are
 * surfaced as inline messages — the rest of the page is unaffected.
 *
 * The editor instance is obtained via a MutableRefObject from the
 * parent (see BlockNoteEditor's ``editorRef`` prop). When the user
 * clicks Generate, we ``editor.replaceBlocks(...)`` with the new
 * blocks; when they click Improve, we read the selected blocks,
 * call /improve-block, and patch each block's text.
 */
import { useState } from "react";
import { admin, errMsg } from "@/lib/api";
import type { CmsImproveTone } from "@/types/api";
import type {
  Block, BlockNoteEditor as BlockNoteEditorInstance,
} from "@blocknote/core";

// AIAssistButton uses only generic editor operations (replaceBlocks,
// getSelection, updateBlock, document) — none are schema-specific —
// so we accept any schema flavour to keep the prop loose.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type EditorInstance = BlockNoteEditorInstance<any, any, any>;

interface AIAssistButtonProps {
  /** Set by the parent via BlockNoteEditor's editorRef prop. */
  editorRef: React.MutableRefObject<EditorInstance | null>;
}

const TONES: { value: CmsImproveTone; label: string }[] = [
  { value: "shorter",    label: "Shorter" },
  { value: "longer",     label: "Longer" },
  { value: "friendlier", label: "Friendlier" },
  { value: "formal",     label: "More formal" },
  { value: "grammar",    label: "Fix grammar" },
];

export default function AIAssistButton({ editorRef }: AIAssistButtonProps) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"menu" | "generate" | "improve">("menu");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function close() {
    setOpen(false); setMode("menu"); setPrompt(""); setErr(null);
  }

  async function doGenerate() {
    const editor = editorRef.current;
    if (!editor) { setErr("Editor not ready"); return; }
    if (!prompt.trim()) { setErr("Enter a prompt first"); return; }
    setBusy(true); setErr(null);
    try {
      const { blocks } = await admin.cmsAi.generatePage({ prompt });
      // Replace the entire document with the generated blocks. Cast
      // because BlockNote's ``PartialBlock`` type permits the shape we
      // get back from the server.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      editor.replaceBlocks(editor.document, blocks as any);
      close();
    } catch (e) {
      console.error("[cms-ai] generate", e); setErr(errMsg(e));
    } finally { setBusy(false); }
  }

  async function doImprove(tone: CmsImproveTone) {
    const editor = editorRef.current;
    if (!editor) { setErr("Editor not ready"); return; }
    const selection = editor.getSelection();
    const blocks: Block[] = (selection?.blocks ?? []) as Block[];
    if (blocks.length === 0) {
      setErr("Select one or more blocks to improve");
      return;
    }
    setBusy(true); setErr(null);
    try {
      for (const b of blocks) {
        const original = extractText(b);
        if (!original.trim()) continue;
        const { text } = await admin.cmsAi.improveBlock({ text: original, tone });
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        editor.updateBlock(b, { type: b.type, content: text } as any);
      }
      close();
    } catch (e) {
      console.error("[cms-ai] improve", e); setErr(errMsg(e));
    } finally { setBusy(false); }
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="px-3 py-2 bg-purple-600 text-white text-sm font-medium rounded-lg
                   hover:bg-purple-700 flex items-center gap-2">
        ✨ AI assist
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 bg-white border border-slate-200
                        rounded-xl shadow-lg p-4 z-20">
          {err && (
            <div role="alert"
                 className="bg-rose-50 border border-rose-200 text-rose-700 p-2 rounded mb-3 text-xs">
              {err}
            </div>
          )}

          {mode === "menu" && (
            <div className="space-y-2">
              <button onClick={() => setMode("generate")}
                      className="w-full text-left px-3 py-2 hover:bg-slate-50 rounded text-sm">
                <div className="font-medium text-slate-900">Generate page from prompt</div>
                <div className="text-xs text-slate-500">Replaces the whole document with AI-drafted blocks</div>
              </button>
              <button onClick={() => setMode("improve")}
                      className="w-full text-left px-3 py-2 hover:bg-slate-50 rounded text-sm">
                <div className="font-medium text-slate-900">Improve selection</div>
                <div className="text-xs text-slate-500">Rewrite selected blocks in a chosen tone</div>
              </button>
              <div className="pt-2 border-t border-slate-100">
                <button onClick={close}
                        className="w-full text-xs text-slate-500 hover:text-slate-700">
                  Cancel
                </button>
              </div>
            </div>
          )}

          {mode === "generate" && (
            <div className="space-y-3">
              <label className="block text-xs font-medium text-slate-700">
                Describe the page
              </label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={4}
                placeholder="A study guide for the Business Understanding phase, with 3 sections and a CTA at the end."
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm
                           focus:outline-none focus:ring-2 focus:ring-indigo-500" />
              <div className="flex gap-2">
                <button onClick={doGenerate} disabled={busy}
                        className="flex-1 px-3 py-2 bg-indigo-600 text-white text-sm rounded-lg
                                   hover:bg-indigo-700 disabled:bg-slate-300">
                  {busy ? "Generating…" : "Generate"}
                </button>
                <button onClick={() => setMode("menu")}
                        className="px-3 py-2 bg-white border border-slate-300 text-slate-700 text-sm rounded-lg
                                   hover:bg-slate-50">
                  Back
                </button>
              </div>
              <p className="text-xs text-slate-500">
                ⚠️ Generating replaces the entire document.
              </p>
            </div>
          )}

          {mode === "improve" && (
            <div className="space-y-3">
              <p className="text-xs text-slate-600">
                Select blocks in the editor first, then pick a tone:
              </p>
              <div className="grid grid-cols-2 gap-2">
                {TONES.map((t) => (
                  <button key={t.value}
                          onClick={() => doImprove(t.value)}
                          disabled={busy}
                          className="px-3 py-2 bg-white border border-slate-300 text-slate-700 text-sm rounded-lg
                                     hover:bg-slate-50 disabled:bg-slate-100">
                    {t.label}
                  </button>
                ))}
              </div>
              <button onClick={() => setMode("menu")}
                      className="w-full px-3 py-1 text-xs text-slate-500 hover:text-slate-700">
                Back
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}


/** Pull a plain string out of a BlockNote block's content. The
 *  content can be a string, a list of inline objects, or empty. */
function extractText(b: Block): string {
  const c = b.content;
  if (typeof c === "string") return c;
  if (Array.isArray(c)) {
    return c.map((it) => {
      if (typeof it === "string") return it;
      if (typeof it === "object" && it !== null && "text" in it) {
        return String((it as { text: unknown }).text ?? "");
      }
      return "";
    }).join("");
  }
  return "";
}
