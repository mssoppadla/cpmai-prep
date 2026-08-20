"use client";
/**
 * WhatsApp chat bubble — floats LEFT of the AI assistant bubble on
 * every page, for logged-in and anonymous visitors alike.
 *
 * It is a deep link, not a panel: clicking opens a chat with the
 * configured number in the visitor's OWN WhatsApp (app on phones,
 * WhatsApp Web on desktop) with a pre-typed message. Nothing opens on
 * our page, so it can never conflict with the assistant panel — the
 * panel floats at bottom≥96px while both bubbles sit in the ≤76px
 * strip below it.
 *
 * Config is admin-driven (chat.* settings) and arrives via the public
 * /content/site payload: an empty whatsapp_number (disabled or
 * unconfigured, or the fetch failed) renders NOTHING — the site
 * behaves exactly as before the feature existed.
 *
 * The prefill is enriched so the operator can identify who is writing:
 * logged-in users get their name/email appended; everyone gets the
 * page they came from. WhatsApp itself shows the sender's number and
 * profile name either way.
 */
import { useEffect, useState } from "react";
import { content } from "@/lib/api";
import type { UserOut } from "@/types/api";

/** Module-level cache: the root layout keeps this mounted across
 *  client navigation, but remounts (full reloads) shouldn't refetch
 *  in dev StrictMode double-invokes either. */
let cached: { number: string; prefill: string } | null = null;

export function WhatsAppBubble({
  user,
  pathname,
}: {
  user: UserOut | null;
  pathname: string;
}) {
  const [cfg, setCfg] = useState(cached);

  useEffect(() => {
    if (cached) { setCfg(cached); return; }
    let cancelled = false;
    content.site()
      .then((s) => {
        cached = {
          number: s.whatsapp_number || "",
          prefill: s.whatsapp_prefill || "",
        };
        if (!cancelled) setCfg(cached);
      })
      .catch(() => { /* silent — bubble simply doesn't render */ });
    return () => { cancelled = true; };
  }, []);

  if (!cfg || !cfg.number) return null;

  const identity = user
    ? ` — I'm ${user.name || user.email} (${user.email}).`
    : "";
  const page = pathname && pathname !== "/" ? pathname : "/home";
  const text = `${cfg.prefill}${identity} [via ${page}]`;
  const href =
    `https://wa.me/${cfg.number}?text=${encodeURIComponent(text)}`;

  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Chat with us on WhatsApp"
      title="Chat with us on WhatsApp"
      style={{
        // Same bottom line as the assistant bubble; shifted one
        // bubble-width + gap to its left so the pair never overlaps
        // and both stay below the assistant panel (bottom: 96px).
        bottom: "max(1.25rem, calc(env(safe-area-inset-bottom, 0px) + 0.75rem))",
        right: "max(5.5rem, calc(env(safe-area-inset-right, 0px) + 4.75rem))",
        backgroundColor: "#25D366",
      }}
      className="fixed z-30 w-14 h-14 rounded-full text-white shadow-lg
                 hover:brightness-95 focus:outline-none focus:ring-4
                 focus:ring-green-300 flex items-center justify-center
                 transition-transform hover:scale-105"
    >
      <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor"
           aria-hidden="true">
        <path d="M17.47 14.38c-.3-.15-1.76-.87-2.03-.97-.27-.1-.47-.15-.67.15-.2.3-.77.97-.94 1.16-.17.2-.35.22-.64.08-.3-.15-1.26-.47-2.39-1.48-.88-.79-1.48-1.76-1.65-2.06-.17-.3-.02-.46.13-.6.13-.14.3-.35.45-.52.15-.18.2-.3.3-.5.1-.2.05-.37-.03-.52-.07-.15-.67-1.61-.91-2.2-.24-.58-.49-.5-.67-.51h-.57c-.2 0-.52.07-.79.37-.27.3-1.04 1.02-1.04 2.48s1.07 2.87 1.21 3.07c.15.2 2.1 3.2 5.08 4.49.71.31 1.26.49 1.7.63.71.22 1.36.19 1.87.11.57-.08 1.76-.72 2-1.41.25-.7.25-1.29.18-1.41-.08-.13-.28-.2-.57-.35M12.05 21.79h-.01a9.87 9.87 0 0 1-5.03-1.38l-.36-.21-3.74.98 1-3.65-.24-.37a9.86 9.86 0 0 1-1.51-5.26c0-5.45 4.44-9.88 9.89-9.88a9.82 9.82 0 0 1 9.88 9.89c0 5.45-4.43 9.88-9.88 9.88m8.41-18.3A11.82 11.82 0 0 0 12.05 0C5.5 0 .16 5.34.16 11.89c0 2.1.55 4.14 1.59 5.95L.06 24l6.3-1.65a11.88 11.88 0 0 0 5.68 1.45c6.56 0 11.89-5.34 11.9-11.89a11.82 11.82 0 0 0-3.48-8.42" />
      </svg>
    </a>
  );
}
