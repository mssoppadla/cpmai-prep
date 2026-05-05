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
export type AttemptStatus = "in_progress" | "submitted" | "expired";
export type LeadSource =
  | "landing_hero" | "newsletter" | "exit_intent" | "gated_download"
  | "blog" | "pricing_page" | "exam_preview" | "demo_request";
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
  explanation?: string | null;
  options: QuestionOptionIn[];
  is_active?: boolean;
}
export interface QuestionAdminOut extends QuestionAdminIn {
  id: number;
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
  selected_letter: string | null;
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
}

// ---------- Payments -------------------------------------------------------
export interface CreateOrderIn { plan: "pro" | "enterprise"; amount_paise: number }
export interface CreateOrderOut {
  order_id: string; amount: number; currency: string; razorpay_key_id: string;
}
export interface VerifyPaymentIn {
  order_id: string;
  payment_id: string;
  signature: string;
  plan: "pro" | "enterprise";
}

// ---------- Assistant ------------------------------------------------------
export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}
export interface AssistantRequest { message: string; history?: ChatMessage[] }
export interface AssistantCitation { source: string; title: string; url: string | null }
export interface AssistantResponse {
  intent: "account" | "faq" | "content" | "insights";
  intent_confidence: number;
  message: string;
  citations: AssistantCitation[];
  suggested_actions: string[];
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
  key: string; value: unknown; description: string | null; updated_at: string | null;
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
