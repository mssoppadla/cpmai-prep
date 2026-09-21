"use client";
/**
 * Standalone question editor (deep links from exam-set pages, and
 * "new"). Day-to-day editing happens in the side panel on
 * /admin/questions, which keeps the list's filters in place; this page
 * reuses the same form so both stay identical.
 */
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { QuestionEditorForm } from "@/components/admin/QuestionEditorForm";

export default function QuestionEditorPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const isNew = id === "new";
  const [dirty, setDirty] = useState(false);

  // Browser-level guard: closing the tab / hard navigation with edits.
  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  return (
    <div className="p-4 sm:p-8 max-w-4xl">
      <Link href="/admin/questions"
            onClick={(e) => { if (dirty && !confirm("You have unsaved changes. Leave and discard them?")) e.preventDefault(); }}
            className="text-sm text-slate-500 hover:text-indigo-600">
        ← All questions
      </Link>
      <h1 className="text-2xl font-bold text-slate-900 mt-2 mb-6">
        {isNew ? "New question" : `Edit question #${id}`}
      </h1>
      <QuestionEditorForm
        questionId={isNew ? "new" : Number(id)}
        onDirtyChange={setDirty}
        onSaved={(row, wasNew) => { if (wasNew) router.push(`/admin/questions/${row.id}`); }}
        onCancel={() => {
          if (dirty && !confirm("Discard your unsaved changes?")) return;
          router.push("/admin/questions");
        }}
      />
    </div>
  );
}
