// Learn more: https://docs.expo.dev/guides/customizing-metro/
const { getDefaultConfig } = require('expo/metro-config');
const { withNativeWind } = require('nativewind/metro');

/** @type {import('expo/metro-config').MetroConfig} */
const config = getDefaultConfig(__dirname);

// ---------------------------------------------------------------------------------------------
// expo-sqlite on web: the web implementation is wa-sqlite (SQLite compiled to WASM) running in
// a worker. Two things are required locally:
//   1. Metro must treat `.wasm` files as assets so the worker can fetch() them.
//   2. The dev server must send COOP/COEP headers so the page becomes cross-origin isolated and
//      `SharedArrayBuffer` is available (used to share memory with the SQLite worker).
// Native iOS/Android builds need neither — they use the native SQLite binding directly.
// If you deploy the web build behind a CDN, set these two headers there as well.
// ---------------------------------------------------------------------------------------------
if (!config.resolver.assetExts.includes('wasm')) {
  config.resolver.assetExts.push('wasm');
}

config.server.enhanceMiddleware = (middleware, server) => {
  return (req, res, next) => {
    res.setHeader('Cross-Origin-Embedder-Policy', 'require-corp');
    res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
    return middleware(req, res, next);
  };
};

module.exports = withNativeWind(config, {
  // Tailwind entry point compiled into a React Native stylesheet.
  input: './global.css',
  // The generated class-name map is written here for debugging in dev builds.
  inlineRem: 16,
});
