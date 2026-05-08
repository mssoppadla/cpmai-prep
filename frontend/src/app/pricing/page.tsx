"use client";
/**
 * Public /pricing page.
 *
 * Lists active plans, accepts an offer code + free-text referrer, and
 * lets a signed-in user check out via Razorpay. Final price is fetched
 * from the server (`/pricing/quote`) so the breakdown shown matches
 * exactly what would be charged — no client-side discount math.
 *
 * Phase 1 keeps the user on this page for offer entry. Phase 2 will
 * gate the "Buy" button behind Google login when the user isn't auth'd.
 * Today we just send unauthenticated users to /login?next=/pricing.
 */
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Script from "next/script";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import { pricing, payments, auth, errMsg } from "@/lib/api";
import type {
  PlanPublicOut, PriceQuoteOut, UserOut, CreateOrderOut,
} from "@/types/api";

declare global {
  interface Window { Razorpay?: new (opts: RazorpayOptions) => RazorpayInstance }
}
interface RazorpayInstance { open(): void; on(event: string, cb: (resp: unknown) => void): void }
interface RazorpayOptions {
  key: string; amount: number; currency: string; order_id: string;
  name?: string; description?: string;
  prefill?: { email?: string; name?: string };
  theme?: { color?: string };
  handler: (resp: { razorpay_payment_id: string; razorpay_order_id: string;
                     razorpay_signature: string }) => void;
  modal?: { ondismiss?: () => void };
}


function rupees(paise: number) { return (paise / 100).toFixed(2); }


export default function PricingPage() {
  const router = useRouter();
  const [plans, setPlans] = useState<PlanPublicOut[] | null>(null);
  const [user, setUser] = useState<UserOut | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [offerCode, setOfferCode] = useState("");
  const [referrer, setReferrer] = useState("");
  const [quote, setQuote] = useState<PriceQuoteOut | null>(null);
  const [quoteBusy, setQuoteBusy] = useState(false);
  const [checkoutBusy, setCheckoutBusy] = useState(false);

  // Load plans + auth state in parallel.
  useEffect(() => {
    (async () => {
      try { setPlans(await pricing.listPlans()); }
      catch (e) { setErr(errMsg(e)); }
    })();
    (async () => {
      try { setUser(await auth.me()); }
      catch { setUser(null); }
      finally { setAuthChecked(true); }
    })();
  }, []);

  // Default to the first plan once loaded.
  useEffect(() => {
    if (plans && plans.length > 0 && selectedSlug === null) {
      setSelectedSlug(plans[0].slug);
    }
  }, [plans, selectedSlug]);

  // Re-quote any time selection or offer changes.
  useEffect(() => {
    if (!selectedSlug) { setQuote(null); return; }
    let cancelled = false;
    (async () => {
      setQuoteBusy(true); setErr(null);
      try {
        const q = await pricing.quote(selectedSlug, offerCode || undefined);
        if (!cancelled) setQuote(q);
      } catch (e) {
        if (!cancelled) { setErr(errMsg(e)); setQuote(null); }
      } finally {
        if (!cancelled) setQuoteBusy(false);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedSlug, offerCode]);

  const selectedPlan = useMemo(
    () => plans?.find(p => p.slug === selectedSlug) ?? null,
    [plans, selectedSlug]);

  async function checkout() {
    if (!quote || !selectedPlan) return;
    if (!user) {
      router.push(`/login?next=${encodeURIComponent("/pricing")}`);
      return;
    }
    if (!window.Razorpay) {
      setErr("Razorpay checkout script hasn't loaded yet. Refresh and try again.");
      return;
    }

    setCheckoutBusy(true); setErr(null);
    let order: CreateOrderOut;
    try {
      order = await payments.createOrder({
        plan_slug: selectedPlan.slug,
        offer_code: offerCode || null,
        referrer: referrer || null,
      });
    } catch (e) {
      setErr(errMsg(e)); setCheckoutBusy(false); return;
    }

    // Open Razorpay's hosted checkout. On success, post the signed
    // payment back to /payments/verify — that's where Subscription is
    // actually created. Cancel/dismiss leaves the order in 'created'
    // state; webhook hardening (phase 3) will reconcile it.
    const rzp = new window.Razorpay({
      key: order.razorpay_key_id,
      amount: order.amount,
      currency: order.currency,
      order_id: order.order_id,
      name: order.plan_name,
      description: `${selectedPlan.duration_days}-day access`,
      prefill: { email: user.email, name: user.name ?? undefined },
      theme: { color: "#4f46e5" },
      handler: async (resp) => {
        try {
          const verified = await payments.verify({
            order_id: resp.razorpay_order_id,
            payment_id: resp.razorpay_payment_id,
            signature: resp.razorpay_signature,
          });
          // Subscription is now active. Send them straight to the
          // exam list — paywall now lets them through.
          router.push(`/exams?paid=${encodeURIComponent(verified.plan_slug)}`);
        } catch (e) {
          setErr(`Payment captured but verification failed: ${errMsg(e)}. ` +
                  "Refresh and your subscription should appear; if not, contact support.");
        } finally {
          setCheckoutBusy(false);
        }
      },
      modal: { ondismiss: () => setCheckoutBusy(false) },
    });
    rzp.open();
  }

  return (
    <div className="min-h-screen flex flex-col bg-slate-50">
      {/* Razorpay's hosted checkout SDK. Loaded once per page render —
          only when the user actually hits /pricing, not site-wide.
          afterInteractive: load after the page is interactive but
          before the user can realistically click "Pay". */}
      <Script src="https://checkout.razorpay.com/v1/checkout.js"
              strategy="afterInteractive" />
      <SiteHeader active="pricing" />
      <main className="flex-1 max-w-5xl w-full mx-auto px-4 py-10">
        <h1 className="text-3xl font-bold text-slate-900">Pricing</h1>
        <p className="text-slate-600 mt-2">
          One-time payment, 1-year access. All plans include CPMAI-aligned
          mock exams and the AI tutor.
        </p>

        {err && (
          <div role="alert" className="bg-rose-50 border border-rose-200 text-rose-700 p-3 rounded-lg my-4 text-sm">
            {err}
          </div>
        )}

        {plans === null && !err ? (
          <div className="mt-8 text-slate-500">Loading plans…</div>
        ) : plans === null ? null : plans.length === 0 ? (
          <div className="mt-8 text-slate-500">
            No plans are currently active. Check back soon.
          </div>
        ) : (
          <div className="mt-8 grid md:grid-cols-2 gap-6">
            {/* ------------- Plan cards ------------- */}
            <div className="space-y-3">
              {plans.map(p => {
                const selected = p.slug === selectedSlug;
                return (
                  <button key={p.id} onClick={() => setSelectedSlug(p.slug)}
                    className={`w-full text-left rounded-xl border p-5 transition ${
                      selected
                        ? "border-indigo-600 ring-2 ring-indigo-200 bg-white"
                        : "border-slate-200 bg-white hover:border-slate-300"}`}>
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="font-semibold text-slate-900">{p.name}</span>
                      <span className="text-xs uppercase tracking-wide text-slate-500">
                        {p.bundle_type.replace("_", " ")}
                      </span>
                    </div>
                    {p.description && (
                      <p className="text-sm text-slate-600 mt-1">{p.description}</p>
                    )}
                    <div className="mt-3 flex items-baseline gap-2">
                      {p.discount_price_paise != null ? (
                        <>
                          <span className="text-2xl font-bold text-slate-900">
                            ₹{rupees(p.discount_price_paise)}
                          </span>
                          <span className="text-sm text-slate-400 line-through">
                            ₹{rupees(p.base_price_paise)}
                          </span>
                        </>
                      ) : (
                        <span className="text-2xl font-bold text-slate-900">
                          ₹{rupees(p.base_price_paise)}
                        </span>
                      )}
                      <span className="text-sm text-slate-500">
                        / {p.duration_days} days
                      </span>
                    </div>
                    {p.exam_sets.length > 0 && (
                      <div className="mt-3 text-xs text-slate-500">
                        Includes {p.exam_sets.length} exam set
                        {p.exam_sets.length === 1 ? "" : "s"}.
                      </div>
                    )}
                  </button>
                );
              })}
            </div>

            {/* ------------- Quote + checkout ------------- */}
            <div className="bg-white rounded-xl border border-slate-200 p-5">
              <h2 className="font-semibold text-slate-900">Order summary</h2>
              {!selectedPlan ? (
                <div className="text-sm text-slate-500 mt-2">Select a plan.</div>
              ) : (
                <div className="mt-4 space-y-4">
                  <div className="text-sm">
                    <div className="font-medium">{selectedPlan.name}</div>
                    <div className="text-slate-500">/{selectedPlan.slug}</div>
                  </div>

                  <label className="block">
                    <span className="block text-xs font-medium text-slate-700 mb-1">
                      Offer code (optional)
                    </span>
                    <input value={offerCode}
                           onChange={e => setOfferCode(e.target.value)}
                           placeholder="e.g. SAVE10"
                           className="w-full border border-slate-300 rounded px-3 py-2 uppercase text-sm" />
                    {quote?.offer_reason && !quote.offer_applied && (
                      <div className="mt-1 text-xs text-amber-700">
                        {quote.offer_reason}
                      </div>
                    )}
                    {quote?.offer_applied && (
                      <div className="mt-1 text-xs text-emerald-700">
                        Offer applied — saving ₹{rupees(quote.offer_discount_paise)}.
                      </div>
                    )}
                  </label>

                  <label className="block">
                    <span className="block text-xs font-medium text-slate-700 mb-1">
                      Referred by (optional)
                    </span>
                    <input value={referrer}
                           onChange={e => setReferrer(e.target.value)}
                           placeholder="Name or email of who referred you"
                           className="w-full border border-slate-300 rounded px-3 py-2 text-sm" />
                  </label>

                  <div className="border-t border-slate-200 pt-3 text-sm space-y-1">
                    <Row label="Base" value={`₹${rupees(selectedPlan.base_price_paise)}`} />
                    {selectedPlan.discount_price_paise != null && (
                      <Row label="Plan discount"
                           value={`-₹${rupees(selectedPlan.base_price_paise - selectedPlan.discount_price_paise)}`}
                           muted />
                    )}
                    {quote?.offer_applied && (
                      <Row label={`Offer (${quote.offer_code})`}
                           value={`-₹${rupees(quote.offer_discount_paise)}`}
                           muted />
                    )}
                    {quote && quote.gst_percent > 0 && (
                      <>
                        <Row label="Subtotal"
                             value={`₹${rupees(quote.subtotal_paise)}`} muted />
                        <Row label={`GST (${quote.gst_percent}%)`}
                             value={`+₹${rupees(quote.gst_paise)}`} muted />
                      </>
                    )}
                    <Row strong label="Total to pay"
                         value={quote
                            ? `₹${rupees(quote.final_price_paise)}`
                            : (quoteBusy ? "…" : "—")} />
                  </div>

                  <button onClick={checkout}
                          disabled={!quote || quoteBusy || checkoutBusy}
                          className="w-full px-4 py-3 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50">
                    {!authChecked
                      ? "…"
                      : !user
                        ? "Sign in to continue"
                        : (checkoutBusy ? "Creating order…" : "Pay with Razorpay")}
                  </button>
                  {!user && authChecked && (
                    <p className="text-xs text-slate-500 text-center">
                      You'll be redirected to sign in first — your selection
                      will be remembered.
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </main>
      <SiteFooter />
    </div>
  );
}


function Row({ label, value, muted, strong }:
              { label: string; value: string; muted?: boolean; strong?: boolean }) {
  return (
    <div className={`flex justify-between ${strong ? "font-semibold text-slate-900 pt-2" : ""}`}>
      <span className={muted ? "text-slate-500" : "text-slate-700"}>{label}</span>
      <span>{value}</span>
    </div>
  );
}
