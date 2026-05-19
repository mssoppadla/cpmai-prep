"use client";
/**
 * YouTube Gallery — custom BlockNote block.
 *
 * Exposes a single atomic block type "youtubeGallery" with two props:
 *   - urls:    comma/newline separated YouTube URLs (string, default "")
 *   - columns: 1 | 2 | 3 (number, default 3)
 *
 * In the editor, the block renders the gallery view PLUS an "Edit URLs"
 * textarea below it so the operator can paste/edit URLs without
 * leaving the editor. The textarea is hidden in the public renderer
 * (the same view component is used, sans editor controls).
 *
 * Persistence: BlockNote serialises this as
 *   { type: "youtubeGallery", props: { urls: "...", columns: 3 } }
 * which round-trips through the existing /api/v1/admin/content-pages
 * blocks JSON column. No schema migration needed.
 *
 * Why props (not content) for the URL list:
 *   BlockNote inline content is designed for text-with-formatting,
 *   not opaque data. URLs as a comma-separated string in a prop is
 *   the documented pattern for "block holds structured data". The
 *   downside is the operator types into a textarea — but pasting
 *   YouTube links in is a one-shot action, so this is fine.
 */
import { useState } from "react";
import {
  createReactBlockSpec,
} from "@blocknote/react";
import YouTubeGalleryView from "./YouTubeGalleryView";


export const youtubeGallerySpec = createReactBlockSpec(
  {
    type: "youtubeGallery",
    propSchema: {
      urls:    { default: "" },
      columns: { default: 3, values: [1, 2, 3] as const },
    },
    content: "none",
  },
  {
    render: (props) => {
      const { block, editor } = props;
      // ``block.props.urls`` and ``columns`` always exist (BlockNote
      // fills in defaults). Both are typed by the propSchema above.
      const urls = (block.props as { urls: string }).urls;
      const columns = (block.props as { columns: number }).columns;

      // Show/hide the URL editor. Default collapsed so the gallery
      // looks like the final output; admins click "Edit URLs" to
      // change them.
      const [editing, setEditing] = useState(false);
      const [draft, setDraft] = useState(urls);

      function commit() {
        // BlockNote's updateBlock copies the block + applies our patch.
        // We must spread existing props or BlockNote will clear them.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        editor.updateBlock(block, {
          type: "youtubeGallery",
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          props: { urls: draft, columns } as any,
        } as any);
        setEditing(false);
      }

      function setColumns(n: number) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        editor.updateBlock(block, {
          type: "youtubeGallery",
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          props: { urls, columns: n } as any,
        } as any);
      }

      return (
        <div className="my-2 w-full" data-block-type="youtubeGallery">
          <YouTubeGalleryView urls={urls} columns={columns} />
          {/* Admin-only controls — hidden in public render */}
          <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
            <span className="font-medium">YouTube Gallery</span>
            <span>·</span>
            <button type="button"
                    onClick={() => { setDraft(urls); setEditing((e) => !e); }}
                    className="text-indigo-600 hover:underline">
              {editing ? "Cancel" : "Edit URLs"}
            </button>
            <span>·</span>
            <span>Columns:</span>
            {[1, 2, 3].map((n) => (
              <button key={n} type="button"
                      onClick={() => setColumns(n)}
                      className={n === columns
                        ? "px-1.5 rounded bg-indigo-600 text-white font-medium"
                        : "px-1.5 rounded border border-slate-300 hover:bg-slate-100"}>
                {n}
              </button>
            ))}
          </div>
          {editing && (
            <div className="mt-2 rounded-lg border border-indigo-200 bg-indigo-50/40 p-3">
              <label className="block text-xs font-medium text-slate-700 mb-1">
                YouTube URLs (one per line)
              </label>
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={Math.min(8, Math.max(3, draft.split(/\n/).length + 1))}
                placeholder="https://www.youtube.com/watch?v=...&#10;https://youtu.be/..."
                className="w-full px-3 py-2 border border-slate-300 rounded text-sm font-mono
                           focus:outline-none focus:ring-2 focus:ring-indigo-500" />
              <div className="mt-2 flex gap-2">
                <button type="button" onClick={commit}
                        className="px-3 py-1 bg-indigo-600 text-white text-xs font-medium rounded
                                   hover:bg-indigo-700">
                  Save
                </button>
                <button type="button" onClick={() => setEditing(false)}
                        className="px-3 py-1 bg-white border border-slate-300 text-slate-700 text-xs font-medium rounded
                                   hover:bg-slate-50">
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      );
    },
  },
);
