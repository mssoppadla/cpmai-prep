/**
 * Pure helpers for filtering the post-exam question review.
 *
 * The results screen lets a learner narrow the review by ECO domain AND by
 * outcome (correct / incorrect / unanswered) at the same time — e.g. "show
 * the questions I got wrong in Data Needs". Keeping the logic here (rather
 * than inline in the page) makes the combined behaviour unit-testable.
 */
import type { QuestionResultView } from "@/types/api";

export type ReviewStatus = "correct" | "incorrect" | "unanswered";

/** A question's outcome. Incorrect vs unanswered is decided by whether the
 *  learner selected any option (both have is_user_correct === false). */
export function questionStatus(q: QuestionResultView): ReviewStatus {
  if (q.is_user_correct) return "correct";
  return q.options.some((o) => o.selected_by_user) ? "incorrect" : "unanswered";
}

export interface ReviewFilters {
  /** Canonical ECO domain code to keep, or null for all domains. */
  domain: string | null;
  /** Outcome to keep, or null for all outcomes. */
  status: ReviewStatus | null;
  /** Resolves a question's stored domain value to its canonical code, so the
   *  filter matches the breakdown rows even for legacy name/slug values. */
  canon: (raw: string | null | undefined) => string;
}

/** True when a question passes BOTH the active domain and status filters.
 *  Either filter being null means "don't constrain on that axis", so the two
 *  compose: domain-only, status-only, both, or neither. */
export function matchesReviewFilters(q: QuestionResultView, f: ReviewFilters): boolean {
  if (f.domain && f.canon(q.domain) !== f.domain) return false;
  if (f.status && questionStatus(q) !== f.status) return false;
  return true;
}
