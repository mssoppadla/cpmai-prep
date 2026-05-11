"use client";
/**
 * Layout for the authenticated user route group.
 *
 * Mounts the floating AI chat widget on every page inside `(app)/*`
 * — currently `/exams`, `/exams/[slug]`, `/exams/results/[id]`, and
 * future authenticated routes. Public pages (landing, /pricing,
 * /login) stay clean.
 *
 * Auth check is non-blocking: the layout shows page content
 * immediately and probes `/users/me` in the background. The widget
 * mounts once we know who's signed in (null for anon → widget hides
 * itself).
 */
import { useEffect, useState } from "react";
import { auth } from "@/lib/api";
import type { UserOut } from "@/types/api";
import { AssistantWidget } from "@/components/assistant/AssistantWidget";


export default function AppLayout({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null);
  const [probed, setProbed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    auth.me()
      .then((u) => { if (!cancelled) setUser(u); })
      .catch(() => { /* anon or expired token — widget stays hidden */ })
      .finally(() => { if (!cancelled) setProbed(true); });
    return () => { cancelled = true; };
  }, []);

  return (
    <>
      {children}
      {/* Widget renders only for authenticated users; takes itself off
          the DOM for anon visitors (so the bubble doesn't appear and
          then disappear on the auth probe race). */}
      {probed && <AssistantWidget user={user} />}
    </>
  );
}
