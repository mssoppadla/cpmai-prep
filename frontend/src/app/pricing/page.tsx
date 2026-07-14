/**
 * /pricing — SERVER page.
 *
 * Fetches plans + the currency option list server-side so every plan
 * card ships in the crawlable initial HTML (search engines and ad
 * landing-page review never execute our client JS). Everything
 * user-specific — GeoIP currency suggestion, live quotes, checkout —
 * stays in PricingClient. ISR: 60s.
 */
import type { Metadata } from "next";
import { fetchJson } from "@/lib/ssr";
import type { CurrencyOption, PlanPublicOut } from "@/types/api";
import { PricingClient } from "./PricingClient";

export const revalidate = 60;

export const metadata: Metadata = {
  title: "Pricing — CPMAI Exam Prep Plans",
  description:
    "One-time payment, 1-year access. CPMAI exam bundles and course "
    + "bundles with mock exams, AI tutor, and live classes. Pay in INR, "
    + "USD, GBP, EUR and more.",
  alternates: { canonical: "/pricing" },
  openGraph: {
    title: "Pricing — CPMAI Exam Prep Plans | CPMAI Prep",
    description:
      "One-time payment, 1-year access. Exam bundles and course bundles "
      + "with mock exams, AI tutor, and live classes.",
    url: "/pricing",
  },
};

type CurrenciesOut = {
  options: CurrencyOption[];
  suggested_currency?: string | null;
};

export default async function PricingPage() {
  const [plans, currencies] = await Promise.all([
    fetchJson<PlanPublicOut[] | null>("/pricing/plans", null),
    fetchJson<CurrenciesOut | null>("/pricing/currencies", null),
  ]);
  return (
    <PricingClient
      initialPlans={Array.isArray(plans) ? plans : null}
      initialCurrencies={
        currencies && Array.isArray(currencies.options) ? currencies : null}
    />
  );
}
