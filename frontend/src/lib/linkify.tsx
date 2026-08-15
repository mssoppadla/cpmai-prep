import React from "react";

/**
 * Render admin-entered plain text with clickable links — nothing else.
 *
 * Two link forms are recognised:
 *   [label](https://example.com)   → <a>label</a>   (markdown-style)
 *   https://example.com            → <a>https://example.com</a>
 *
 * Only http(s) URLs become anchors (a malformed or javascript: "link"
 * stays literal text), and everything outside a link renders through
 * React's normal escaping — admin text can never inject markup. Links
 * open in a new tab; wa.me / LinkedIn URLs hand off to the native app
 * on mobile exactly like any anchor would.
 *
 * Built for pricing.intl_notice_text ("email us / WhatsApp us" style
 * banners) but content-agnostic — reuse for any admin-entered copy.
 */

// [label](url) — label may not contain brackets; url must be http(s).
// Bare URLs stop before whitespace and common trailing punctuation.
const TOKEN = /\[([^\[\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<>"']+[^\s<>"'.,;:!?)])/g;

export function linkifyText(text: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of text.matchAll(TOKEN)) {
    const idx = m.index ?? 0;
    if (idx > last) out.push(text.slice(last, idx));
    const label = m[1] ?? m[3];
    const href = m[2] ?? m[3];
    out.push(
      <a key={key++} href={href} target="_blank" rel="noopener noreferrer"
         className="font-medium underline underline-offset-2 hover:opacity-80">
        {label}
      </a>,
    );
    last = idx + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
