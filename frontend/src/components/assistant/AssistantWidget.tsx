"use client";
/**
 * Floating AI assistant widget.
 *
 * Bottom-right bubble visible on every authenticated page. Click to
 * open a side-panel chat. Behaviour:
 *
 *   - Anonymous visitor → no widget rendered (auth gate done by the
 *     parent layout via the `user` prop being null).
 *   - Signed-in user → bubble + panel. Messages POST to
 *     /api/v1/assistant/chat which returns grounded answers + citations.
 *   - Quota exhausted → panel renders the cap + reset time. User can
 *     still browse history; the input disables.
 *
 * Layout choices:
 *   - Panel pinned bottom-right at 380×600 max on desktop, full-width
 *     bottom-sheet on mobile. (Avoids covering primary content.)
 *   - Bubble doesn't follow scroll — `fixed` so it stays put.
 *   - Citations rendered inline under each assistant message as a
 *     small "Sources" footer; clicking a citation with a URL opens it.
 *   - Suggested actions render as buttons immediately after the
 *     answer body (admin handlers populate these on `account` /
 *     `pmi_reference` intents).
 */
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { content, leads, errMsg } from "@/lib/api";
import type { UserOut, AssistantCitation, SuggestedAction } from "@/types/api";
import { useAssistant, type ChatTurn } from "./useAssistant";

const DEFAULT_SUBTITLE = "Grounded in our FAQ, pricing & question explanations";


export function AssistantWidget({ user }: { user: UserOut | null }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [subtitle, setSubtitle] = useState(DEFAULT_SUBTITLE);
  // Callback-request state. Separate "view" inside the panel so the user
  // can step out of the chat to request a human follow-up without losing
  // the conversation, then return to the chat.
  const [view, setView] = useState<"chat" | "callback" | "callback_sent">("chat");
  const [cbPhone, setCbPhone] = useState("");
  const [cbNote, setCbNote] = useState("");
  const [cbBusy, setCbBusy] = useState(false);
  const [cbErr, setCbErr] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const { turns, quota, busy, error, send, clear } = useAssistant(user?.id ?? null);

  // Subtitle is admin-editable via /admin/settings → assistant.widget_subtitle.
  // Lives on SiteChrome (one public endpoint, cached). If the fetch fails or
  // returns an empty string, we fall back to the default copy — never show
  // an empty subtitle box.
  useEffect(() => {
    let cancelled = false;
    content.site()
      .then((s) => {
        if (cancelled) return;
        const v = s.assistant_widget_subtitle?.trim();
        if (v) setSubtitle(v);
      })
      .catch(() => { /* keep default */ });
    return () => { cancelled = true; };
  }, []);

  // Auto-scroll to bottom whenever turns change.
  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [turns.length, busy]);

  // Focus the input when the panel opens.
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  // Don't render the widget for anon visitors — they can't chat anyway
  // (server requires auth) and a bubble that always 401s is worse than
  // no bubble.
  if (!user) return null;

  const quotaExhausted = quota && quota.remaining <= 0;

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!draft.trim() || busy || quotaExhausted) return;
    const m = draft;
    setDraft("");
    send(m);
  }

  async function onCallbackSubmit(e: React.FormEvent) {
    e.preventDefault();
    setCbErr(null);
    const phone = cbPhone.trim();
    // Loose validation — backend still validates. Just catch obvious typos.
    if (!phone || phone.replace(/[^\d]/g, "").length < 7) {
      setCbErr("Please enter a valid phone number.");
      return;
    }
    setCbBusy(true);
    try {
      await leads.submit({
        email: user?.email ?? "",
        name:  user?.name ?? null,
        phone,
        source: "chat_callback",
        landing_url: typeof window !== "undefined" ? window.location.href : null,
        consent_marketing: false,
        interests: cbNote.trim() ? [cbNote.trim().slice(0, 200)] : [],
      });
      setView("callback_sent");
    } catch (err) {
      console.error("[assistant] callback submit failed", err);
      setCbErr(errMsg(err));
    } finally {
      setCbBusy(false);
    }
  }

  function openCallback() {
    setCbPhone("");
    setCbNote("");
    setCbErr(null);
    setView("callback");
  }

  return (
    <>
      {/* Floating bubble — always visible, toggles panel.
          `bottom` uses env(safe-area-inset-bottom) so the bubble doesn't sit
          under the iOS home-indicator gesture bar (iPhone X+) or Android
          gesture nav strip. Fallback floor of 1.25rem on devices that
          don't expose the inset.
          z-30 keeps it below the panel (z-40) and below standard modals
          (z-50) so site dialogs always cover it. */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={open ? "Close AI assistant" : "Open AI assistant"}
        style={{
          bottom: "max(1.25rem, calc(env(safe-area-inset-bottom, 0px) + 0.75rem))",
          right:  "max(1.25rem, calc(env(safe-area-inset-right, 0px) + 0.5rem))",
        }}
        className="fixed z-30 w-14 h-14 rounded-full
                   bg-indigo-600 text-white shadow-lg hover:bg-indigo-700
                   focus:outline-none focus:ring-4 focus:ring-indigo-300
                   flex items-center justify-center transition-transform
                   hover:scale-105"
      >
        {open ? (
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        ) : (
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
          </svg>
        )}
      </button>

      {/* Mobile-only backdrop — tap anywhere outside the panel dismisses it.
          Hidden ≥sm because the panel doesn't cover the viewport there. */}
      {open && (
        <div
          onClick={() => setOpen(false)}
          aria-hidden="true"
          className="fixed inset-0 z-30 bg-slate-900/20 sm:hidden"
        />
      )}

      {/* Chat panel */}
      {open && (
        <div
          style={{
            paddingBottom: "env(safe-area-inset-bottom, 0px)",
          }}
          className="fixed inset-x-0 bottom-0 sm:bottom-24 sm:right-5 sm:left-auto
                        sm:w-[380px] sm:max-h-[600px] sm:rounded-xl
                        z-40 bg-white border border-slate-200 shadow-2xl
                        flex flex-col max-h-[85vh]">
          {/* Header */}
          <header className="px-4 py-3 border-b border-slate-200 flex items-center justify-between bg-indigo-50 sm:rounded-t-xl">
            <div>
              <div className="font-semibold text-slate-900 text-sm">CPMAI Assistant</div>
              <div className="text-xs text-slate-500">
                {subtitle}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {turns.length > 0 && (
                <button
                  onClick={clear}
                  className="text-xs text-slate-500 hover:text-rose-600"
                  title="Clear conversation"
                >
                  Clear
                </button>
              )}
              <button
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="text-slate-400 hover:text-slate-700"
              >
                ✕
              </button>
            </div>
          </header>

          {/* Quota strip — only shown in chat view, hidden during callback flow */}
          {view === "chat" && quota && (
            <div className={`px-4 py-1.5 text-xs border-b border-slate-200 ${
              quotaExhausted ? "bg-rose-50 text-rose-700" : "bg-slate-50 text-slate-600"
            }`}>
              {quotaExhausted
                ? `Daily cap reached (${quota.used}/${quota.limit}). Resets ${formatReset(quota.reset_at)}.`
                : `${quota.remaining} of ${quota.limit} messages left today`}
            </div>
          )}

          {view === "chat" && (
            <>
              {/* Message list */}
              <div ref={scrollRef}
                   className="flex-1 overflow-y-auto px-4 py-3 space-y-3 bg-white">
                {turns.length === 0 && (
                  <EmptyState />
                )}
                {turns.map((t, i) => (
                  <TurnBubble key={i} turn={t} />
                ))}
                {busy && (
                  <div className="flex items-start gap-2">
                    <Avatar role="assistant" />
                    <div className="bg-slate-100 text-slate-500 rounded-lg px-3 py-2 text-sm">
                      Thinking…
                    </div>
                  </div>
                )}
                {error && (
                  <div className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded p-2">
                    {error}
                  </div>
                )}
              </div>

              {/* Input */}
              <form onSubmit={onSubmit}
                    className="border-t border-slate-200 p-3 flex gap-2 bg-white">
                <input
                  ref={inputRef}
                  type="text"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder={quotaExhausted ? "Daily cap reached" : "Ask about CPMAI…"}
                  disabled={busy || !!quotaExhausted}
                  maxLength={4000}
                  className="flex-1 px-3 py-2 text-sm border border-slate-300 rounded
                             focus:outline-none focus:ring-2 focus:ring-indigo-500
                             disabled:bg-slate-100 disabled:cursor-not-allowed"
                />
                <button
                  type="submit"
                  disabled={!draft.trim() || busy || !!quotaExhausted}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium
                             rounded hover:bg-indigo-700 disabled:opacity-50
                             disabled:cursor-not-allowed"
                >
                  Send
                </button>
              </form>
              {/* Escalation link — kept low-key so it's there when you need
                  it but doesn't shout. Lives below the input so high-intent
                  users see it after sending a message. */}
              <div className="px-3 pb-2 text-center bg-white sm:rounded-b-xl">
                <button
                  type="button"
                  onClick={openCallback}
                  className="text-xs text-slate-500 hover:text-indigo-600 hover:underline"
                >
                  Talk to a human →
                </button>
              </div>
            </>
          )}

          {view === "callback" && (
            <form onSubmit={onCallbackSubmit}
                  className="flex-1 overflow-y-auto px-4 py-4 space-y-3 bg-white sm:rounded-b-xl">
              <div>
                <div className="text-sm font-medium text-slate-900">
                  Request a callback
                </div>
                <p className="text-xs text-slate-500 mt-1">
                  Leave your phone number and we&apos;ll reach out within one
                  business day.
                </p>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  Email
                </label>
                <input type="email"
                       value={user?.email ?? ""}
                       disabled
                       className="w-full px-3 py-2 text-sm border border-slate-200 rounded bg-slate-50 text-slate-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  Phone <span className="text-rose-600">*</span>
                </label>
                <input type="tel" inputMode="tel"
                       value={cbPhone}
                       onChange={(e) => setCbPhone(e.target.value)}
                       placeholder="+91 98XXXXXXXX"
                       autoComplete="tel"
                       maxLength={32}
                       className="w-full px-3 py-2 text-sm border border-slate-300 rounded
                                  focus:outline-none focus:ring-2 focus:ring-indigo-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  Anything we should know? <span className="text-slate-400">(optional)</span>
                </label>
                <textarea value={cbNote}
                          onChange={(e) => setCbNote(e.target.value)}
                          rows={2}
                          maxLength={200}
                          placeholder="Best time to call, topic, etc."
                          className="w-full px-3 py-2 text-sm border border-slate-300 rounded
                                     focus:outline-none focus:ring-2 focus:ring-indigo-500
                                     resize-none" />
              </div>
              {cbErr && (
                <div className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded p-2">
                  {cbErr}
                </div>
              )}
              <div className="flex gap-2 pt-1">
                <button type="button"
                        onClick={() => setView("chat")}
                        className="flex-1 px-3 py-2 border border-slate-300 text-slate-700 text-sm rounded
                                   hover:bg-slate-50">
                  Back to chat
                </button>
                <button type="submit"
                        disabled={cbBusy}
                        className="flex-1 px-3 py-2 bg-indigo-600 text-white text-sm font-medium rounded
                                   hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed">
                  {cbBusy ? "Sending…" : "Request callback"}
                </button>
              </div>
            </form>
          )}

          {view === "callback_sent" && (
            <div className="flex-1 overflow-y-auto px-4 py-6 bg-white sm:rounded-b-xl flex flex-col items-center text-center gap-3">
              <div className="w-12 h-12 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </div>
              <div className="text-sm font-medium text-slate-900">
                We&apos;ll be in touch
              </div>
              <p className="text-xs text-slate-500 max-w-[260px]">
                Thanks — we&apos;ve logged your request and someone will reach
                you on the number you provided within one business day.
              </p>
              <button type="button"
                      onClick={() => setView("chat")}
                      className="mt-2 text-xs text-indigo-600 hover:underline">
                Back to chat
              </button>
            </div>
          )}
        </div>
      )}
    </>
  );
}


function EmptyState() {
  return (
    <div className="text-center py-8 text-slate-500 text-sm space-y-2">
      <p className="font-medium text-slate-700">Hi! I'm here to help with CPMAI questions.</p>
      <p className="text-xs">Try asking:</p>
      <ul className="text-xs space-y-1 text-indigo-700">
        <li>"What's the difference between Phase 2 and Phase 3?"</li>
        <li>"How much is the exam bundle?"</li>
        <li>"Where do I register for the actual exam?"</li>
      </ul>
    </div>
  );
}


function TurnBubble({ turn }: { turn: ChatTurn }) {
  if (turn.role === "user") {
    return (
      <div className="flex items-start gap-2 justify-end">
        <div className="bg-indigo-600 text-white rounded-lg px-3 py-2 text-sm max-w-[85%] whitespace-pre-wrap">
          {turn.content}
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-start gap-2">
      <Avatar role="assistant" />
      <div className="flex-1 max-w-[85%]">
        <div className="bg-slate-100 text-slate-900 rounded-lg px-3 py-2 text-sm whitespace-pre-wrap">
          {turn.content}
        </div>
        {turn.response?.suggested_actions && turn.response.suggested_actions.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {turn.response.suggested_actions.map((a, i) => (
              <ActionChip key={i} action={a} />
            ))}
          </div>
        )}
        {turn.response?.citations && turn.response.citations.length > 0 && (
          <Citations citations={turn.response.citations} />
        )}
      </div>
    </div>
  );
}


function ActionChip({ action }: { action: SuggestedAction }) {
  const internal = action.url.startsWith("/");
  if (internal) {
    return (
      <Link href={action.url}
            className="text-xs px-2 py-1 bg-indigo-50 text-indigo-700 rounded border border-indigo-200 hover:bg-indigo-100">
        {action.label} →
      </Link>
    );
  }
  return (
    <a href={action.url} target="_blank" rel="noopener noreferrer"
       className="text-xs px-2 py-1 bg-indigo-50 text-indigo-700 rounded border border-indigo-200 hover:bg-indigo-100">
      {action.label} ↗
    </a>
  );
}


function Citations({ citations }: { citations: AssistantCitation[] }) {
  return (
    <div className="mt-2 pt-2 border-t border-slate-200">
      <div className="text-xs text-slate-500 mb-1">Sources:</div>
      <ul className="space-y-0.5">
        {citations.map((c, i) => (
          <li key={i} className="text-xs">
            {c.url ? (
              c.url.startsWith("/") ? (
                <Link href={c.url} className="text-indigo-700 hover:underline">
                  [{i + 1}] {c.source}: {c.title}
                </Link>
              ) : (
                <a href={c.url} target="_blank" rel="noopener noreferrer"
                   className="text-indigo-700 hover:underline">
                  [{i + 1}] {c.source}: {c.title} ↗
                </a>
              )
            ) : (
              <span className="text-slate-600">
                [{i + 1}] {c.source}: {c.title}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}


function Avatar({ role }: { role: "user" | "assistant" }) {
  return (
    <div className={`w-6 h-6 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-bold ${
      role === "assistant"
        ? "bg-indigo-100 text-indigo-700"
        : "bg-slate-200 text-slate-600"
    }`}>
      {role === "assistant" ? "AI" : "You"}
    </div>
  );
}


function formatReset(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "soon";
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) {
      return `at ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
    }
    return `on ${d.toLocaleDateString()}`;
  } catch {
    return "soon";
  }
}
