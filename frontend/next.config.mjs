/** @type {import('next').NextConfig} */
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig = {
  async rewrites() {
    // The browser calls relative URLs (/backend/...) and the dev server
    // proxies them to the FastAPI backend — no CORS issues, and the
    // browser never needs to know the backend's origin.
    return [
      {
        source: "/backend/:path*",
        destination: `${BACKEND_URL}/:path*`,
      },
    ];
  },
};

export default nextConfig;
