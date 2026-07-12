/** Quick links shown on the 404 / error pages when
 *  errors.show_help_links is on. Shared so both pages stay in sync. */
export const HELP_LINKS = [
  { href: "/",        label: "Home" },
  { href: "/courses", label: "Courses" },
  { href: "/exams",   label: "Mock exams" },
  { href: "/pricing", label: "Pricing" },
] as const;
