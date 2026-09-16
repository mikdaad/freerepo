/** @type {import('next').NextConfig} */

// The Arena preview (and any reverse proxy) reaches the dev server through a
// different host name, so allow extra origins without hard-coding them.
// Usage: ALLOWED_DEV_ORIGINS="3000-my-sandbox.e2b.app" npm run dev
const allowed = (process.env.ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((entry) => entry.trim())
  .filter(Boolean);

const nextConfig = {
  reactStrictMode: true,
  // Self-hosted build: no remote images, fonts or analytics to whitelist.
  images: { unoptimized: true },
  ...(allowed.length > 0 ? { allowedDevOrigins: allowed } : {}),
};

export default nextConfig;
