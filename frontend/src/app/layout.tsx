import type { Metadata, Viewport } from "next";
import "./globals.css";
import { AssistantWidgetMount } from "@/components/assistant/AssistantWidgetMount";

// Fallback is the REAL production domain — not a placeholder. iOS Safari
// and Android Chrome share sheets prefer the og:url / canonical meta tags
// over window.location, so the value baked in here at build time IS the
// URL that gets shared. Plumb NEXT_PUBLIC_SITE_URL through the build env
// to override (e.g. for staging), but never let a placeholder leak.
//
// IMPORTANT: use `||` not `??` — Docker ARG/ENV substitution can pass an
// EMPTY STRING (not undefined) when the build arg isn't provided, and
// `??` only triggers on null/undefined. An empty string flowing into
// `new URL("")` (the metadataBase call below) throws `ERR_INVALID_URL`
// during static page collection, breaking the prod build. `||` covers
// both empty-string and undefined cases.
const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://cpmaiexamprep.com";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,             // a11y — let users zoom; never lock to 1
  viewportFit: "cover",        // iPhone notch / Dynamic Island
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#4f46e5" },
    { media: "(prefers-color-scheme: dark)",  color: "#1e1b4b" },
  ],
  colorScheme: "light",
};

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "CPMAI Prep — Pass the CPMAI Certification on Your First Attempt",
    template: "%s | CPMAI Prep",
  },
  description:
    "Prepare for the Cognitive Project Management for AI (CPMAI) certification with realistic mock exams, AI-powered coaching, and detailed answer reasoning across all 6 phases.",
  keywords: [
    "CPMAI", "CPMAI certification", "CPMAI exam", "AI project management",
    "CPMAI mock test", "CPMAI practice questions", "AI certification India",
  ],
  applicationName: "CPMAI Prep",
  authors: [{ name: "CPMAI Prep" }],
  alternates: { canonical: "/" },
  manifest: "/manifest.webmanifest",
  openGraph: {
    type: "website",
    siteName: "CPMAI Prep",
    title: "CPMAI Prep — Pass the CPMAI Certification on Your First Attempt",
    description:
      "Realistic mock exams, AI-powered coaching, and detailed reasoning for every CPMAI question.",
    locale: "en_IN",
  },
  twitter: {
    card: "summary_large_image",
    title: "CPMAI Prep",
    description: "Pass the CPMAI certification on your first attempt.",
  },
  robots: {
    index: true, follow: true,
    googleBot: { index: true, follow: true },
  },
  category: "education",
  appleWebApp: {
    capable: true,
    title: "CPMAI Prep",
    statusBarStyle: "default",
  },
  icons: {
    icon: [
      { url: "/icons/icon.svg", type: "image/svg+xml" },
    ],
    apple: [
      { url: "/icons/apple-touch-icon.svg", sizes: "180x180", type: "image/svg+xml" },
    ],
  },
  formatDetection: {
    telephone: false,
    email: false,
    address: false,
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-50 text-slate-900 antialiased min-h-screen">
        {children}
        {/* Chat widget — follows signed-in users across every page.
            Self-hides for anon visitors (so marketing pages stay clean). */}
        <AssistantWidgetMount />
      </body>
    </html>
  );
}
