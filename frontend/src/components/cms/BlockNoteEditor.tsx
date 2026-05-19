"use client";
/**
 * BlockNoteEditor — thin wrapper around @blocknote/react + Mantine theme.
 *
 * Why it's its own component:
 *
 *   1. **SSR isolation.** BlockNote requires the DOM (it uses ProseMirror
 *      under the hood). The parent page imports this via Next.js's
 *      ``dynamic(..., { ssr: false })`` so the editor never runs on the
 *      server. Putting it in its own file makes that boundary obvious
 *      and keeps SSR pages from accidentally importing editor CSS.
 *
 *   2. **CSS scoping.** ``@blocknote/mantine/style.css`` and
 *      ``@mantine/core/styles.css`` are loaded once here, not at the
 *      app shell, so the rest of the admin keeps its Tailwind look and
 *      Mantine styles only activate inside the editor.
 *
 *   3. **Theme override.** We force the light theme. Once we add a
 *      global dark mode, swap this for ``useTheme()``.
 *
 * Props are intentionally small: the parent owns the persistence path
 * (debounced auto-save, dirty tracking). This component just renders
 * the editor and emits ``onBlocksChange`` whenever the document
 * changes.
 */
import { useEffect, useMemo, useRef } from "react";
import { useCreateBlockNote } from "@blocknote/react";
import { BlockNoteView } from "@blocknote/mantine";
import type { Block, PartialBlock } from "@blocknote/core";

import "@blocknote/core/fonts/inter.css";
import "@blocknote/mantine/style.css";
import "@mantine/core/styles.css";

interface BlockNoteEditorProps {
  /** Initial blocks loaded from the server. The editor will be
   *  recreated if this changes identity — so the parent should keep
   *  ``initialBlocks`` stable (memoised) once loaded, otherwise the
   *  user's in-flight edits get blown away. */
  initialBlocks: PartialBlock[] | undefined;
  /** Called every time the document changes. The parent debounces
   *  this before POSTing to the API. */
  onBlocksChange: (blocks: Block[]) => void;
  /** Optional placeholder shown when the document is empty. */
  placeholderText?: string;
  /** Imperative ref to the editor instance. Used by AI assist buttons
   *  to insert / replace blocks programmatically. */
  editorRef?: React.MutableRefObject<ReturnType<typeof useCreateBlockNote> | null>;
}

export default function BlockNoteEditor({
  initialBlocks,
  onBlocksChange,
  placeholderText,
  editorRef,
}: BlockNoteEditorProps) {
  // ``useCreateBlockNote`` returns a stable editor instance for the
  // lifetime of this component. We seed it with the server's blocks
  // once; subsequent edits flow OUT via onBlocksChange.
  const editor = useCreateBlockNote({
    initialContent: useMemo(
      () =>
        initialBlocks && initialBlocks.length > 0
          ? initialBlocks
          : ([{ type: "paragraph", content: "" }] as PartialBlock[]),
      // We deliberately seed once on mount. Subsequent prop changes
      // to ``initialBlocks`` are ignored — see component contract above.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      []
    ),
  });

  // Expose the editor instance to the parent (for AI insert/replace).
  useEffect(() => {
    if (editorRef) editorRef.current = editor;
    return () => { if (editorRef) editorRef.current = null; };
  }, [editor, editorRef]);

  // Wire up onChange. BlockNote uses ``editor.onChange()`` which is a
  // function-returning-unsubscribe, so guard against doubled
  // subscriptions across re-renders with a ref.
  const offRef = useRef<(() => void) | null>(null);
  useEffect(() => {
    if (offRef.current) {
      offRef.current();
      offRef.current = null;
    }
    const off = editor.onChange(() => {
      onBlocksChange(editor.document as Block[]);
    });
    offRef.current = off ?? null;
    return () => { if (off) off(); };
  }, [editor, onBlocksChange]);

  return (
    <div className="blocknote-shell rounded-xl bg-white border border-slate-200 p-4">
      {placeholderText && (
        <div className="text-xs text-slate-400 mb-2">{placeholderText}</div>
      )}
      <BlockNoteView editor={editor} theme="light" />
    </div>
  );
}
