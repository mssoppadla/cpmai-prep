/**
 * Typed API client. Auto-attaches Bearer token, captures chat-quota headers,
 * and normalizes errors to the contract's `ApiErrorBody`.
 */
import type {
  ApiErrorBody, AuthTokens, LoginIn, SignupIn, RefreshIn,
  UserOut, ExamSetSummaryOut, ExamAttemptOut, AnswerIn,
  SubmitAttemptOut, AssistantRequest, AssistantResponse,
  LeadCreateIn, LeadCreateOut, ChatQuota,
} from "@/types/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

const TOKEN_KEY = "cpmai.access";
const REFRESH_KEY = "cpmai.refresh";

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

export class ApiError extends Error {
  status: number;
  body: ApiErrorBody;
  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.status = status;
    this.body = body;
  }
}

interface FetchOpts extends RequestInit {
  authed?: boolean;
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
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers,
    credentials: "include",
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
    const { data } = await request<ExamAttemptOut>(
      `/exam-sets/${slug}/start`, { method: "POST", authed: true }
    );
    return data;
  },
  async getAttempt(id: number): Promise<ExamAttemptOut> {
    const { data } = await request<ExamAttemptOut>(`/exams/attempts/${id}`,
      { authed: true });
    return data;
  },
  async saveAnswer(id: number, payload: AnswerIn): Promise<void> {
    await request(`/exams/attempts/${id}/answer`,
      { method: "PATCH", json: payload, authed: true });
  },
  async submit(id: number): Promise<SubmitAttemptOut> {
    const { data } = await request<SubmitAttemptOut>(
      `/exams/attempts/${id}/submit`, { method: "POST", authed: true }
    );
    return data;
  },
};

// ---------- Assistant ------------------------------------------------------
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
};

// ---------- Leads ----------------------------------------------------------
export const leads = {
  async submit(payload: LeadCreateIn): Promise<LeadCreateOut> {
    const { data } = await request<LeadCreateOut>("/leads",
      { method: "POST", json: payload });
    return data;
  },
};
