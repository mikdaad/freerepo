/** @type {import('next').NextConfig} */

// The Arena preview (and any reverse proxy) reaches the dev server through a
// different host name, so allow extra origins without hard-coding them.
// Usage: ALLOWED_DEV_ORIGINS="3000-my-sandbox.e2b.app" npm run dev
const allowed = (process.env.ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((entry) => entry.trim())
  .filter(Boolean);

// The FastAPI service (see ../server.py). When the browser cannot reach
// http://localhost:8000 directly — a proxied preview, a VM, a container — the
// client falls back to same-origin /api/* and these rewrites forward it here.
// Set API_PROXY_TARGET="" to disable the proxy (e.g. the backend is on another host).
const proxyTarget = (process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000").trim();

const nextConfig = {
  reactStrictMode: true,
  // Self-hosted build: no remote images, fonts or analytics to whitelist.
  images: { unoptimized: true },
  ...(allowed.length > 0 ? { allowedDevOrigins: allowed } : {}),
  async rewrites() {
    if (!proxyTarget) return [];
    return [
      {
        source: "/api/:path*",
        destination: `${proxyTarget.replace(/\/+$/, "")}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
