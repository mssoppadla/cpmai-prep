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
    }];
  },
};
module.exports = nextConfig;
