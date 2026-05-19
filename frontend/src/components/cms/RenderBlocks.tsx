/**
 * RenderBlocks — server-renderable BlockNote → React component.
 *
 * Used by the public CMS routes (/pages/[slug] and the landing-page-
 * aware /) to turn the JSON blocks array stored in the database into
 * actual HTML. This is a deliberate FRESH implementation, NOT a
 * thin wrapper around BlockNote — for two reasons:
 *
 *   1. **SSR-safe**. The BlockNote editor needs the browser DOM
 *      (ProseMirror). Our public pages are server-rendered for SEO,
 *      so we walk the block JSON ourselves and emit plain JSX.
 *
 *   2. **Stripped-down output**. The public page doesn't need
 *      contenteditable, drag handles, slash menus, or any editor
 *      chrome — just the content. Hand-rolling the renderer lets us
 *      produce minimal, accessible HTML.
 *
 * Block types supported (matches the stock BlockNote-Mantine palette
 * plus our custom youtubeGallery):
 *
 *   - paragraph, heading (levels 1-3)
 *   - bulletListItem, numberedListItem, checkListItem
 *   - table (full row/cell structure)
 *   - image (URL + optional caption)
 *   - video (URL — basic <video> element; not click-to-load)
 *   - codeBlock (with language hint as className for highlighting)
 *   - youtubeGallery (custom — uses the same view component as the editor)
 *
 * Unknown block types render nothing — silently dropped so a single
 * unknown type doesn't break the entire page.
 */
import type { BlockNoteBlock } from "@/types/api";
import YouTubeGalleryView from "./blocks/YouTubeGalleryView";


/** BlockNote inline content can be a string OR an array of inline
 *  spans (text + styles). We collapse to flat text for now — Phase 2
 *  polish will render formatting (bold, italic, links). */
function inlineText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "text" in item) {
        return String((item as { text: unknown }).text ?? "");
      }
      return "";
    }).join("");
  }
  return "";
}


/** Pull the cells out of a BlockNote table block. Shape:
 *  ``{ content: { type: "tableContent", rows: [{ cells: [{...}] }] } }``
 *  Each cell has its own ``content`` array (inline content). Returns a
 *  2D array of strings ready for `<td>` rendering. */
function tableRows(block: BlockNoteBlock): string[][] {
  const c = block.content;
  if (!c || typeof c !== "object" || Array.isArray(c)) return [];
  const rows = (c as { rows?: unknown }).rows;
  if (!Array.isArray(rows)) return [];
  return rows.map((row) => {
    if (!row || typeof row !== "object") return [];
    const cells = (row as { cells?: unknown }).cells;
    if (!Array.isArray(cells)) return [];
    return cells.map((cell) => {
      if (cell && typeof cell === "object" && "content" in cell) {
        return inlineText((cell as { content: unknown }).content);
      }
      return "";
    });
  });
}


function RenderBlock({ block }: { block: BlockNoteBlock }) {
  const type = block.type;
  const text = inlineText(block.content);
  const props = (block.props ?? {}) as Record<string, unknown>;

  switch (type) {
    case "paragraph":
      return <p className="my-3 text-slate-800 leading-relaxed">{text}</p>;

    case "heading": {
      const level = Number((props.level as number | string | undefined) ?? 2);
      const cls = level === 1
        ? "text-3xl font-bold mt-6 mb-3 text-slate-900"
        : level === 2
        ? "text-2xl font-semibold mt-5 mb-2 text-slate-900"
        : "text-xl font-semibold mt-4 mb-2 text-slate-900";
      if (level === 1) return <h1 className={cls}>{text}</h1>;
      if (level === 2) return <h2 className={cls}>{text}</h2>;
      return <h3 className={cls}>{text}</h3>;
    }

    case "bulletListItem":
      return <li className="ml-6 list-disc text-slate-800">{text}</li>;

    case "numberedListItem":
      return <li className="ml-6 list-decimal text-slate-800">{text}</li>;

    case "checkListItem": {
      const checked = Boolean(props.checked);
      return (
        <li className="ml-6 list-none text-slate-800 flex items-start gap-2">
          {/* Read-only on the public page — operators tick boxes in admin. */}
          <input type="checkbox" checked={checked} readOnly
                 className="mt-1.5" aria-label="task status" />
          <span className={checked ? "line-through text-slate-400" : ""}>{text}</span>
        </li>
      );
    }

    case "table": {
      const rows = tableRows(block);
      if (rows.length === 0) return null;
      // BlockNote tables don't distinguish header rows in the JSON shape
      // — the editor treats the first row as data by default. We render
      // it as <tbody> only to match.
      return (
        <div className="my-4 overflow-x-auto">
          <table className="border-collapse w-full text-sm">
            <tbody>
              {rows.map((cells, ri) => (
                <tr key={ri} className="border-b border-slate-200">
                  {cells.map((cellText, ci) => (
                    <td key={ci}
                        className="px-3 py-2 border border-slate-200 text-slate-800 align-top">
                      {cellText}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }

    case "image": {
      const url = String(props.url ?? "");
      const caption = String(props.caption ?? "");
      const name = String(props.name ?? "");
      if (!url) return null;
      return (
        <figure className="my-4">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={url} alt={caption || name || ""}
               className="max-w-full rounded-lg" loading="lazy" />
          {caption && (
            <figcaption className="text-xs text-slate-500 mt-1 text-center">
              {caption}
            </figcaption>
          )}
        </figure>
      );
    }

    case "video": {
      const url = String(props.url ?? "");
      const caption = String(props.caption ?? "");
      if (!url) return null;
      return (
        <figure className="my-4">
          <video src={url} controls className="max-w-full rounded-lg" />
          {caption && (
            <figcaption className="text-xs text-slate-500 mt-1 text-center">
              {caption}
            </figcaption>
          )}
        </figure>
      );
    }

    case "codeBlock": {
      const lang = String(props.language ?? "");
      return (
        <pre className="my-4 p-4 rounded-lg bg-slate-900 text-slate-100 overflow-x-auto text-sm">
          <code className={lang ? `language-${lang}` : undefined}>{text}</code>
        </pre>
      );
    }

    case "youtubeGallery": {
      const urls = String(props.urls ?? "");
      const columns = Number(props.columns ?? 3);
      return (
        <div className="my-6">
          <YouTubeGalleryView urls={urls} columns={columns} />
        </div>
      );
    }

    default:
      // Unknown / un-renderable block — render nothing rather than
      // breaking the page. Debug builds could surface a placeholder.
      return null;
  }
}


export function RenderBlocks({ blocks }: { blocks: BlockNoteBlock[] }) {
  // Wrap consecutive list items in <ul>/<ol> so list semantics survive.
  // checkListItem groups into <ul> with a marker class — it inherits
  // bullet semantics for screen readers but the items render their own
  // checkbox marker (see RenderBlock above).
  const out: React.ReactNode[] = [];
  let listBuffer: BlockNoteBlock[] = [];
  let listType: "ul" | "ol" | null = null;

  function flush() {
    if (!listBuffer.length || !listType) return;
    const Tag = listType;
    out.push(
      <Tag key={`list-${out.length}`} className="my-3">
        {listBuffer.map((b, i) => (
          <RenderBlock key={`${b.id ?? "li"}-${i}`} block={b} />
        ))}
      </Tag>
    );
    listBuffer = [];
    listType = null;
  }

  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i];
    const wantList =
      b.type === "bulletListItem"    ? "ul" :
      b.type === "numberedListItem"  ? "ol" :
      b.type === "checkListItem"     ? "ul" : null;
    if (wantList) {
      if (listType && listType !== wantList) flush();
      listType = wantList;
      listBuffer.push(b);
    } else {
      flush();
      out.push(<RenderBlock key={`${b.id ?? "b"}-${i}`} block={b} />);
    }
  }
  flush();

  return <>{out}</>;
}

export default RenderBlocks;
