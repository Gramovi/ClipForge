import type { NextConfig } from "next"

const API_URL = process.env.API_URL || "http://localhost:8000"

const nextConfig: NextConfig = {
  output: "standalone",
  // gzip would buffer Server-Sent Events coming through the proxy
  compress: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }]
  },
  experimental: {
    // long-running proxied requests (upload chunks on slow links, SSE streams)
    proxyTimeout: 30 * 60 * 1000,
  },
}

export default nextConfig
