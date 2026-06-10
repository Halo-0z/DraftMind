import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Forward every /api/* request to the FastAPI backend.  This keeps the
  // browser on a same-origin request and sidesteps CORS, while still
  // letting the dev tools show the proxied call.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
