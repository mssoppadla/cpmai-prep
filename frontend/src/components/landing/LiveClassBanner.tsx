/**
 * Live-class registration banner — rendered directly under the hero
 * subtitle on the landing page.
 *
 * Everything visual is admin-owned via /admin/landing-banner
 * (landing.live_banner_* settings): text, font size/style, text +
 * background colors, an optional pulse/blink attention animation, and
 * TWO independently-toggleable buttons:
 *
 *   1. Registration (calendar/Zoom link) — primary style. Automatic
 *      colors invert the banner palette (bg = text color, label =
 *      banner bg) so it always contrasts; admins can override both.
 *   2. On-demand training request (Google Form) — secondary style.
 *      Automatic colors: white bg, banner-text-colored label + border.
 *
 * Colors and size arrive as raw values so they're applied via inline
 * styles (Tailwind can't generate arbitrary runtime colors); the
 * animation is a class toggle, gated behind motion-safe: so
 * reduced-motion users never see it.
 *
 * No hooks — stays a server component inside the landing page render.
 */
import type { LandingCopy } from "@/types/api";

type BannerProps = Pick<LandingCopy,
  | "live_banner_enabled" | "live_banner_text"
  | "live_banner_link_url" | "live_banner_link_label"
  | "live_banner_font_size" | "live_banner_font_style"
  | "live_banner_font_color" | "live_banner_bg_color"
  | "live_banner_animation"> &
  Partial<Pick<LandingCopy,
    | "live_banner_link_enabled"
    | "live_banner_link_bg_color" | "live_banner_link_text_color"
    | "live_banner_ondemand_enabled" | "live_banner_ondemand_label"
    | "live_banner_ondemand_url"
    | "live_banner_ondemand_bg_color" | "live_banner_ondemand_text_color">>;

const ANIMATION_CLASS: Record<string, string> = {
  pulse: "motion-safe:animate-pulse",
  blink: "motion-safe:animate-blink",
};

export function LiveClassBanner({ landing }: { landing: BannerProps }) {
  if (!landing.live_banner_enabled || !landing.live_banner_text) return null;

  const style = landing.live_banner_font_style ?? "normal";
  const fontWeight = style.includes("bold") ? 700 : 400;
  const fontStyle: "italic" | "normal" =
    style.includes("italic") ? "italic" : "normal";
  const fontSize = clampPx(landing.live_banner_font_size, 10, 48, 16);
  const color = landing.live_banner_font_color || "#312e81";
  const background = landing.live_banner_bg_color || "#e0e7ff";
  const animation = ANIMATION_CLASS[landing.live_banner_animation] ?? "";
  const buttonFontSize = Math.max(12, Math.round(fontSize * 0.875));

  // Button 1 — registration. Defaults preserve the pre-color-option
  // behavior: enabled unless explicitly switched off, inverted colors.
  const showRegister = (landing.live_banner_link_enabled ?? true)
    && Boolean(landing.live_banner_link_url);
  const registerBg = landing.live_banner_link_bg_color || color;
  const registerText = landing.live_banner_link_text_color || background;

  // Button 2 — on-demand training request (Google Form). Secondary
  // "outline" style when colors are automatic.
  const showOndemand = Boolean(landing.live_banner_ondemand_enabled)
    && Boolean(landing.live_banner_ondemand_url);
  const ondemandBg = landing.live_banner_ondemand_bg_color || "#ffffff";
  const ondemandText = landing.live_banner_ondemand_text_color || color;

  return (
    <div role="status"
         className={`mt-6 sm:mt-7 max-w-2xl mx-auto rounded-2xl px-4 py-3.5 sm:px-6
                     sm:py-4 shadow-sm flex flex-col sm:flex-row items-center
                     justify-center gap-3 sm:gap-4 flex-wrap ${animation}`}
         style={{ background }}>
      <p className="leading-snug text-center sm:text-left"
         style={{ color, fontSize, fontWeight, fontStyle }}>
        {landing.live_banner_text}
      </p>
      {(showRegister || showOndemand) && (
        <div className="flex flex-col sm:flex-row items-center gap-2 sm:gap-3 flex-shrink-0">
          {showRegister && (
            <a href={landing.live_banner_link_url}
               target="_blank" rel="noopener noreferrer"
               data-track="cta:live_class_register"
               className="rounded-lg px-4 py-2 font-semibold shadow-sm
                          hover:opacity-90 transition whitespace-nowrap"
               style={{ background: registerBg, color: registerText,
                        fontSize: buttonFontSize }}>
              {landing.live_banner_link_label || "Register now"}
            </a>
          )}
          {showOndemand && (
            <a href={landing.live_banner_ondemand_url}
               target="_blank" rel="noopener noreferrer"
               data-track="cta:ondemand_training_request"
               className="rounded-lg px-4 py-2 font-semibold shadow-sm border
                          hover:opacity-80 transition whitespace-nowrap"
               style={{ background: ondemandBg, color: ondemandText,
                        borderColor: ondemandText,
                        fontSize: buttonFontSize }}>
              {landing.live_banner_ondemand_label || "Request on-demand training"}
            </a>
          )}
        </div>
      )}
    </div>
  );
}

function clampPx(v: number, lo: number, hi: number, fallback: number): number {
  if (typeof v !== "number" || Number.isNaN(v)) return fallback;
  return Math.min(hi, Math.max(lo, Math.round(v)));
}
