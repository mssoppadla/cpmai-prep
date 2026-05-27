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
import { assistant, content, leads, errMsg,
         type AssistantNotification } from "@/lib/api";
import type { UserOut, AssistantCitation, SuggestedAction } from "@/types/api";
import { useAssistant, type ChatTurn } from "./useAssistant";

const DEFAULT_SUBTITLE = "Grounded in our FAQ, pricing & question explanations";
// EmptyState fallback — matches the previously-hardcoded list so the
// widget keeps working before /content/site has resolved (and as a
// guard if an admin nukes the setting entirely).
const DEFAULT_TRY_ASKING: string[] = [
  "What's the difference between Phase 2 and Phase 3?",
  "How much is the exam bundle?",
  "Where do I register for the actual exam?",
];
// Anon-state copy shown when an unauthenticated visitor opens the
// chat. Kept in sync with the backend seed default so SSR/CSR don't
// flicker different text on first paint.
const DEFAULT_ANON_MESSAGE =
  "Please sign in to continue chatting. Anonymous chat needs a " +
  "browser identifier — refresh the page or sign in.";


export function AssistantWidget({ user }: { user: UserOut | null }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [subtitle, setSubtitle] = useState(DEFAULT_SUBTITLE);
  // Admin-editable starter prompts. Pulled from the SAME /content/site
  // fetch as the subtitle so we don't add another round-trip.
  const [tryAsking, setTryAsking] = useState<string[]>(DEFAULT_TRY_ASKING);
  // Anon-state copy. Shown when `user === null` instead of the chat
  // input — admin-editable so the wording can be tuned (and stays in
  // sync with the backend guardrail error that triggers if anyone
  // bypasses the frontend and POSTs without auth).
  const [anonMessage, setAnonMessage] = useState(DEFAULT_ANON_MESSAGE);
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

  // HITL: unread admin replies. Drives the red-dot indicator on the
  // bubble + the "Support reply" cards prepended to the message list.
  const [notifications, setNotifications] = useState<AssistantNotification[]>([]);

  // Per-turn flag UI state, keyed by turn_id from the AssistantResponse.
  // "resolved" mode is the post-withdrawal terminal state: the user
  // saw their own flag close. Shipped in feat/flagged-turn-resolve.
  const [flagState, setFlagState] = useState<Record<number, {
    mode: "idle" | "open" | "submitting" | "sent" | "error" | "resolved";
    note: string;
    err?: string;
  }>>({});

  // Poll notifications on mount + every time the panel opens. No
  // long-polling; opening the widget is the natural read trigger.
  //
  // Extra guard: the `user` prop can be non-null (set from a /auth/me
  // cookie path) while the localStorage access token has been cleared
  // or expired in the background. Calling the endpoint in that state
  // returns a legitimate 401, which the browser logs to the devtools
  // console even though our `.catch` swallows it. To keep the console
  // clean for end-users, only fire the request when we have BOTH a
  // user AND a usable token.
  useEffect(() => {
    if (!user) return;
    if (typeof window === "undefined") return;
    const tok = window.localStorage.getItem("cpmai.access");
    if (!tok) return;
    let cancelled = false;
    assistant.notifications()
      .then((n) => { if (!cancelled) setNotifications(n); })
      .catch(() => { /* silent — not critical */ });
    return () => { cancelled = true; };
  }, [user, open]);

  // When the panel opens and there are unread replies, mark them seen
  // after a short delay (so the user has time to see the highlight).
  useEffect(() => {
    if (!open || notifications.length === 0) return;
    const ids = notifications.map((n) => n.id);
    const t = setTimeout(() => {
      Promise.all(ids.map((id) => assistant.markNotificationSeen(id)
                                            .catch(() => null)))
        .then(() => setNotifications([]));
    }, 2500);
    return () => clearTimeout(t);
  }, [open, notifications]);

  async function submitFlag(turnId: number) {
    const s = flagState[turnId];
    setFlagState((m) => ({ ...m, [turnId]: { ...s, mode: "submitting", note: s?.note ?? "" } }));
    try {
      await assistant.flagTurn(turnId, s?.note);
      setFlagState((m) => ({ ...m, [turnId]: { mode: "sent", note: "" } }));
    } catch (e) {
      setFlagState((m) => ({ ...m, [turnId]: {
        ...s, mode: "error", note: s?.note ?? "",
        err: errMsg(e),
      } }));
    }
  }

  // User withdraws their own flag — either pending (before admin
  // replied) or after seeing the admin reply. Idempotent on the
  // backend; UI just shows the terminal "resolved" mode.
  async function resolveUserFlag(turnId: number) {
    try {
      await assistant.resolveFlaggedTurn(turnId);
      setFlagState((m) => ({ ...m, [turnId]: { mode: "resolved", note: "" } }));
    } catch (e) {
      // Don't surface errors — resolve is a "best effort" UX action.
      // If the network failed, the next page refresh will re-fetch
      // the real state from the server.
      console.error("[chat] resolve flag failed", e);
    }
  }

  // After the admin's reply lands and the user sees the
  // SupportReplyBubble, they can mark the whole thread resolved.
  // Optimistically removes the bubble from the local notifications
  // list so the widget chrome stops nagging the user about it.
  async function resolveNotificationFromBubble(
    flagId: number, logId: number,
  ) {
    try {
      // Resolve is keyed on the chat turn (log_id), not the flag_id.
      // The user-facing endpoint takes log_id because the user
      // doesn't know flag_ids.
      await assistant.resolveFlaggedTurn(logId);
      setNotifications((n) => n.filter((x) => x.id !== flagId));
      // Also stamp the flag state if we have one for this turn so
      // the "Wasn't helpful?" affordance under the turn bubble
      // reflects the resolved state.
      setFlagState((m) => ({ ...m, [logId]: { mode: "resolved", note: "" } }));
    } catch (e) {
      console.error("[chat] resolve from notification failed", e);
    }
  }

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
        // Suggestions: admin can clear the list entirely (server enforces
        // 0..10 entries). Treat an empty array as "admin opted out" and
        // skip rendering the EmptyState block — don't fall back to the
        // hardcoded default in that case.
        if (Array.isArray(s.assistant_try_asking_suggestions)) {
          setTryAsking(
            s.assistant_try_asking_suggestions
              .map((x: string) => String(x).trim())
              .filter(Boolean)
          );
        }
        const am = s.assistant_anonymous_no_identity_message?.trim();
        if (am) setAnonMessage(am);
      })
      .catch(() => { /* keep defaults */ });
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

  // Anonymous-visitor tracking — two distinct events:
  //
  //   1. page_view   — fired ONCE per browser session, on any page the
  //                    widget mounts on (so just landing on the site
  //                    counts; the visitor doesn't have to interact
  //                    with the bubble). This is "raw traffic".
  //   2. bubble_open — fired ONCE per browser session when an anon
  //                    actually clicks the chat. This is "intent to
  //                    engage" — a stronger signal than a page view.
  //
  // Both go through the same /assistant/anon-event endpoint; the `kind`
  // ends up as the audit_logs.action suffix and the summary endpoint
  // aggregates either way. The dashboard shows total events + unique
  // anons; operators can compare bubble_open count vs page_view count
  // to see the conversion rate from traffic to engagement.
  //
  // Backend short-circuits for authenticated users, so a user who
  // signs in mid-session won't get retroactively tracked.
  //
  // Why sessionStorage rather than useRef for the page_view flag:
  //   * useRef dedupes within a single React mount only. The widget
  //     IS mounted at the layout level so route changes don't unmount
  //     it — but a full page reload (Ctrl-R, navigating to an
  //     external link and back, opening the site in a new tab) WOULD
  //     remount and fire again.
  //   * sessionStorage survives full reloads within the same tab,
  //     resets when the tab closes. That matches the conceptual unit
  //     of "one visit" — a returning visitor next day counts again,
  //     but tab-internal navigation/refresh doesn't.
  //
  // The audit_logs volume is bounded by (sessions × distinct kinds).
  // For a site at our scale that's fine; if traffic explodes we can
  // add a daily TTL job.
  useEffect(() => {
    if (user) return;
    if (typeof window === "undefined") return;   // SSR guard
    const KEY = "cpmai_anon_pageview_fired";
    try {
      if (sessionStorage.getItem(KEY)) return;
      sessionStorage.setItem(KEY, "1");
    } catch {
      // Storage blocked (private-browsing quirks, strict cookie
      // settings) — fire anyway. Worst case the same anon counts
      // twice per route change. Better than no data.
    }
    assistant.anonEvent("page_view");
  }, [user]);

  // bubble_open — fires when the anon clicks the bubble to actually
  // engage with chat. Kept separate from page_view so the dashboard
  // can show both "traffic" and "engagement" metrics.
  const anonEventFired = useRef(false);
  useEffect(() => {
    // Inline `!user` rather than `isAnon` — `isAnon` is declared
    // below for readability in the JSX, but this effect runs above
    // that declaration in source order. TypeScript caught the use-
    // before-declaration; the semantics are identical either way.
    if (open && !user && !anonEventFired.current) {
      anonEventFired.current = true;
      // Fire-and-forget. Lib client swallows errors; this is operational
      // telemetry, not user-blocking.
      assistant.anonEvent("bubble_open");
    }
  }, [open, user]);

  // Anon users see the bubble + the panel — opening it shows the
  // configured "please sign in" CTA instead of the chat input. The
  // bubble is one of the strongest acquisition affordances on the
  // page, so we WANT anon visitors to interact with it; the panel
  // is just gated behind login. The backend's no-identity guardrail
  // raises the same configured message from `assistant.anonymous_
  // no_identity_message`, so the inline message and any defensive
  // backend error stay in sync.
  const isAnon = !user;

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
        {/* The red-dot notification badge is ``position: absolute`` and
            anchors to the top-right of THIS button via its
            ``position: fixed`` containing block (fixed elements
            establish a positioning context for their abs-positioned
            descendants — no need to add ``relative`` to the button).
            Adding ``relative`` here previously CLOBBERED ``fixed`` (both
            are position utilities, ``.relative`` wins in Tailwind's
            output order) — that's how the bubble drifted into the
            document flow and ended up bottom-LEFT on pages where the
            layout pushed it that way. Don't reintroduce it. */}
        {!open && notifications.length > 0 && (
          <span
            aria-label={`${notifications.length} unread reply`}
            className="absolute top-0 right-0 w-3.5 h-3.5 rounded-full
                       bg-rose-500 border-2 border-white"
          />
        )}
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

          {view === "chat" && isAnon && (
            <AnonChatState message={anonMessage}
                            currentPath={typeof window !== "undefined"
                              ? window.location.pathname : "/"} />
          )}

          {view === "chat" && !isAnon && (
            <>
              {/* Message list */}
              <div ref={scrollRef}
                   className="flex-1 overflow-y-auto px-4 py-3 space-y-3 bg-white">
                {turns.length === 0 && notifications.length === 0 && (
                  <EmptyState
                    suggestions={tryAsking}
                    onPick={(text) => {
                      setDraft(text);
                      // Refocus the input so the keyboard cursor lands
                      // there immediately and the user can hit Enter
                      // without an extra click.
                      setTimeout(() => inputRef.current?.focus(), 0);
                    }}
                  />
                )}
                {notifications.map((n) => (
                  <SupportReplyBubble key={n.id} notification={n}
                                       onResolve={() =>
                                         resolveNotificationFromBubble(
                                           n.id, n.assistant_log_id)} />
                ))}
                {turns.map((t, i) => (
                  <TurnBubble key={i} turn={t}
                              flagState={t.response?.turn_id != null
                                ? flagState[t.response.turn_id] : undefined}
                              onFlagOpen={(id) => setFlagState((m) => ({
                                ...m, [id]: { mode: "open", note: "" },
                              }))}
                              onFlagCancel={(id) => setFlagState((m) => {
                                const { [id]: _drop, ...rest } = m;
                                return rest;
                              })}
                              onFlagNoteChange={(id, v) => setFlagState((m) => ({
                                ...m, [id]: { ...(m[id] ?? { mode: "open", note: "" }), note: v },
                              }))}
                              onFlagSubmit={submitFlag}
                              onFlagResolve={resolveUserFlag} />
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
                  data-track="cta:talk_to_human"
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
                        data-track="cta:request_callback_submit"
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


/** Panel content shown to unauthenticated visitors who open the chat.
 *
 *  Renders the admin-configured ``assistant.anonymous_no_identity_message``
 *  (same key the backend guardrail raises, so SSR and any defensive
 *  backend response stay in lockstep). Replaces the message list +
 *  input + "Talk to a human" link — the input would just trigger the
 *  same backend error, so showing it up-front is faster than the
 *  type-and-discover flow.
 *
 *  ``currentPath`` is encoded into the Sign In link's `?next=` so the
 *  visitor lands back on the page they were on after authenticating —
 *  natural continuation of whatever they were reading when the chat
 *  invited them in.
 */
function AnonChatState({
  message, currentPath,
}: {
  message: string;
  currentPath: string;
}) {
  const next = encodeURIComponent(currentPath || "/");
  return (
    <div className="flex-1 overflow-y-auto px-5 py-6 bg-white
                    sm:rounded-b-xl flex flex-col items-center text-center gap-4">
      <div className="w-12 h-12 rounded-full bg-indigo-100 text-indigo-700
                      flex items-center justify-center">
        {/* Lock-with-key icon — same stroke style as the bubble icon
            so the panel feels visually consistent. */}
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2" strokeLinecap="round"
             strokeLinejoin="round">
          <rect x="3" y="11" width="18" height="11" rx="2" />
          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
        </svg>
      </div>
      <p className="text-sm text-slate-700 max-w-[280px] leading-relaxed">
        {message}
      </p>
      <div className="w-full max-w-[220px]">
        {/* Sign-in only — the app's authentication is Google-only (no
            email/password signup page exists). The /login route hosts
            the Google one-tap flow; signing in there also serves as
            the account-creation path for first-time visitors. */}
        <a href={`/login?next=${next}`}
           className="block px-4 py-2 bg-indigo-600 text-white text-sm font-semibold
                      rounded-lg hover:bg-indigo-700 transition-colors text-center">
          Sign in with Google
        </a>
      </div>
      <p className="text-xs text-slate-400 max-w-[260px]">
        New here? Signing in with Google creates your account
        automatically — no separate signup needed.
      </p>
    </div>
  );
}


function EmptyState({
  suggestions, onPick,
}: {
  suggestions: string[];
  /** Called when the learner clicks a suggestion chip. Should pre-fill
   *  the chat input with the text so the learner can Enter to send. */
  onPick: (text: string) => void;
}) {
  return (
    <div className="text-center py-8 text-slate-500 text-sm space-y-3">
      <p className="font-medium text-slate-700">Hi! I'm here to help with CPMAI questions.</p>
      {suggestions.length > 0 && (
        <>
          <p className="text-xs">Try asking:</p>
          {/* Clickable chips. Buttons (not <li>) so screen readers
              recognise them as interactive and Enter/Space activate
              them. type="button" stops the surrounding form from
              submitting — pre-fill only, don't send yet. */}
          <ul className="flex flex-col items-center gap-1.5 text-xs">
            {suggestions.map((s) => (
              <li key={s}>
                <button type="button"
                        onClick={() => onPick(s)}
                        className="text-left text-indigo-700 hover:text-indigo-900
                                   hover:underline focus:outline-none focus:ring-2
                                   focus:ring-indigo-400 rounded px-1 py-0.5
                                   max-w-full break-words">
                  &ldquo;{s}&rdquo;
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}


interface FlagUiState {
  mode: "idle" | "open" | "submitting" | "sent" | "error" | "resolved";
  note: string;
  err?: string;
}

function TurnBubble({ turn, flagState, onFlagOpen, onFlagCancel,
                     onFlagNoteChange, onFlagSubmit, onFlagResolve }: {
  turn: ChatTurn;
  flagState?: FlagUiState;
  onFlagOpen?: (id: number) => void;
  onFlagCancel?: (id: number) => void;
  onFlagNoteChange?: (id: number, v: string) => void;
  onFlagSubmit?: (id: number) => void;
  onFlagResolve?: (id: number) => void;
}) {
  if (turn.role === "user") {
    return (
      <div className="flex items-start gap-2 justify-end">
        <div className="bg-indigo-600 text-white rounded-lg px-3 py-2 text-sm max-w-[85%] whitespace-pre-wrap">
          {turn.content}
        </div>
      </div>
    );
  }
  const turnId = turn.response?.turn_id ?? null;
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
        {turnId != null && (
          <FlagControl turnId={turnId} state={flagState}
                       onOpen={onFlagOpen} onCancel={onFlagCancel}
                       onNoteChange={onFlagNoteChange}
                       onSubmit={onFlagSubmit}
                       onResolve={onFlagResolve} />
        )}
      </div>
    </div>
  );
}


function FlagControl({ turnId, state, onOpen, onCancel, onNoteChange,
                       onSubmit, onResolve }: {
  turnId: number; state?: FlagUiState;
  onOpen?: (id: number) => void;
  onCancel?: (id: number) => void;
  onNoteChange?: (id: number, v: string) => void;
  onSubmit?: (id: number) => void;
  /** User-initiated withdrawal — called when the user taps
   *  "Withdraw" / "Mark resolved" under their own flag. Optional;
   *  if omitted, the resolve UI is hidden (graceful degrade). */
  onResolve?: (id: number) => void;
}) {
  const mode = state?.mode ?? "idle";
  if (mode === "resolved") {
    // Terminal state after the user withdrew their own flag. Stays
    // muted — we don't want to bother them about a thing they
    // already closed.
    return (
      <div className="mt-1.5 text-xs text-slate-500 italic">
        ✓ Flag withdrawn.
      </div>
    );
  }
  if (mode === "sent") {
    return (
      <div className="mt-1.5 text-xs text-emerald-700 bg-emerald-50 border
                       border-emerald-200 rounded px-2 py-1 flex items-center
                       justify-between gap-2">
        <span>
          ✓ Sent for review. A teammate will reply here when they can.
        </span>
        {onResolve && (
          <button type="button"
            onClick={() => onResolve(turnId)}
            className="text-[11px] text-emerald-700 hover:text-emerald-900
                       hover:underline shrink-0"
            title="Withdraw this flag — you don't need a follow-up.">
            Withdraw
          </button>
        )}
      </div>
    );
  }
  if (mode === "open" || mode === "submitting" || mode === "error") {
    return (
      <div className="mt-2 border border-slate-200 rounded-lg p-2 bg-slate-50">
        <label className="block text-xs text-slate-600 mb-1">
          What was wrong about this answer? <span className="text-slate-400">(optional)</span>
        </label>
        <textarea
          value={state?.note ?? ""}
          onChange={(e) => onNoteChange?.(turnId, e.target.value)}
          rows={2} maxLength={500}
          disabled={mode === "submitting"}
          className="w-full text-sm border border-slate-300 rounded px-2 py-1
                     focus:outline-none focus:ring-1 focus:ring-indigo-400"
          placeholder="e.g. The exam is monthly, not quarterly."
        />
        {state?.err && (
          <div className="text-xs text-rose-600 mt-1">{state.err}</div>
        )}
        <div className="flex justify-end gap-1.5 mt-1.5">
          <button type="button"
            onClick={() => onCancel?.(turnId)}
            disabled={mode === "submitting"}
            className="text-xs px-2 py-1 text-slate-600 hover:text-slate-900 disabled:opacity-50">
            Cancel
          </button>
          <button type="button"
            onClick={() => onSubmit?.(turnId)}
            disabled={mode === "submitting"}
            className="text-xs px-2 py-1 bg-indigo-600 text-white rounded
                       hover:bg-indigo-700 disabled:opacity-50">
            {mode === "submitting" ? "Sending…" : "Send for review"}
          </button>
        </div>
      </div>
    );
  }
  return (
    <button type="button"
      onClick={() => onOpen?.(turnId)}
      className="mt-1 text-xs text-slate-400 hover:text-rose-600 hover:underline">
      Wasn't helpful?
    </button>
  );
}


function SupportReplyBubble({ notification, onResolve }: {
  notification: AssistantNotification;
  /** User taps "Mark resolved" — fire-and-forget call to the
   *  resolve endpoint + optimistic-remove from the widget. */
  onResolve?: () => void;
}) {
  return (
    <div className="flex items-start gap-2">
      <div className="w-6 h-6 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-bold bg-emerald-100 text-emerald-700">
        ✓
      </div>
      <div className="flex-1 max-w-[85%]">
        <div className="bg-emerald-50 border border-emerald-200 text-slate-900 rounded-lg px-3 py-2 text-sm whitespace-pre-wrap">
          <div className="text-xs font-semibold text-emerald-700 mb-1">
            Reply from our team
            {notification.replied_by_name && ` · ${notification.replied_by_name}`}
          </div>
          {notification.admin_reply}
        </div>
        <div className="text-[10px] text-slate-400 mt-1 flex items-center
                          justify-between gap-2">
          <span>
            Re: <em>&ldquo;{notification.original_message.slice(0, 80)}
              {notification.original_message.length > 80 ? "…" : ""}&rdquo;</em>
          </span>
          {onResolve && (
            <button type="button"
              onClick={onResolve}
              className="text-[10px] text-emerald-700 hover:text-emerald-900
                         hover:underline shrink-0"
              title="Close this thread — this reply helped.">
              Mark resolved
            </button>
          )}
        </div>
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
  // Native HTML <details>/<summary>: collapsed by default, click to expand.
  // Chose native over a custom toggle because:
  //   * keyboard-accessible out of the box (Tab + Enter / Space)
  //   * screen-reader friendly without aria-* boilerplate
  //   * zero JS for the toggle behavior
  //   * one less piece of state to manage
  //
  // Style is intentionally low-contrast — sources are reference material,
  // not the primary content. The "📚 N sources" summary line gives users
  // a quick at-a-glance source count without overwhelming the message.
  const count = citations.length;
  return (
    <details className="mt-2 pt-2 border-t border-slate-200 group">
      <summary className="text-xs text-slate-500 cursor-pointer
                          hover:text-slate-700 select-none
                          flex items-center gap-1
                          marker:hidden [&::-webkit-details-marker]:hidden">
        <span className="inline-block transition-transform duration-150
                          group-open:rotate-90">▸</span>
        <span>📚 {count} source{count === 1 ? "" : "s"}</span>
      </summary>
      <ul className="space-y-0.5 mt-1.5 ml-3 border-l-2 border-slate-100 pl-2.5">
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
    </details>
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
