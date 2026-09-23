/** @type {import('next').NextConfig} */
const dsai_withBundleAnalyzer = require("@next/bundle-analyzer")({
  enabled: process.env.ANALYZE === "true",
});

const dsai_nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  experimental: {
    typedRoutes: false,
  },
  images: {
    formats: ["image/avif", "image/webp"],
    remotePatterns: [
      {
        protocol: "http",
        hostname: "localhost",
        port: "9000",
        pathname: "/**",
      },
      {
        protocol: "http",
        hostname: "minio",
        port: "9000",
        pathname: "/**",
      },
      {
        protocol: "https",
        hostname: "*.swatah.ai",
        pathname: "/**",
      },
    ],
  },
  async headers() {
    return [
      {
        source: "/_next/static/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
      {
        source: "/api/media/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=86400, stale-while-revalidate=43200",
          },
        ],
      },
    ];
  },
  // Reverse-proxy rewrites so browser calls are same-origin (avoids CORS on backend FastAPI services)
  async rewrites() {
    return [
      {
        source: "/api/backend/auth/:path*",
        destination: `${process.env.AUTH_SERVICE_URL || "http://auth-service:8002"}/:path*`,
      },
      {
        source: "/api/backend/search/:path*",
        destination: `${process.env.SEARCH_SERVICE_URL || "http://search-service:8081"}/:path*`,
      },
      {
        source: "/api/backend/server/:path*",
        destination: `${process.env.SERVER_SERVICE_URL || "http://main-api:8080"}/:path*`,
      },
      {
        source: "/api/backend/watchlist/:path*",
        destination: `${process.env.WATCHLIST_SERVICE_URL || "http://watchlist-matcher:8083"}/:path*`,
      },
      // Alias: /api/backend/extractor/* also proxies to ServerAndExtractor (main-api)
      {
        source: "/api/backend/extractor/:path*",
        destination: `${process.env.SERVER_SERVICE_URL || "http://main-api:8080"}/:path*`,
      },
    ];
  },
};

module.exports = dsai_withBundleAnalyzer(dsai_nextConfig);
