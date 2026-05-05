"use client";
import type { QuestionResultView } from "@/types/api";

export function QuestionResultCard({
  result, index,
}: { result: QuestionResultView; index: number }) {
  const correctOption = result.options.find(o => o.is_correct);
  const userOption = result.options.find(o => o.selected_by_user);

  return (
    <div className={`bg-white rounded-xl border p-6 ${
      result.is_user_correct ? "border-emerald-300" : "border-rose-200"
    }`}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium text-slate-500">
          Question {index + 1}
        </span>
        <span className={`text-xs font-semibold px-2 py-1 rounded ${
          result.is_user_correct
            ? "bg-emerald-100 text-emerald-800"
            : "bg-rose-100 text-rose-800"
        }`}>
          {result.is_user_correct ? "✓ Correct" : userOption ? "✗ Incorrect" : "○ Unanswered"}
        </span>
      </div>

      <h3 className="text-base font-semibold text-slate-900 mb-2 leading-relaxed">
        {result.stem}
      </h3>

      {(result.domain || result.task) && (
        <div className="flex flex-wrap gap-2 mb-4 text-xs">
          {result.domain && (
            <span className="px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded">
              {result.domain}
            </span>
          )}
          {result.task && (
            <span className="px-2 py-0.5 bg-slate-100 text-slate-700 rounded">
              {result.task}
            </span>
          )}
        </div>
      )}

      {/* Each option with its reasoning */}
      <div className="space-y-3 mb-5">
        {result.options.map((opt) => {
          const isCorrect = opt.is_correct;
          const isUserChoice = opt.selected_by_user;
          const wrapperClass = isCorrect
            ? "border-emerald-300 bg-emerald-50"
            : isUserChoice
              ? "border-rose-300 bg-rose-50"
              : "border-slate-200 bg-slate-50/50";
          const letterClass = isCorrect
            ? "bg-emerald-600 border-emerald-600 text-white"
            : isUserChoice
              ? "bg-rose-600 border-rose-600 text-white"
              : "bg-white border-slate-300 text-slate-500";
          return (
            <div key={opt.option_letter}
                 className={`border rounded-lg p-3 ${wrapperClass}`}>
              <div className="flex items-start gap-3">
                <span className={`w-6 h-6 rounded-full border-2 flex items-center
                                  justify-center mt-0.5 font-bold text-xs flex-shrink-0
                                  ${letterClass}`}>
                  {opt.option_letter}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-slate-900">{opt.text}</div>
                  <div className="flex items-center gap-2 mt-1.5">
                    {isCorrect && (
                      <span className="text-xs font-semibold text-emerald-700">
                        ✓ Correct answer
                      </span>
                    )}
                    {isUserChoice && (
                      <span className="text-xs font-semibold text-slate-700">
                        Your choice
                      </span>
                    )}
                  </div>
                  {opt.reasoning && (
                    <div className={`mt-2 text-sm leading-relaxed ${
                      isCorrect ? "text-emerald-900"
                                : isUserChoice ? "text-rose-900"
                                              : "text-slate-600"
                    }`}>
                      <strong>{isCorrect ? "Why this is correct: "
                                          : "Why this is wrong: "}</strong>
                      {opt.reasoning}
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* General explanation */}
      {result.explanation && (
        <div className="border-t border-slate-200 pt-4 text-sm text-slate-700 leading-relaxed">
          <strong className="text-slate-900">Explanation:</strong>{" "}
          {result.explanation}
        </div>
      )}

      {/* Metadata footer */}
      {(result.enablers?.length || result.remarks) && (
        <div className="border-t border-slate-200 pt-4 mt-4 space-y-2">
          {result.enablers?.length > 0 && (
            <div className="text-xs">
              <span className="text-slate-500 font-medium">Enablers:</span>{" "}
              {result.enablers.map((e) => (
                <span key={e} className="inline-block mr-1.5 px-2 py-0.5
                                          bg-slate-100 text-slate-700 rounded">
                  {e}
                </span>
              ))}
            </div>
          )}
          {result.remarks && (
            <div className="text-xs text-slate-500 italic">{result.remarks}</div>
          )}
        </div>
      )}
    </div>
  );
}
