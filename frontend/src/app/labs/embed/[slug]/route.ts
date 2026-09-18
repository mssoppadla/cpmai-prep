/**
 * /labs/embed/<slug>?t=<embed_token> — the iframe document for a lab.
 *
 * Reads the asset from frontend/labs-assets/<slug>.html (NOT under
 * /public, so the file cannot be fetched directly), asks the backend
 * what the visitor may see, and serves the asset cut at that decision
 * with the lock UI in place of the rest. Locked sections never leave
 * the server.
 *
 *  - ``t`` is the short-lived embed token the page obtained from
 *    /content/labs/<slug>/access with its Bearer token; the backend
 *    re-checks it against the CURRENT lab settings.
 *  - No/invalid token → the backend resolves the visitor as anonymous.
 *  - Backend unreachable → 503 with a friendly page. Deliberately
 *    fail-CLOSED: a gated asset must not leak because the API blinked.
 *
 * X-Frame-Options SAMEORIGIN comes from next.config.js headers().
 */
import { readFile } from "fs/promises";
import path from "path";
import type { LabAccessOut } from "@/types/api";
import { API } from "@/lib/ssr";
import { labPagePath, truncateLabHtml } from "@/lib/labs";

export const dynamic = "force-dynamic";

const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,80}$/;

function html(body: string, status = 200, extra: Record<string, string> = {}) {
  return new Response(body, {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "private, no-store",
      "X-Robots-Tag": "noindex",
      ...extra,
    },
  });
}

function message(title: string, text: string, status: number) {
  return html(`<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${title}</title>
<style>body{margin:0;background:#f8fafc;font:15px/1.5 system-ui,sans-serif;color:#0f172a}
.m{max-width:520px;margin:48px auto;padding:24px;border:1px solid #e2e8f0;border-radius:14px;background:#fff;text-align:center}</style></head>
<body><div class="m"><h2 style="margin:0 0 6px">${title}</h2><p style="margin:0;color:#475569">${text}</p></div></body></html>`, status);
}

export async function GET(
  req: Request, { params }: { params: { slug: string } },
) {
  const slug = params.slug;
  if (!SLUG_RE.test(slug)) return message("Not found", "No such lab.", 404);
  const url = new URL(req.url);
  const t = url.searchParams.get("t");

  let access: LabAccessOut;
  try {
    const q = t ? `?t=${encodeURIComponent(t)}` : "";
    const r = await fetch(`${API}/content/labs/${encodeURIComponent(slug)}/access${q}`,
      { cache: "no-store", headers: { Accept: "application/json" } });
    if (r.status === 404) return message("Not found", "No such lab.", 404);
    if (!r.ok) throw new Error(`access ${r.status}`);
    access = (await r.json()) as LabAccessOut;
  } catch {
    return message("Lab temporarily unavailable",
      "We could not confirm access right now. Please reload in a moment.", 503);
  }

  let asset: string;
  try {
    asset = await readFile(
      path.join(process.cwd(), "labs-assets", `${slug}.html`), "utf-8");
  } catch {
    return message("Not found", "This lab has no embedded page.", 404);
  }

  return html(truncateLabHtml(asset, access, labPagePath(slug)));
}
