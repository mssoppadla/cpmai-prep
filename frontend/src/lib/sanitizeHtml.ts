/**
 * Allowlist HTML sanitizer for ADMIN-authored rich-text settings
 * rendered on public pages (Model Error Lab teaching copy).
 *
 * Only admins can write these values, so this is defense-in-depth
 * rather than a hostile-input boundary — but public pages should
 * never render markup outside a known vocabulary. Works in both the
 * Node (SSR) and browser runtimes: pure string processing, no DOM.
 *
 * Allowed tags: b i strong em u br p span div ul ol li
 *               table thead tbody tr td th h3 h4 a
 * Allowed attributes: style (color/background-color/font-weight/
 *               text-align only), href (http/https/mailto, adds
 *               rel+target), colspan/rowspan on cells.
 * Everything else — scripts, event handlers, iframes, unknown tags —
 * is stripped (tag removed, inner text kept).
 */

const ALLOWED = new Set([
  "b", "i", "strong", "em", "u", "br", "p", "span", "div", "ul", "ol",
  "li", "table", "thead", "tbody", "tr", "td", "th", "h3", "h4", "a",
]);

const STYLE_PROPS = new Set([
  "color", "background-color", "font-weight", "text-align",
]);

function cleanStyle(raw: string): string {
  return raw
    .split(";")
    .map((decl) => {
      const idx = decl.indexOf(":");
      if (idx < 0) return "";
      const prop = decl.slice(0, idx).trim().toLowerCase();
      const val = decl.slice(idx + 1).trim();
      if (!STYLE_PROPS.has(prop)) return "";
      // Values: word chars, #hex, rgb()/hsl() with digits/commas/%.
      if (!/^[\w#(),.%\s-]{1,60}$/.test(val)) return "";
      if (/url|expression|javascript/i.test(val)) return "";
      return `${prop}: ${val}`;
    })
    .filter(Boolean)
    .join("; ");
}

function cleanHref(raw: string): string | null {
  const v = raw.trim();
  if (/^(https?:\/\/|mailto:)/i.test(v) && !/["'<>]/.test(v)) return v;
  if (v.startsWith("/") && !v.startsWith("//") && !/["'<>]/.test(v)) return v;
  return null;
}

export function sanitizeHtml(input: string): string {
  if (!input) return "";
  // Drop comments and the CONTENT of dangerous containers outright.
  let html = input
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/<(script|style|iframe|object|embed|svg|math|form|textarea)\b[\s\S]*?<\/\1\s*>/gi, "")
    .replace(/<(script|style|iframe|object|embed|svg|math|form|textarea)\b[^>]*\/?>/gi, "");

  return html.replace(/<\/?([a-zA-Z][a-zA-Z0-9]*)\b([^>]*)>/g,
    (_whole, rawTag: string, rawAttrs: string) => {
      const tag = rawTag.toLowerCase();
      if (!ALLOWED.has(tag)) return "";           // strip tag, keep text
      const closing = _whole.startsWith("</");
      if (closing) return `</${tag}>`;

      let attrs = "";
      const styleMatch = /style\s*=\s*("([^"]*)"|'([^']*)')/i
        .exec(rawAttrs);
      if (styleMatch) {
        const cleaned = cleanStyle(styleMatch[2] ?? styleMatch[3] ?? "");
        if (cleaned) attrs += ` style="${cleaned}"`;
      }
      if (tag === "a") {
        const hrefMatch = /href\s*=\s*("([^"]*)"|'([^']*)')/i
          .exec(rawAttrs);
        const href = hrefMatch
          ? cleanHref(hrefMatch[2] ?? hrefMatch[3] ?? "") : null;
        if (href) {
          attrs += ` href="${href}" target="_blank" rel="noopener noreferrer"`;
        }
      }
      if (tag === "td" || tag === "th") {
        for (const name of ["colspan", "rowspan"]) {
          const mm = new RegExp(`${name}\\s*=\\s*"?(\\d{1,2})"?`, "i")
            .exec(rawAttrs);
          if (mm) attrs += ` ${name}="${mm[1]}"`;
        }
      }
      return `<${tag}${attrs}>`;
    });
}
