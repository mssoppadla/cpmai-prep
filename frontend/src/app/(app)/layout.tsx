/**
 * Layout for the authenticated user route group.
 *
 * Currently a pass-through. The chat widget used to mount here, but it now
 * lives in the root layout so signed-in users see the bubble on every page
 * (landing, pricing, dashboard, exams). Keeping this file means the route
 * group still has an explicit layout slot — useful for any future
 * authenticated-only chrome (e.g. an in-app top bar).
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
