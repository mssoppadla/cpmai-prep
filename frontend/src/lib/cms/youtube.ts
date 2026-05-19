/**
 * YouTube URL parsing helpers — pure functions, no DOM.
 *
 * The gallery block stores URLs as a comma-separated string in a
 * BlockNote prop (props must be primitives). We parse the string,
 * extract video IDs, and render thumbnails. The iframe is only loaded
 * when the user clicks (privacy-friendly facade — no YouTube cookies
 * until interaction).
 *
 * Supported URL shapes:
 *   - https://www.youtube.com/watch?v=ID&t=42s
 *   - https://youtu.be/ID
 *   - https://www.youtube.com/embed/ID
 *   - https://youtube.com/shorts/ID
 *   - https://m.youtube.com/watch?v=ID
 *   - Bare ID (11 chars) — useful for paste tolerance
 *
 * Invalid / unrecognised URLs produce ``null`` IDs — the gallery
 * silently skips them so a single bad URL doesn't break the row.
 */

/** YouTube IDs are 11 characters: a-z A-Z 0-9 _ -. Anything else is invalid. */
const YT_ID_RE = /^[A-Za-z0-9_-]{11}$/;


export function extractYouTubeId(input: string): string | null {
  const url = input.trim();
  if (!url) return null;

  // 1. Bare ID
  if (YT_ID_RE.test(url)) return url;

  // 2. Anything else must look like a URL with a host.
  let u: URL;
  try {
    u = new URL(url);
  } catch {
    return null;
  }

  const host = u.hostname.replace(/^www\./, "").replace(/^m\./, "");

  // 3. youtu.be/ID
  if (host === "youtu.be") {
    const id = u.pathname.split("/").filter(Boolean)[0] ?? "";
    return YT_ID_RE.test(id) ? id : null;
  }

  // 4. youtube.com/...
  if (host === "youtube.com" || host === "youtube-nocookie.com") {
    // /watch?v=ID
    const v = u.searchParams.get("v");
    if (v && YT_ID_RE.test(v)) return v;
    // /embed/ID, /shorts/ID, /v/ID, /live/ID
    const segs = u.pathname.split("/").filter(Boolean);
    if (segs.length >= 2 && ["embed", "shorts", "v", "live"].includes(segs[0])) {
      const id = segs[1];
      return YT_ID_RE.test(id) ? id : null;
    }
  }

  return null;
}


/**
 * Given the gallery's comma-or-newline-separated URL string, return
 * the list of valid YouTube IDs in order. Whitespace + empty lines
 * are tolerated. Invalid entries are dropped (caller can warn).
 */
export function parseUrlList(raw: string): string[] {
  if (!raw) return [];
  return raw
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map(extractYouTubeId)
    .filter((id): id is string => id !== null);
}


/** YouTube thumbnail URL. `hqdefault` is 480x360, universally available. */
export function thumbnailUrl(videoId: string): string {
  return `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`;
}


/** Embed URL — only constructed when the user actually clicks play.
 *  Uses youtube-nocookie.com for privacy. */
export function embedUrl(videoId: string): string {
  return `https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1&rel=0`;
}
