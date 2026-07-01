/**
 * Typed API client. Auto-attaches Bearer token, captures chat-quota headers,
 * and normalizes errors to the contract's `ApiErrorBody`.
 */
import type {
  ApiErrorBody, AuthTokens, LoginIn, SignupIn, RefreshIn,
  UserOut, UserAdminOut, UserInsights, UserDashboardOut, ExamSetSummaryOut, ExamSetAdminIn,
  ExamAttemptOut, AnswerIn, SubmitAttemptOut, DomainOut, AttemptHistoryOut,
  AssistantRequest, AssistantResponse,
  LeadCreateIn, LeadCreateOut, LeadAdminOut, ContactRow, ChatQuota,
  FaqOut, FaqAdminOut, FaqIn, LandingCopy, SiteChrome,
  ContentPageOut, ContentPageCreateIn, ContentPageUpdateIn,
  ContentPagePublicOut, ContentPageNavItemOut,
  CmsGeneratePageIn, CmsGeneratePageOut,
  CmsFillBlockIn, CmsFillBlockOut,
  CmsImproveBlockIn, CmsImproveBlockOut,
  CourseOut, CourseCreateIn, CourseUpdateIn, CoursePublicOut,
  CourseDetailPublicOut,
  ChapterOut, ChapterCreateIn, ChapterUpdateIn,
  LessonOut, LessonCreateIn, LessonUpdateIn,
  LessonFileOut, LessonFileCreateIn,
  EnrollmentOut, EnrollmentGrantIn,
  LessonProgressOut, LessonProgressUpdateIn,
  CourseCategoryOut, CourseCategoryCreateIn, CourseCategoryUpdateIn,
  DiskUsageOut,
  CourseAnnouncementOut, CourseAnnouncementCreateIn,
  LessonNoteOut, CourseReviewOut,
  QuizOut, QuizConfigUpsertIn,
  QuizQuestionOut, QuizQuestionCreateIn, QuizQuestionUpdateIn,
  QuizOptionOut, QuizOptionCreateIn, QuizOptionUpdateIn,
  QuizAttemptOut, QuizAttemptSubmitIn,
  QuestionAdminIn, QuestionAdminOut, ExamSetLinkedQuestion,
  SettingOut, LLMProviderOut, LLMProviderCreate, LLMProviderUpdate,
  PaymentProviderOut, PaymentProviderCreate, PaymentProviderUpdate,
  PlanPublicOut, PlanAdminOut, PlanCreate, PlanUpdate,
  OfferCodeAdminOut, OfferCodeCreate, OfferCodeUpdate,
  EmailTemplateOut, EmailTemplateCreate, EmailTemplateUpdate,
  PriceQuoteOut, CreateOrderIn, CreateOrderOut, CurrenciesOut,
  VerifyPaymentIn, VerifyPaymentOut,
  PayPalCaptureIn, PayPalCaptureOut,
  GeoIPStatusOut, GeoIPRefreshOut, GeoIPTestKeyOut, GeoIPLookupOut,
  GeoIPSchedulePreviewOut,
  FXStatusOut, FXRefreshOut,
  ZoomSessionCreateIn, ZoomSessionUpdateIn,
  ZoomSessionAdminOut, ZoomSessionPublicOut,
  ZoomSDKTokenOut, RecordingOut, SignedRecordingPlaybackOut,
  CampaignCreateIn, CampaignUpdateIn, CampaignOut,
  CampaignRunOut, MarkPostedIn, WorkflowMetaOut,
} from "@/types/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

/**
 * Convert a relative ``/uploads/...`` URL (returned by the upload
 * endpoint) into an absolute URL that loads cross-origin from the
 * backend. Pure /uploads/foo paths point at the backend's StaticFiles
 * mount, not the frontend's host.
 */
export function absoluteUploadUrl(relativeUrl: string): string {
  if (!relativeUrl) return relativeUrl;
  if (/^https?:\/\//i.test(relativeUrl)) return relativeUrl;
  // Strip the trailing "/api/v1" from BASE to get the backend origin.
  const origin = BASE.replace(/\/api\/v1\/?$/, "");
  return origin + relativeUrl;
}

const TOKEN_KEY = "cpmai.access";
const REFRESH_KEY = "cpmai.refresh";
const ANON_KEY = "cpmai.anon_token";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}
function setTokens(access: string, refresh: string) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, access);
  window.localStorage.setItem(REFRESH_KEY, refresh);
}
function clearTokens() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(REFRESH_KEY);
}

/**
 * Browser-bound anonymous identifier for guest exam attempts on free sets.
 * Persisted in localStorage so the same browser keeps the same in-progress
 * attempt across navigations. Servers treat it as opaque.
 */
function getOrCreateAnonToken(): string {
  if (typeof window === "undefined") return "";
  let t = window.localStorage.getItem(ANON_KEY);
  if (!t) {
    t = (crypto && "randomUUID" in crypto)
      ? crypto.randomUUID()
      // Fallback for older browsers — sufficiently unique for our purposes.
      : Math.random().toString(36).slice(2) + Date.now().toString(36);
    window.localStorage.setItem(ANON_KEY, t);
  }
  return t;
}

export class ApiError extends Error {
  status: number;
  body: ApiErrorBody;
  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.status = status;
    this.body = body;
  }
}

/**
 * Safe error-to-string for catch blocks. Handles ApiError (with optional
 * field-level details), plain Errors (network failures), and unknowns.
 * Use everywhere instead of `(e as ApiError).body.message`, which throws
 * if `e` is anything other than an ApiError.
 */
export function errMsg(e: unknown): string {
  if (e instanceof ApiError) {
    const fields = e.body?.fields
      ? " (" + Object.entries(e.body.fields)
          .map(([k, v]) => `${k}: ${v}`).join(", ") + ")"
      : "";
    return (e.body?.message ?? `HTTP ${e.status}`) + fields;
  }
  if (e instanceof Error) return e.message;
  return String(e);
}

interface FetchOpts extends RequestInit {
  authed?: boolean;
  /** Send X-Anon-Token alongside (or instead of) the Bearer token. Used on
   *  exam endpoints that accept either signed-in users or anonymous guests
   *  on free sets. Backend's get_actor prefers Bearer when both are present. */
  withAnon?: boolean;
  json?: unknown;
  /** Internal — set by request() when retrying after a silent refresh, so
   *  we never recurse if the retried call also returns 401. Callers
   *  should not set this directly. */
  _isRetry?: boolean;
}

/**
 * In-flight refresh deduper. Multiple concurrent requests that all see
 * 401 must NOT each fire `/auth/refresh` independently — that races on
 * localStorage and burns refresh attempts. We share a single promise
 * across all concurrent callers so only one refresh is ever in flight.
 */
let _refreshInFlight: Promise<boolean> | null = null;

async function silentRefresh(): Promise<boolean> {
  if (typeof window === "undefined") return false;
  if (_refreshInFlight) return _refreshInFlight;
  const refresh = window.localStorage.getItem(REFRESH_KEY);
  if (!refresh) return false;
  _refreshInFlight = (async () => {
    try {
      // Direct fetch — bypass request() so we never trigger our own
      // 401-interceptor on the refresh call itself.
      const r = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json",
        },
        credentials: "same-origin",
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!r.ok) {
        // Refresh token expired or revoked → drop tokens, force re-login.
        clearTokens();
        return false;
      }
      const data = await r.json() as { access: string; refresh: string };
      setTokens(data.access, data.refresh);
      return true;
    } catch {
      // Network failure — leave tokens in place so a subsequent request
      // can try again. Don't clear: the user might just be offline.
      return false;
    } finally {
      _refreshInFlight = null;
    }
  })();
  return _refreshInFlight;
}

async function request<T>(path: string, opts: FetchOpts = {}): Promise<{
  data: T; headers: Headers; status: number;
}> {
  const headers = new Headers(opts.headers);
  headers.set("Accept", "application/json");
  if (opts.json !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (opts.authed) {
    const t = getToken();
    if (t) headers.set("Authorization", `Bearer ${t}`);
  }
  if (opts.withAnon) {
    const at = getOrCreateAnonToken();
    if (at) headers.set("X-Anon-Token", at);
  }
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers,
    // Auth is carried in the Authorization header (Bearer token from
    // localStorage), not cookies. Forcing credentials: "include" on every
    // request triggered credentialed CORS on anonymous endpoints like
    // POST /leads — and against a wildcard CORS origin the browser
    // rejects the response, surfacing as `TypeError: Failed to fetch`.
    credentials: opts.credentials ?? "same-origin",
    body: opts.json !== undefined ? JSON.stringify(opts.json) : opts.body,
  });

  // 401 silent-refresh interceptor.
  // When an authed request comes back 401 (likely access-token expiry),
  // try the refresh-token flow once and replay the original request.
  // This makes the effective session length the refresh-token lifetime
  // (7 days idle) rather than the access-token lifetime (4h on prod),
  // so a user who returns to a tab after 5 hours doesn't see a session-
  // timeout error mid-action. Skips:
  //   - `/auth/*` paths (refresh/login/signup) → never recurse
  //   - non-authed requests (no token to refresh)
  //   - retried requests (one retry per call, no infinite loop)
  if (
    res.status === 401 &&
    opts.authed &&
    !opts._isRetry &&
    !path.startsWith("/auth/")
  ) {
    const refreshed = await silentRefresh();
    if (refreshed) {
      return request<T>(path, { ...opts, _isRetry: true });
    }
  }

  let body: unknown = null;
  if (res.status !== 204) {
    const txt = await res.text();
    body = txt ? JSON.parse(txt) : null;
  }
  if (!res.ok) {
    const err = (body as { error?: ApiErrorBody })?.error ?? {
      code: "unknown_error", message: `HTTP ${res.status}`,
    };
    throw new ApiError(res.status, err);
  }
  return { data: body as T, headers: res.headers, status: res.status };
}

// ---------- Auth -----------------------------------------------------------
export const auth = {
  async signup(payload: SignupIn): Promise<AuthTokens> {
    const { data } = await request<AuthTokens>("/auth/signup", {
      method: "POST", json: payload,
    });
    setTokens(data.access, data.refresh);
    return data;
  },
  async googleLogin(credential: string): Promise<AuthTokens> {
    const { data } = await request<AuthTokens>("/auth/google", {
      method: "POST", json: { credential },
    });
    setTokens(data.access, data.refresh);
    return data;
  },
  async login(payload: LoginIn): Promise<AuthTokens> {
    const { data } = await request<AuthTokens>("/auth/login", {
      method: "POST", json: payload,
    });
    setTokens(data.access, data.refresh);
    return data;
  },
  async refresh(): Promise<boolean> {
    if (typeof window === "undefined") return false;
    const refresh = window.localStorage.getItem(REFRESH_KEY);
    if (!refresh) return false;
    try {
      const { data } = await request<{ access: string; refresh: string }>(
        "/auth/refresh", { method: "POST", json: { refresh_token: refresh } }
      );
      setTokens(data.access, data.refresh);
      return true;
    } catch { clearTokens(); return false; }
  },
  async logout() {
    try { await request("/auth/logout", { method: "POST", authed: true }); }
    catch {} finally { clearTokens(); }
  },
  async me(): Promise<UserOut> {
    const { data } = await request<UserOut>("/users/me", { authed: true });
    return data;
  },
  async dashboard(): Promise<UserDashboardOut> {
    const { data } = await request<UserDashboardOut>(
      "/users/me/dashboard", { authed: true });
    return data;
  },
  /** GDPR data export. Returns the raw JSON object (everything the
   *  server holds for this user). Caller offers it as a downloadable file. */
  async exportMyData(): Promise<unknown> {
    const { data } = await request<unknown>("/users/me/export",
      { authed: true });
    return data;
  },
  /** GDPR account deletion. Server soft-deletes + redacts PII; on 204
   *  the caller should clear local auth and route to the landing page. */
  async deleteMyAccount(): Promise<void> {
    await request("/users/me", { method: "DELETE", authed: true });
    clearTokens();
  },
};

// ---------- Exam sets & attempts ------------------------------------------
export const exams = {
  async listSets(): Promise<ExamSetSummaryOut[]> {
    const { data } = await request<ExamSetSummaryOut[]>("/exam-sets",
      { authed: true });
    return data;
  },
  async getSet(slug: string): Promise<ExamSetSummaryOut> {
    const { data } = await request<ExamSetSummaryOut>(`/exam-sets/${slug}`,
      { authed: true });
    return data;
  },
  async startAttempt(slug: string): Promise<ExamAttemptOut> {
    // withAnon: true → if the user isn't signed in, X-Anon-Token authorizes
    // the request for free sets (premium still rejects anon → 401).
    const { data } = await request<ExamAttemptOut>(
      `/exam-sets/${slug}/start`,
      { method: "POST", authed: true, withAnon: true }
    );
    return data;
  },
  /** Start (or resume) a focused practice over one ECO domain's questions
   *  within a set — the results-screen drill-down. Same access rules as a
   *  full sitting. */
  async startDomainPractice(slug: string, domainCode: string): Promise<ExamAttemptOut> {
    const { data } = await request<ExamAttemptOut>(
      `/exam-sets/${slug}/practice/${encodeURIComponent(domainCode)}/start`,
      { method: "POST", authed: true, withAnon: true }
    );
    return data;
  },
  async getAttempt(id: number): Promise<ExamAttemptOut> {
    const { data } = await request<ExamAttemptOut>(`/exams/attempts/${id}`,
      { authed: true, withAnon: true });
    return data;
  },
  async saveAnswer(id: number, payload: AnswerIn): Promise<void> {
    await request(`/exams/attempts/${id}/answer`,
      { method: "PATCH", json: payload, authed: true, withAnon: true });
  },
  async getResult(id: number): Promise<SubmitAttemptOut> {
    const { data } = await request<SubmitAttemptOut>(
      `/exams/attempts/${id}/result`, { authed: true, withAnon: true }
    );
    return data;
  },
  /** The signed-in learner's past submitted attempts (exam history),
   *  newest first. Each links back into the results screen via its id. */
  async listAttempts(): Promise<AttemptHistoryOut[]> {
    const { data } = await request<AttemptHistoryOut[]>(
      "/exams/attempts", { authed: true });
    return data;
  },
  async submit(id: number): Promise<SubmitAttemptOut> {
    const { data } = await request<SubmitAttemptOut>(
      `/exams/attempts/${id}/submit`,
      { method: "POST", authed: true, withAnon: true }
    );
    return data;
  },
};

// ---------- Assistant ------------------------------------------------------
export interface AssistantNotification {
  id: number;
  assistant_log_id: number;
  original_message: string;
  original_reply: string;
  admin_reply: string;
  replied_at: string;
  replied_by_name: string | null;
}


/** One row of the /admin/chat-history/flagged response.
 *  Shipped in feat/flagged-turn-resolve — exposes resolved_at +
 *  resolved_by + the derived ``status`` string the backend computes
 *  from the row's timestamps. */
export interface FlaggedTurnAdminRow {
  id: number;
  assistant_log_id: number;
  user: { id: number | null; email: string | null; name: string | null };
  original_message: string;
  original_reply: string;
  provider: string | null;
  model: string | null;
  flag_note: string | null;
  flagged_at: string;
  admin_reply: string | null;
  replied_at: string | null;
  replied_by: { id: number | null; name: string | null;
                email: string | null } | null;
  resolved_at: string | null;
  resolved_by: { id: number | null; name: string | null;
                 email: string | null; is_self: boolean } | null;
  /** "pending" | "replied" | "resolved" — derived server-side. */
  status: "pending" | "replied" | "resolved";
}

export const assistant = {
  async chat(payload: AssistantRequest): Promise<{
    response: AssistantResponse; quota: ChatQuota;
  }> {
    const { data, headers } = await request<AssistantResponse>(
      "/assistant/chat", { method: "POST", json: payload, authed: true }
    );
    const quota: ChatQuota = {
      used: parseInt(headers.get("X-Chat-Quota-Used") ?? "0", 10),
      limit: parseInt(headers.get("X-Chat-Quota-Limit") ?? "0", 10),
      remaining: parseInt(headers.get("X-Chat-Quota-Remaining") ?? "0", 10),
      reset_at: headers.get("X-Chat-Quota-Reset") ?? "",
    };
    return { response: data, quota };
  },
  /** Record an anonymous-visitor interaction (typically: clicked the
   *  chat bubble while not signed in). Server captures IP + geoip and
   *  writes one audit_logs row. No-op when the request is from a
   *  signed-in user — the endpoint short-circuits server-side so
   *  the frontend doesn't need to branch.
   *
   *  Fire-and-forget: don't await failures, don't surface errors —
   *  this is operational telemetry, not a load-bearing call. */
  async anonEvent(kind: string = "bubble_open"): Promise<void> {
    try {
      await request("/assistant/anon-event", {
        method: "POST", authed: true, json: { kind },
      });
    } catch {
      /* swallow — anon-event is best-effort tracking, never user-visible */
    }
  },
  /** Flag an AI turn as unhelpful. Idempotent on (turn_id) — the
   *  backend returns the existing flag row on second submit instead
   *  of erroring, so the widget can be safely re-clicked. */
  async flagTurn(turnId: number, note?: string): Promise<{
    id: number; status: "pending" | "replied" | "resolved" | "closed";
  }> {
    const { data } = await request<{
      id: number; status: "pending" | "replied" | "resolved" | "closed";
    }>(`/assistant/turns/${turnId}/flag`, {
      method: "POST", authed: true,
      json: { note: note?.trim() || null },
    });
    return data;
  },
  /** User marks their own flag as resolved (withdraws, or
   *  acknowledges a satisfying admin reply). Idempotent. */
  async resolveFlaggedTurn(turnId: number): Promise<void> {
    await request(`/assistant/turns/${turnId}/flag/resolve`,
      { method: "POST", authed: true });
  },
  /** Unread admin replies — drives the chat widget's red-dot indicator. */
  async notifications(): Promise<AssistantNotification[]> {
    const { data } = await request<AssistantNotification[]>(
      "/assistant/notifications", { authed: true });
    return data;
  },
  /** Acknowledge an admin reply (clears the red dot for this flag). */
  async markNotificationSeen(flagId: number): Promise<void> {
    await request(`/assistant/notifications/${flagId}/seen`,
      { method: "POST", authed: true });
  },
};

// ---------- Pricing (public) ----------------------------------------------
export const pricing = {
  async listPlans(): Promise<PlanPublicOut[]> {
    const { data } = await request<PlanPublicOut[]>("/pricing/plans");
    return data;
  },
  async quote(plan_slug: string,
              offer_code?: string,
              currency?: string): Promise<PriceQuoteOut> {
    const { data } = await request<PriceQuoteOut>("/pricing/quote", {
      method: "POST",
      json: {
        plan_slug,
        offer_code: offer_code || null,
        // Default to INR matches the backend default — keeps existing
        // callers (e.g. mid-page re-quote without picker change) working
        // when they don't pass a currency.
        currency: (currency || "INR").toUpperCase(),
      },
    });
    return data;
  },
  /** Currencies the picker should offer. Public, no auth — same surface
   *  as /pricing/plans. */
  async listCurrencies(): Promise<CurrenciesOut> {
    const { data } = await request<CurrenciesOut>("/pricing/currencies");
    return data;
  },
};

// ---------- Payments (public, auth-required) -------------------------------
export const payments = {
  async createOrder(payload: CreateOrderIn): Promise<CreateOrderOut> {
    const { data } = await request<CreateOrderOut>("/payments/orders", {
      method: "POST", authed: true, json: payload,
    });
    return data;
  },
  async verify(payload: VerifyPaymentIn): Promise<VerifyPaymentOut> {
    const { data } = await request<VerifyPaymentOut>("/payments/verify", {
      method: "POST", authed: true, json: payload,
    });
    return data;
  },
  /** PayPal-specific 2-step capture. Called from the Smart Button's
   *  onApprove callback after the buyer approves on PayPal's domain.
   *  Razorpay uses verify() above — PayPal needs this because the
   *  Orders v2 flow separates authorization from capture. */
  async paypalCapture(payload: PayPalCaptureIn): Promise<PayPalCaptureOut> {
    const { data } = await request<PayPalCaptureOut>(
      "/payments/paypal/capture", {
        method: "POST", authed: true, json: payload,
    });
    return data;
  },
};

// ---------- Leads ----------------------------------------------------------
//
// `/leads` is on EasyList tracking filters (uBlock Origin, Brave shields,
// Firefox strict-mode) and gets blocked client-side before the request
// even leaves the browser, surfacing as `TypeError: Failed to fetch`
// with no server trace. To make sure prospect callback requests don't
// silently fail for ~20% of users with ad-blockers, this submit call
// uses the `/contact-request` alias the backend exposes; the lead row
// is created identically. Admin-side reads (`/admin/leads`) keep the
// original path — admins typically don't browse with content blockers.
export const leads = {
  async submit(payload: LeadCreateIn): Promise<LeadCreateOut> {
    const { data } = await request<LeadCreateOut>("/contact-request",
      { method: "POST", json: payload });
    return data;
  },
};

// ==========================================================================
// Admin API surface — gated server-side by RBAC. Calling these as a regular
// user will throw `ApiError` with code === "forbidden".
// ==========================================================================
function qs(params?: Record<string, unknown>): string {
  if (!params) return "";
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null) u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

/** GET an authed .xlsx endpoint and return the blob for save-as. */
async function downloadXlsx(path: string, label: string): Promise<Blob> {
  const token = typeof window !== "undefined"
    ? window.localStorage.getItem("cpmai.access") : null;
  const r = await fetch(`${BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!r.ok) throw new ApiError(r.status, {
    code: "download_failed",
    message: `${label} failed (HTTP ${r.status}).`,
  });
  return r.blob();
}

export const content = {
  async topics(): Promise<Array<{id: number; code: string; name: string; order: number}>> {
    const { data } = await request<Array<{id: number; code: string; name: string; order: number}>>(
      "/content/topics");
    return data;
  },
  /** The five CPMAI ECO domains, with live active-question counts. */
  async domains(): Promise<DomainOut[]> {
    const { data } = await request<DomainOut[]>("/content/domains");
    return data;
  },
  async faqs(): Promise<FaqOut[]> {
    const { data } = await request<FaqOut[]>("/content/faqs");
    return data;
  },
  async landing(): Promise<LandingCopy> {
    const { data } = await request<LandingCopy>("/content/landing");
    return data;
  },
  async site(): Promise<SiteChrome> {
    const { data } = await request<SiteChrome>("/content/site");
    return data;
  },
};

/**
 * Public LMS endpoints — most are anon-friendly catalog reads; auth
 * required for enrollment, progress, notes, reviews, quiz attempts.
 */
export const lmsPublic = {
  async listCategories(): Promise<CourseCategoryOut[]> {
    const { data } = await request<CourseCategoryOut[]>("/lms/categories", { authed: true });
    return data;
  },
  async listCourses(params: { difficulty?: string; category?: string; limit?: number; offset?: number } = {}): Promise<Array<CoursePublicOut & { categories: { id: number; slug: string; name: string }[] }>> {
    const qs: string[] = [];
    if (params.difficulty) qs.push(`difficulty=${encodeURIComponent(params.difficulty)}`);
    if (params.category)   qs.push(`category=${encodeURIComponent(params.category)}`);
    if (params.limit !== undefined) qs.push(`limit=${params.limit}`);
    if (params.offset !== undefined) qs.push(`offset=${params.offset}`);
    const suffix = qs.length ? `?${qs.join("&")}` : "";
    const { data } = await request<Array<CoursePublicOut & { categories: { id: number; slug: string; name: string }[] }>>(
      `/lms/courses${suffix}`, { authed: true });
    return data;
  },
  async getCourse(slug: string): Promise<CourseDetailPublicOut> {
    const { data } = await request<CourseDetailPublicOut>(
      `/lms/courses/${encodeURIComponent(slug)}`, { authed: true });
    return data;
  },
  async myEnrollments(): Promise<EnrollmentOut[]> {
    const { data } = await request<EnrollmentOut[]>("/lms/me/enrollments", { authed: true });
    return data;
  },
  async selfEnrollFree(slug: string): Promise<EnrollmentOut> {
    const { data } = await request<EnrollmentOut>(
      `/lms/courses/${encodeURIComponent(slug)}/enroll`,
      { method: "POST", authed: true });
    return data;
  },
  async listProgress(enrollmentId: number): Promise<LessonProgressOut[]> {
    const { data } = await request<LessonProgressOut[]>(
      `/lms/enrollments/${enrollmentId}/progress`, { authed: true });
    return data;
  },
  async updateProgress(enrollmentId: number, lessonId: number, p: LessonProgressUpdateIn): Promise<LessonProgressOut> {
    const { data } = await request<LessonProgressOut>(
      `/lms/enrollments/${enrollmentId}/progress/${lessonId}`,
      { method: "PUT", json: p, authed: true });
    return data;
  },
  async savePodcastPointer(
    enrollmentId: number,
    p: { lesson_id?: number | null; position_seconds?: number | null },
  ): Promise<EnrollmentOut> {
    const { data } = await request<EnrollmentOut>(
      `/lms/enrollments/${enrollmentId}/podcast`,
      { method: "PUT", json: p, authed: true });
    return data;
  },
  async listAnnouncements(slug: string): Promise<CourseAnnouncementOut[]> {
    const { data } = await request<CourseAnnouncementOut[]>(
      `/lms/courses/${encodeURIComponent(slug)}/announcements`, { authed: true });
    return data;
  },
  async getMyNote(lessonId: number): Promise<LessonNoteOut | null> {
    const { data } = await request<LessonNoteOut | null>(
      `/lms/lessons/${lessonId}/note`, { authed: true });
    return data;
  },
  async upsertMyNote(lessonId: number, body: string): Promise<LessonNoteOut | null> {
    const { data } = await request<LessonNoteOut | null>(
      `/lms/lessons/${lessonId}/note`,
      { method: "PUT", json: { body }, authed: true });
    return data;
  },
  async listReviews(slug: string): Promise<CourseReviewOut[]> {
    const { data } = await request<CourseReviewOut[]>(
      `/lms/courses/${encodeURIComponent(slug)}/reviews`, { authed: true });
    return data;
  },
  async upsertReview(enrollmentId: number, stars: number, body: string | null): Promise<CourseReviewOut> {
    const { data } = await request<CourseReviewOut>(
      `/lms/enrollments/${enrollmentId}/review`,
      { method: "PUT", json: { stars, body }, authed: true });
    return data;
  },
  async listQuizQuestions(lessonId: number): Promise<QuizQuestionOut[]> {
    const { data } = await request<QuizQuestionOut[]>(
      `/lms/quizzes/${lessonId}/questions`, { authed: true });
    return data;
  },
  async submitQuizAttempt(lessonId: number, p: QuizAttemptSubmitIn): Promise<QuizAttemptOut> {
    const { data } = await request<QuizAttemptOut>(
      `/lms/quizzes/${lessonId}/attempts`,
      { method: "POST", json: p, authed: true });
    return data;
  },
  async listMyAttempts(lessonId: number): Promise<QuizAttemptOut[]> {
    const { data } = await request<QuizAttemptOut[]>(
      `/lms/quizzes/${lessonId}/attempts`, { authed: true });
    return data;
  },
  // ─────── Zoom sessions (subscription-gated public reads) ───────
  /** Sessions the current user can see — drafts hidden, gated by
   *  course enrollment (for course-linked sessions) or any active
   *  subscription (for standalone sessions). */
  async listSessions(p?: { course_id?: number; include_past?: boolean }) {
    const params: Record<string, string | number | boolean> = {};
    if (p?.course_id !== undefined) params.course_id = p.course_id;
    if (p?.include_past) params.include_past = true;
    const { data } = await request<ZoomSessionPublicOut[]>(
      `/lms/sessions${qs(params)}`, { authed: true });
    return data;
  },
  async getSession(id: number) {
    const { data } = await request<ZoomSessionPublicOut>(
      `/lms/sessions/${id}`, { authed: true });
    return data;
  },
  /** Mint a Zoom Web SDK JWT for this user + session. The frontend
   *  feeds the returned signature + sdk_key into the Meeting SDK's
   *  client.join() call. 30-minute TTL. */
  async getSessionSDKToken(id: number) {
    const { data } = await request<ZoomSDKTokenOut>(
      `/lms/sessions/${id}/sdk-token`,
      { method: "POST", authed: true });
    return data;
  },
  /** Get a 1-hour playback URL for the latest recording of this
   *  session. Each call is audit-logged; calling again issues a
   *  fresh URL. */
  async getSessionRecording(id: number) {
    const { data } = await request<SignedRecordingPlaybackOut>(
      `/lms/sessions/${id}/recording`, { authed: true });
    return data;
  },
};


/**
 * Public CMS endpoints — no auth required (anon-friendly). Auth headers
 * are still attached if a token exists so the visibility filter widens
 * for signed-in users (authenticated tier) and subscribers (subscribed
 * tier).
 */
export const cmsPublic = {
  async nav(): Promise<ContentPageNavItemOut[]> {
    const { data } = await request<unknown>(
      "/cms/nav", { authed: true });  // authed: true means "send token if present"
    // Coerce defensively: anything other than an array becomes empty so
    // a malformed / mocked / outdated response can't crash the header.
    return Array.isArray(data) ? (data as ContentPageNavItemOut[]) : [];
  },
  async page(slug: string): Promise<ContentPagePublicOut> {
    const { data } = await request<ContentPagePublicOut>(
      `/cms/pages/${encodeURIComponent(slug)}`, { authed: true });
    return data;
  },
  async landing(): Promise<ContentPagePublicOut | null> {
    // 404 is the documented "no landing configured" response — translate
    // to null so callers don't have to catch ApiError for the happy path.
    try {
      const { data } = await request<ContentPagePublicOut>(
        "/cms/landing", { authed: true });
      return data;
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }
  },
};

export const admin = {
  questions: {
    async list(p?: {
      topic_id?: number;
      domain?: string;
      /** Restrict to questions tagged into this specific exam set. */
      exam_set_id?: number;
      q?: string;
      /** "any" → only questions tagged into ≥1 set; "none" → orphans only;
       *  omit → no filter. */
      tagged?: "any" | "none";
      limit?: number;
      offset?: number;
    }) {
      const { data } = await request<QuestionAdminOut[]>(
        `/admin/questions${qs(p)}`, { authed: true });
      return data;
    },
    /** Download the BLANK .xlsx template (headers + examples). Returns the
     *  raw blob so the caller can save-as locally. */
    async downloadBulkTemplate(): Promise<Blob> {
      return downloadXlsx("/admin/questions/bulk-template",
        "Template download");
    },
    /** Download every existing question pre-filled into the bulk sheet —
     *  id, all fields, ECO domain, and exam-set memberships. Edit + re-upload
     *  to update in place. */
    async exportQuestions(): Promise<Blob> {
      return downloadXlsx("/admin/questions/export", "Export");
    },
    /** Upload a filled .xlsx. Rows with an id update in place (+ sync set
     *  memberships); rows with a blank id create new. Returns per-row
     *  breakdown so the caller can surface errors. */
    async bulkUpload(file: File): Promise<{
      created: number;
      created_ids: number[];
      updated: number;
      updated_ids: number[];
      errors: Array<{ row: number; field: string; message: string }>;
    }> {
      const token = typeof window !== "undefined"
        ? window.localStorage.getItem("cpmai.access") : null;
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch(`${BASE}/admin/questions/bulk-upload`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: fd,
      });
      const body = await r.json();
      if (!r.ok) throw new ApiError(r.status, body?.error ?? {
        code: "upload_failed", message: `Upload failed (HTTP ${r.status}).`,
      });
      return body;
    },
    async get(id: number) {
      const { data } = await request<QuestionAdminOut>(
        `/admin/questions/${id}`, { authed: true });
      return data;
    },
    async create(payload: QuestionAdminIn) {
      const { data } = await request<QuestionAdminOut>(
        "/admin/questions", { method: "POST", json: payload, authed: true });
      return data;
    },
    async update(id: number, payload: QuestionAdminIn) {
      const { data } = await request<QuestionAdminOut>(
        `/admin/questions/${id}`, { method: "PATCH", json: payload, authed: true });
      return data;
    },
    async delete(id: number) {
      await request(`/admin/questions/${id}`, { method: "DELETE", authed: true });
    },
  },
  examSets: {
    async list() {
      const { data } = await request<ExamSetSummaryOut[]>(
        "/admin/exam-sets", { authed: true });
      return data;
    },
    async create(p: ExamSetAdminIn) {
      const { data } = await request<ExamSetSummaryOut>(
        "/admin/exam-sets", { method: "POST", json: p, authed: true });
      return data;
    },
    async update(id: number, p: ExamSetAdminIn) {
      const { data } = await request<ExamSetSummaryOut>(
        `/admin/exam-sets/${id}`, { method: "PATCH", json: p, authed: true });
      return data;
    },
    async addQuestions(id: number, qids: number[]) {
      await request(`/admin/exam-sets/${id}/questions`,
        { method: "POST", json: { question_ids: qids }, authed: true });
    },
    async listLinkedQuestions(id: number) {
      const { data } = await request<ExamSetLinkedQuestion[]>(
        `/admin/exam-sets/${id}/questions`, { authed: true });
      return data;
    },
    async reorderQuestions(
      id: number,
      items: Array<{ question_id: number; position: number }>,
    ) {
      await request(`/admin/exam-sets/${id}/questions/reorder`,
        { method: "PATCH", json: { items }, authed: true });
    },
    async removeQuestion(setId: number, qid: number) {
      await request(`/admin/exam-sets/${setId}/questions/${qid}`,
        { method: "DELETE", authed: true });
    },
    async delete(id: number) {
      await request(`/admin/exam-sets/${id}`, { method: "DELETE", authed: true });
    },
  },
  leads: {
    async list(p?: { source?: string; q?: string;
                     sort?: "recent" | "score";
                     limit?: number; offset?: number }) {
      const { data } = await request<LeadAdminOut[]>(
        `/admin/leads${qs(p)}`, { authed: true });
      return data;
    },
    async updateNotes(id: number, notes: string) {
      const { data } = await request<LeadAdminOut>(
        `/admin/leads/${id}/notes`,
        { method: "PATCH", json: { notes }, authed: true });
      return data;
    },
    async delete(id: number) {
      await request(`/admin/leads/${id}`,
        { method: "DELETE", authed: true });
    },
  },
  contacts: {
    /** Unified feed: leads (landing-form) + users (signed up) in one stream.
     *
     *  ``include_deleted`` defaults to false on the server — soft-deleted
     *  users are hidden unless the admin clicks the "Show deleted" toggle
     *  on /admin/leads. */
    async list(p?: {
      kind?: "lead" | "user"; q?: string;
      include_deleted?: boolean;
      active_from?: string; active_to?: string;
      limit?: number; offset?: number;
    }) {
      const { data } = await request<ContactRow[]>(
        `/admin/leads/contacts${qs(p)}`, { authed: true });
      return data;
    },
  },
  faqs: {
    async list() {
      const { data } = await request<FaqAdminOut[]>("/admin/faqs", { authed: true });
      return data;
    },
    async create(p: FaqIn) {
      const { data } = await request<FaqAdminOut>(
        "/admin/faqs", { method: "POST", json: p, authed: true });
      return data;
    },
    async update(id: number, p: FaqIn) {
      const { data } = await request<FaqAdminOut>(
        `/admin/faqs/${id}`, { method: "PATCH", json: p, authed: true });
      return data;
    },
    async delete(id: number) {
      await request(`/admin/faqs/${id}`, { method: "DELETE", authed: true });
    },
  },
  contentPages: {
    async list(includeUnpublished: boolean = true) {
      const qs = includeUnpublished ? "" : "?include_unpublished=false";
      const { data } = await request<ContentPageOut[]>(
        `/admin/content-pages${qs}`, { authed: true });
      return data;
    },
    async get(id: number) {
      const { data } = await request<ContentPageOut>(
        `/admin/content-pages/${id}`, { authed: true });
      return data;
    },
    async create(p: ContentPageCreateIn) {
      const { data } = await request<ContentPageOut>(
        "/admin/content-pages", { method: "POST", json: p, authed: true });
      return data;
    },
    async update(id: number, p: ContentPageUpdateIn) {
      const { data } = await request<ContentPageOut>(
        `/admin/content-pages/${id}`,
        { method: "PATCH", json: p, authed: true });
      return data;
    },
    async delete(id: number) {
      await request(
        `/admin/content-pages/${id}`,
        { method: "DELETE", authed: true });
    },
    async setLanding(id: number) {
      const { data } = await request<ContentPageOut>(
        `/admin/content-pages/${id}/set-landing`,
        { method: "POST", authed: true });
      return data;
    },
    async clearLanding(id: number) {
      const { data } = await request<ContentPageOut>(
        `/admin/content-pages/${id}/clear-landing`,
        { method: "POST", authed: true });
      return data;
    },
  },
  lms: {
    // ------------- Courses
    async listCourses(includeUnpublished = true) {
      const qs = includeUnpublished ? "" : "?include_unpublished=false";
      const { data } = await request<CourseOut[]>(`/admin/courses${qs}`, { authed: true });
      return data;
    },
    async getCourse(id: number) {
      const { data } = await request<CourseOut>(`/admin/courses/${id}`, { authed: true });
      return data;
    },
    async getCourseTree(id: number) {
      // Returns { course, chapters: [{ ..., lessons: [{ ..., files: [...] }] }] }
      // Admin view — includes drafts.
      const { data } = await request<{
        course: CourseOut;
        chapters: Array<ChapterOut & {
          lessons: Array<LessonOut & { files: LessonFileOut[] }>;
        }>;
      }>(`/admin/courses/${id}/tree`, { authed: true });
      return data;
    },
    async getLesson(id: number) {
      // Backend nests course_id alongside the standard lesson fields so
      // the editor can render a correct "← Back to course" link without
      // an extra round-trip.
      const { data } = await request<LessonOut & { course_id: number | null }>(
        `/admin/lessons/${id}`, { authed: true });
      return data;
    },
    async listLessonFiles(lessonId: number) {
      const { data } = await request<LessonFileOut[]>(
        `/admin/lessons/${lessonId}/files`, { authed: true });
      return data;
    },
    async createCourse(p: CourseCreateIn) {
      const { data } = await request<CourseOut>(
        "/admin/courses", { method: "POST", json: p, authed: true });
      return data;
    },
    async updateCourse(id: number, p: CourseUpdateIn) {
      const { data } = await request<CourseOut>(
        `/admin/courses/${id}`, { method: "PATCH", json: p, authed: true });
      return data;
    },
    async deleteCourse(id: number) {
      await request(`/admin/courses/${id}`, { method: "DELETE", authed: true });
    },
    // ------------- Chapters
    async createChapter(courseId: number, p: ChapterCreateIn) {
      const { data } = await request<ChapterOut>(
        `/admin/courses/${courseId}/chapters`, { method: "POST", json: p, authed: true });
      return data;
    },
    async updateChapter(id: number, p: ChapterUpdateIn) {
      const { data } = await request<ChapterOut>(
        `/admin/chapters/${id}`, { method: "PATCH", json: p, authed: true });
      return data;
    },
    async deleteChapter(id: number) {
      await request(`/admin/chapters/${id}`, { method: "DELETE", authed: true });
    },
    // ------------- Lessons
    async createLesson(chapterId: number, p: LessonCreateIn) {
      const { data } = await request<LessonOut>(
        `/admin/chapters/${chapterId}/lessons`, { method: "POST", json: p, authed: true });
      return data;
    },
    async updateLesson(id: number, p: LessonUpdateIn) {
      const { data } = await request<LessonOut>(
        `/admin/lessons/${id}`, { method: "PATCH", json: p, authed: true });
      return data;
    },
    async deleteLesson(id: number) {
      await request(`/admin/lessons/${id}`, { method: "DELETE", authed: true });
    },
    // ------------- Files
    async addFile(lessonId: number, p: LessonFileCreateIn) {
      const { data } = await request<LessonFileOut>(
        `/admin/lessons/${lessonId}/files`, { method: "POST", json: p, authed: true });
      return data;
    },
    async deleteFile(fileId: number) {
      await request(`/admin/lesson-files/${fileId}`, { method: "DELETE", authed: true });
    },
    // ------------- Enrollments
    async listEnrollments(courseId: number, includeRevoked = false) {
      const qs = includeRevoked ? "?include_revoked=true" : "";
      const { data } = await request<EnrollmentOut[]>(
        `/admin/courses/${courseId}/enrollments${qs}`, { authed: true });
      return data;
    },
    async grantEnrollment(courseId: number, p: EnrollmentGrantIn) {
      const { data } = await request<EnrollmentOut>(
        `/admin/courses/${courseId}/enrollments`, { method: "POST", json: p, authed: true });
      return data;
    },
    async revokeEnrollment(id: number) {
      await request(`/admin/enrollments/${id}`, { method: "DELETE", authed: true });
    },
    // ------------- Categories
    async listCategories() {
      const { data } = await request<CourseCategoryOut[]>("/admin/course-categories", { authed: true });
      return data;
    },
    async createCategory(p: CourseCategoryCreateIn) {
      const { data } = await request<CourseCategoryOut>(
        "/admin/course-categories", { method: "POST", json: p, authed: true });
      return data;
    },
    async updateCategory(id: number, p: CourseCategoryUpdateIn) {
      const { data } = await request<CourseCategoryOut>(
        `/admin/course-categories/${id}`, { method: "PATCH", json: p, authed: true });
      return data;
    },
    async deleteCategory(id: number) {
      await request(`/admin/course-categories/${id}`, { method: "DELETE", authed: true });
    },
    async listCourseCategories(courseId: number) {
      const { data } = await request<CourseCategoryOut[]>(
        `/admin/courses/${courseId}/categories`, { authed: true });
      return data;
    },
    async linkCategory(courseId: number, catId: number) {
      await request(`/admin/courses/${courseId}/categories/${catId}`,
                    { method: "POST", authed: true });
    },
    async unlinkCategory(courseId: number, catId: number) {
      await request(`/admin/courses/${courseId}/categories/${catId}`,
                    { method: "DELETE", authed: true });
    },
    // ------------- Announcements
    async listAnnouncements(courseId: number) {
      const { data } = await request<CourseAnnouncementOut[]>(
        `/admin/courses/${courseId}/announcements`, { authed: true });
      return data;
    },
    async createAnnouncement(courseId: number, p: CourseAnnouncementCreateIn) {
      const { data } = await request<CourseAnnouncementOut>(
        `/admin/courses/${courseId}/announcements`, { method: "POST", json: p, authed: true });
      return data;
    },
    async deleteAnnouncement(id: number) {
      await request(`/admin/announcements/${id}`, { method: "DELETE", authed: true });
    },
    // ------------- Quizzes
    async upsertQuizConfig(lessonId: number, p: QuizConfigUpsertIn) {
      const { data } = await request<QuizOut>(
        `/admin/quizzes/${lessonId}`, { method: "PUT", json: p, authed: true });
      return data;
    },
    async getQuizConfig(lessonId: number) {
      const { data } = await request<QuizOut>(
        `/admin/quizzes/${lessonId}`, { authed: true });
      return data;
    },
    async listQuizQuestions(lessonId: number) {
      const { data } = await request<QuizQuestionOut[]>(
        `/admin/quizzes/${lessonId}/questions`, { authed: true });
      return data;
    },
    async addQuizQuestion(lessonId: number, p: QuizQuestionCreateIn) {
      const { data } = await request<QuizQuestionOut>(
        `/admin/quizzes/${lessonId}/questions`, { method: "POST", json: p, authed: true });
      return data;
    },
    async updateQuizQuestion(qId: number, p: QuizQuestionUpdateIn) {
      const { data } = await request<QuizQuestionOut>(
        `/admin/quiz-questions/${qId}`, { method: "PATCH", json: p, authed: true });
      return data;
    },
    async deleteQuizQuestion(qId: number) {
      await request(`/admin/quiz-questions/${qId}`, { method: "DELETE", authed: true });
    },
    async listQuizOptions(qId: number) {
      const { data } = await request<QuizOptionOut[]>(
        `/admin/quiz-questions/${qId}/options`, { authed: true });
      return data;
    },
    async addQuizOption(qId: number, p: QuizOptionCreateIn) {
      const { data } = await request<QuizOptionOut>(
        `/admin/quiz-questions/${qId}/options`, { method: "POST", json: p, authed: true });
      return data;
    },
    async updateQuizOption(oId: number, p: QuizOptionUpdateIn) {
      const { data } = await request<QuizOptionOut>(
        `/admin/quiz-options/${oId}`, { method: "PATCH", json: p, authed: true });
      return data;
    },
    async deleteQuizOption(oId: number) {
      await request(`/admin/quiz-options/${oId}`, { method: "DELETE", authed: true });
    },
  },
  /**
   * File upload — POSTs multipart/form-data to /admin/uploads. Returns
   * { url, filename, mime_type, size_bytes }. The ``url`` is relative
   * (``/uploads/...``); callers prepend NEXT_PUBLIC_API_URL's origin
   * to get an absolute URL when needed (e.g. when storing in a
   * BlockNote image block that loads from a different origin).
   */
  uploads: {
    async config() {
      const { data } = await request<{ max_bytes: number; max_mb: number; allowed_mimes: string[] }>(
        `/admin/uploads/config`, { authed: true });
      return data;
    },
    async file(file: File): Promise<{ url: string; filename: string; mime_type: string; size_bytes: number }> {
      const t = typeof window !== "undefined" ? localStorage.getItem("cpmai.access") : null;
      const fd = new FormData();
      fd.append("file", file);
      const headers: Record<string, string> = {};
      if (t) headers["Authorization"] = `Bearer ${t}`;
      // Don't set Content-Type — browser fills in the multipart boundary.
      const r = await fetch(`${BASE}/admin/uploads`, {
        method: "POST",
        headers,
        body: fd,
        credentials: "same-origin",
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new ApiError(r.status, body.error ?? { code: "upload_failed", message: "Upload failed" });
      }
      return r.json();
    },
  },
  zoom: {
    /** Admin Zoom session management. Mounted at /api/v1/admin/sessions
     *  (the prefix is empty in admin/router.py because /admin is already
     *  added by the umbrella admin_router). */
    async listSessions(p?: {
      course_id?: number; status?: string;
      limit?: number; offset?: number;
    }) {
      const { data } = await request<ZoomSessionAdminOut[]>(
        `/admin/sessions${qs(p)}`, { authed: true });
      return data;
    },
    async getSession(id: number) {
      const { data } = await request<ZoomSessionAdminOut>(
        `/admin/sessions/${id}`, { authed: true });
      return data;
    },
    async createSession(payload: ZoomSessionCreateIn) {
      const { data } = await request<ZoomSessionAdminOut>(
        `/admin/sessions`,
        { method: "POST", json: payload, authed: true });
      return data;
    },
    async publishSession(id: number) {
      const { data } = await request<ZoomSessionAdminOut>(
        `/admin/sessions/${id}/publish`,
        { method: "POST", authed: true });
      return data;
    },
    async updateSession(id: number, payload: ZoomSessionUpdateIn) {
      const { data } = await request<ZoomSessionAdminOut>(
        `/admin/sessions/${id}`,
        { method: "PATCH", json: payload, authed: true });
      return data;
    },
    async deleteSession(id: number) {
      await request(`/admin/sessions/${id}`,
        { method: "DELETE", authed: true });
    },
    async listRecordings(sessionId: number) {
      const { data } = await request<RecordingOut[]>(
        `/admin/sessions/${sessionId}/recordings`, { authed: true });
      return data;
    },
  },
  social: {
    /** Admin social-automation campaigns + queue. */
    async listCampaigns(p?: { active?: boolean; workflow_type?: string }) {
      const { data } = await request<CampaignOut[]>(
        `/admin/campaigns${qs(p)}`, { authed: true });
      return data;
    },
    async getCampaign(id: number) {
      const { data } = await request<CampaignOut>(
        `/admin/campaigns/${id}`, { authed: true });
      return data;
    },
    async createCampaign(payload: CampaignCreateIn) {
      const { data } = await request<CampaignOut>(
        `/admin/campaigns`,
        { method: "POST", json: payload, authed: true });
      return data;
    },
    async updateCampaign(id: number, payload: CampaignUpdateIn) {
      const { data } = await request<CampaignOut>(
        `/admin/campaigns/${id}`,
        { method: "PATCH", json: payload, authed: true });
      return data;
    },
    async deleteCampaign(id: number) {
      await request(`/admin/campaigns/${id}`,
        { method: "DELETE", authed: true });
    },
    async runCampaignNow(id: number) {
      const { data } = await request<CampaignRunOut>(
        `/admin/campaigns/${id}/run-now`,
        { method: "POST", authed: true });
      return data;
    },
    async listCampaignRuns(id: number, limit = 50) {
      const { data } = await request<CampaignRunOut[]>(
        `/admin/campaigns/${id}/runs?limit=${limit}`, { authed: true });
      return data;
    },
    async listWorkflows() {
      const { data } = await request<WorkflowMetaOut[]>(
        `/admin/campaigns/workflows`, { authed: true });
      return data;
    },
    /** Social queue feed for /admin/social-queue. */
    async listQueue(status?: string) {
      const params = status ? { status } : undefined;
      const { data } = await request<CampaignRunOut[]>(
        `/admin/social-queue${qs(params)}`, { authed: true });
      return data;
    },
    async markPosted(runId: number, payload: MarkPostedIn) {
      const { data } = await request<CampaignRunOut>(
        `/admin/social-queue/${runId}/mark-posted`,
        { method: "POST", json: payload, authed: true });
      return data;
    },
    async retryRun(runId: number) {
      const { data } = await request<CampaignRunOut>(
        `/admin/social-queue/${runId}/retry`,
        { method: "POST", authed: true });
      return data;
    },
  },
  observability: {
    /** Disk gauge + per-app breakdown + operator-side reclaim hints.
     *  Backend can't shell out to docker / find, so reclaim items
     *  return command strings the operator runs via SSH. */
    async disk() {
      const { data } = await request<DiskUsageOut>(
        "/admin/observability/disk", { authed: true });
      return data;
    },
  },
  cmsAi: {
    async generatePage(p: CmsGeneratePageIn) {
      const { data } = await request<CmsGeneratePageOut>(
        "/admin/cms-ai/generate-page",
        { method: "POST", json: p, authed: true });
      return data;
    },
    async fillBlock(p: CmsFillBlockIn) {
      const { data } = await request<CmsFillBlockOut>(
        "/admin/cms-ai/fill-block",
        { method: "POST", json: p, authed: true });
      return data;
    },
    async improveBlock(p: CmsImproveBlockIn) {
      const { data } = await request<CmsImproveBlockOut>(
        "/admin/cms-ai/improve-block",
        { method: "POST", json: p, authed: true });
      return data;
    },
  },
  settings: {
    async list() {
      const { data } = await request<SettingOut[]>(
        "/admin/settings", { authed: true });
      return data;
    },
    async update(key: string, value: unknown) {
      const { data } = await request<SettingOut>(
        `/admin/settings/${encodeURIComponent(key)}`,
        { method: "PATCH", json: { value }, authed: true });
      return data;
    },
  },
  geoip: {
    async status() {
      const { data } = await request<GeoIPStatusOut>(
        "/admin/geoip/status", { authed: true });
      return data;
    },
    async testKey() {
      const { data } = await request<GeoIPTestKeyOut>(
        "/admin/geoip/test-key", { method: "POST", authed: true });
      return data;
    },
    async refreshNow() {
      const { data } = await request<GeoIPRefreshOut>(
        "/admin/geoip/refresh-now", { method: "POST", authed: true });
      return data;
    },
    async lookup(ip: string) {
      const { data } = await request<GeoIPLookupOut>(
        "/admin/geoip/lookup", { method: "POST", json: { ip }, authed: true });
      return data;
    },
    async previewSchedule(expression: string, count: number = 5) {
      const { data } = await request<GeoIPSchedulePreviewOut>(
        "/admin/geoip/schedule-preview",
        { method: "POST", json: { expression, count }, authed: true });
      return data;
    },
  },
  /** Drift dashboard reads. /admin/assistant-drift surfaces post-check
   *  events (refused-with-context, missing-citation, etc.) so admins
   *  can see when the LLM goes off the rails — and compare legacy vs
   *  agentic flows side-by-side once the agentic toggle ships. */
  /** Anonymous-visitor traffic — reads the `assistant.anon.*` audit
   *  events that fire when an unauthenticated user clicks the chat
   *  bubble. Drives the "Anonymous traffic" section on /admin/leads. */
  anonymousTraffic: {
    async summary(window: "24h" | "7d" | "30d" = "7d") {
      const { data } = await request<{
        window: string;
        since: string;
        totals: { unique_anons: number; events: number };
        by_region: {
          country: string | null;
          city:    string | null;
          events: number;
          unique_anons: number;
        }[];
        by_day: { day: string; events: number; unique_anons: number }[];
      }>(`/admin/anonymous-traffic/summary?window=${window}`,
         { authed: true });
      return data;
    },
  },
  /** Visitor Insights v2 — broader funnel + page-level analytics built
   *  on the journey_events stream populated by the SPA tracker. Backs
   *  /admin/insights. Four read endpoints + a GDPR action.
   *
   *  Window vocabulary mirrors anonymousTraffic / assistant-drift so a
   *  future operator can flip windows on any dashboard with the same
   *  mental model. */
  insights: {
    async overview(window: "24h" | "7d" | "30d" | "90d" = "7d") {
      const { data } = await request<{
        window: string;
        since:  string;
        kpi: {
          sessions: number;
          visitors: number;
          page_views: number;
          avg_session_seconds: number;
          avg_pages_per_session: number;
          bounce_rate: number;
          conversion_rate: number;
        };
      }>(`/admin/insights/overview?window=${window}`,
         { authed: true });
      return data;
    },
    async pages(window: "24h" | "7d" | "30d" | "90d" = "7d", limit = 20) {
      const { data } = await request<{
        window: string;
        since:  string;
        pages: {
          path: string;
          views: number;
          unique_visitors: number;
          avg_seconds: number;
          bounce_rate: number;
          exit_rate: number;
        }[];
      }>(`/admin/insights/pages?window=${window}&limit=${limit}`,
         { authed: true });
      return data;
    },
    async funnel(window: "24h" | "7d" | "30d" | "90d" = "7d") {
      const { data } = await request<{
        window: string;
        since:  string;
        stages: {
          label: string;
          event: string;
          path: string | null;
          visitors: number;
          conversion_from_prev: number | null;
        }[];
        overall_conversion: number;
      }>(`/admin/insights/funnel?window=${window}`,
         { authed: true });
      return data;
    },
    async session(anonId: string, limit = 500) {
      const { data } = await request<{
        anon_id: string;
        linked_user_ids: number[];
        event_count: number;
        first_seen: string;
        last_seen:  string;
        events: {
          id: number;
          event: string;
          at: string;
          path: string | null;
          referrer: string | null;
          device: string | null;
          browser: string | null;
          os: string | null;
          country: string | null;
          city: string | null;
          user_id: number | null;
          session_id: string | null;
          duration_ms: number | null;
          scroll_pct: number | null;
          metadata: Record<string, unknown>;
        }[];
      }>(`/admin/insights/sessions/${encodeURIComponent(anonId)}?limit=${limit}`,
         { authed: true });
      return data;
    },
    async anonymize(anonId: string) {
      const { data } = await request<{
        anon_id: string;
        rows_affected: number;
      }>(`/admin/insights/anonymize/${encodeURIComponent(anonId)}`,
         { method: "POST", authed: true });
      return data;
    },
  },
  /** Live state + cohort preview for the assistant.flow toggle.
   *  Backed by /api/v1/admin/assistant-flow/{state,preview}. */
  assistantFlow: {
    async state() {
      const { data } = await request<{
        flow: string;
        tools_max_calls: number;
        router_system: string;
        synthesis_system: string;
        shadow_sampling_rate: number;
        is_agentic_reachable: boolean;
        is_shadow_enabled: boolean;
        percent_rollout: number | null;
      }>("/admin/assistant-flow/state", { authed: true });
      return data;
    },
    async preview(params: {
      as_user_id?: number;
      as_anon_id?: string;
    } = {}) {
      const qs = new URLSearchParams();
      if (params.as_user_id !== undefined)
        qs.set("as_user_id", String(params.as_user_id));
      if (params.as_anon_id) qs.set("as_anon_id", params.as_anon_id);
      const path = "/admin/assistant-flow/preview" +
                    (qs.toString() ? "?" + qs.toString() : "");
      const { data } = await request<{
        as_user_id: number | null;
        as_anon_id: string | null;
        decision: {
          primary: "legacy" | "agentic";
          shadow:  "legacy" | "agentic" | null;
          reason:  string;
        };
        cohort_bucket: number;
      }>(path, { authed: true });
      return data;
    },
  },

  assistantDrift: {
    async summary(window: "24h" | "7d" | "30d" = "7d") {
      const { data } = await request<{
        window: string;
        since: string;
        totals: {
          // legacy + agentic always present. shadow_agentic surfaces
          // only when there were shadow drift events in the window —
          // see backend assistant_drift.py for the "no shadow events
          // → no shadow column" rationale.
          legacy:          { turns: number;       drift_events: number };
          agentic:         { turns: number;       drift_events: number };
          shadow_agentic?: { turns: number | null; drift_events: number };
        };
        by_flow_reason: { flow: string; reason: string; count: number }[];
      }>(`/admin/assistant-drift/summary?window=${window}`,
         { authed: true });
      return data;
    },
    async toolUsage(window: "24h" | "7d" | "30d" = "7d") {
      const { data } = await request<{
        window: string;
        since: string;
        total_turns: number;
        router_only_turns: number;
        tools: {
          name: string;
          calls: number;
          turns_with: number;
          by_status: Record<string, number>;
          avg_latency_ms: number | null;
          p95_latency_ms: number | null;
        }[];
      }>(`/admin/assistant-drift/tool-usage?window=${window}`,
          { authed: true });
      return data;
    },
    async events(params: {
      window?: "24h" | "7d" | "30d";
      // Backend filters on the metadata.flow value. shadow_agentic
      // is the value the AssistantOrchestrator writes for the
      // shadow side's drift detector — surfaces in the dashboard as
      // a distinct filter option.
      flow?: "legacy" | "agentic" | "shadow_agentic";
      reason?: string;
      handler?: string;
      limit?: number;
    } = {}) {
      const qs = new URLSearchParams();
      if (params.window)  qs.set("window", params.window);
      if (params.flow)    qs.set("flow", params.flow);
      if (params.reason)  qs.set("reason", params.reason);
      if (params.handler) qs.set("handler", params.handler);
      if (params.limit)   qs.set("limit", String(params.limit));
      const { data } = await request<{
        events: {
          id: number;
          user_id: number | null;
          action: string;
          reason: string;
          metadata: Record<string, unknown>;
          created_at: string;
        }[];
        count: number;
        limit: number;
      }>(`/admin/assistant-drift/events?${qs}`, { authed: true });
      return data;
    },
  },
  pricing: {
    /** /admin/pricing/fx-status — current rates + last-fetched-at +
     *  per-currency provenance. Drives the /admin/pricing dashboard. */
    async fxStatus() {
      const { data } = await request<FXStatusOut>(
        "/admin/pricing/fx-status", { authed: true });
      return data;
    },
    /** /admin/pricing/fx-refresh-now — admin-triggered pull from
     *  Frankfurter. Rate-limited to 5/hour. */
    async fxRefreshNow() {
      const { data } = await request<FXRefreshOut>(
        "/admin/pricing/fx-refresh-now", { method: "POST", authed: true });
      return data;
    },
  },
  llmProviders: {
    async list() {
      const { data } = await request<LLMProviderOut[]>(
        "/admin/llm-providers", { authed: true });
      return data;
    },
    async create(p: LLMProviderCreate) {
      const { data } = await request<LLMProviderOut>(
        "/admin/llm-providers", { method: "POST", json: p, authed: true });
      return data;
    },
    async update(id: number, p: LLMProviderUpdate) {
      const { data } = await request<LLMProviderOut>(
        `/admin/llm-providers/${id}`, { method: "PATCH", json: p, authed: true });
      return data;
    },
    async activate(id: number) {
      const { data } = await request<LLMProviderOut>(
        `/admin/llm-providers/${id}/activate`,
        { method: "POST", authed: true });
      return data;
    },
    async test(id: number) {
      const { data } = await request<{
        ok: boolean; latency_ms?: number; preview?: string; error?: string;
      }>(`/admin/llm-providers/${id}/test`, { method: "POST", authed: true });
      return data;
    },
    async delete(id: number) {
      await request(`/admin/llm-providers/${id}`,
        { method: "DELETE", authed: true });
    },
  },
  paymentProviders: {
    async list() {
      const { data } = await request<PaymentProviderOut[]>(
        "/admin/payment-providers", { authed: true });
      return data;
    },
    async create(p: PaymentProviderCreate) {
      const { data } = await request<PaymentProviderOut>(
        "/admin/payment-providers", { method: "POST", json: p, authed: true });
      return data;
    },
    async update(id: number, p: PaymentProviderUpdate) {
      const { data } = await request<PaymentProviderOut>(
        `/admin/payment-providers/${id}`,
        { method: "PATCH", json: p, authed: true });
      return data;
    },
    async activate(id: number) {
      const { data } = await request<PaymentProviderOut>(
        `/admin/payment-providers/${id}/activate`,
        { method: "POST", authed: true });
      return data;
    },
    /** Make this provider the non-INR-rail provider (typically PayPal).
     *  Razorpay continues to handle INR via activate() above. */
    async activateNonInr(id: number) {
      const { data } = await request<PaymentProviderOut>(
        `/admin/payment-providers/${id}/activate-non-inr`,
        { method: "POST", authed: true });
      return data;
    },
    async test(id: number) {
      const { data } = await request<{ ok: boolean; error?: string }>(
        `/admin/payment-providers/${id}/test`,
        { method: "POST", authed: true });
      return data;
    },
    /** Diagnose webhook signature mismatches without prod-log access.
     *  Paste a real delivery's body + signature header from the
     *  gateway dashboard's "Recent deliveries" view; we round-trip it
     *  through our verifier with the currently-stored secret and
     *  report whether it would accept. Read-only. */
    async testWebhookSignature(id: number,
                                payload: { payload: string; signature: string }) {
      const { data } = await request<{
        ok: boolean;
        reason: string;
        secret_configured: boolean;
      }>(`/admin/payment-providers/${id}/test-webhook-signature`,
         { method: "POST", json: payload, authed: true });
      return data;
    },
    async delete(id: number) {
      await request(`/admin/payment-providers/${id}`,
        { method: "DELETE", authed: true });
    },
  },
  users: {
    async list(p?: {
      q?: string; role?: string; method?: "google" | "password" | "both";
      active_from?: string; active_to?: string;
      limit?: number; offset?: number;
    }) {
      const { data } = await request<UserAdminOut[]>(
        `/admin/users${qs(p)}`, { authed: true });
      return data;
    },
    /** Per-user analytics: exam attempts/scores, time-per-course-part, quiz
     *  attempts, recent activity. Powers the admin "User Insights" page. */
    async insights(userId: number): Promise<UserInsights> {
      const { data } = await request<UserInsights>(
        `/admin/users/${userId}/insights`, { authed: true });
      return data;
    },
    async changeRole(userId: number, role: string) {
      const { data } = await request<UserAdminOut>(
        `/admin/users/${userId}/role?role=${encodeURIComponent(role)}`,
        { method: "PATCH", authed: true });
      return data;
    },
    async resetPassword(userId: number, newPassword: string) {
      const { data } = await request<UserAdminOut>(
        `/admin/users/${userId}/password`,
        { method: "PATCH", authed: true,
          json: { new_password: newPassword } });
      return data;
    },
    async delete(userId: number) {
      await request(`/admin/users/${userId}`,
        { method: "DELETE", authed: true });
    },
    /** Set or clear a user's admin-only internal notes. Mirrors
     *  ``leads.updateNotes`` so the Contacts feed can edit notes on
     *  user rows too. */
    async updateNotes(userId: number, notes: string) {
      const { data } = await request<UserAdminOut>(
        `/admin/users/${userId}/notes`,
        { method: "PATCH", json: { notes }, authed: true });
      return data;
    },
    /** Override the user's daily chat-message cap. `null` clears the
     *  override and falls back to the global `chat.daily_limit.authenticated`
     *  setting; a number sets it to exactly that many messages/day. */
    async setChatLimitOverride(userId: number, override: number | null) {
      const { data } = await request<UserAdminOut>(
        `/admin/users/${userId}/chat-limit`,
        { method: "PATCH", authed: true,
          json: { daily_chat_limit_override: override } });
      return data;
    },
  },
  plans: {
    async list(): Promise<PlanAdminOut[]> {
      const { data } = await request<PlanAdminOut[]>(
        "/admin/plans", { authed: true });
      return data;
    },
    async create(p: PlanCreate): Promise<PlanAdminOut> {
      const { data } = await request<PlanAdminOut>(
        "/admin/plans", { method: "POST", json: p, authed: true });
      return data;
    },
    async update(id: number, p: PlanUpdate): Promise<PlanAdminOut> {
      const { data } = await request<PlanAdminOut>(
        `/admin/plans/${id}`, { method: "PATCH", json: p, authed: true });
      return data;
    },
    async delete(id: number): Promise<void> {
      await request(`/admin/plans/${id}`, { method: "DELETE", authed: true });
    },
  },
  offerCodes: {
    async list(): Promise<OfferCodeAdminOut[]> {
      const { data } = await request<OfferCodeAdminOut[]>(
        "/admin/offer-codes", { authed: true });
      return data;
    },
    async create(p: OfferCodeCreate): Promise<OfferCodeAdminOut> {
      const { data } = await request<OfferCodeAdminOut>(
        "/admin/offer-codes", { method: "POST", json: p, authed: true });
      return data;
    },
    async update(id: number, p: OfferCodeUpdate): Promise<OfferCodeAdminOut> {
      const { data } = await request<OfferCodeAdminOut>(
        `/admin/offer-codes/${id}`,
        { method: "PATCH", json: p, authed: true });
      return data;
    },
    async delete(id: number): Promise<void> {
      await request(`/admin/offer-codes/${id}`,
        { method: "DELETE", authed: true });
    },
  },
  emailTemplates: {
    async list(): Promise<EmailTemplateOut[]> {
      const { data } = await request<EmailTemplateOut[]>(
        "/admin/email-templates", { authed: true });
      return data;
    },
    async create(p: EmailTemplateCreate): Promise<EmailTemplateOut> {
      const { data } = await request<EmailTemplateOut>(
        "/admin/email-templates", { method: "POST", json: p, authed: true });
      return data;
    },
    async update(id: number, p: EmailTemplateUpdate): Promise<EmailTemplateOut> {
      const { data } = await request<EmailTemplateOut>(
        `/admin/email-templates/${id}`,
        { method: "PATCH", json: p, authed: true });
      return data;
    },
    async delete(id: number): Promise<void> {
      await request(`/admin/email-templates/${id}`,
        { method: "DELETE", authed: true });
    },
    /** Send a rendered preview to the admin (or `to` override). */
    async test(id: number, to?: string): Promise<{ sent: boolean; to: string }> {
      const { data } = await request<{ sent: boolean; to: string }>(
        `/admin/email-templates/${id}/test`,
        { method: "POST", json: { to: to ?? null }, authed: true });
      return data;
    },
  },
  chatHistory: {
    async listUsers(p?: { limit?: number; offset?: number }): Promise<{
      users: Array<{
        user_id: number | null;
        email: string | null;
        name: string | null;
        turns: number;
        flagged: number;
        last_active: string;
        tokens_in: number;
        tokens_out: number;
        cost_usd: number;
      }>;
    }> {
      const { data } = await request<{
        users: Array<{
          user_id: number | null;
          email: string | null;
          name: string | null;
          turns: number;
          flagged: number;
          last_active: string;
          tokens_in: number;
          tokens_out: number;
          cost_usd: number;
        }>;
      }>(`/admin/chat-history/users${qs(p)}`, { authed: true });
      return data;
    },
    /** HITL: list flagged turns awaiting (or, with includeReplied,
     *  including already-replied) admin attention. */
    async listFlagged(p?: { include_replied?: boolean;
                            include_resolved?: boolean;
                            limit?: number; offset?: number }): Promise<{
      items: Array<FlaggedTurnAdminRow>;
    }> {
      const { data } = await request<{
        items: Array<FlaggedTurnAdminRow>;
      }>(`/admin/chat-history/flagged${qs(p)}`, { authed: true });
      return data;
    },
    /** HITL: admin posts a reply for a flagged turn. */
    async replyToFlagged(flagId: number, reply: string): Promise<{
      id: number; replied_at: string;
    }> {
      const { data } = await request<{ id: number; replied_at: string }>(
        `/admin/chat-history/turns/${flagId}/reply`,
        { method: "POST", authed: true, json: { reply } });
      return data;
    },
    /** HITL: admin closes a flagged turn (with or without replying).
     *  Hides the row from the default queue. Idempotent. */
    async resolveFlagged(flagId: number): Promise<{
      id: number; resolved_at: string; resolved_by_admin: boolean;
    }> {
      const { data } = await request<{
        id: number; resolved_at: string; resolved_by_admin: boolean;
      }>(`/admin/chat-history/turns/${flagId}/resolve`,
         { method: "POST", authed: true });
      return data;
    },
    async userTranscript(userId: number, p?: { limit?: number; offset?: number }): Promise<{
      user: { id: number; email: string | null; name: string | null };
      turns: Array<{
        id: number;
        created_at: string;
        intent: string | null;
        intent_confidence: number | null;
        provider: string | null;
        model: string | null;
        input: string | null;
        response_preview: string | null;
        tokens_in: number;
        tokens_out: number;
        cost_usd: number;
      }>;
    }> {
      const { data } = await request<{
        user: { id: number; email: string | null; name: string | null };
        turns: Array<{
          id: number;
          created_at: string;
          intent: string | null;
          intent_confidence: number | null;
          provider: string | null;
          model: string | null;
          input: string | null;
          response_preview: string | null;
          tokens_in: number;
          tokens_out: number;
          cost_usd: number;
        }>;
      }>(`/admin/chat-history/users/${userId}${qs(p)}`, { authed: true });
      return data;
    },
  },
  subscriptions: {
    /** List all subscriptions for a user (current + historical, paid + manual).
     *  Powers the "Subscriptions" sub-section on /admin/users/[id]. */
    async listForUser(userId: number): Promise<SubscriptionAdminOut[]> {
      const { data } = await request<SubscriptionAdminOut[]>(
        `/admin/users/${userId}/subscriptions`, { authed: true });
      return data;
    },
    /** Manually grant a paid plan to a user. Use when a payment was
     *  debited at the gateway but never marked successful in our system
     *  (e.g. PayPal PENDING that never released). */
    async grant(userId: number, payload: {
      plan_id: number;
      period_days: number;
      reason: string;
      source?: "manual_admin_grant" | "comp" | "refund_reversed";
    }): Promise<SubscriptionAdminOut> {
      const { data } = await request<SubscriptionAdminOut>(
        `/admin/users/${userId}/subscriptions`,
        { method: "POST", json: payload, authed: true });
      return data;
    },
    /** Bump expires_at by ``days`` for an existing sub. */
    async extend(subscriptionId: number, payload: {
      days: number; reason: string;
    }): Promise<SubscriptionAdminOut> {
      const { data } = await request<SubscriptionAdminOut>(
        `/admin/subscriptions/${subscriptionId}/extend`,
        { method: "POST", json: payload, authed: true });
      return data;
    },
    /** Mark a sub as revoked (typically after a refund). Paywall
     *  ignores it from this point on regardless of expires_at.
     *  Idempotent: re-revoking is a no-op. */
    async revoke(subscriptionId: number, payload: {
      reason: string;
    }): Promise<SubscriptionAdminOut> {
      const { data } = await request<SubscriptionAdminOut>(
        `/admin/subscriptions/${subscriptionId}/revoke`,
        { method: "POST", json: payload, authed: true });
      return data;
    },
  },
  rag: {
    async status(): Promise<{
      sources: Record<string, {
        chunks: number;
        last_indexed: string | null;
        provider: string | null;
        model: string | null;
      }>;
    }> {
      const { data } = await request<{
        sources: Record<string, {
          chunks: number; last_indexed: string | null;
          provider: string | null; model: string | null;
        }>;
      }>("/admin/rag/status", { authed: true });
      return data;
    },
    async reindex(): Promise<{ counts: Record<string, number> }> {
      const { data } = await request<{ counts: Record<string, number> }>(
        "/admin/rag/reindex", { method: "POST", authed: true });
      return data;
    },
    async listUploads(): Promise<{ documents: RagDocumentOut[] }> {
      const { data } = await request<{ documents: RagDocumentOut[] }>(
        "/admin/rag/uploads", { authed: true });
      return data;
    },
    async upload(file: File): Promise<RagDocumentOut> {
      const token = typeof window !== "undefined"
        ? window.localStorage.getItem("cpmai.access") : null;
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch(`${BASE}/admin/rag/upload`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: fd,
      });
      const body = await r.json();
      if (!r.ok) throw new ApiError(r.status, body?.error ?? {
        code: "upload_failed", message: `Upload failed (HTTP ${r.status}).`,
      });
      return body;
    },
    async deleteUpload(id: number): Promise<void> {
      await request(`/admin/rag/uploads/${id}`, {
        method: "DELETE", authed: true });
    },
  },
};

/** One subscription row in the admin view, as returned by the
 *  /admin/users/{id}/subscriptions endpoint. ``is_active_now`` is the
 *  derived paywall view at fetch time (matches what exam_service +
 *  account_state see); ``source``='paid' for organic rows and
 *  'manual_admin_grant'/'comp'/'refund_reversed' for admin-granted. */
export interface SubscriptionAdminOut {
  id: number;
  user_id: number;
  plan: string;
  plan_id: number | null;
  status: string;
  expires_at: string | null;
  current_period_start: string | null;
  current_period_end:   string | null;
  source: string;
  granted_by_user_id: number | null;
  granted_by_email:   string | null;
  grant_reason: string | null;
  revoked_at: string | null;
  revoked_by_user_id: number | null;
  revoked_by_email:   string | null;
  revoke_reason: string | null;
  is_active_now: boolean;
  created_at: string;
}

export interface RagDocumentOut {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  chunk_count: number;
  status: string;
  created_by: number | null;
  created_at: string;
}
