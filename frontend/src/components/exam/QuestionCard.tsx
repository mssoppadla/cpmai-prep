"use client";
import { useCallback } from "react";
import type { QuestionAttemptView } from "@/types/api";
import { AnnotatableText, type TextRange } from "./AnnotatableText";

export type Tool = "none" | "highlight" | "strike" | "eraser";

/** Per-target ranges keyed by `stem` or `option-A` / `option-B` etc. */
export type QuestionRanges = Record<string, TextRange[]>;

interface Props {
  question: QuestionAttemptView;
  index: number;
  total: number;
  /** Set of currently-picked option letters. Single-choice questions
   *  hold 0 or 1 letter; multi-choice hold any number. Empty = unanswered. */
  selected: string[];
  markedForReview: boolean;
  tool: Tool;
  ranges: QuestionRanges;
  /** Always called with the new full set after a click. */
  onSelect: (next: string[]) => void;
  onToggleReview: () => void;
  onRangesChange: (next: QuestionRanges) => void;
}

/**
 * Question + options card.
 *
 * Stem text + each option's text render through AnnotatableText, which
 * lets the learner drag-select to highlight or strike via the toolbox.
 *
 * Picking an answer happens via the letter pill on the left of each
 * option. The pill is a radio-button look for single-choice questions
 * (one selection at a time, click again to deselect) and a square
 * checkbox look for multi-choice (independent toggles, multiple ok).
 * Clicking the option text itself does NOT toggle — that surface is
 * reserved for text selection / annotation.
 */
export function QuestionCard({
  question, index, total, selected, markedForReview,
  tool, ranges, onSelect, onToggleReview, onRangesChange,
}: Props) {
  const updateTarget = useCallback(
    (target: string, next: TextRange[]) => {
      onRangesChange({ ...ranges, [target]: next });
    },
    [ranges, onRangesChange],
  );

  const isMulti = question.question_type === "multi_choice";

  function clickOption(letter: string, isSelected: boolean) {
    if (isMulti) {
      // Toggle this letter in the set independently of the others.
      const next = isSelected
        ? selected.filter((l) => l !== letter)
        : [...selected, letter];
      onSelect(next);
    } else {
      // Single-choice: clicking selected = deselect; otherwise replace.
      onSelect(isSelected ? [] : [letter]);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-6">
      <div className="flex items-center justify-between mb-4 text-sm text-slate-500">
        <span>Question {index + 1} of {total}</span>
        <div className="flex items-center gap-2">
          {isMulti && (
            <span className="px-2 py-0.5 bg-amber-50 text-amber-700 rounded text-xs font-medium">
              Pick all that apply
            </span>
          )}
          {question.domain && (
            <span className="px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded">
              {question.domain}
            </span>
          )}
        </div>
      </div>

      <h2 className="text-lg font-semibold text-slate-900 leading-relaxed mb-6">
        <AnnotatableText
          text={question.stem}
          ranges={ranges["stem"] ?? []}
          tool={tool}
          onChange={(next) => updateTarget("stem", next)}
        />
      </h2>

      <div className="space-y-2">
        {question.options.map((opt) => {
          const isSelected = selected.includes(opt.option_letter);
          const targetKey = `option-${opt.option_letter}`;
          return (
            <div
              key={opt.option_letter}
              className={`flex items-start gap-3 p-3 rounded-lg border transition ${
                isSelected
                  ? "bg-indigo-50 border-indigo-300"
                  : "bg-white border-slate-200"
              }`}
            >
              <button
                type="button"
                onClick={() => clickOption(opt.option_letter, isSelected)}
                aria-label={`Select option ${opt.option_letter}`}
                aria-pressed={isSelected}
                role={isMulti ? "checkbox" : "radio"}
                aria-checked={isSelected}
                className={`w-6 h-6 ${isMulti ? "rounded" : "rounded-full"}
                            border-2 flex items-center justify-center mt-0.5
                            font-bold text-xs flex-shrink-0 transition ${
                              isSelected
                                ? "bg-indigo-600 border-indigo-600 text-white"
                                : "border-slate-300 text-slate-500 hover:border-slate-500"
                            }`}
              >
                {opt.option_letter}
              </button>
              <span className="text-sm text-slate-700 leading-relaxed pt-0.5 flex-1">
                <AnnotatableText
                  text={opt.text}
                  ranges={ranges[targetKey] ?? []}
                  tool={tool}
                  onChange={(next) => updateTarget(targetKey, next)}
                />
              </span>
            </div>
          );
        })}
      </div>

      <label className="mt-5 flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
        <input type="checkbox" checked={markedForReview}
               onChange={onToggleReview}
               className="rounded border-slate-300" />
        Mark for review
      </label>
    </div>
  );
}
