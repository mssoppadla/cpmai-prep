import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Hard on/off blink for the live-class banner (animate-pulse is
      // Tailwind's built-in soft fade; this is the attention-grabbing
      // variant admins can pick instead). Both are suppressed for
      // reduced-motion users via motion-safe: in the component.
      keyframes: {
        blink: { "0%, 100%": { opacity: "1" }, "50%": { opacity: "0.25" } },
      },
      animation: {
        blink: "blink 1.2s step-start infinite",
      },
    },
  },
  plugins: [],
};
export default config;
