/**
 * Segment layout whose only job is metadata: this route is per-user /
 * transactional and must never appear in search results. robots.ts
 * blocks crawling; this noindex blocks indexing of externally-linked
 * URLs. The pages below stay client components — metadata can only be
 * exported from a server file, hence this wrapper.
 */
import type { Metadata } from "next";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function NoIndexLayout({ children }: { children: React.ReactNode }) {
  return children;
}
