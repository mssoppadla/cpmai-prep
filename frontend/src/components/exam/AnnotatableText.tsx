"use client";
/**
 * AnnotatableText — drag-to-select highlight & strike, with toggle removal.
 *
 * Behavior:
 *   - When the active `tool` is "highlight" or "strike": drag-select text
 *     inside this component to apply the annotation to that range.
 *   - Re-applying the same tool over an existing range removes it
 *     (toggle).
 *   - Tool "eraser": drag-select to remove any overlapping annotations.
 *   - Tool "none": text is plain selectable but no annotations applied.
 *
 * Storage is range-based: each annotation is `{start, end, kind}` where
 * the offsets are characters within this component's text. The parent
 * owns the array; this component just renders + reports new ranges.
 */
import React, { useEffect, useRef } from "react";
import type { Tool } from "./QuestionCard";

export interface TextRange {
  start: number;
  end: number;
  kind: "highlight" | "strike";
}

interface Props {
  text: string;
  ranges: TextRange[];
  tool: Tool;
  className?: string;
  onChange: (next: TextRange[]) => void;
}

export function AnnotatableText({
  text, ranges, tool, className, onChange,
}: Props) {
  const ref = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    function onMouseUp() {
      if (tool === "none") return;
      // Re-narrow inside the closure: TS doesn't carry the outer `if (!el)`
      // refinement across the function boundary.
      if (!el) return;
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0) return;
      const r = sel.getRangeAt(0);
      if (r.collapsed) return;

      // Both ends must be inside this element
      if (!el.contains(r.startContainer) || !el.contains(r.endContainer)) return;

      const start = offsetWithin(el, r.startContainer, r.startOffset);
      const end   = offsetWithin(el, r.endContainer,   r.endOffset);
      if (start == null || end == null) return;
      const lo = Math.min(start, end);
      const hi = Math.max(start, end);
      if (lo === hi) return;

      const next = applyTool(ranges, { start: lo, end: hi }, tool);
      onChange(next);
      sel.removeAllRanges();
    }

    el.addEventListener("mouseup", onMouseUp);
    return () => { el.removeEventListener("mouseup", onMouseUp); };
  }, [tool, ranges, onChange]);

  return (
    <span
      ref={ref}
      className={[className, "select-text"].filter(Boolean).join(" ")}
      style={{ cursor: tool === "none" ? undefined : "crosshair" }}
    >
      {renderSegments(text, ranges)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Character offset of a (node, offset) pair within `root`'s textContent. */
function offsetWithin(root: Node, node: Node, offset: number): number | null {
  let acc = 0;
  let found = false;
  function walk(n: Node): boolean {
    if (n === node) {
      acc += offset;
      found = true;
      return true;
    }
    if (n.nodeType === Node.TEXT_NODE) {
      acc += (n as Text).length;
      return false;
    }
    for (let i = 0; i < n.childNodes.length; i++) {
      if (walk(n.childNodes[i])) return true;
    }
    return false;
  }
  walk(root);
  return found ? acc : null;
}

/**
 * Apply the active tool to the new selection. Toggle semantics:
 *   - highlight + selection inside an existing highlight → strip it
 *   - same kind in two adjacent ranges → merge
 *   - eraser → remove any overlap
 */
function applyTool(
  current: TextRange[],
  sel: { start: number; end: number },
  tool: Tool,
): TextRange[] {
  if (tool === "eraser") {
    return removeOverlaps(current, sel);
  }
  if (tool === "highlight" || tool === "strike") {
    // If the entire selection is already covered by the same kind →
    // toggle it off. Otherwise apply the new annotation, replacing any
    // overlap of the SAME kind, leaving the OTHER kind alone.
    const same = current.filter(r => r.kind === tool);
    if (covers(same, sel)) {
      return removeOverlaps(current, sel, tool);
    }
    const cleared = removeOverlaps(current, sel, tool);
    return mergeSameKind([...cleared, { ...sel, kind: tool }]);
  }
  return current;
}

function covers(ranges: TextRange[], sel: { start: number; end: number }): boolean {
  // True when [sel.start, sel.end] is fully inside the union of `ranges`.
  let pos = sel.start;
  const sorted = [...ranges].sort((a, b) => a.start - b.start);
  for (const r of sorted) {
    if (r.end <= pos) continue;
    if (r.start > pos) return false;
    pos = Math.max(pos, r.end);
    if (pos >= sel.end) return true;
  }
  return false;
}

function removeOverlaps(
  ranges: TextRange[],
  sel: { start: number; end: number },
  onlyKind?: TextRange["kind"],
): TextRange[] {
  const out: TextRange[] = [];
  for (const r of ranges) {
    if (onlyKind && r.kind !== onlyKind) {
      out.push(r);
      continue;
    }
    if (r.end <= sel.start || r.start >= sel.end) {
      out.push(r);
      continue;
    }
    // overlaps — split around the selection
    if (r.start < sel.start) {
      out.push({ start: r.start, end: sel.start, kind: r.kind });
    }
    if (r.end > sel.end) {
      out.push({ start: sel.end, end: r.end, kind: r.kind });
    }
  }
  return out;
}

function mergeSameKind(ranges: TextRange[]): TextRange[] {
  const sorted = [...ranges].sort((a, b) =>
    a.kind === b.kind
      ? a.start - b.start
      : a.kind.localeCompare(b.kind)
  );
  const out: TextRange[] = [];
  for (const r of sorted) {
    const last = out[out.length - 1];
    if (last && last.kind === r.kind && r.start <= last.end) {
      last.end = Math.max(last.end, r.end);
    } else {
      out.push({ ...r });
    }
  }
  return out;
}

/** Split text into segments based on ranges, render each with appropriate styling. */
function renderSegments(text: string, ranges: TextRange[]): React.ReactNode[] {
  if (ranges.length === 0) return [text];

  // Build a list of breakpoints: where each segment starts/ends.
  const points = new Set<number>([0, text.length]);
  for (const r of ranges) {
    points.add(Math.max(0, Math.min(text.length, r.start)));
    points.add(Math.max(0, Math.min(text.length, r.end)));
  }
  const stops = [...points].sort((a, b) => a - b);

  const out: React.ReactNode[] = [];
  for (let i = 0; i < stops.length - 1; i++) {
    const a = stops[i], b = stops[i + 1];
    if (a === b) continue;
    // Find which kinds cover [a, b)
    const kinds = ranges
      .filter(r => r.start <= a && r.end >= b)
      .map(r => r.kind);
    const piece = text.slice(a, b);
    const cls = [
      kinds.includes("highlight") ? "bg-yellow-200/80 rounded-sm px-0.5" : "",
      kinds.includes("strike")    ? "line-through text-slate-400"        : "",
    ].filter(Boolean).join(" ");
    out.push(
      cls
        ? <span key={a} className={cls}>{piece}</span>
        : <React.Fragment key={a}>{piece}</React.Fragment>
    );
  }
  return out;
}
