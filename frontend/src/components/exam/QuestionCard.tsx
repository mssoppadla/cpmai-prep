"use client";
import type { QuestionAttemptView } from "@/types/api";

interface Props {
  question: QuestionAttemptView;
  index: number;
  total: number;
  selected: string | null;
  markedForReview: boolean;
  onSelect: (letter: string | null) => void;
  onToggleReview: () => void;
}

export function QuestionCard({
  question, index, total, selected, markedForReview, onSelect, onToggleReview,
}: Props) {
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
          return (
            <button
              key={opt.option_letter}
              type="button"
              onClick={() => onSelect(isSelected ? null : opt.option_letter)}
              className={`w-full text-left flex items-start gap-3 p-3 rounded-lg border
                          transition ${isSelected
                  ? "bg-indigo-50 border-indigo-300"
                  : "bg-white border-slate-200 hover:border-slate-300"}`}
            >
              <span className={`w-6 h-6 rounded-full border-2 flex items-center
                                justify-center mt-0.5 font-bold text-xs flex-shrink-0
                                ${isSelected
                  ? "bg-indigo-600 border-indigo-600 text-white"
                  : "border-slate-300 text-slate-500"}`}>
                {opt.option_letter}
              </span>
              <span className="text-sm text-slate-700 leading-relaxed pt-0.5">
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
