/**
 * YouTube URL parser tests — pure function, fast to exercise.
 *
 * Pins the URL shapes we accept and reject. The gallery block's
 * usefulness depends on this parser being permissive (admins paste
 * lots of URL shapes) while still rejecting non-YouTube URLs cleanly.
 */
import { describe, it, expect } from "vitest";
import {
  embedUrl,
  extractYouTubeId,
  parseUrlList,
  thumbnailUrl,
} from "@/lib/cms/youtube";


describe("extractYouTubeId — accepted shapes", () => {
  const cases: Array<[string, string]> = [
    ["https://www.youtube.com/watch?v=dQw4w9WgXcQ",                "dQw4w9WgXcQ"],
    ["https://youtube.com/watch?v=dQw4w9WgXcQ",                    "dQw4w9WgXcQ"],
    ["https://m.youtube.com/watch?v=dQw4w9WgXcQ",                  "dQw4w9WgXcQ"],
    ["https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s",          "dQw4w9WgXcQ"],
    ["https://youtu.be/dQw4w9WgXcQ",                               "dQw4w9WgXcQ"],
    ["https://www.youtube.com/embed/dQw4w9WgXcQ",                  "dQw4w9WgXcQ"],
    ["https://www.youtube.com/shorts/dQw4w9WgXcQ",                 "dQw4w9WgXcQ"],
    ["https://www.youtube.com/v/dQw4w9WgXcQ",                      "dQw4w9WgXcQ"],
    ["https://www.youtube.com/live/dQw4w9WgXcQ",                   "dQw4w9WgXcQ"],
    ["dQw4w9WgXcQ",                                                "dQw4w9WgXcQ"],
    ["  dQw4w9WgXcQ  ",                                            "dQw4w9WgXcQ"],
  ];
  it.each(cases)("%s → %s", (input, expected) => {
    expect(extractYouTubeId(input)).toBe(expected);
  });
});


describe("extractYouTubeId — rejected shapes", () => {
  const cases = [
    "",
    "not a url",
    "https://example.com/watch?v=dQw4w9WgXcQ",       // wrong host
    "https://youtube.com/foo/dQw4w9WgXcQ",            // unknown path
    "https://youtube.com/watch",                       // no v param
    "https://youtu.be/",                                // empty
    "https://youtu.be/too-short",                       // bad length
    "https://www.youtube.com/watch?v=too-short",        // bad length
    "dQw4w9WgXcQQQ",                                    // too long
    "https://twitter.com/dQw4w9WgXcQ",                  // entirely wrong site
  ];
  it.each(cases)("%s → null", (input) => {
    expect(extractYouTubeId(input)).toBeNull();
  });
});


describe("parseUrlList", () => {
  it("returns empty array for empty input", () => {
    expect(parseUrlList("")).toEqual([]);
    expect(parseUrlList("   ")).toEqual([]);
  });

  it("splits on newlines", () => {
    const input = `
      https://youtu.be/aaaaaaaaaaa
      https://youtu.be/bbbbbbbbbbb
      https://youtu.be/ccccccccccc
    `;
    expect(parseUrlList(input)).toEqual([
      "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc",
    ]);
  });

  it("splits on commas", () => {
    expect(parseUrlList("aaaaaaaaaaa,bbbbbbbbbbb,ccccccccccc")).toEqual([
      "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc",
    ]);
  });

  it("drops invalid entries silently", () => {
    const input = "https://youtu.be/validvalid1\ninvalid url\nhttps://youtu.be/validvalid2";
    expect(parseUrlList(input)).toEqual(["validvalid1", "validvalid2"]);
  });

  it("trims whitespace and ignores empty lines", () => {
    expect(parseUrlList("\n\n  https://youtu.be/aaaaaaaaaaa  \n\n")).toEqual([
      "aaaaaaaaaaa",
    ]);
  });
});


describe("URL helpers", () => {
  it("thumbnailUrl points at YouTube CDN", () => {
    expect(thumbnailUrl("abc")).toBe("https://img.youtube.com/vi/abc/hqdefault.jpg");
  });

  it("embedUrl uses youtube-nocookie.com and autoplay", () => {
    expect(embedUrl("abc")).toBe(
      "https://www.youtube-nocookie.com/embed/abc?autoplay=1&rel=0"
    );
  });
});
