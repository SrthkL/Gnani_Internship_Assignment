import type { NextConfig } from "next";

const backendUrl = (
  process.env.BACKEND_URL ?? "http://127.0.0.1:8010"
).replace(/\/$/, "");

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;