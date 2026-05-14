/**
 * Typed API client. Auto-attaches Bearer token, captures chat-quota headers,
 * and normalizes errors to the contract's `ApiErrorBody`.
 */
import type {
  ApiErrorBody, AuthTokens, LoginIn, SignupIn, RefreshIn,
  UserOut, UserAdminOut, UserDashboardOut, ExamSetSummaryOut, ExamSetAdminIn,
  ExamAttemptOut, AnswerIn, SubmitAttemptOut,
  AssistantRequest, AssistantResponse,
  LeadCreateIn, LeadCreateOut, LeadAdminOut, ContactRow, ChatQuota,
  FaqOut, FaqAdminOut, FaqIn, LandingCopy, SiteChrome,
  QuestionAdminIn, QuestionAdminOut, ExamSetLinkedQuestion,
  SettingOut, LLMProviderOut, LLMProviderCreate, LLMProviderUpdate,
  PaymentProviderOut, PaymentProviderCreate, PaymentProviderUpdate,
  PlanPublicOut, PlanAdminOut, PlanCreate, PlanUpdate,
  OfferCodeAdminOut, OfferCodeCreate, OfferCodeUpdate,
  PriceQuoteOut, CreateOrderIn, CreateOrderOut, CurrenciesOut,
  VerifyPaymentIn, VerifyPaymentOut,
  PayPalCaptureIn, PayPalCaptureOut,
  GeoIPStatusOut, GeoIPRefreshOut, GeoIPTestKeyOut, GeoIPLookupOut,
  GeoIPSchedulePreviewOut,
  FXStatusOut, FXRefreshOut,
} from "@/types/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

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
    id: number; status: "pending" | "replied" | "closed";
  }> {
    const { data } = await request<{
      id: number; status: "pending" | "replied" | "closed";
    }>(`/assistant/turns/${turnId}/flag`, {
      method: "POST", authed: true,
      json: { note: note?.trim() || null },
    });
    return data;
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
export const leads = {
  async submit(payload: LeadCreateIn): Promise<LeadCreateOut> {
    const { data } = await request<LeadCreateOut>("/leads",
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

export const content = {
  async topics(): Promise<Array<{id: number; code: string; name: string; order: number}>> {
    const { data } = await request<Array<{id: number; code: string; name: string; order: number}>>(
      "/content/topics");
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

export const admin = {
  questions: {
    async list(p?: {
      topic_id?: number;
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
    /** Download the .xlsx template admins fill in for bulk uploads.
     *  Returns the raw blob so the caller can save-as locally. */
    async downloadBulkTemplate(): Promise<Blob> {
      const token = typeof window !== "undefined"
        ? window.localStorage.getItem("cpmai.access") : null;
      const r = await fetch(`${BASE}/admin/questions/bulk-template`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!r.ok) throw new ApiError(r.status, {
        code: "download_failed",
        message: `Template download failed (HTTP ${r.status}).`,
      });
      return r.blob();
    },
    /** Upload a filled .xlsx. Returns per-row breakdown:
     *    { created: N, created_ids: number[], errors: [{row, field, message}] }
     *  Caller should surface errors to the admin so they can fix the
     *  failing rows in their sheet and re-upload only those. */
    async bulkUpload(file: File): Promise<{
      created: number;
      created_ids: number[];
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
      limit?: number; offset?: number;
    }) {
      const { data } = await request<UserAdminOut[]>(
        `/admin/users${qs(p)}`, { authed: true });
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
                            limit?: number; offset?: number }): Promise<{
      items: Array<{
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
      }>;
    }> {
      const { data } = await request<{
        items: Array<{
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
        }>;
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
