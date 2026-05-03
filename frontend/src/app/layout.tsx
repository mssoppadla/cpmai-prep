import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CPMAI Prep",
  description: "Paid CPMAI exam preparation platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-50 text-slate-900">{children}</body>
    </html>
  );
}
