/**
 * Tracker auth header — page events must carry the signed-in user's
 * bearer token so the backend can attribute them (admin User Insights
 * page journey). Regression for "page visits not showing per user".
 */
import { afterEach, describe, expect, it } from "vitest";
import { trackAuthHeaders } from "@/lib/tracker";

describe("trackAuthHeaders", () => {
  afterEach(() => window.localStorage.clear());

  it("returns the Authorization header when an access token is stored", () => {
    window.localStorage.setItem("cpmai.access", "tok-123");
    expect(trackAuthHeaders()).toEqual({ Authorization: "Bearer tok-123" });
  });

  it("returns no headers when signed out", () => {
    expect(trackAuthHeaders()).toEqual({});
  });
});
