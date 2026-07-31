import { describe, it, expect } from "vitest";
import { makeCanon, questionStatus, matchesReviewFilters } from "@/lib/examReview";
import type { ReviewStatus as Status } from "@/lib/examReview";
import type { DomainOut, QuestionResultView } from "@/types/api";

// Identity-ish canon: codes pass through; blank -> "Unassigned".
const canon = (raw: string | null | undefined) => (raw ?? "").trim() || "Unassigned";

function q(id: number, domain: string, status: Status): QuestionResultView {
  const correct = status === "correct";
  const answeredWrong = status === "incorrect";
  return {
    id, stem: "", topic_id: 1, domain, task: null, enablers: [], remarks: null,
    difficulty: "medium", question_type: "single_choice", explanation: null,
    is_user_correct: correct,
    options: [
      { option_letter: "A", text: "a", is_correct: false, reasoning: null,
        selected_by_user: answeredWrong },
      { option_letter: "B", text: "b", is_correct: true, reasoning: null,
        selected_by_user: correct },
    ],
  };
}

const QS: QuestionResultView[] = [
  q(1, "D-I", "correct"),
  q(2, "D-I", "incorrect"),
  q(3, "D-III", "incorrect"),
  q(4, "D-III", "unanswered"),
  q(5, "D-III", "correct"),
];

const ids = (f: { domain: string | null; status: Status | null }) =>
  QS.filter((x) => matchesReviewFilters(x, { ...f, canon })).map((x) => x.id);

describe("questionStatus", () => {
  it("classifies correct / incorrect / unanswered", () => {
    expect(questionStatus(q(0, "D-I", "correct"))).toBe("correct");
    expect(questionStatus(q(0, "D-I", "incorrect"))).toBe("incorrect");
    expect(questionStatus(q(0, "D-I", "unanswered"))).toBe("unanswered");
  });
});

describe("matchesReviewFilters — domain + outcome compose", () => {
  it("no filters → all", () => {
    expect(ids({ domain: null, status: null })).toEqual([1, 2, 3, 4, 5]);
  });
  it("domain only", () => {
    expect(ids({ domain: "D-III", status: null })).toEqual([3, 4, 5]);
  });
  it("status only", () => {
    expect(ids({ domain: null, status: "incorrect" })).toEqual([2, 3]);
  });
  it("domain + incorrect → wrong answers within that domain", () => {
    expect(ids({ domain: "D-III", status: "incorrect" })).toEqual([3]);
  });
  it("domain + unanswered", () => {
    expect(ids({ domain: "D-III", status: "unanswered" })).toEqual([4]);
  });
  it("domain + correct", () => {
    expect(ids({ domain: "D-III", status: "correct" })).toEqual([5]);
    expect(ids({ domain: "D-I", status: "correct" })).toEqual([1]);
  });
  it("empty intersection → none", () => {
    expect(ids({ domain: "D-I", status: "unanswered" })).toEqual([]);
  });
});

describe("makeCanon — legacy domain spelling resolution", () => {
  const domains = [
    { code: "D-I", name: "Trustworthy AI", slug: "trustworthy-ai" },
    { code: "D-II", name: "Identify Business Needs & Solutions", slug: "business-needs" },
    { code: "D-III", name: "Identify Data Needs", slug: "data-needs" },
    { code: "D-IV", name: "Manage AI Model Development & Evaluation", slug: "model-dev-eval" },
    { code: "D-V", name: "Model Operationalization", slug: "operationalization" },
  ] as DomainOut[];
  const canon = makeCanon(domains);

  it("codes, names, slugs pass through to the code", () => {
    expect(canon("D-I")).toBe("D-I");
    expect(canon("trustworthy-ai")).toBe("D-I");
    expect(canon("Identify Data Needs")).toBe("D-III");
  });
  it("'&' vs 'and' and case drift resolve", () => {
    expect(canon("Identify Business Needs and Solutions")).toBe("D-II");
    expect(canon("manage ai model development and evaluation")).toBe("D-IV");
  });
  it("legacy 'code + label' free-text resolves by its leading code", () => {
    expect(canon("D-I Trustworthy")).toBe("D-I");
    expect(canon("D-II Identify Business Needs and Solutions")).toBe("D-II");
    expect(canon("D-V Model Operationalize")).toBe("D-V");
    // Spaced-code spellings exactly as found in the dev DB.
    expect(canon("D I - Trustworthy AI")).toBe("D-I");
    expect(canon("D III -Identify Data Needs")).toBe("D-III");
    expect(canon("D IV - Manage Data model Development and Evaluation")).toBe("D-IV");
  });
  it("blank → Unassigned; unknown text passes through verbatim", () => {
    expect(canon("")).toBe("Unassigned");
    expect(canon(null)).toBe("Unassigned");
    expect(canon("General AI")).toBe("General AI");
  });
  it("filters match legacy-spelled questions under the canonical code", () => {
    const legacy = [q(9, "D-I Trustworthy", "incorrect")];
    const hit = legacy.filter((x) =>
      matchesReviewFilters(x, { domain: "D-I", status: null, canon }));
    expect(hit.map((x) => x.id)).toEqual([9]);
  });
});
