"use client";
import Link from "next/link";
import type { ExamSetSummaryOut } from "@/types/api";

const DIFF_COLORS = {
  easy:   "bg-emerald-50 text-emerald-700 border-emerald-200",
  medium: "bg-amber-50 text-amber-700 border-amber-200",
  hard:   "bg-rose-50 text-rose-700 border-rose-200",
};

export function ExamSetCard({ set }: { set: ExamSetSummaryOut }) {
  return (
    <Link href={`/exams/${set.slug}`}
          className="block bg-white border border-slate-200 rounded-xl p-5
                     hover:border-indigo-300 hover:shadow-sm transition">
      <div className="flex items-start justify-between mb-3">
        <h3 className="font-semibold text-slate-900">{set.name}</h3>
        <span className={`text-xs px-2 py-0.5 rounded border ${DIFF_COLORS[set.difficulty]}`}>
          {set.difficulty}
        </span>
      </div>
      {set.description && (
        <p className="text-sm text-slate-600 mb-4 line-clamp-2">{set.description}</p>
      )}
      <div className="flex items-center justify-between text-xs text-slate-500">
        <span>{set.question_count} questions · {set.time_limit_minutes} min</span>
        <span>{set.passing_score}% to pass</span>
      </div>
      {set.is_premium && (
        <div className="mt-3 text-xs font-medium text-indigo-700">
          ⭐ Premium — subscription required
        </div>
      )}
      {set.user_attempts > 0 && (
        <div className="mt-3 text-xs text-slate-500">
          You have {set.user_attempts} previous attempt{set.user_attempts === 1 ? "" : "s"}
        </div>
      )}
    </Link>
  );
}
