/**
 * Regression test for the "Failed to fetch" callback bug.
 *
 * Background: the chat widget's "Talk to a human → Request callback"
 * button calls POST /leads anonymously. The request() helper used to
 * hardcode `credentials: "include"` on every call, which made the
 * browser do a credentialed CORS preflight. Against a wildcard
 * `Access-Control-Allow-Origin: *` (the prod default until CORS_ORIGINS
 * is set explicitly), the browser rejects the response and surfaces
 * `TypeError: Failed to fetch` — no API error code, just an opaque
 * network failure.
 *
 * Contract going forward: api.ts default is `credentials: "same-origin"`.
 * The app uses Bearer tokens in localStorage, never cookies, so this is
 * always safe. Callers can still opt in via opts.credentials if needed.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { leads, auth } from "@/lib/api";

describe("api credentials default", () => {
  beforeEach(() => {
    global.fetch = vi.fn(async () => new Response(
      JSON.stringify({ id: 1, message: "ok", access: "a", refresh: "r" }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    )) as typeof fetch;
  });

  it("anon POST /leads does NOT send credentials: 'include'", async () => {
    await leads.submit({
      email: "a@b.com",
      source: "chat_callback",
      consent_marketing: false,
      interests: [],
    } as never);

    const call = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const init = call[1] as RequestInit;
    expect(init.credentials).toBe("same-origin");
    expect(init.credentials).not.toBe("include");
  });

  it("authed call (login) also defaults to same-origin (Bearer carries auth)", async () => {
    await auth.login({ email: "a@b.com", password: "x" } as never);

    const call = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const init = call[1] as RequestInit;
    expect(init.credentials).toBe("same-origin");
  });
});
