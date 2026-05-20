/**
 * API types — hand-maintained to mirror Pydantic schemas exactly.
 *
 * To regenerate from a running backend:
 *   npx openapi-typescript http://localhost:8000/openapi.json \
 *     -o frontend/src/types/api.generated.ts
 *
 * Then re-export the generated types from this file with friendlier names.
 */

export type UserRole = "user" | "admin" | "super_admin";
export type Difficulty = "easy" | "medium" | "hard";
export type QuestionType = "single_choice" | "multi_choice";
export type AttemptStatus = "in_progress" | "submitted" | "expired";
export type LeadSource =
  | "landing_hero" | "newsletter" | "exit_intent" | "gated_download"
  | "blog" | "pricing_page" | "exam_preview" | "demo_request"
  | "chat_callback";
export type ProviderType =
  | "openai" | "anthropic" | "azure_openai" | "ollama" | "stub";

// ---------- Errors ---------------------------------------------------------
export interface ApiErrorBody {
  code: string;
  message: string;
  fields?: Record<string, string>;
  request_id?: string;
  [k: string]: unknown;
}
export interface ApiErrorResponse { error: ApiErrorBody }

// ---------- Auth & user ----------------------------------------------------
export interface SignupIn {
  email: string;
  password: string;
  name?: string | null;
  consent_marketing?: boolean;
  target_exam_date?: string | null;
}
export interface LoginIn { email: string; password: string }
export interface RefreshIn { refresh_token: string }

export interface UserOut {
  id: number;
  email: string;
  name: string | null;
  role: UserRole;
  created_at: string;
  /** GeoIP-resolved signup country (ISO-3166-1 alpha-2). Surfaced so
   *  /pricing can default the currency picker. Null for legacy users
   *  / private IPs / lookup misses. */
  country?: string | null;
}
export interface UserAdminOut extends UserOut {
  is_active: boolean;
  failed_login_count: number;
  locked_until: string | null;
  last_login_at: string | null;
  /** Set after GDPR self-delete OR admin-triggered soft-delete (via the
   *  /admin/users delete button). When non-null: email is redacted to
   *  "deleted-{id}@redacted.invalid", PII is wiped, login blocked. Admin
   *  UI dims/strikethrough's these rows so they aren't mistaken for
   *  active accounts. Soft-delete (not hard) because the row is FK-
   *  referenced by audit_logs / payments / etc. which must be retained
   *  for compliance. */
  deleted_at: string | null;
  /** GeoIP enrichment (PR-A). Signup-time snapshot — never overwritten
   *  on subsequent logins. `null` for historical users / private-IP
   *  signups / lookup misses. */
  country: string | null;
  city: string | null;
  /** Most-recent login IP (any successful login). 45 chars max
   *  (IPv6 with safety margin). Useful for security forensics. */
  last_login_ip: string | null;
  /** Country resolved from `last_login_ip` at the time of that login.
   *  Updated on every login. Independent of `country` so admin can see
   *  "user signed up in IN, now logging in from SG". */
  last_login_country: string | null;
  has_google: boolean;
  has_password: boolean;
  has_active_subscription: boolean;
  subscription_plan: string | null;
  /** Per-user daily chat-message cap. `null` = fall back to the global
   *  `chat.daily_limit.authenticated` setting; a number is the explicit
   *  override; `0` blocks chat entirely for this user. */
  daily_chat_limit_override: number | null;
}
export interface SubscriptionSummary {
  active: boolean;
  plan: string | null;
  status: string | null;
  current_period_end: string | null;
}
export interface UserDashboardOut {
  user: UserOut;
  subscription: SubscriptionSummary;
  has_google: boolean;
  has_password: boolean;
}
export interface AuthTokens { access: string; refresh: string; user: UserOut }

// ---------- Topic ----------------------------------------------------------
export interface TopicOut { id: number; code: string; name: string; order: number }

// ---------- Question -------------------------------------------------------
export interface QuestionOptionOut {
  option_letter: string;
  text: string;
}
export interface QuestionAttemptView {
  id: number;
  stem: string;
  topic_id: number;
  domain: string | null;
  task: string | null;
  difficulty: Difficulty;
  question_type: QuestionType;
  options: QuestionOptionOut[];
}
export interface QuestionOptionResultOut extends QuestionOptionOut {
  is_correct: boolean;
  reasoning: string | null;
  selected_by_user: boolean;
}
export interface QuestionResultView {
  id: number;
  stem: string;
  topic_id: number;
  domain: string | null;
  task: string | null;
  enablers: string[];
  remarks: string | null;
  difficulty: Difficulty;
  question_type: QuestionType;
  explanation: string | null;
  options: QuestionOptionResultOut[];
  is_user_correct: boolean;
}
export interface QuestionOptionIn {
  option_letter: string;
  text: string;
  is_correct?: boolean;
  reasoning?: string | null;
}
export interface QuestionAdminIn {
  stem: string;
  topic_id: number;
  domain?: string | null;
  task?: string | null;
  enablers?: string[];
  remarks?: string | null;
  difficulty?: Difficulty;
  question_type?: QuestionType;
  explanation?: string | null;
  options: QuestionOptionIn[];
  is_active?: boolean;
}
export interface QuestionInSetRef {
  id: number;
  slug: string;
  name: string;
}

export interface QuestionAdminOut extends QuestionAdminIn {
  id: number;
  /** Sets this question is currently tagged into (display-order). Used
   *  in admin to spot duplicates before tagging into yet another set.
   *  Server-populated via a bulk JOIN — empty list = unattached. */
  in_sets: QuestionInSetRef[];
  created_at: string;
  updated_at: string;
}

// ---------- Exam set & attempt --------------------------------------------
export interface ExamSetSummaryOut {
  id: number;
  name: string;
  slug: string;
  description: string | null;
  difficulty: Difficulty;
  time_limit_minutes: number;
  passing_score: number;
  is_premium: boolean;
  cover_image_url: string | null;
  question_count: number;
  user_attempts: number;
}
export interface ExamSetAdminIn {
  name: string;
  slug: string;
  description?: string | null;
  difficulty?: Difficulty;
  time_limit_minutes?: number;
  passing_score?: number;
  is_active?: boolean;
  is_premium?: boolean;
  display_order?: number;
  cover_image_url?: string | null;
}
export interface AddQuestionsIn { question_ids: number[] }
export interface ReorderIn { items: Array<{ question_id: number; position: number }> }

export interface ExamAttemptOut {
  id: number;
  exam_set: ExamSetSummaryOut;
  started_at: string;
  expires_at: string;
  status: AttemptStatus;
  questions: QuestionAttemptView[];
  user_answers: Record<number, string | null>;
}
export interface AnswerIn {
  question_id: number;
  /** Single-choice questions: option letter or null. */
  selected_letter?: string | null;
  /** Multi-choice questions: list of letters. Empty list = unanswered. */
  selected_letters?: string[] | null;
  marked_for_review?: boolean;
}
export interface PhaseBreakdown {
  topic_code: string;
  topic_name: string;
  correct: number;
  total: number;
  percent: number;
}
export interface SubmitAttemptOut {
  id: number;
  score: number;
  passed: boolean;
  correct_count: number;
  incorrect_count: number;
  unanswered_count: number;
  time_taken_seconds: number;
  questions: QuestionResultView[];
  by_phase: PhaseBreakdown[];
}

// ---------- Leads ----------------------------------------------------------
export interface UtmIn {
  source?: string | null; medium?: string | null;
  campaign?: string | null; term?: string | null; content?: string | null;
}
export interface LeadCreateIn {
  email: string;
  name?: string | null;
  phone?: string | null;
  company?: string | null;
  role?: string | null;
  source: LeadSource;
  landing_url?: string | null;
  utm?: UtmIn | null;
  interests?: string[];
  target_exam_date?: string | null;
  experience_level?: string | null;
  consent_marketing?: boolean;
}
export interface LeadCreateOut { id: number; message: string }
// ---------- FAQ -----------------------------------------------------------
export interface FaqOut {
  id: number;
  question: string;
  answer: string;
  display_order: number;
}
export interface FaqAdminOut extends FaqOut {
  is_active: boolean;
  created_at: string;
  updated_at: string;
}
export interface FaqIn {
  question: string;
  answer: string;
  display_order: number;
  is_active: boolean;
}

// ---------- CMS content pages --------------------------------------------
// Mirrors backend/app/schemas/content_page.py
export type NavVisibility = "always" | "authenticated" | "subscribed" | "hidden";

/** A BlockNote block. We deliberately keep this loose — the canonical
 *  schema lives in @blocknote/core; we just need to round-trip the
 *  JSON to/from the API without losing fields. */
export type BlockNoteBlock = {
  id?: string;
  type: string;
  props?: Record<string, unknown>;
  content?: unknown;
  children?: BlockNoteBlock[];
  [k: string]: unknown;
};

export interface ContentPageOut {
  id: number;
  tenant_id: number;
  slug: string;
  title: string;
  blocks: BlockNoteBlock[];
  nav_visibility: NavVisibility;
  nav_label: string | null;
  nav_order: number;
  is_published: boolean;
  is_landing: boolean;
  is_deleted: boolean;
  deleted_at: string | null;
  deleted_by: number | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

/** Public payload — admin-only fields stripped (tenant_id, deleted_*, etc.). */
export interface ContentPagePublicOut {
  id: number;
  slug: string;
  title: string;
  blocks: BlockNoteBlock[];
  nav_visibility: NavVisibility;
  nav_label: string | null;
  nav_order: number;
  is_landing: boolean;
  updated_at: string;
}

export interface ContentPageNavItemOut {
  slug: string;
  label: string;
  order: number;
}

export interface ContentPageCreateIn {
  slug: string;
  title: string;
  blocks?: BlockNoteBlock[];
  nav_visibility?: NavVisibility;
  nav_label?: string | null;
  nav_order?: number;
  is_published?: boolean;
}

export interface ContentPageUpdateIn {
  slug?: string;
  title?: string;
  blocks?: BlockNoteBlock[];
  nav_visibility?: NavVisibility;
  nav_label?: string | null;
  nav_order?: number;
  is_published?: boolean;
}

// ---------- CMS AI ---------------------------------------------------------
export type CmsBlockType =
  | "paragraph" | "heading" | "bulletListItem" | "numberedListItem";
export type CmsImproveTone =
  | "shorter" | "longer" | "friendlier" | "formal" | "grammar";

export interface CmsGeneratePageIn { prompt: string }
export interface CmsGeneratePageOut { blocks: BlockNoteBlock[] }
export interface CmsFillBlockIn { block_type: CmsBlockType; context: string }
export interface CmsFillBlockOut { text: string }
export interface CmsImproveBlockIn { text: string; tone: CmsImproveTone }
export interface CmsImproveBlockOut { text: string }

// ---------- LMS -----------------------------------------------------------
// Mirrors backend/app/schemas/lms.py
export type EnrollmentType   = "free" | "paid" | "subscription_bundle";
export type CourseDifficulty = "beginner" | "intermediate" | "advanced";
export type LessonType       = "video" | "text" | "quiz" | "checklist" | "live" | "assignment";
export type VideoProvider    = "r2" | "youtube" | "vimeo" | "stream";
export type FileCategory     = "assignment" | "reference" | "starter_code" | "solution";
export type EnrollmentSource = "purchased" | "admin_grant" | "subscription" | "free";
export type QuizQuestionType = "single_choice" | "multi_choice" | "true_false" | "short_answer";

export interface CourseOut {
  id: number;
  tenant_id: number;
  slug: string;
  title: string;
  subtitle: string | null;
  description: string | null;
  cover_image_url: string | null;
  base_price_paise: number;
  currency: string;
  plan_id: number | null;
  enrollment_type: EnrollmentType;
  difficulty: CourseDifficulty;
  language: string;
  estimated_hours: number | null;
  learning_outcomes: string[];
  prerequisites_text: string | null;
  target_audience: string | null;
  completion_threshold_percent: number;
  lead_instructor_id: number | null;
  discussion_url: string | null;
  display_order: number;
  is_published: boolean;
  is_deleted: boolean;
  deleted_at: string | null;
  deleted_by: number | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}
export interface CoursePublicOut {
  id: number;
  slug: string;
  title: string;
  subtitle: string | null;
  description: string | null;
  cover_image_url: string | null;
  base_price_paise: number;
  currency: string;
  enrollment_type: EnrollmentType;
  difficulty: CourseDifficulty;
  language: string;
  estimated_hours: number | null;
  learning_outcomes: string[];
  prerequisites_text: string | null;
  target_audience: string | null;
  completion_threshold_percent: number;
  lead_instructor_id: number | null;
  discussion_url: string | null;
  display_order: number;
}
export interface CourseCreateIn {
  slug: string;
  title: string;
  subtitle?: string | null;
  description?: string | null;
  cover_image_url?: string | null;
  base_price_paise?: number;
  currency?: string;
  plan_id?: number | null;
  enrollment_type?: EnrollmentType;
  difficulty?: CourseDifficulty;
  language?: string;
  estimated_hours?: number | null;
  learning_outcomes?: string[];
  prerequisites_text?: string | null;
  target_audience?: string | null;
  completion_threshold_percent?: number;
  lead_instructor_id?: number | null;
  discussion_url?: string | null;
  display_order?: number;
  is_published?: boolean;
}
export type CourseUpdateIn = Partial<CourseCreateIn>;

export interface ChapterOut {
  id: number;
  tenant_id: number;
  course_id: number;
  title: string;
  description: string | null;
  position: number;
  is_mandatory: boolean;
  is_published: boolean;
  is_deleted: boolean;
  created_at: string;
  updated_at: string;
}
export interface ChapterCreateIn {
  title: string;
  description?: string | null;
  position?: number;
  is_mandatory?: boolean;
  is_published?: boolean;
}
export type ChapterUpdateIn = Partial<ChapterCreateIn>;

export interface LessonOut {
  id: number;
  tenant_id: number;
  chapter_id: number;
  lesson_type: LessonType;
  title: string;
  subtitle: string | null;
  position: number;
  is_mandatory: boolean;
  video_url: string | null;
  video_provider: VideoProvider | null;
  video_object_key: string | null;
  duration_seconds: number | null;
  thumbnail_url: string | null;
  captions_url: string | null;
  body_blocks: BlockNoteBlock[];
  checklist_items: Array<{ text: string; position?: number }>;
  discussion_url: string | null;
  instructor_id: number | null;
  quiz_pass_threshold_percent: number;
  quiz_attempts_allowed: number | null;
  is_free_preview: boolean;
  is_published: boolean;
  is_deleted: boolean;
  created_at: string;
  updated_at: string;
}
export interface LessonCreateIn {
  lesson_type: LessonType;
  title: string;
  subtitle?: string | null;
  position?: number;
  is_mandatory?: boolean;
  video_url?: string | null;
  video_provider?: VideoProvider | null;
  video_object_key?: string | null;
  duration_seconds?: number | null;
  thumbnail_url?: string | null;
  captions_url?: string | null;
  body_blocks?: BlockNoteBlock[];
  checklist_items?: Array<{ text: string }>;
  discussion_url?: string | null;
  instructor_id?: number | null;
  quiz_pass_threshold_percent?: number;
  quiz_attempts_allowed?: number | null;
  is_free_preview?: boolean;
  is_published?: boolean;
}
export type LessonUpdateIn = Partial<LessonCreateIn>;

export interface LessonFileOut {
  id: number;
  tenant_id: number;
  lesson_id: number;
  filename: string;
  file_url: string;
  file_object_key: string | null;
  file_size_bytes: number | null;
  mime_type: string | null;
  description: string | null;
  file_category: FileCategory;
  is_required: boolean;
  position: number;
  uploaded_by_id: number | null;
  created_at: string;
}
export interface LessonFileCreateIn {
  filename: string;
  file_url: string;
  file_object_key?: string | null;
  file_size_bytes?: number | null;
  mime_type?: string | null;
  description?: string | null;
  file_category?: FileCategory;
  is_required?: boolean;
  position?: number;
}

export interface EnrollmentOut {
  id: number;
  tenant_id: number;
  user_id: number;
  course_id: number;
  source: EnrollmentSource;
  enrolled_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  completed_at: string | null;
  last_accessed_at: string | null;
  granted_by_id: number | null;
  grant_reason: string | null;
  payment_id: number | null;
  offer_code_id: number | null;
  created_at: string;
  updated_at: string;
}
export interface EnrollmentGrantIn {
  user_id: number;
  expires_at?: string | null;
  grant_reason: string;
}

export interface LessonProgressOut {
  id: number;
  enrollment_id: number;
  lesson_id: number;
  started_at: string | null;
  first_completed_at: string | null;
  completed_at: string | null;
  last_position_seconds: number;
  watch_time_seconds: number;
  checklist_state: Record<string, unknown>;
}
export interface LessonProgressUpdateIn {
  last_position_seconds?: number;
  watch_time_seconds?: number;
  checklist_state?: Record<string, unknown>;
  mark_completed?: boolean;
}

export interface CourseCategoryOut {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  display_order: number;
}
export interface CourseCategoryCreateIn {
  slug: string;
  name: string;
  description?: string | null;
  display_order?: number;
}
export type CourseCategoryUpdateIn = Partial<CourseCategoryCreateIn>;

export interface CourseAnnouncementOut {
  id: number;
  course_id: number;
  title: string;
  body: string;
  posted_by: number | null;
  posted_at: string;
  is_pinned: boolean;
}
export interface CourseAnnouncementCreateIn {
  title: string;
  body: string;
  is_pinned?: boolean;
}

export interface LessonNoteOut {
  id: number;
  lesson_id: number;
  body: string;
  created_at: string;
  updated_at: string;
}
export interface CourseReviewOut {
  id: number;
  course_id: number;
  user_id: number;
  stars: number;
  body: string | null;
  is_published: boolean;
  created_at: string;
  updated_at: string;
}

export interface QuizOut {
  id: number;
  lesson_id: number;
  pass_threshold_percent: number;
  attempts_allowed: number | null;
  time_limit_seconds: number | null;
  shuffle_questions: boolean;
  show_correct_answers: boolean;
}
export interface QuizConfigUpsertIn {
  pass_threshold_percent?: number;
  attempts_allowed?: number | null;
  time_limit_seconds?: number | null;
  shuffle_questions?: boolean;
  show_correct_answers?: boolean;
}
export interface QuizQuestionOut {
  id: number;
  quiz_id: number;
  position: number;
  question_type: QuizQuestionType;
  question_text: string;
  explanation: string | null;
  points: number;
  accepted_answers: string[];
}
export interface QuizQuestionCreateIn {
  question_type: QuizQuestionType;
  question_text: string;
  explanation?: string | null;
  points?: number;
  position?: number;
  accepted_answers?: string[];
}
export type QuizQuestionUpdateIn = Partial<QuizQuestionCreateIn>;
export interface QuizOptionOut {
  id: number;
  position: number;
  text: string;
  is_correct: boolean;
  reasoning: string | null;
}
export interface QuizOptionCreateIn {
  text: string;
  is_correct?: boolean;
  reasoning?: string | null;
  position?: number;
}
export type QuizOptionUpdateIn = Partial<QuizOptionCreateIn>;
export interface QuizAttemptOut {
  id: number;
  enrollment_id: number;
  quiz_id: number;
  attempt_number: number;
  started_at: string;
  submitted_at: string | null;
  score_points: number;
  max_points: number;
  percent: number;
  passed: boolean;
}
export interface QuizAttemptAnswerIn {
  question_id: number;
  selected_option_ids?: number[];
  short_answer_text?: string | null;
}
export interface QuizAttemptSubmitIn {
  answers: QuizAttemptAnswerIn[];
}

/** Nested course-detail public response.
 *  Endpoint returns { course, is_enrolled, chapters[{...lessons[{...files[]}]}] } */
export interface CourseDetailPublicOut {
  course: CoursePublicOut;
  is_enrolled: boolean;
  chapters: Array<{
    id: number;
    title: string;
    description: string | null;
    position: number;
    is_mandatory: boolean;
    lessons: Array<LessonPublicOut & { files: LessonFileOut[] }>;
  }>;
}
export interface LessonPublicOut {
  id: number;
  chapter_id: number;
  lesson_type: LessonType;
  title: string;
  subtitle: string | null;
  position: number;
  is_mandatory: boolean;
  duration_seconds: number | null;
  thumbnail_url: string | null;
  discussion_url: string | null;
  instructor_id: number | null;
  is_free_preview: boolean;
  video_url: string | null;
  body_blocks: BlockNoteBlock[];
}

// ---------- Landing copy --------------------------------------------------
export interface LandingCopy {
  lead_section_heading: string;
  lead_cta_text: string;
  lead_post_submit_route: string;
  premium_upsell_title: string;
  premium_upsell_body: string;
  /** H1 + supporting paragraph on the public landing page. */
  hero_headline: string;
  hero_subtitle: string;
  /** Banner shown on /exams when the visitor is NOT signed in. */
  exams_anonymous_banner: string;
}

/** Admin-editable site-wide chrome (header + footer). */
export interface SiteChrome {
  brand_name: string;
  tagline: string;
  support_email: string;
  linkedin_url: string;
  youtube_url: string;
  twitter_url: string;
  copyright_text: string;
  show_pricing_link: boolean;
  /** Subtitle shown under "CPMAI Assistant" in the chat-widget header. */
  assistant_widget_subtitle: string;
  /** Starter prompts in the chat widget's empty state. Each entry is
   *  rendered as a clickable chip that pre-fills the chat input.
   *  Empty list disables the suggestions block entirely. */
  assistant_try_asking_suggestions: string[];
  /** Inline message shown to anonymous (not-signed-in) visitors when
   *  they open the chat widget — typically "please sign in to chat".
   *  Same setting the backend's no_identity guardrail raises, so
   *  edits propagate to both surfaces from one place. */
  assistant_anonymous_no_identity_message: string;
}

export interface ContactRow {
  kind: "lead" | "user";
  id: number;
  email: string;
  name: string | null;
  created_at: string;
  // lead-only
  source?: string | null;
  utm_campaign?: string | null;
  consent_marketing?: boolean | null;
  notes?: string | null;
  converted_user_id?: number | null;
  target_exam_date?: string | null;
  /** Rule-based 0..100 score (lead rows only). `null` for user rows
   *  and for leads created before scoring shipped. */
  score?: number | null;
  /** GeoIP enrichment (PR-A). ISO-3166-1 alpha-2 country code (e.g.
   *  "IN"); UI converts to flag emoji via `lib/country-flag.ts`.
   *  `null` for user rows, legacy leads, and private-IP submissions. */
  country?: string | null;
  /** GeoIP city (English transliteration). `null` when MaxMind has
   *  a country-only record (anonymous proxies) or no record at all. */
  city?: string | null;
  // user-only
  role?: string | null;
  has_google?: boolean | null;
  has_password?: boolean | null;
  has_active_subscription?: boolean | null;
  last_login_at?: string | null;
  /** Non-null when the user has been soft-deleted (GDPR self-delete OR
   *  admin delete). UI dims the row + shows a "deleted" badge so it
   *  isn't confused with active accounts. Always null for lead rows. */
  deleted_at?: string | null;
}

export interface LeadAdminOut {
  id: number;
  email: string;
  name: string | null;
  phone: string | null;
  company: string | null;
  role: string | null;
  source: LeadSource;
  landing_url: string | null;
  utm_source: string | null;
  utm_medium: string | null;
  utm_campaign: string | null;
  interests: string[];
  target_exam_date: string | null;
  experience_level: string | null;
  consent_marketing: boolean;
  consent_at: string | null;
  converted_user_id: number | null;
  notes: string | null;
  created_at: string;
  /** Rule-based 0..100 score. `null` for leads created before the
   *  scoring feature shipped; backfilled when admin saves notes. */
  score: number | null;
  /** GeoIP enrichment (PR-A). ISO-3166-1 alpha-2 country code. */
  country: string | null;
  /** GeoIP city, English transliteration. */
  city: string | null;
}

// ---------- GeoIP admin -----------------------------------------------------
export interface GeoIPStatusOut {
  database_present: boolean;
  database_path: string;
  database_size_bytes: number | null;
  database_size_human: string | null;
  database_mtime: string | null;
  database_age_days: number | null;
  database_stale: boolean;
  last_lookup_count: number;
  credentials_configured: boolean;
  /** Schedule preview, sourced from geoip.refresh_schedule setting. */
  refresh_schedule: string | null;
  refresh_schedule_human: string | null;
  refresh_schedule_next_runs: string[];
  refresh_enabled: boolean;
}

export interface GeoIPSchedulePreviewIn {
  expression: string;
  count?: number;
}

export interface GeoIPSchedulePreviewOut {
  expression: string;
  ok: boolean;
  reason: string;
  human: string;
  next_runs: string[];
}

export interface GeoIPRefreshOut {
  updated: boolean;
  database_date: string | null;
  database_size_bytes: number;
  bytes_downloaded: number;
  elapsed_seconds: number;
  message: string;
}

export interface GeoIPTestKeyOut {
  ok: boolean;
  status_code: number | null;
  message: string;
  latest_db_date: string | null;
}

export interface GeoIPLookupOut {
  ip: string;
  found: boolean;
  country?: string | null;
  city?: string | null;
  latitude?: number | null;
  longitude?: number | null;
}

/** UI tier label for a lead score. Matches `app/services/lead_scoring.py:
 *  score_tier`. Drives the chip color on the admin list. */
export type LeadTier = "hot" | "warm" | "cold" | "unknown";

export function leadTier(score: number | null | undefined): LeadTier {
  if (score === null || score === undefined) return "unknown";
  if (score >= 70) return "hot";
  if (score >= 40) return "warm";
  return "cold";
}

// ---------- Payments -------------------------------------------------------
export interface CreateOrderIn {
  plan_slug: string;
  offer_code?: string | null;
  referrer?: string | null;
  /** ISO-4217 code. Default "INR" — pass the user's selected currency
   *  so Razorpay opens the popup in that currency. Unsupported codes
   *  get rejected by the backend (we don't silently fall back when
   *  we're about to actually charge). */
  currency?: string;
}
export interface CreateOrderOut {
  order_id: string;
  amount: number;             // minor units of `currency` (paise / cents)
  currency: string;           // what the gateway will charge in
  /** Which gateway minted this order. Frontend reads this to decide
   *  whether to render the Razorpay popup or the PayPal Smart Button. */
  provider: "razorpay" | "paypal";
  /** Set when provider="razorpay". Public key — ship to Razorpay SDK. */
  razorpay_key_id: string | null;
  /** Set when provider="paypal". Client ID — ship to PayPal JS SDK. */
  paypal_client_id: string | null;
  /** Set when provider="paypal". Hosted-page redirect URL — fallback
   *  if the Smart Button can't render (very old browsers / blocked
   *  third-party scripts). */
  paypal_approval_url: string | null;
  plan_slug: string;
  plan_name: string;
  base_amount: number;        // INR paise (canonical breakdown stays in INR)
  discount_amount: number;    // INR paise
  subtotal_amount: number;    // post-discount, pre-GST, INR paise
  gst_percent: number;
  gst_amount: number;         // 0 for non-INR orders (no Indian GST)
  offer_code: string | null;
  offer_applied: boolean;
  offer_reason: string | null;
  /** INR-side reference final (= subtotal + GST). For non-INR orders
   *  the actual charge is `amount` in `currency`; this stays for
   *  receipts and admin audits. */
  final_inr_paise?: number;
  /** FX rate used (INR per 1 unit of `currency`). 1.0 for INR. */
  fx_rate?: number;
}

/** PayPal 2-step capture body — sent from Smart Button onApprove. */
export interface PayPalCaptureIn {
  order_id: string;
}
export interface PayPalCaptureOut {
  /** "active" = subscription live; "pending" = PayPal in risk review,
   *  webhook will activate later. */
  status: "active" | "pending";
  plan_slug: string;
  expires_at?: string | null;
}
export interface VerifyPaymentIn {
  order_id: string;
  payment_id: string;
  signature: string;
}
export interface VerifyPaymentOut {
  status: "active";
  plan_slug: string;
  expires_at: string;
}

// ---------- Plans / Offers / Pricing --------------------------------------
export type BundleType = "exam_bundle" | "course_bundle" | "custom";

export interface PlanExamSetRef { id: number; slug: string; name: string }
export interface PlanCourseRef  { id: number; slug: string; title: string }

export interface PlanPublicOut {
  id: number;
  name: string;
  slug: string;
  description: string | null;
  bundle_type: string;
  base_price_paise: number;
  discount_price_paise: number | null;
  currency: string;
  duration_days: number;
  perks: Record<string, unknown>;
  exam_sets: PlanExamSetRef[];
  courses: PlanCourseRef[];
}

export interface PlanAdminOut extends PlanPublicOut {
  is_active: boolean;
  display_order: number;
  created_at: string;
  updated_at: string;
}

export interface PlanCreate {
  name: string;
  slug: string;
  description?: string | null;
  bundle_type: BundleType;
  base_price_paise: number;
  discount_price_paise?: number | null;
  currency?: string;
  duration_days?: number;
  perks?: Record<string, unknown>;
  is_active?: boolean;
  display_order?: number;
  exam_set_ids?: number[];
  course_ids?: number[];
}

export interface PlanUpdate {
  name?: string;
  description?: string | null;
  bundle_type?: BundleType;
  base_price_paise?: number;
  discount_price_paise?: number | null;
  duration_days?: number;
  perks?: Record<string, unknown>;
  is_active?: boolean;
  display_order?: number;
  exam_set_ids?: number[];
  course_ids?: number[];
}

export type DiscountType = "percent" | "flat";

export interface OfferCodeAdminOut {
  id: number;
  code: string;
  description: string | null;
  discount_type: DiscountType;
  discount_value: number;
  valid_from: string | null;
  valid_until: string | null;
  max_redemptions: number | null;
  used_count: number;
  applies_to_plan_ids: number[] | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface OfferCodeCreate {
  code: string;
  description?: string | null;
  discount_type: DiscountType;
  discount_value: number;
  valid_from?: string | null;
  valid_until?: string | null;
  max_redemptions?: number | null;
  applies_to_plan_ids?: number[] | null;
  is_active?: boolean;
}

export interface OfferCodeUpdate {
  description?: string | null;
  discount_type?: DiscountType;
  discount_value?: number;
  valid_from?: string | null;
  valid_until?: string | null;
  max_redemptions?: number | null;
  applies_to_plan_ids?: number[] | null;
  is_active?: boolean;
}

export interface PriceQuoteOut {
  plan_id: number;
  plan_slug: string;
  plan_name: string;
  currency: string;
  base_price_paise: number;
  discount_price_paise: number | null;
  effective_before_offer_paise: number;
  offer_code: string | null;
  offer_applied: boolean;
  offer_reason: string | null;
  offer_discount_paise: number;
  // Pre-GST subtotal (post-offer). UI shows this as the "Subtotal" line.
  subtotal_paise: number;
  // GST line — gst_percent==0 means "no GST line shown".
  gst_percent: number;
  gst_paise: number;
  // final_price_paise = subtotal_paise + gst_paise. What an INR-currency
  // user pays. Non-INR users pay display_amount_minor in display_currency.
  final_price_paise: number;
  stack_offer_with_discount: boolean;
  // Display block — currency the caller asked us to compute for.
  // For non-INR + LIVE source: subtotal-at-mid-market + transparent
  // markup line = total. UI breaks out the markup so the buyer can
  // see it on the receipt instead of having it baked into the rate.
  display_currency: string;
  display_amount_minor: number;        // minor units of display_currency
  display_fx_rate: number | null;      // effective rate (post-markup for LIVE)
  display_fx_rate_raw?: number | null; // raw mid-market (pre-markup, LIVE/STALE only)
  display_currency_supported: boolean;
  display_fx_source?: string;          // "inr"|"live"|"override"|"stale"|"unavailable"
  display_fx_fetched_at?: string | null;
  display_subtotal_minor?: number;     // amount at mid-market, pre-markup
  display_markup_percent?: number;
  display_markup_minor?: number;       // international processing fee
  // Ceiling delta to the next whole major unit. Razorpay International
  // accepts only whole units for some currencies (GBP confirmed in prod).
  // Zero for INR; non-zero when the pre-round total had fractional units.
  display_rounding_adjustment_minor?: number;
}

// ---------- Admin FX dashboard --------------------------------------------
export interface FXCurrencyStatus {
  code: string;
  symbol: string;
  razorpay_supported: boolean;
  frankfurter_supported: boolean;
  has_live_rate: boolean;
  has_override: boolean;
  raw_inr_per_unit: number | null;
  effective_inr_per_unit: number | null;
  source: string;                       // RateSource enum value
  in_picker: boolean;
}
export interface FXStatusOut {
  last_fetched_at: string | null;
  age_days: number | null;
  stale: boolean;
  markup_percent: number;
  currencies: FXCurrencyStatus[];
}
export interface FXRefreshOut {
  updated: boolean;
  fetched_at: string | null;
  rates_count: number;
  rejected_codes: string[];
  elapsed_seconds: number;
  message: string;
}

export interface CurrencyOption {
  code: string;        // ISO-4217 (e.g. "USD")
  symbol: string;      // display symbol (e.g. "$")
  has_fx_rate: boolean;  // false if admin half-configured (code listed but no FX rate)
}
export interface CurrenciesOut {
  options: CurrencyOption[];
}

// ---------- Assistant ------------------------------------------------------
export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}
export interface AssistantRequest { message: string; history?: ChatMessage[] }
export interface AssistantCitation { source: string; title: string; url: string | null }
export interface SuggestedAction { label: string; url: string }
// Legacy flow emits one of the five handler-intent values. The
// agentic flow doesn't have a per-handler intent (the router picks
// tools, not an intent), so it surfaces the literal "agentic" in
// this slot. The widget doesn't currently branch on this — but it
// keeps the wire shape honest and makes a future "render differently
// per flow" treatment trivial.
export type AssistantIntent =
  | "account" | "faq" | "content" | "insights" | "pmi_reference"
  | "agentic";
export interface AssistantResponse {
  /** AssistantLog row id for this turn. Null on older clients / pre-HITL
   *  responses. Required to flag a turn via /assistant/turns/{id}/flag. */
  turn_id: number | null;
  intent: AssistantIntent;
  intent_confidence: number;
  message: string;
  citations: AssistantCitation[];
  suggested_actions: SuggestedAction[];
  provider: string;
  model_version: string | null;
  is_ai_generated: boolean;
  disclaimer: string;
}
export interface ChatQuota {
  used: number; limit: number; remaining: number; reset_at: string;
}

// ---------- Settings & LLM providers --------------------------------------
export interface SettingOut {
  key: string;
  value: unknown;
  description: string | null;
  updated_at: string | null;
  /** When true, the value is a secret. The `value` field will be a
   *  masked representation (e.g. "••••6e4f"), and the UI should render
   *  a `SecretInput` (write-only) instead of a regular text input. */
  is_secret?: boolean;
}
export interface SettingUpdate { value: unknown }

export interface LLMProviderOut {
  id: number;
  name: string;
  provider_type: ProviderType;
  model: string;
  base_url: string | null;
  config: Record<string, unknown>;
  is_enabled: boolean;
  priority: number;
  is_active: boolean;
  has_api_key: boolean;
}
export interface LLMProviderCreate {
  name: string;
  provider_type: ProviderType;
  model: string;
  api_key?: string | null;
  base_url?: string | null;
  config?: Record<string, unknown> | null;
  is_enabled?: boolean;
  priority?: number;
}
export interface LLMProviderUpdate {
  name?: string | null;
  model?: string | null;
  api_key?: string | null;
  base_url?: string | null;
  config?: Record<string, unknown> | null;
  is_enabled?: boolean | null;
  priority?: number | null;
}

// ---------- Payment providers --------------------------------------------
export type PaymentProviderType = "razorpay" | "paypal" | "stripe";
export type PaymentMode = "test" | "live";

export interface PaymentProviderOut {
  id: number;
  name: string;
  provider_type: PaymentProviderType;
  mode: PaymentMode;
  display_name: string | null;
  public_key: string | null;
  config: Record<string, unknown>;
  is_enabled: boolean;
  priority: number;
  /** True if this is the INR-rail provider (typically Razorpay). */
  is_active: boolean;
  /** True if this is the non-INR-rail provider (typically PayPal). */
  is_non_inr_active: boolean;
  has_api_secret: boolean;
  has_webhook_secret: boolean;
}
export interface PaymentProviderCreate {
  name: string;
  provider_type?: PaymentProviderType;
  mode?: PaymentMode;
  display_name?: string | null;
  public_key: string;
  api_secret: string;
  webhook_secret?: string | null;
  config?: Record<string, unknown> | null;
  is_enabled?: boolean;
  priority?: number;
}
export interface PaymentProviderUpdate {
  name?: string | null;
  mode?: PaymentMode | null;
  display_name?: string | null;
  public_key?: string | null;
  api_secret?: string | null;
  webhook_secret?: string | null;
  config?: Record<string, unknown> | null;
  is_enabled?: boolean | null;
  priority?: number | null;
}

// ---------- Exam-set linked questions (admin view) -----------------------
export interface ExamSetLinkedQuestion {
  position: number;
  question: QuestionAdminOut;
}
