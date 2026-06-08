import { describe, it, expect } from "vitest";
import { questionStatus, matchesReviewFilters } from "@/lib/examReview";
import type { ReviewStatus as Status } from "@/lib/examReview";
import type { QuestionResultView } from "@/types/api";

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
