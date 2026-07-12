"use client";
/**
 * Root error boundary — replaces Next's unstyled default when a page
 * render throws. Copy is ADMIN-EDITABLE (errors.server_error_* in
 * /admin/settings) with the seeded defaults baked in as fallbacks:
 * when the API is the thing that broke, the error page must still
 * render something sensible. The help-links block obeys the same
 * errors.show_help_links toggle as the 404 page.
 *
 * Must be a client component (Next passes {error, reset}); copy is
 * fetched after mount and swaps in when it arrives.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { content } from "@/lib/api";
import { HELP_LINKS } from "@/lib/help-links";

const FALLBACK = {
  server_error_title: "Something went wrong on our end",
  server_error_body: "Please try again — or jump back to one of these pages:",
  show_help_links: true,
};

export default function RootError({ error, reset }: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const [copy, setCopy] = useState(FALLBACK);

  useEffect(() => {
    console.error("[error-boundary]", error);
    let cancel = false;
    (async () => {
      try {
        const c = await content.errors();
        if (!cancel) setCopy(c);
      } catch { /* API down — keep fallbacks */ }
    })();
    return () => { cancel = true; };
  }, [error]);

  return (
    <main className="min-h-screen bg-slate-50">
      <div className="max-w-2xl mx-auto px-4 sm:px-6 pt-20 sm:pt-28 pb-24 text-center">
        <div aria-hidden className="text-6xl sm:text-7xl font-bold text-rose-100 select-none">
          !
        </div>
        <h1 className="mt-4 text-2xl sm:text-3xl font-bold text-slate-900">
          {copy.server_error_title}
        </h1>
        {copy.server_error_body && (
          <p className="mt-3 text-slate-600">{copy.server_error_body}</p>
        )}

        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <button onClick={reset}
                  className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm
                             font-semibold hover:bg-indigo-700 transition">
            Try again
          </button>
          {copy.show_help_links && HELP_LINKS.map(l => (
            <Link key={l.href} href={l.href}
                  className="px-4 py-2 rounded-lg border border-slate-300 bg-white
                             text-sm font-medium text-slate-700 hover:border-indigo-300
                             hover:text-indigo-700 transition">
              {l.label}
            </Link>
          ))}
        </div>
      </div>
    </main>
  );
}
