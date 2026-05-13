"use client";
/**
 * Public /pricing page with currency selector.
 *
 * Lists active plans, accepts an offer code + free-text referrer, and
 * lets a signed-in user check out via Razorpay. Final price is fetched
 * from the server (`/pricing/quote`) so the breakdown shown matches
 * exactly what would be charged — no client-side discount math.
 *
 * International pricing (added 2026-05-14)
 * ----------------------------------------
 * The currency dropdown lets the visitor switch the checkout currency.
 * Each plan card shows TWO amounts side-by-side: the INR (canonical)
 * price and the user's selected-currency equivalent (computed by the
 * backend using admin-configurable FX rates). Default currency:
 *
 *   - signed-in IN user → INR
 *   - signed-in other-country user → USD
 *   - anon visitor → USD (most common non-Indian case; admin can change
 *     by editing the order of `pricing.supported_currencies` in settings)
 *
 * When the user clicks Pay, /payments/orders is called with the chosen
 * currency. Razorpay's popup opens in that currency — for non-INR,
 * the Razorpay account must have international payments enabled on
 * their dashboard. GST is INR-only (international customers don't
 * pay Indian GST), so the GST row hides automatically for non-INR.
 */
import { useEffect, useMemo, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Script from "next/script";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";
import { pricing, payments, auth, errMsg } from "@/lib/api";
import type {
  PlanPublicOut, PriceQuoteOut, UserOut, CreateOrderOut,
  CurrencyOption,
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


/**
 * Format a minor-unit amount (paise/cents) in a currency-aware way.
 * For all currencies in our default supported set the subunit is /100,
 * so we just divide and apply the symbol. JPY-style no-subunit currencies
 * would need a special case — flagged in a comment for the future.
 */
function formatMinor(minor: number, symbol: string): string {
  // All supported currencies (INR/USD/EUR/GBP/SGD/AED) use 1:100 subunits.
  return `${symbol}${(minor / 100).toFixed(2)}`;
}


/**
 * Country → preferred currency mapping. Mirrors what the backend would
 * default to if it had logic — but the backend doesn't pre-fill, so
 * this map lives client-side. Admin can shadow these defaults by
 * reordering `pricing.supported_currencies` in settings if needed.
 */
function preferredCurrencyForCountry(
  country: string | null | undefined,
  available: string[],
): string {
  const c = (country || "").toUpperCase();
  const has = (code: string) => available.includes(code);
  if (c === "IN" && has("INR")) return "INR";
  if (["US", "CA", "MX"].includes(c) && has("USD")) return "USD";
  if (c === "GB" && has("GBP")) return "GBP";
  if (c === "SG" && has("SGD")) return "SGD";
  if (c === "AE" && has("AED")) return "AED";
  // EU member states default to EUR if we support it.
  const EU = ["DE","FR","IT","ES","NL","BE","AT","IE","PT","FI",
              "GR","SK","SI","LT","LV","EE","LU","MT","CY","HR"];
  if (EU.includes(c) && has("EUR")) return "EUR";
  if (has("USD")) return "USD";
  return available[0] || "INR";
}


export default function PricingPage() {
  const router = useRouter();
  const [plans, setPlans] = useState<PlanPublicOut[] | null>(null);
  const [user, setUser] = useState<UserOut | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Currency picker state. The list comes from /pricing/currencies
  // (admin-configurable). The chosen code drives every quote + the
  // checkout currency.
  const [currencyOptions, setCurrencyOptions] = useState<CurrencyOption[]>([]);
  const [currency, setCurrency] = useState<string>("INR");
  const [currencyInitialised, setCurrencyInitialised] = useState(false);

  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [offerCode, setOfferCode] = useState("");
  const [referrer, setReferrer] = useState("");
  const [quote, setQuote] = useState<PriceQuoteOut | null>(null);
  const [quoteBusy, setQuoteBusy] = useState(false);
  const [checkoutBusy, setCheckoutBusy] = useState(false);

  // Per-plan quotes (one quote per card, in the selected currency).
  // Kept separate from `quote` (the active plan's quote shown in the
  // summary) because we want EVERY card to show the selected-currency
  // price, not just the selected one.
  const [perPlanQuotes, setPerPlanQuotes] = useState<Record<string, PriceQuoteOut>>({});

  // Load plans + currencies + auth state in parallel.
  useEffect(() => {
    (async () => {
      try { setPlans(await pricing.listPlans()); }
      catch (e) { setErr(errMsg(e)); }
    })();
    (async () => {
      try {
        const r = await pricing.listCurrencies();
        // Defensive: if the backend (or a test mock) returns a body
        // missing the ``options`` field, fall back to INR-only.
        const opts = Array.isArray(r?.options) ? r.options : [];
        setCurrencyOptions(opts.length > 0 ? opts : [
          { code: "INR", symbol: "₹", has_fx_rate: true },
        ]);
      } catch (e) {
        // Non-fatal — fall back to INR-only.
        console.warn("[pricing] currencies fetch failed", e);
        setCurrencyOptions([
          { code: "INR", symbol: "₹", has_fx_rate: true },
        ]);
      }
    })();
    (async () => {
      try { setUser(await auth.me()); }
      catch { setUser(null); }
      finally { setAuthChecked(true); }
    })();
  }, []);

  // Initialise currency exactly once, after we know both the available
  // options AND the user's country. Until that's settled, leave the
  // picker on its INR default. Once initialised, the user's manual
  // selection wins (we don't re-snap when their country changes — it
  // doesn't, but defensively).
  useEffect(() => {
    if (currencyInitialised) return;
    if (currencyOptions.length === 0) return;
    if (!authChecked) return;
    const available = currencyOptions.filter(o => o.has_fx_rate).map(o => o.code);
    if (available.length === 0) return;
    setCurrency(preferredCurrencyForCountry(user?.country, available));
    setCurrencyInitialised(true);
  }, [currencyInitialised, currencyOptions, authChecked, user]);

  // Default to the first plan once loaded.
  useEffect(() => {
    if (plans && plans.length > 0 && selectedSlug === null) {
      setSelectedSlug(plans[0].slug);
    }
  }, [plans, selectedSlug]);

  // Re-quote the SELECTED plan (drives the order-summary panel) whenever
  // selection / offer / currency changes.
  useEffect(() => {
    if (!selectedSlug) { setQuote(null); return; }
    let cancelled = false;
    (async () => {
      setQuoteBusy(true); setErr(null);
      try {
        const q = await pricing.quote(selectedSlug, offerCode || undefined, currency);
        if (!cancelled) setQuote(q);
      } catch (e) {
        if (!cancelled) { setErr(errMsg(e)); setQuote(null); }
      } finally {
        if (!cancelled) setQuoteBusy(false);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedSlug, offerCode, currency]);

  // Quote EVERY plan in the selected currency, so each card can show
  // the dual-amount column. Triggered on currency change (and on plan
  // list load). No offer code — the per-card preview is "list price";
  // the summary panel handles the offer-applied math.
  const fetchAllQuotes = useCallback(async (cur: string) => {
    if (!plans || plans.length === 0) return;
    const entries: Record<string, PriceQuoteOut> = {};
    await Promise.all(plans.map(async (p) => {
      try { entries[p.slug] = await pricing.quote(p.slug, undefined, cur); }
      catch { /* skip — card just won't show converted amount */ }
    }));
    setPerPlanQuotes(entries);
  }, [plans]);

  useEffect(() => {
    if (currencyInitialised && plans) fetchAllQuotes(currency);
  }, [currencyInitialised, currency, plans, fetchAllQuotes]);

  const selectedPlan = useMemo(
    () => plans?.find(p => p.slug === selectedSlug) ?? null,
    [plans, selectedSlug]);

  const currentCurrencyOption = useMemo(
    () => currencyOptions.find(o => o.code === currency)
       ?? { code: currency, symbol: currency, has_fx_rate: false },
    [currencyOptions, currency]);

  // Disable Pay when the selected currency isn't actually chargeable
  // (admin listed it without configuring an FX rate). The dropdown
  // option is rendered disabled for these too, but defense-in-depth.
  // ``display_currency_supported`` defaults to true if the field is
  // absent (older backend / partial test mock) — that way we still
  // allow INR checkout against a mock that doesn't include the new
  // fields.
  const canCheckout = !!quote && (quote.display_currency_supported ?? true)
                     && currentCurrencyOption.has_fx_rate;

  async function checkout() {
    if (!quote || !selectedPlan) return;
    if (!user) {
      router.push(`/login?next=${encodeURIComponent("/pricing")}`);
      return;
    }
    if (!canCheckout) {
      setErr(`Currency ${currency} isn't configured for checkout yet. ` +
              "Pick another currency or contact the admin.");
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
        currency,
      });
    } catch (e) {
      setErr(errMsg(e)); setCheckoutBusy(false); return;
    }

    // Open Razorpay's hosted checkout in the selected currency.
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
      <Script src="https://checkout.razorpay.com/v1/checkout.js"
              strategy="afterInteractive" />
      <SiteHeader active="pricing" />
      <main className="flex-1 max-w-5xl w-full mx-auto px-4 py-10">
        <div className="flex items-baseline justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-3xl font-bold text-slate-900">Pricing</h1>
            <p className="text-slate-600 mt-2">
              One-time payment, 1-year access. All plans include
              CPMAI-aligned mock exams and the AI tutor.
            </p>
          </div>
          {/* Currency picker. Disabled options are visible but
              unselectable — admin needs to add an FX rate before
              they become chargeable. */}
          <label className="text-sm flex items-center gap-2">
            <span className="text-slate-700">Show prices in:</span>
            <select
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              className="px-3 py-1.5 text-sm border border-slate-300 rounded
                         focus:ring-1 focus:ring-indigo-500 outline-none bg-white"
            >
              {currencyOptions.map(opt => (
                <option key={opt.code}
                        value={opt.code}
                        disabled={!opt.has_fx_rate}>
                  {opt.symbol} {opt.code}
                  {!opt.has_fx_rate ? " (not configured)" : ""}
                </option>
              ))}
            </select>
          </label>
        </div>

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
                const planQuote = perPlanQuotes[p.slug];
                const showConverted = currency !== "INR"
                  && planQuote
                  && planQuote.display_currency_supported;
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
                    {/* Dual-amount row. Always shows INR canonical; if
                        a non-INR currency is selected, the converted
                        amount sits to the right of the INR price. */}
                    <div className="mt-3 flex items-baseline gap-3 flex-wrap">
                      {p.discount_price_paise != null ? (
                        <>
                          <span className="text-2xl font-bold text-slate-900">
                            ₹{(p.discount_price_paise / 100).toFixed(2)}
                          </span>
                          <span className="text-sm text-slate-400 line-through">
                            ₹{(p.base_price_paise / 100).toFixed(2)}
                          </span>
                        </>
                      ) : (
                        <span className="text-2xl font-bold text-slate-900">
                          ₹{(p.base_price_paise / 100).toFixed(2)}
                        </span>
                      )}
                      {showConverted && (
                        <span className="text-lg font-semibold text-indigo-700"
                              title={`@ ₹${planQuote.display_fx_rate?.toFixed(2)} per 1 ${currency}`}>
                          ≈ {formatMinor(planQuote.display_amount_minor,
                                          currentCurrencyOption.symbol)}
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
                        Offer applied — saving ₹{(quote.offer_discount_paise / 100).toFixed(2)}.
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
                    <Row label="Base" value={`₹${(selectedPlan.base_price_paise / 100).toFixed(2)}`} />
                    {selectedPlan.discount_price_paise != null && (
                      <Row label="Plan discount"
                           value={`-₹${((selectedPlan.base_price_paise - selectedPlan.discount_price_paise) / 100).toFixed(2)}`}
                           muted />
                    )}
                    {quote?.offer_applied && (
                      <Row label={`Offer (${quote.offer_code})`}
                           value={`-₹${(quote.offer_discount_paise / 100).toFixed(2)}`}
                           muted />
                    )}
                    {/* GST line ONLY when the selected currency is INR.
                        International customers don't pay Indian GST,
                        and the backend already drops it from the charge. */}
                    {quote && quote.gst_percent > 0 && currency === "INR" && (
                      <>
                        <Row label="Subtotal"
                             value={`₹${(quote.subtotal_paise / 100).toFixed(2)}`} muted />
                        <Row label={`GST (${quote.gst_percent}%)`}
                             value={`+₹${(quote.gst_paise / 100).toFixed(2)}`} muted />
                      </>
                    )}
                    {/* For non-INR: GST is INR-only so we explicitly
                        note it doesn't apply. Then we BREAK OUT the
                        international processing fee (markup) as a
                        separate line, so the buyer sees exactly what
                        they're paying for: subtotal at mid-market FX
                        + a transparent fee. */}
                    {quote && currency !== "INR" && quote.display_currency_supported && (
                      <>
                        <Row label="Indian GST"
                             value="not applicable (international)"
                             muted />
                        {(quote.display_subtotal_minor ?? 0) > 0 && (
                          <Row label={`Subtotal (${currency})`}
                               value={formatMinor(quote.display_subtotal_minor ?? 0,
                                                   currentCurrencyOption.symbol)}
                               muted />
                        )}
                        {(quote.display_markup_minor ?? 0) > 0 && (
                          <Row
                            label={`International processing fee (${(quote.display_markup_percent ?? 0).toFixed(1)}%)`}
                            value={`+${formatMinor(quote.display_markup_minor ?? 0,
                                                    currentCurrencyOption.symbol)}`}
                            muted />
                        )}
                        {/* Razorpay International accepts only whole units
                            for some currencies (GBP confirmed). We ceil the
                            total to the next whole unit and surface the
                            delta as its own line so the buyer sees the
                            cents added, not a silent mismatch between the
                            quoted price and the card charge. */}
                        {(quote.display_rounding_adjustment_minor ?? 0) > 0 && (
                          <Row
                            label="Rounded to whole unit"
                            value={`+${formatMinor(quote.display_rounding_adjustment_minor ?? 0,
                                                    currentCurrencyOption.symbol)}`}
                            muted />
                        )}
                      </>
                    )}
                    {/* TOTAL row. INR: final INR. Non-INR: total
                        (subtotal + markup) with FX rate as a footnote. */}
                    {currency === "INR" ? (
                      <Row strong label="Total to pay"
                           value={quote
                              ? `₹${(quote.final_price_paise / 100).toFixed(2)}`
                              : (quoteBusy ? "…" : "—")} />
                    ) : (
                      <>
                        <Row strong label={`Total to pay (${currency})`}
                             value={quote && quote.display_currency_supported
                                ? formatMinor(quote.display_amount_minor,
                                               currentCurrencyOption.symbol)
                                : (quoteBusy ? "…" : "—")} />
                        {quote && quote.display_currency_supported && (
                          <div className="text-xs text-slate-500 text-right -mt-0.5 space-y-0.5">
                            <div>
                              ≈ ₹{(quote.subtotal_paise / 100).toFixed(2)} INR
                            </div>
                            {quote.display_fx_rate_raw && (
                              <div className="italic">
                                Live ECB FX: 1 {currency} = ₹{quote.display_fx_rate_raw.toFixed(2)}
                                {quote.display_fx_source === "stale" && (
                                  <span className="text-amber-600 not-italic">
                                    {" "}(may be stale)
                                  </span>
                                )}
                              </div>
                            )}
                            {quote.display_fx_source === "override" && (
                              <div className="italic">
                                Rate: ₹{quote.display_fx_rate?.toFixed(2)} per 1 {currency}
                                {" "}(admin-set)
                              </div>
                            )}
                          </div>
                        )}
                      </>
                    )}
                  </div>

                  <button onClick={checkout}
                          disabled={!canCheckout || quoteBusy || checkoutBusy}
                          className="w-full px-4 py-3 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50">
                    {!authChecked
                      ? "…"
                      : !user
                        ? "Sign in to continue"
                        : (checkoutBusy
                           ? "Creating order…"
                           : `Pay with Razorpay (${currency})`)}
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
