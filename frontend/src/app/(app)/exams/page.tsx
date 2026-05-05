"use client";
import { useEffect, useState } from "react";
import { exams as examsApi, ApiError } from "@/lib/api";
import type { ExamSetSummaryOut } from "@/types/api";
import { ExamSetCard } from "@/components/exam/ExamSetCard";

export default function ExamSetsPage() {
  const [sets, setSets] = useState<ExamSetSummaryOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    examsApi.listSets()
      .then(setSets)
      .catch((e: ApiError) => setError(e.body.message));
  }, []);

  return (
    <main className="max-w-5xl mx-auto px-6 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-slate-900">Mock Exams</h1>
        <p className="text-slate-600 mt-2">
          Pick a set to start. Each set is a complete CPMAI exam simulation.
        </p>
      </header>
      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 p-4 rounded-lg mb-6">
          {error}
        </div>
      )}
      {!sets ? (
        <div className="text-slate-500">Loading...</div>
      ) : sets.length === 0 ? (
        <div className="text-slate-500">No exam sets available yet.</div>
      ) : (
        <div className="grid sm:grid-cols-2 gap-4">
          {sets.map((s) => <ExamSetCard key={s.id} set={s} />)}
        </div>
      )}
    </main>
  );
}
