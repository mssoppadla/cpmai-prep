"use client";
/**
 * YouTubeGalleryView — the visual component for a YouTube gallery
 * block. Used in BOTH the BlockNote editor and the public renderer
 * so authors see what end users will see.
 *
 * Privacy-friendly "click to play" facade:
 *   1. On render, show YouTube's thumbnail image only (1 GET to img.youtube.com).
 *   2. No YouTube iframe = no cookies, no trackers, no tracking pixels.
 *   3. On click, swap the placeholder for a real iframe with autoplay=1.
 *   4. Once swapped, that one tile loads the full YouTube embed (cookies etc.)
 *      — but only for the videos the user explicitly engaged with.
 *
 * Layout: CSS grid, 1 / 2 / 3 columns, gap 12px. Falls back to 1
 * column on viewports under 640px regardless of the configured value
 * — playing on a phone, one tile per row is the right thing.
 */
import { useState } from "react";
import { embedUrl, parseUrlList, thumbnailUrl } from "@/lib/cms/youtube";


interface YouTubeGalleryViewProps {
  /** Comma- or newline-separated YouTube URLs. */
  urls: string;
  /** Grid columns: 1 | 2 | 3. Other values are clamped. */
  columns?: number;
}


export default function YouTubeGalleryView({
  urls, columns = 3,
}: YouTubeGalleryViewProps) {
  const ids = parseUrlList(urls);
  // Track which tiles the user has clicked (replaced thumbnail with iframe).
  const [playing, setPlaying] = useState<Set<string>>(new Set());

  if (ids.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
        No YouTube videos. Add URLs (one per line) above.
      </div>
    );
  }

  const cols = Math.max(1, Math.min(3, columns));

  return (
    <div
      className="yt-gallery-grid"
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
        gap: "12px",
      }}
    >
      {ids.map((id) => {
        const isPlaying = playing.has(id);
        return (
          <div key={id}
               className="relative aspect-video rounded-lg overflow-hidden bg-black">
            {isPlaying ? (
              <iframe
                src={embedUrl(id)}
                className="absolute inset-0 w-full h-full"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
                title={`YouTube video ${id}`}
              />
            ) : (
              <button
                type="button"
                onClick={() => setPlaying((s) => new Set(s).add(id))}
                className="absolute inset-0 w-full h-full group"
                aria-label={`Play YouTube video ${id}`}>
                {/* Thumbnail */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={thumbnailUrl(id)}
                     alt=""
                     loading="lazy"
                     className="absolute inset-0 w-full h-full object-cover" />
                {/* Dim overlay on hover */}
                <span className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-colors" />
                {/* Red play button — YouTube-style */}
                <span className="absolute inset-0 flex items-center justify-center">
                  <span className="flex items-center justify-center w-16 h-12 rounded-xl bg-red-600 shadow-lg
                                   group-hover:bg-red-700 transition-colors">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="white">
                      <path d="M8 5v14l11-7z" />
                    </svg>
                  </span>
                </span>
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
