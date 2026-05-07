import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

/**
 * vitest config for the Next.js frontend.
 *
 * - jsdom environment so React Testing Library can mount components
 *   and query the DOM.
 * - resolve.alias mirrors tsconfig.json's "@/*" → "./src/*" mapping
 *   manually (the vite-tsconfig-paths plugin is ESM-only and breaks
 *   when vitest's config loader uses CJS).
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/__tests__/setup.tsx"],
    css: false,
    include: ["src/**/*.test.{ts,tsx}", "src/__tests__/**/*.test.{ts,tsx}"],
  },
});
