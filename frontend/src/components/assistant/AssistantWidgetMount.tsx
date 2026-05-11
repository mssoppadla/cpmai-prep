"use client";
/**
 * Client mount-point for the AssistantWidget.
 *
 * Lives in the root layout so the chat bubble follows signed-in users on
 * EVERY page — landing, pricing, dashboard, exams, etc. The widget itself
 * returns null when `user` is null, so anonymous visitors get no UI
 * disturbance on marketing pages.
 *
 * Auth check is non-blocking: page content shows immediately and the
 * /users/me probe runs in the background. Bubble appears once the probe
 * resolves to a real user. If the probe 401s (no token / expired), the
 * widget stays hidden.
 */
import { useEffect, useState } from "react";
import { auth } from "@/lib/api";
import type { UserOut } from "@/types/api";
import { AssistantWidget } from "./AssistantWidget";


export function AssistantWidgetMount() {
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

  // Render once we know the auth state. Defers the bubble flash that
  // would otherwise show + immediately hide on anon page loads.
  if (!probed) return null;
  return <AssistantWidget user={user} />;
}
