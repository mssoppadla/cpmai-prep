/**
 * Lab embed helpers — server-side truncation of a lab asset at the
 * admin-chosen cut point, and the lock UI that replaces what was cut.
 *
 * The POLICY (who sees what) is decided by the backend
 * (/content/labs/{slug}/access). This module only renders that
 * decision: given the asset HTML and the access response, it returns
 * the HTML the visitor is allowed to receive. Locked sections are never
 * sent to the browser — the blur below the cut is a placeholder.
 *
 * Marker grammar inside an asset (frontend/labs-assets/<slug>.html):
 *   <!--LABSEC id="s7"-->                                    section start (HTML)
 *   <!--LABSEC id="sec4" y="1530" close="</svg></figure>"--> section start inside an
 *        <svg>: y = where to cut the viewBox, close = tags to close if cut here
 *   <!--LABSEC:END-->                                         end of sectioned content
 * Section ORDER in the asset must match the registry's section list.
 */
import type { LabAccessOut, LabSectionOut } from "@/types/api";

export const LAB_EMBED_PATH = "/labs/embed";
/** Bump when an asset changes so browsers drop the cached iframe doc. */
export const LAB_ASSET_VERSION = 6;

export function labPagePath(slug: string): string {
  return `/labs/${slug}`;
}

export function labEmbedUrl(slug: string, token?: string | null): string {
  const q = new URLSearchParams({ v: String(LAB_ASSET_VERSION) });
  if (token) q.set("t", token);
  return `${LAB_EMBED_PATH}/${encodeURIComponent(slug)}?${q.toString()}`;
}

interface Marker {
  id: string;
  y: number | null;
  close: string;
  start: number;   // index of the marker comment
  end: number;     // index just after it
}

const MARKER_RE = /<!--LABSEC id="([^"]+)"(?: y="(\d+)")?(?: close="([^"]*)")?-->/g;
const END_MARKER = "<!--LABSEC:END-->";

export function parseMarkers(html: string): { markers: Marker[]; end: number } {
  const markers: Marker[] = [];
  for (const m of html.matchAll(MARKER_RE)) {
    markers.push({
      id: m[1], y: m[2] ? Number(m[2]) : null, close: m[3] ?? "",
      start: m.index ?? 0, end: (m.index ?? 0) + m[0].length,
    });
  }
  return { markers, end: html.indexOf(END_MARKER) };
}

function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export interface LockCopy {
  title: string;
  body: string;
  plans: string;          // "" when nothing to name
  primaryLabel: string;
  primaryHref: string;
  secondaryLabel?: string;
  secondaryHref?: string;
  barLabel: string;
}

/** The words on the lock panel, per the access decision. */
export function lockCopy(access: LabAccessOut, pagePath: string): LockCopy {
  const n = access.locked_sections.length;
  const names = access.locked_sections.slice(0, 4).map(s => s.title).join(" · ")
    + (n > 4 ? " · …" : "");
  const loginHref = `/login?next=${encodeURIComponent(pagePath)}`;
  if (access.reason === "disabled") {
    return {
      title: "This lab is currently offline", body: "Check back soon.",
      plans: "", primaryLabel: "Back to labs", primaryHref: "/labs",
      barLabel: "Lab offline",
    };
  }
  if (access.reason === "signin") {
    return {
      title: "Sign in to open this lab",
      body: "A free account is all you need — no plan required.",
      plans: "", primaryLabel: "Sign in / create a free account",
      primaryHref: loginHref, barLabel: "Sign in to open the full lab",
    };
  }
  const preview = access.free_upto_index >= 0;
  const plans = access.plans.length
    ? "Included in: " + access.plans.map(p => `<em>${esc(p.name)}</em>`).join(" · ")
    : "";
  return {
    title: preview ? "End of the free preview" : "This lab is part of a plan",
    body: n > 0
      ? `${n} more section${n === 1 ? "" : "s"}: ${esc(names)}`
      : "The full page is available to plan members.",
    plans,
    primaryLabel: "See plans", primaryHref: "/pricing",
    secondaryLabel: "Sign in", secondaryHref: loginHref,
    barLabel: `${n} more section${n === 1 ? "" : "s"} · plan members only`,
  };
}

/** Lock UI injected in place of the cut content. Self-contained
 *  (own styles + script); links target the parent window. */
export function buildLockUi(access: LabAccessOut, pagePath: string): string {
  const c = lockCopy(access, pagePath);
  const ghosts = Math.max(3, Math.min(access.locked_sections.length || 3, 5));
  const ghost = '<div class="lab-ghost" aria-hidden="true"><b></b><i style="width:92%"></i><i style="width:78%"></i><i style="width:85%"></i><i style="width:60%"></i></div>';
  const secondary = c.secondaryLabel
    ? `<a class="lab-btn" href="${esc(c.secondaryHref ?? "#")}" target="_top">${esc(c.secondaryLabel)}</a>`
    : "";
  return `
<!-- lab lock: locked sections are not in this document -->
<style>
  .lab-locked{position:relative;max-width:1400px;margin:0 auto;padding:12px 24px 40px}
  .lab-ghost{border:1px dashed #cfd4e2;border-radius:12px;padding:16px;margin:14px 0;filter:blur(3px);opacity:.55;pointer-events:none;user-select:none}
  .lab-ghost b{display:block;height:13px;width:38%;background:#cfd4e2;border-radius:4px;margin-bottom:10px}
  .lab-ghost i{display:block;height:9px;background:#dfe3ee;border-radius:4px;margin:7px 0}
  .lab-lock{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:min(520px,92%);background:#fff;color:#0f172a;border:1.5px solid #6d28d9;border-radius:14px;padding:22px 24px 20px;text-align:center;box-shadow:0 12px 40px rgba(15,23,42,.18);font:15px/1.5 "Source Sans 3","Segoe UI",system-ui,sans-serif;z-index:5}
  .lab-lock .x{position:absolute;top:8px;right:10px;border:0;background:transparent;font-size:20px;line-height:1;color:#64748b;cursor:pointer;padding:4px 6px;border-radius:6px}
  .lab-lock .x:hover,.lab-lock .x:focus-visible{background:#f1f5f9;color:#0f172a;outline:none}
  .lab-lock .ic{font-size:26px}.lab-lock h2{margin:6px 0 4px;font-size:19px;font-weight:700}
  .lab-lock p{margin:0 0 10px;color:#475569;font-size:14px}
  .lab-lock .plans{font-size:13px;margin-bottom:12px;color:#334155}.lab-lock .plans em{font-style:normal;font-weight:700;color:#6d28d9}
  .lab-lock .btns{display:flex;gap:8px;justify-content:center;flex-wrap:wrap}
  .lab-btn{display:inline-block;padding:8px 16px;border-radius:9px;font-weight:600;font-size:14px;text-decoration:none;border:1px solid #4f46e5;color:#4f46e5;background:#fff}
  .lab-btn.pri{background:#4f46e5;color:#fff}
  .lab-lockbar{display:none;align-items:center;justify-content:space-between;gap:12px;max-width:1400px;margin:0 auto;padding:10px 16px;border:1px solid #ddd6fe;background:#f5f3ff;color:#4c1d95;border-radius:10px;font:600 14px "Source Sans 3","Segoe UI",system-ui,sans-serif}
  .lab-lockbar a{color:#4f46e5;text-decoration:none;font-weight:700}
  .lab-locked.dismissed .lab-lock{display:none}.lab-locked.dismissed .lab-lockbar{display:flex}
  a.lab-sec-locked{opacity:.55}a.lab-sec-locked::after{content:" 🔒";font-size:.85em}
</style>
<div class="lab-locked" id="lab-locked" data-locked="${access.locked_sections.length}">
  <div class="lab-lockbar" role="status">🔒 ${esc(c.barLabel)} <a href="#lab-locked" id="lab-lock-reopen">Show options</a></div>
  ${ghost.repeat(ghosts)}
  <div class="lab-lock" role="dialog" aria-labelledby="lab-lock-title">
    <button class="x" type="button" id="lab-lock-close" aria-label="Close">×</button>
    <div class="ic">🔒</div>
    <h2 id="lab-lock-title">${esc(c.title)}</h2>
    <p>${c.body}</p>
    ${c.plans ? `<div class="plans">${c.plans}</div>` : ""}
    <div class="btns"><a class="lab-btn pri" href="${esc(c.primaryHref)}" target="_top">${esc(c.primaryLabel)}</a>${secondary}</div>
  </div>
</div>
<script>
(() => {
  const box = document.getElementById("lab-locked"); if (!box) return;
  const closeBtn = document.getElementById("lab-lock-close"), reopen = document.getElementById("lab-lock-reopen");
  const show = () => { box.classList.remove("dismissed"); box.scrollIntoView({ block: "center" }); };
  closeBtn && closeBtn.addEventListener("click", () => box.classList.add("dismissed"));
  reopen && reopen.addEventListener("click", (e) => { e.preventDefault(); show(); });
  // in-page links to sections that were cut: mark them and route to the lock panel
  document.querySelectorAll('a[href^="#"]').forEach(a => {
    const id = a.getAttribute("href").slice(1);
    if (id && !document.getElementById(id)) { a.classList.add("lab-sec-locked"); a.addEventListener("click", (e) => { e.preventDefault(); show(); }); }
  });
  try { parent.postMessage({ type: "lab-lock", locked: Number(box.dataset.locked || 0) }, window.location.origin); } catch (e) {}
})();
</script>
`;
}

/**
 * Cut ``html`` after the last free section and put the lock UI where
 * the locked content was. ``full`` → the asset unchanged. Assets
 * without markers (the interactive Simulator) are all-or-nothing: a
 * locked visitor gets a lock-only document.
 */
export function truncateLabHtml(
  html: string, access: LabAccessOut, pagePath: string,
): string {
  if (access.full) return html;
  const lock = buildLockUi(access, pagePath);
  const { markers, end } = parseMarkers(html);
  if (!markers.length || end < 0) {
    return lockOnlyDocument(access.title, lock);
  }
  const upto = access.free_upto_index;              // -1 = nothing free
  const cut = markers[upto + 1];                    // first locked marker
  if (!cut) return html;                            // cut beyond the last section → nothing to hide
  let out = html.slice(0, cut.start);
  if (cut.y !== null) {
    out = out.replace(/viewBox="0 0 (\d+) \d+"/, (_m, w) => `viewBox="0 0 ${w} ${cut.y}"`);
  }
  out += cut.close + lock + html.slice(end + END_MARKER.length);
  // strip any marker comments that survived (before the cut)
  return out.replace(MARKER_RE, "");
}

export function lockOnlyDocument(title: string, lock: string): string {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex"><title>${esc(title)}</title>
<style>body{margin:0;background:#f8fafc;font:15px/1.5 "Source Sans 3","Segoe UI",system-ui,sans-serif;color:#0f172a}</style></head>
<body>${lock}
<script>(()=>{const post=()=>{try{parent.postMessage({type:"lab-height",h:document.documentElement.scrollHeight},window.location.origin)}catch(e){}};new ResizeObserver(post).observe(document.documentElement);window.addEventListener("load",post);setTimeout(post,300)})();</script>
</body></html>`;
}

/** Section titles the page lists for search engines and the outline. */
export function sectionOutline(sections: LabSectionOut[]): string[] {
  return sections.map(s => s.title);
}
