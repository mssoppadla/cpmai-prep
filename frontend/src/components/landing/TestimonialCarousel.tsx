"use client";
/**
 * Testimonial carousel for the landing page.
 *
 * - Responsive: 1 card on mobile, 2 on small tablets, 3 on desktop.
 *   Card widths are pure CSS (Tailwind breakpoints) so the server
 *   render is correct before hydration; JS only drives the translate
 *   offset, which is 0 on first paint either way.
 * - Auto-rotates every `intervalMs` (admin-configurable). The timer
 *   resets on manual navigation, pauses while hovered/focused, and is
 *   disabled entirely for prefers-reduced-motion users.
 * - Arrows both sides + dots; swipe works via touch events (iOS /
 *   Android browsers included).
 * - Cards with a link_url link out (LinkedIn or other testimonial
 *   sites) in a new tab.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
import { absoluteUploadUrl } from "@/lib/api";
import type { TestimonialOut } from "@/types/api";

const SWIPE_THRESHOLD_PX = 40;

export function TestimonialCarousel({ items, heading, intervalMs }: {
  items: TestimonialOut[];
  heading: string;
  intervalMs: number;
}) {
  const [index, setIndex] = useState(0);
  const [perView, setPerView] = useState(1);
  const [paused, setPaused] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const touchStartX = useRef<number | null>(null);

  // Track how many cards are visible so the max index matches what the
  // CSS breakpoints are actually showing.
  useEffect(() => {
    const mqDesktop = window.matchMedia("(min-width: 1024px)");
    const mqTablet = window.matchMedia("(min-width: 640px)");
    const mqMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => {
      setPerView(mqDesktop.matches ? 3 : mqTablet.matches ? 2 : 1);
      setReducedMotion(mqMotion.matches);
    };
    apply();
    mqDesktop.addEventListener("change", apply);
    mqTablet.addEventListener("change", apply);
    mqMotion.addEventListener("change", apply);
    return () => {
      mqDesktop.removeEventListener("change", apply);
      mqTablet.removeEventListener("change", apply);
      mqMotion.removeEventListener("change", apply);
    };
  }, []);

  const maxIndex = Math.max(0, items.length - perView);
  const clamped = Math.min(index, maxIndex);

  const goTo = useCallback((i: number) => {
    setIndex(i < 0 ? maxIndex : i > maxIndex ? 0 : i);
  }, [maxIndex]);

  // Auto-rotate. Depending on `clamped` means every navigation (auto or
  // manual) restarts the countdown — exactly the "manual click resets
  // the timer" behavior we want.
  useEffect(() => {
    if (paused || reducedMotion || maxIndex === 0) return;
    const ms = Math.min(60000, Math.max(2000, intervalMs || 6000));
    const t = setInterval(() => {
      setIndex(i => (i >= maxIndex ? 0 : i + 1));
    }, ms);
    return () => clearInterval(t);
  }, [paused, reducedMotion, maxIndex, intervalMs, clamped]);

  if (items.length === 0) return null;
  const showControls = items.length > perView;

  return (
    <section aria-roledescription="carousel" aria-label={heading}
             className="max-w-5xl mx-auto px-4 sm:px-6 pb-14 sm:pb-16">
      <h2 className="text-xl sm:text-2xl font-bold text-slate-900 text-center mb-6 sm:mb-8">
        {heading}
      </h2>

      <div className="relative"
           onMouseEnter={() => setPaused(true)}
           onMouseLeave={() => setPaused(false)}
           onFocus={() => setPaused(true)}
           onBlur={() => setPaused(false)}>
        {showControls && (
          <>
            <CarouselArrow side="left" onClick={() => goTo(clamped - 1)} />
            <CarouselArrow side="right" onClick={() => goTo(clamped + 1)} />
          </>
        )}

        <div className="overflow-hidden"
             onTouchStart={(e) => { touchStartX.current = e.touches[0].clientX; }}
             onTouchEnd={(e) => {
               if (touchStartX.current === null) return;
               const dx = e.changedTouches[0].clientX - touchStartX.current;
               touchStartX.current = null;
               if (Math.abs(dx) < SWIPE_THRESHOLD_PX) return;
               goTo(dx < 0 ? clamped + 1 : clamped - 1);
             }}>
          <div className="flex transition-transform duration-500 ease-out"
               style={{ transform: `translateX(-${clamped * (100 / perView)}%)` }}>
            {items.map(t => (
              <div key={t.id}
                   className="w-full sm:w-1/2 lg:w-1/3 flex-shrink-0 px-2 sm:px-2.5">
                <TestimonialCard t={t} />
              </div>
            ))}
          </div>
        </div>

        {showControls && (
          <div className="flex justify-center gap-2 mt-5">
            {Array.from({ length: maxIndex + 1 }, (_, i) => (
              <button key={i} onClick={() => goTo(i)}
                      aria-label={`Go to testimonial ${i + 1}`}
                      aria-current={i === clamped}
                      className={`h-2 rounded-full transition-all ${
                        i === clamped ? "w-6 bg-indigo-600"
                                      : "w-2 bg-slate-300 hover:bg-slate-400"}`} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function CarouselArrow({ side, onClick }: { side: "left" | "right"; onClick: () => void }) {
  return (
    <button onClick={onClick}
            aria-label={side === "left" ? "Previous testimonials" : "Next testimonials"}
            className={`absolute top-1/2 -translate-y-1/2 z-10 w-9 h-9 sm:w-10 sm:h-10
                        rounded-full bg-white border border-slate-200 shadow-md
                        grid place-items-center text-slate-600
                        hover:text-indigo-600 hover:border-indigo-300 transition
                        ${side === "left" ? "-left-2 sm:-left-4" : "-right-2 sm:-right-4"}`}>
      {side === "left" ? <ChevronLeft size={20} /> : <ChevronRight size={20} />}
    </button>
  );
}

function TestimonialCard({ t }: { t: TestimonialOut }) {
  const photo = t.photo_url ? absoluteUploadUrl(t.photo_url) : null;
  const card = (
    <article className="h-full bg-white border border-slate-200 rounded-2xl shadow-sm
                        overflow-hidden flex flex-col hover:shadow-md transition-shadow">
      {photo ? (
        // Admin-uploaded media served from the backend origin; next/image
        // would need a remotePatterns entry per deploy host for no benefit.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={photo} alt={`Photo of ${t.name}`}
             className="w-full aspect-video object-cover" loading="lazy" />
      ) : (
        <div aria-hidden
             className="w-full h-24 bg-gradient-to-br from-indigo-100 to-slate-100
                        grid place-items-center">
          <span className="text-3xl font-bold text-indigo-300">
            {t.name.trim().charAt(0).toUpperCase()}
          </span>
        </div>
      )}
      <div className="p-4 sm:p-5 flex flex-col gap-1.5 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="font-bold text-slate-900">{t.name}</span>
          {t.link_url && <ExternalLink size={14} className="text-indigo-500 flex-shrink-0" />}
        </div>
        {t.role && (
          <span className="self-start text-[11px] font-semibold uppercase tracking-wide
                           px-2 py-0.5 rounded bg-indigo-50 text-indigo-700">
            {t.role}
          </span>
        )}
        <p className="mt-1 text-sm text-slate-600 leading-relaxed">{t.quote}</p>
      </div>
    </article>
  );

  return t.link_url ? (
    <a href={t.link_url} target="_blank" rel="noopener noreferrer"
       data-track="cta:testimonial_link"
       aria-label={`Read ${t.name}'s testimonial on an external site`}
       className="block h-full focus:outline-none focus:ring-2 focus:ring-indigo-500
                  rounded-2xl">
      {card}
    </a>
  ) : card;
}
