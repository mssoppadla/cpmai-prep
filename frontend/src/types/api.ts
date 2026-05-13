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

// ---------- Landing copy --------------------------------------------------
export interface LandingCopy {
  lead_section_heading: string;
  lead_cta_text: string;
  lead_post_submit_route: string;
  premium_upsell_title: string;
  premium_upsell_body: string;
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
}
export interface CreateOrderOut {
  order_id: string;
  amount: number;             // final amount (post-discount + GST)
  currency: string;
  razorpay_key_id: string;
  plan_slug: string;
  plan_name: string;
  base_amount: number;
  discount_amount: number;
  subtotal_amount: number;    // post-discount, pre-GST
  gst_percent: number;
  gst_amount: number;
  offer_code: string | null;
  offer_applied: boolean;
  offer_reason: string | null;
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
  // final_price_paise = subtotal_paise + gst_paise. What the user pays.
  final_price_paise: number;
  stack_offer_with_discount: boolean;
}

// ---------- Assistant ------------------------------------------------------
export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}
export interface AssistantRequest { message: string; history?: ChatMessage[] }
export interface AssistantCitation { source: string; title: string; url: string | null }
export interface SuggestedAction { label: string; url: string }
export type AssistantIntent =
  | "account" | "faq" | "content" | "insights" | "pmi_reference";
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
export type PaymentProviderType = "razorpay" | "stripe";
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
  is_active: boolean;
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
