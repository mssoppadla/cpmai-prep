/**
 * Convert an ISO-3166-1 alpha-2 country code (e.g. "IN") to a Unicode
 * flag emoji ("🇮🇳") by mapping each letter to its regional-indicator
 * code point.
 *
 * Why this instead of an icon library:
 *   - Zero dependencies, zero bytes shipped
 *   - Unicode is rendered by the OS / browser font (consistent with
 *     keyboard emoji, no version drift)
 *   - Works in plain text exports (e.g. CSV column), not just JSX
 *
 * Caveats:
 *   - Some OS/browsers don't render flags (notably Windows < 11 — the
 *     two letters appear instead). We don't try to fall back; the
 *     country code is a fine degraded experience.
 *   - "UK" is not a valid code — use "GB". MaxMind returns the ISO
 *     code so this is rarely a problem in practice.
 */

/** Map a 2-letter ISO country code to its flag emoji. Returns an empty
 *  string for invalid input (preserves layout in tables — no surprise
 *  null/undefined renders). */
export function countryFlag(code: string | null | undefined): string {
  if (!code || code.length !== 2) return "";
  const upper = code.toUpperCase();
  // Reject non-letter input ("US", not "U5"). Regional indicators
  // exist only for A-Z; anything else gives nonsense glyphs.
  if (!/^[A-Z]{2}$/.test(upper)) return "";
  const A = 0x41;                                // 'A'
  const REGIONAL_BASE = 0x1f1e6;                  // 🇦
  const first  = REGIONAL_BASE + (upper.charCodeAt(0) - A);
  const second = REGIONAL_BASE + (upper.charCodeAt(1) - A);
  return String.fromCodePoint(first, second);
}


/** Format country + city for a one-line cell. Designed for admin lists.
 *
 *  Render patterns:
 *    countryAndCity("IN", "Bengaluru") → "🇮🇳 Bengaluru"
 *    countryAndCity("AE", null)        → "🇦🇪"
 *    countryAndCity(null, null)        → "—"
 *
 *  The em-dash for the empty case is the same placeholder we use in
 *  the score/notes columns — keeps the table visually consistent.
 */
export function countryAndCity(
  country: string | null | undefined,
  city: string | null | undefined,
): string {
  const flag = countryFlag(country);
  if (flag && city) return `${flag} ${city}`;
  if (flag)         return flag;
  if (city)         return city;   // city without a country is unusual but valid
  return "—";
}
