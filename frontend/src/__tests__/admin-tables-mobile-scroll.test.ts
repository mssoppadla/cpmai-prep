/**
 * Regression guard: every admin data table must be horizontally
 * scrollable on small screens.
 *
 * Bug history (2026-07): the Contacts page (/admin/leads) wrapped its
 * table in `overflow-hidden`, so on phones the right-hand columns —
 * including the row actions (Delete) — were clipped with no way to
 * reach them. The same pattern existed on a dozen other admin pages.
 *
 * The rule this test pins: a `<table>` inside an admin page/component
 * must have `overflow-x-auto` on its nearest styled wrapper, and that
 * wrapper must NOT be `overflow-hidden` (which silently clips columns).
 * `overflow-x-auto` is a no-op when the table fits, so there is no
 * downside on wide screens — do not "fix" a failure here by shrinking
 * columns or hiding actions; wrap the table instead:
 *
 *   <div className="... overflow-x-auto">
 *     <table className="w-full min-w-[<content width>]"> ...
 *
 * Static source scan on purpose: it needs no rendering/mocking, runs in
 * milliseconds inside `npm test` (and therefore in scripts/preflight.sh
 * and the CI test gate), and automatically covers every admin page
 * added in the future.
 */
import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOTS = [
  join(__dirname, "..", "app", "admin"),
  join(__dirname, "..", "components", "admin"),
];

/** Recursively collect .tsx files under a directory. */
function tsxFiles(dir: string): string[] {
  let out: string[] = [];
  let entries: string[];
  try { entries = readdirSync(dir); } catch { return out; }
  for (const name of entries) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out = out.concat(tsxFiles(p));
    else if (name.endsWith(".tsx")) out.push(p);
  }
  return out;
}

/**
 * For one source file, find every `<table` and report offences where
 * the nearest preceding `overflow-*` utility is missing or is
 * `overflow-hidden`. "Nearest preceding" = last overflow class in the
 * 400 characters of JSX before the table tag — wrappers sit directly
 * above their table in this codebase, so the window is generous.
 */
function scanFile(path: string): string[] {
  const src = readFileSync(path, "utf8");
  const offences: string[] = [];
  const tableRe = /<table[\s>]/g;
  let m: RegExpExecArray | null;
  while ((m = tableRe.exec(src)) !== null) {
    const windowBefore = src.slice(Math.max(0, m.index - 400), m.index);
    const overflowClasses = windowBefore.match(/overflow-[a-z-]+/g) ?? [];
    const nearest = overflowClasses[overflowClasses.length - 1];
    const line = src.slice(0, m.index).split("\n").length;
    if (!nearest) {
      offences.push(
        `${relative(process.cwd(), path)}:${line} — <table> has no ` +
        `overflow-x-auto wrapper (columns will clip on mobile)`);
    } else if (nearest !== "overflow-x-auto" && nearest !== "overflow-auto") {
      offences.push(
        `${relative(process.cwd(), path)}:${line} — <table> wrapper uses ` +
        `'${nearest}' (clips columns on mobile; use overflow-x-auto)`);
    }
  }
  return offences;
}

describe("admin tables are reachable on mobile", () => {
  const files = ROOTS.flatMap(tsxFiles);

  it("finds admin sources to scan (guards against path drift)", () => {
    // If the admin tree moves, this test must fail loudly rather than
    // silently scanning nothing and passing forever.
    expect(files.length).toBeGreaterThan(10);
  });

  it("every <table> sits in an overflow-x-auto wrapper", () => {
    const offences = files.flatMap(scanFile);
    expect(offences, "\n" + offences.join("\n") + "\n").toEqual([]);
  });
});
