/** @type {import('next').NextConfig} */
const dsai_nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  experimental: {
    typedRoutes: false,
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
    ];
  },
};

module.exports = dsai_nextConfig;
