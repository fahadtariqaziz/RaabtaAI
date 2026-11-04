import path from "node:path";
import type { NextConfig } from "next";

// The browser only talks to the admin origin; Next proxies the API (same-origin → the refresh
// cookie works and no CORS). API_URL is read at build/start time.
const API_URL = process.env.API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${API_URL}/api/v1/:path*` },
      { source: "/widget/v1/:path*", destination: `${API_URL}/widget/v1/:path*` },
    ];
  },
  output: "standalone",
  // Monorepo: trace files from the repo root so the standalone bundle is complete.
  outputFileTracingRoot: path.join(__dirname, ".."),
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
