"use client";
/**
 * PayPal return landing — buyer lands here after approving on PayPal.
 *
 * PayPal appends ``?token=<order_id>&PayerID=<payer_id>`` to the
 * ``return_url`` we set in the backend's create_order. We pull the
 * order_id out of ``token``, call our /payments/paypal/capture
 * endpoint, then route the buyer to /exams (success) or back to
 * /pricing with an error (failure).
 *
 * The capture is idempotent on our side — if the PayPal webhook
 * already fired and activated the subscription before the buyer's
 * browser bounced back, the capture endpoint short-circuits and we
 * just route them to /exams.
 *
 * Loading state matters here: the buyer's just been bounced through
 * PayPal and back. Showing nothing while we capture feels broken.
 * We render a spinner + status text and explicit fallback to
 * /pricing if anything goes wrong.
 */
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { payments, errMsg } from "@/lib/api";
import { firePurchaseConversion } from "@/lib/ads";


// Next.js 14 strict build refuses to prerender pages that call
// useSearchParams() at the top level — the search params can only be
// resolved at request time, so the static path-collection phase bails
// out with a build error. Wrapping in <Suspense> tells the prerenderer
// that the inner component is intentionally request-time; it renders
// the fallback at build time and hydrates with the real params on the
// client. Mirrors the pattern used in /login.
export default function PayPalReturnPage() {
  return (
    <Suspense fallback={<CapturingPlaceholder />}>
      <PayPalReturnInner />
    </Suspense>
  );
}

function CapturingPlaceholder() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 p-6">
      <div className="bg-white rounded-xl border border-slate-200 p-8 max-w-md w-full text-center space-y-4">
        <div className="w-10 h-10 border-4 border-indigo-200 border-t-indigo-600
                        rounded-full animate-spin mx-auto" />
        <h1 className="text-lg font-semibold text-slate-900">
          Finalizing your payment…
        </h1>
      </div>
    </div>
  );
}

function PayPalReturnInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [status, setStatus] = useState<"capturing" | "success" | "pending" | "error">(
    "capturing"
  );
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    const orderId = params.get("token");
    if (!orderId) {
      setErrorMsg("PayPal didn't return an order ID. Try the purchase again.");
      setStatus("error");
      return;
    }
    (async () => {
      try {
        const result = await payments.paypalCapture({ order_id: orderId });
        // Read the plan_slug we stashed before redirect so we route the
        // buyer to the right plan-specific landing. Fall back to the
        // capture response's plan_slug if storage is cleared.
        let planSlug = "";
        try {
          planSlug = sessionStorage.getItem(`paypal:plan:${orderId}`) || "";
        } catch { /* storage disabled */ }
        if (!planSlug) planSlug = result.plan_slug || "";
        try {
          sessionStorage.removeItem(`paypal:plan:${orderId}`);
        } catch { /* ignore */ }

        if (result.status === "active") {
          setStatus("success");
          // Ad-platform purchase conversion (no-op unless configured +
          // consented). Amount intentionally omitted — this page only
          // knows the order id; Google still dedupes on transaction_id.
          firePurchaseConversion({ orderId });
          router.replace(`/exams?paid=${encodeURIComponent(planSlug)}`);
        } else {
          // PayPal accepted the capture but it's pending (risk review).
          // The webhook will activate the subscription when capture
          // completes. Tell the buyer their access will turn on shortly.
          setStatus("pending");
        }
      } catch (e) {
        setErrorMsg(errMsg(e));
        setStatus("error");
      }
    })();
    // Capture is keyed to the orderId from the URL; rerunning the effect
    // on rerender would create a duplicate capture call. The PayPal
    // capture API is idempotent (returns the existing capture on retry)
    // but we still avoid the round-trip.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 p-6">
      <div className="bg-white rounded-xl border border-slate-200 p-8 max-w-md w-full text-center space-y-4">
        {status === "capturing" && (
          <>
            <div className="w-10 h-10 border-4 border-indigo-200 border-t-indigo-600
                            rounded-full animate-spin mx-auto" />
            <h1 className="text-lg font-semibold text-slate-900">
              Finalizing your payment…
            </h1>
            <p className="text-sm text-slate-600">
              We're confirming the capture with PayPal. This usually
              takes a couple of seconds.
            </p>
          </>
        )}

        {status === "success" && (
          <>
            <div className="text-emerald-600 text-3xl">✓</div>
            <h1 className="text-lg font-semibold text-slate-900">Payment complete</h1>
            <p className="text-sm text-slate-600">
              Redirecting you to your exams…
            </p>
          </>
        )}

        {status === "pending" && (
          <>
            <div className="text-amber-600 text-3xl">⏳</div>
            <h1 className="text-lg font-semibold text-slate-900">
              Payment under review
            </h1>
            <p className="text-sm text-slate-600">
              PayPal accepted your payment but is finishing a review.
              Your access will activate within a few minutes — you can
              safely close this page and check{" "}
              <button onClick={() => router.push("/exams")}
                       className="text-indigo-600 hover:underline">
                /exams
              </button>{" "}
              shortly.
            </p>
          </>
        )}

        {status === "error" && (
          <>
            <div className="text-rose-600 text-3xl">✗</div>
            <h1 className="text-lg font-semibold text-slate-900">
              Something went wrong
            </h1>
            <p className="text-sm text-slate-600">{errorMsg}</p>
            <button onClick={() => router.push("/pricing")}
                    className="mt-2 px-4 py-2 bg-indigo-600 text-white text-sm
                               font-medium rounded-lg hover:bg-indigo-700">
              Back to pricing
            </button>
          </>
        )}
      </div>
    </div>
  );
}
