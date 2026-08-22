/**
 * Persistent browser identity (X-Anon-ID) — the localStorage value that
 * owns anonymous exam attempts doubles as the analytics id, so login
 * can claim BOTH the journey history and the exam results.
 *
 *   1. getAnonId mints once and stays stable across calls.
 *   2. Every request() ships it as X-Anon-ID.
 *   3. Signed-in requests carry it TOO (that's what lets the backend
 *      link the browser at login).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { getAnonId, pricing, auth } from "@/lib/api";

function captureFetch() {
  const calls: { url: string; headers: Headers }[] = [];
  global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({
      url: String(input),
      headers: new Headers(init?.headers),
    });
    return new Response("[]", {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
  return calls;
}

describe("persistent anon identity", () => {
  afterEach(() => window.localStorage.clear());

  it("mints one id and keeps it stable", () => {
    const a = getAnonId();
    expect(a).toBeTruthy();
    expect(getAnonId()).toBe(a);
    expect(window.localStorage.getItem("cpmai.anon_token")).toBe(a);
  });

  it("ships X-Anon-ID on anonymous API calls", async () => {
    const calls = captureFetch();
    await pricing.listPlans();
    expect(calls[0].headers.get("X-Anon-ID")).toBe(getAnonId());
  });

  it("ships X-Anon-ID alongside the bearer token when signed in", async () => {
    window.localStorage.setItem("cpmai.access", "tok-abc");
    const calls = captureFetch();
    await auth.me();
    expect(calls[0].headers.get("Authorization")).toBe("Bearer tok-abc");
    expect(calls[0].headers.get("X-Anon-ID")).toBe(getAnonId());
  });

  it("login request itself carries the id (claim-on-login handshake)", async () => {
    const anonBefore = getAnonId();
    global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      expect(headers.get("X-Anon-ID")).toBe(anonBefore);
      return new Response(JSON.stringify({
        access: "a", refresh: "r",
        user: { id: 1, email: "x@y.z" },
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }) as typeof fetch;
    await auth.login({ email: "x@y.z", password: "pw" });
    // Logging in must NOT rotate the browser identity — the same id
    // keeps attributing future signed-out visits to this account.
    expect(getAnonId()).toBe(anonBefore);
  });
});
