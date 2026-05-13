/**
 * Country-flag util tests. Pure-function, so the suite is fast.
 *
 * The bug shape we're guarding against: someone refactors the
 * regional-indicator math and quietly produces wrong glyphs ("FR" →
 * "🇧🇸" or similar). We pin a few well-known codes so any drift
 * surfaces immediately.
 */
import { describe, expect, it } from "vitest";
import { countryFlag, countryAndCity } from "@/lib/country-flag";


describe("countryFlag", () => {
  it("maps common codes to the correct flag emoji", () => {
    // Hand-verified by paste-into-OS-emoji-keyboard.
    expect(countryFlag("IN")).toBe("🇮🇳");
    expect(countryFlag("SG")).toBe("🇸🇬");
    expect(countryFlag("AE")).toBe("🇦🇪");
    expect(countryFlag("US")).toBe("🇺🇸");
    expect(countryFlag("GB")).toBe("🇬🇧");
  });

  it("is case insensitive", () => {
    expect(countryFlag("in")).toBe(countryFlag("IN"));
    expect(countryFlag("Sg")).toBe(countryFlag("SG"));
  });

  it("returns empty string for invalid input", () => {
    expect(countryFlag(null)).toBe("");
    expect(countryFlag(undefined)).toBe("");
    expect(countryFlag("")).toBe("");
    expect(countryFlag("I")).toBe("");     // too short
    expect(countryFlag("IND")).toBe("");   // too long
    expect(countryFlag("U5")).toBe("");    // non-letter
    expect(countryFlag("12")).toBe("");
  });
});


describe("countryAndCity", () => {
  it("renders flag + city when both present", () => {
    expect(countryAndCity("IN", "Bengaluru")).toBe("🇮🇳 Bengaluru");
  });

  it("renders flag only when country present without city", () => {
    expect(countryAndCity("AE", null)).toBe("🇦🇪");
  });

  it("renders city alone when no country code", () => {
    // Rare but possible (older Lead row with city manually entered).
    expect(countryAndCity(null, "Test City")).toBe("Test City");
  });

  it("renders em-dash when neither is set", () => {
    expect(countryAndCity(null, null)).toBe("—");
    expect(countryAndCity(undefined, undefined)).toBe("—");
    expect(countryAndCity("", "")).toBe("—");
  });

  it("invalid country falls back to city or em-dash", () => {
    expect(countryAndCity("U5", "Somewhere")).toBe("Somewhere");
    expect(countryAndCity("U5", null)).toBe("—");
  });
});
