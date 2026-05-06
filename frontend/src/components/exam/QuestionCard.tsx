"use client";
import type { QuestionAttemptView } from "@/types/api";

export type Annotation = "highlight" | "strike";
export type Tool = "none" | Annotation | "eraser";

/** Per-option annotation state for a single question. */
export type OptionAnnotations = Record<string, Annotation | null>;

interface Props {
  question: QuestionAttemptView;
  index: number;
  total: number;
  selected: string | null;
  markedForReview: boolean;
  /** Active toolbox mode (toggles via the toolbar). */
  tool: Tool;
  /** Per-option annotations for this question (highlight | strike | null). */
  annotations: OptionAnnotations;
  onSelect: (letter: string | null) => void;
  onToggleReview: () => void;
  onAnnotate: (letter: string) => void;
}

/**
 * Question + options card. Supports two attempt-time annotations on
 * each option: HIGHLIGHT (yellow background) or STRIKE (line-through).
 *
 * Annotations are applied by clicking an option while a tool is active:
 *   - tool = "highlight" + click   → toggle highlight on that option
 *   - tool = "strike"    + click   → toggle strike on that option
 *   - tool = "eraser"    + click   → clear annotation
 *   - tool = "none"      + click   → normal answer selection
 *
 * Mark-for-review remains independent (its own checkbox).
 */
export function QuestionCard({
  question, index, total, selected, markedForReview,
  tool, annotations, onSelect, onToggleReview, onAnnotate,
}: Props) {
  function handleOptionClick(letter: string) {
    if (tool === "highlight" || tool === "strike" || tool === "eraser") {
      onAnnotate(letter);
    } else {
      onSelect(selected === letter ? null : letter);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-6">
      <div className="flex items-center justify-between mb-4 text-sm text-slate-500">
        <span>Question {index + 1} of {total}</span>
        {question.domain && (
          <span className="px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded">
            {question.domain}
          </span>
        )}
      </div>
      <h2 className="text-lg font-semibold text-slate-900 leading-relaxed mb-6">
        {question.stem}
      </h2>
      <div className="space-y-2">
        {question.options.map((opt) => {
          const isSelected = selected === opt.option_letter;
          const ann = annotations[opt.option_letter] ?? null;
          const struck = ann === "strike";
          const lit    = ann === "highlight";
          return (
            <button
              key={opt.option_letter}
              type="button"
              onClick={() => handleOptionClick(opt.option_letter)}
              className={[
                "w-full text-left flex items-start gap-3 p-3 rounded-lg border transition",
                isSelected
                  ? "bg-indigo-50 border-indigo-300"
                  : "bg-white border-slate-200 hover:border-slate-300",
                lit && !isSelected ? "bg-yellow-50 border-yellow-300" : "",
                tool !== "none" ? "cursor-crosshair" : "",
              ].filter(Boolean).join(" ")}
            >
              <span className={[
                "w-6 h-6 rounded-full border-2 flex items-center justify-center",
                "mt-0.5 font-bold text-xs flex-shrink-0",
                isSelected
                  ? "bg-indigo-600 border-indigo-600 text-white"
                  : "border-slate-300 text-slate-500",
              ].join(" ")}>
                {opt.option_letter}
              </span>
              <span className={[
                "text-sm leading-relaxed pt-0.5 flex-1",
                struck ? "line-through text-slate-400" : "text-slate-700",
                lit ? "bg-yellow-200/70 px-1 rounded" : "",
              ].filter(Boolean).join(" ")}>
                {opt.text}
              </span>
            </button>
          );
        })}
      </div>
      <label className="mt-5 flex items-center gap-2 text-sm text-slate-600">
        <input type="checkbox" checked={markedForReview}
               onChange={onToggleReview}
               className="rounded border-slate-300" />
        Mark for review
      </label>
    </div>
  );
}
