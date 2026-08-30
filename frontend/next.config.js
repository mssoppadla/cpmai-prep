/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    // `/uploads/*` (lesson videos, CMS images, attached PDFs) is served by
    // the FastAPI backend via StaticFiles, reading from the cpmai-uploads
    // docker volume. The reverse proxy routes "/" to this frontend, so
    // without a route here those upload URLs hit Next.js and 404 (the cause
    // of the course-video "404 Not Found"). Forward them to the backend.
    //
    // The destination is resolved server-side from the frontend container,
    // so it uses the INTERNAL backend origin on the compose network
    // (service name `backend`, container port 8000), NOT the public URL.
    // Override with BACKEND_INTERNAL_URL if the service name/port differ.
    const backend = process.env.BACKEND_INTERNAL_URL || "http://backend:8000";
    return [
      { source: "/uploads/:path*", destination: `${backend}/uploads/:path*` },
    ];
  },
  async redirects() {
    return [
      // The Model Error Lab superseded the Threshold Explorer (it
      // contains the threshold interaction plus fit/imbalance/curves).
      // Permanent redirect preserves bookmarks and any search equity.
      {
        source: "/labs/threshold-explorer",
        destination: "/labs/metrics-lab",
        permanent: true,
      },
    ];
  },
  async headers() {
    return [{
      source: "/(.*)",
      headers: [
        { key: "Strict-Transport-Security",   value: "max-age=63072000; includeSubDomains; preload" },
        { key: "X-Content-Type-Options",      value: "nosniff" },
        { key: "X-Frame-Options",             value: "DENY" },
        { key: "Referrer-Policy",             value: "strict-origin-when-cross-origin" },
        { key: "Permissions-Policy",          value: "camera=(), microphone=(), geolocation=()" },
      ],
    }, {
      // The Data Pipeline Navigator simulator is a static page embedded
      // in an <iframe> by /labs/data-pipeline-navigator. The global DENY
      // above blocks even same-origin framing, so relax to SAMEORIGIN
      // for this one file (still no third-party framing).
      source: "/labs/pipeline-sim.html",
      headers: [
        { key: "X-Frame-Options", value: "SAMEORIGIN" },
      ],
    }];
  },
};
module.exports = nextConfig;
