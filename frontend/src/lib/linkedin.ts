/** Normalise a LinkedIn id/URL the aspirant typed into a clickable href. */
export function linkedinHref(v: string): string {
  const s = v.trim();
  if (/^https?:\/\//i.test(s)) return s;
  if (s.startsWith("linkedin.com") || s.startsWith("www.linkedin.com")) return `https://${s}`;
  return `https://www.linkedin.com/in/${s.replace(/^\/?(in\/)?/, "")}`;
}
