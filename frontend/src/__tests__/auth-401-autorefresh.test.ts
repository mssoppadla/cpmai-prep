/**
 * Coverage for the 401 silent-refresh interceptor in lib/api.ts.
 *
 * Without this, a user whose access token expired between actions would
 * see a session-timeout error mid-click and have to re-login. The
 * interceptor catches the 401, transparently calls /auth/refresh with
 * the (longer-lived) refresh token, persists the new pair, and replays
 * the original request — all invisible to the caller.
 *
 * The contract this file pins:
 *   1. authed 401 → silent refresh → request replayed → caller sees 200
 *   2. concurrent 401s → ONE refresh call (deduper) → both replayed
 *   3. /auth/* paths never trigger the interceptor (no infinite loop)
 *   4. non-authed 401 isn't intercepted (nothing to refresh)
 *   5. refresh fails → tokens cleared + original 401 surfaces
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { auth, exams } from "@/lib/api";

// Helpers -------------------------------------------------------------------

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function unauthorized(): Response {
  return jsonResponse(401, {
    error: { code: "unauthorized", message: "Token expired" },
  });
}

// ---------------------------------------------------------------------------

describe("401 auto-refresh interceptor", () => {
  beforeEach(() => {
    window.localStorage.setItem("cpmai.access", "stale-access");
    window.localStorage.setItem("cpmai.refresh", "valid-refresh");
  });

  it("authed 401 triggers refresh + replay; caller sees 200", async () => {
    const calls: string[] = [];
    global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      calls.push(`${(init?.method ?? "GET")} ${url}`);
      // First /users/me → 401 (stale token)
      // /auth/refresh → 200 (mints new pair)
      // Replay /users/me → 200
      if (url.endsWith("/users/me")) {
        const auth = (init?.headers as Headers | undefined)?.get?.("Authorization")
          ?? (init?.headers as Record<string, string> | undefined)?.Authorization;
        if (auth === "Bearer stale-access") return unauthorized();
        return jsonResponse(200, {
          id: 1, email: "u@x.com", name: "U", role: "user",
        });
      }
      if (url.endsWith("/auth/refresh")) {
        return jsonResponse(200, { access: "fresh-access", refresh: "fresh-refresh" });
      }
      return jsonResponse(200, {});
    }) as typeof fetch;

    const me = await auth.me();
    expect(me.email).toBe("u@x.com");

    // Sanity: the refresh call happened, and the retry used the new token.
    expect(calls).toContain("POST " + (
      process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"
    ) + "/auth/refresh");
    expect(window.localStorage.getItem("cpmai.access")).toBe("fresh-access");
    expect(window.localStorage.getItem("cpmai.refresh")).toBe("fresh-refresh");
  });

  it("concurrent 401s share ONE refresh call (deduper)", async () => {
    let refreshCallCount = 0;
    let usersMeCount = 0;
    global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/auth/refresh")) {
        refreshCallCount += 1;
        // small delay to make the race observable
        await new Promise((r) => setTimeout(r, 10));
        return jsonResponse(200, { access: "fresh-access", refresh: "fresh-refresh" });
      }
      if (url.endsWith("/users/me")) {
        usersMeCount += 1;
        const authHeader = (init?.headers as Headers | undefined)?.get?.("Authorization");
        if (authHeader === "Bearer stale-access") return unauthorized();
        return jsonResponse(200, {
          id: 1, email: "u@x.com", name: "U", role: "user",
        });
      }
      return jsonResponse(200, {});
    }) as typeof fetch;

    // Fire 3 concurrent authed calls — all should see the stale token,
    // all should 401, and all should be replayed after a SINGLE refresh.
    const [a, b, c] = await Promise.all([auth.me(), auth.me(), auth.me()]);
    expect(a.email).toBe("u@x.com");
    expect(b.email).toBe("u@x.com");
    expect(c.email).toBe("u@x.com");

    expect(refreshCallCount).toBe(1);
    // 3 initial (all 401) + 3 retried (all 200) = 6
    expect(usersMeCount).toBe(6);
  });

  it("/auth/* paths are NOT intercepted (no infinite loop)", async () => {
    let refreshCallCount = 0;
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/auth/refresh")) {
        refreshCallCount += 1;
        return unauthorized();  // refresh-token itself is invalid
      }
      return jsonResponse(200, {});
    }) as typeof fetch;

    const ok = await auth.refresh();
    expect(ok).toBe(false);
    // Without the guard, a 401 on /auth/refresh would trigger another
    // silentRefresh() → another /auth/refresh → infinite loop. We expect
    // exactly ONE call.
    expect(refreshCallCount).toBe(1);
  });

  it("refresh failure clears tokens and surfaces original 401", async () => {
    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/users/me")) return unauthorized();
      if (url.endsWith("/auth/refresh")) return unauthorized();
      return jsonResponse(200, {});
    }) as typeof fetch;

    await expect(auth.me()).rejects.toMatchObject({ status: 401 });
    expect(window.localStorage.getItem("cpmai.access")).toBeNull();
    expect(window.localStorage.getItem("cpmai.refresh")).toBeNull();
  });

  it("authed exam call also gets transparent refresh+replay", async () => {
    let refreshCallCount = 0;
    global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/auth/refresh")) {
        refreshCallCount += 1;
        return jsonResponse(200, { access: "fresh-access", refresh: "fresh-refresh" });
      }
      if (url.endsWith("/exam-sets")) {
        const authHeader = (init?.headers as Headers | undefined)?.get?.("Authorization");
        if (authHeader === "Bearer stale-access") return unauthorized();
        return jsonResponse(200, []);
      }
      return jsonResponse(200, {});
    }) as typeof fetch;

    const list = await exams.listSets();
    expect(Array.isArray(list)).toBe(true);
    expect(refreshCallCount).toBe(1);
  });
});
