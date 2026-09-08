"use client";
/**
 * Lightweight rich text for question explanations ("General explanation"
 * and per-option "Why this is wrong"): bold/italic/lists, emoji, real
 * line breaks, and pasted/uploaded images.
 *
 * Backward compatibility is the design constraint — thousands of
 * existing rows hold PLAIN text and must render exactly as before:
 *   - values are stored in the same Text columns, no migration
 *   - looksLikeHtml() decides per value: legacy plain strings render as
 *     text (with newlines finally preserved via whitespace-pre-line);
 *     only values saved by RichTextEditor render as sanitized HTML
 *   - nothing rewrites a row until an admin actually edits it
 */
import { useEffect, useRef, useState } from "react";
import { absoluteUploadUrl, admin, errMsg } from "@/lib/api";
import { sanitizeHtml } from "@/lib/sanitizeHtml";

/** True when the value was authored by the rich editor (contains real
 *  markup). Plain legacy text — even with < or emoji — stays plain:
 *  we only claim HTML when a known tag appears. */
export function looksLikeHtml(value: string): boolean {
  return /<(b|i|strong|em|u|br|p|span|div|ul|ol|li|img|a|h3|h4|table)\b[^>]*\/?>/i.test(value);
}

export function RichTextView({ value, className = "" }: {
  value: string | null | undefined;
  className?: string;
}) {
  if (!value) return null;
  if (!looksLikeHtml(value)) {
    // Legacy plain text — unchanged, but line breaks now survive.
    return <span className={`whitespace-pre-line ${className}`}>{value}</span>;
  }
  return (
    <div
      className={`rich-text-view [&_img]:max-w-full [&_img]:rounded-lg [&_img]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-1 ${className}`}
      dangerouslySetInnerHTML={{ __html: sanitizeHtml(value) }}
    />
  );
}

export function RichTextEditor({ value, onChange, placeholder, minRows = 3 }: {
  value: string;
  onChange: (html: string) => void;
  placeholder?: string;
  minRows?: number;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Seed the editor once (and when switching records). Legacy plain
  // text is escaped and its newlines become <br> INSIDE THE EDITOR ONLY
  // — the stored row stays untouched until the admin actually edits.
  const seeded = useRef<string | null>(null);
  useEffect(() => {
    if (!ref.current || seeded.current === value) return;
    // Don't clobber the DOM while the admin is typing in this editor.
    if (document.activeElement === ref.current) return;
    seeded.current = value;
    if (looksLikeHtml(value)) {
      ref.current.innerHTML = sanitizeHtml(value);
    } else {
      const esc = value.replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/\n/g, "<br>");
      ref.current.innerHTML = esc;
    }
  }, [value]);

  function emit() {
    if (!ref.current) return;
    const html = ref.current.innerHTML
      .replace(/^(<br\s*\/?>)+$/i, "");   // empty editor → empty string
    seeded.current = html;
    onChange(html);
  }

  function exec(command: string) {
    ref.current?.focus();
    document.execCommand(command);
    emit();
  }

  async function uploadAndInsert(file: File) {
    setErr(null); setUploading(true);
    try {
      const up = await admin.uploads.file(file);
      ref.current?.focus();
      document.execCommand(
        "insertHTML", false,
        `<img src="${absoluteUploadUrl(up.url)}" alt="${up.filename}">`);
      emit();
    } catch (e) { setErr(errMsg(e)); }
    finally { setUploading(false); }
  }

  return (
    <div className="rounded-lg border border-slate-300 bg-white focus-within:ring-1 focus-within:ring-indigo-400">
      <div className="flex items-center gap-1 border-b border-slate-200 px-2 py-1">
        {[["bold", "B", "font-bold"], ["italic", "I", "italic"],
          ["underline", "U", "underline"],
          ["insertUnorderedList", "• List", ""],
          ["insertOrderedList", "1. List", ""]].map(([cmd, label, cls]) => (
          <button key={cmd} type="button"
            onMouseDown={(e) => { e.preventDefault(); exec(cmd); }}
            className={`rounded px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100 ${cls}`}>
            {label}
          </button>
        ))}
        <button type="button" disabled={uploading}
          onMouseDown={(e) => { e.preventDefault(); fileRef.current?.click(); }}
          className="rounded px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-50">
          {uploading ? "Uploading…" : "🖼 Image"}
        </button>
        <span className="ml-auto text-[10px] text-slate-400">
          paste images & emoji directly
        </span>
        <input ref={fileRef} type="file" accept="image/*" className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void uploadAndInsert(f);
            e.target.value = "";
          }} />
      </div>
      <div
        ref={ref}
        contentEditable
        role="textbox"
        aria-multiline="true"
        data-placeholder={placeholder}
        style={{ minHeight: `${minRows * 1.6}rem` }}
        className="px-3 py-2 text-sm leading-relaxed outline-none [&_img]:max-w-full [&_img]:rounded-lg [&_img]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5 empty:before:content-[attr(data-placeholder)] empty:before:text-slate-400"
        onInput={emit}
        onBlur={emit}
        onPaste={(e) => {
          const item = Array.from(e.clipboardData?.items ?? [])
            .find((it) => it.type.startsWith("image/"));
          if (item) {
            e.preventDefault();
            const f = item.getAsFile();
            if (f) void uploadAndInsert(f);
          }
        }}
      />
      {err && <p className="px-3 pb-2 text-xs text-rose-600">{err}</p>}
    </div>
  );
}
