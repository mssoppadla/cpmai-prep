"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { admin, content as contentApi, ApiError } from "@/lib/api";
import type { Difficulty, QuestionAdminIn, QuestionOptionIn } from "@/types/api";

const LETTERS = ["A", "B", "C", "D", "E", "F"];
const blankOption = (i: number): QuestionOptionIn => ({
  option_letter: LETTERS[i], text: "", is_correct: false, reasoning: "",
});

export default function QuestionEditorPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const isNew = id === "new";

  const [topics, setTopics] = useState<Array<{id:number;code:string;name:string}>>([]);
  const [form, setForm] = useState<QuestionAdminIn>({
    stem: "", topic_id: 0,
    domain: "", task: "", enablers: [], remarks: "",
    difficulty: "medium", explanation: "",
    options: [blankOption(0), blankOption(1), blankOption(2), blankOption(3)],
    is_active: true,
  });
  const [enablersText, setEnablersText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    contentApi.topics().then(t => {
      setTopics(t);
      if (isNew && t.length > 0) setForm(f => ({ ...f, topic_id: t[0].id }));
    });
    if (!isNew) {
      admin.questions.get(Number(id))
        .then(q => {
          setForm({
            stem: q.stem, topic_id: q.topic_id,
            domain: q.domain ?? "", task: q.task ?? "",
            enablers: q.enablers ?? [],
            remarks: q.remarks ?? "",
            difficulty: q.difficulty ?? "medium",
            explanation: q.explanation ?? "",
            options: q.options.map(o => ({
              option_letter: o.option_letter, text: o.text,
              is_correct: o.is_correct ?? false, reasoning: o.reasoning ?? "",
            })),
            is_active: q.is_active ?? true,
          });
          setEnablersText((q.enablers ?? []).join(", "));
        })
        .catch((e: ApiError) => setErr(e.body.message));
    }
  }, [id, isNew]);

  function setOption(i: number, patch: Partial<QuestionOptionIn>) {
    setForm(f => ({
      ...f, options: f.options.map((o, j) => j === i ? { ...o, ...patch } : o),
    }));
  }
  function setCorrect(i: number) {
    setForm(f => ({
      ...f, options: f.options.map((o, j) => ({ ...o, is_correct: j === i })),
    }));
  }
  function addOption() {
    if (form.options.length >= 6) return;
    setForm(f => ({
      ...f, options: [...f.options, blankOption(f.options.length)],
    }));
  }
  function removeOption(i: number) {
    if (form.options.length <= 2) return;
    setForm(f => ({
      ...f, options: f.options.filter((_, j) => j !== i)
        .map((o, j) => ({ ...o, option_letter: LETTERS[j] })),
    }));
  }

  async function save() {
    setBusy(true); setErr(null);
    const payload: QuestionAdminIn = {
      ...form,
      enablers: enablersText.split(",").map(s => s.trim()).filter(Boolean),
      domain: form.domain || null,
      task: form.task || null,
      remarks: form.remarks || null,
      explanation: form.explanation || null,
    };
    try {
      if (isNew) {
        const created = await admin.questions.create(payload);
        router.push(`/admin/questions/${created.id}`);
      } else {
        await admin.questions.update(Number(id), payload);
      }
    } catch (e) {
      const ae = e as ApiError;
      const msg = ae.body.message + (ae.body.fields
        ? " (" + Object.entries(ae.body.fields)
            .map(([k, v]) => `${k}: ${v}`).join(", ") + ")"
        : "");
      setErr(msg);
    } finally { setBusy(false); }
  }

  const correctCount = form.options.filter(o => o.is_correct).length;
  const validOptions = correctCount === 1
    && form.options.every(o => o.text.trim().length > 0)
    && new Set(form.options.map(o => o.option_letter)).size === form.options.length;
  const canSave = form.stem.length >= 10 && form.topic_id > 0 && validOptions;

  return (
    <div className="p-8 max-w-4xl">
      <Link href="/admin/questions"
            className="text-sm text-slate-500 hover:text-indigo-600">
        ← All questions
      </Link>
      <h1 className="text-2xl font-bold text-slate-900 mt-2 mb-6">
        {isNew ? "New question" : `Edit question #${id}`}
      </h1>

      {err && <div className="bg-rose-50 border border-rose-200 text-rose-700
                              p-3 rounded-lg mb-4 text-sm">{err}</div>}

      <div className="bg-white border border-slate-200 rounded-xl p-6 space-y-5">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Question stem
          </label>
          <div className="flex items-center gap-2">
            <Link href="/admin/questions"
                  className="px-4 py-2 text-sm font-medium text-slate-700 bg-white
                             border border-slate-300 rounded-lg hover:bg-slate-50">
              Cancel
            </Link>
            <button onClick={save} disabled={!canSave || busy}
                    className="px-5 py-2 text-sm font-medium text-white bg-indigo-600
                               rounded-lg hover:bg-indigo-700 disabled:opacity-50">
              {busy ? "Saving…" : (isNew ? "Create question" : "Save changes")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

const input = "w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none";
