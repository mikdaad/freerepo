/**
 * Babel configuration — Expo SDK 57 + Expo Router + NativeWind v4.
 *
 * Order matters:
 *  1. `babel-preset-expo` must come first. It handles TypeScript, Fast Refresh, the Expo Router
 *     entry, React Compiler, and it *automatically* appends `react-native-worklets/plugin`
 *     (Reanimated 4) as the final plugin whenever `react-native-worklets` is installed.
 *     Do NOT add that plugin here as well — a duplicate worklets plugin corrupts worklet hashes.
 *  2. `nativewind/babel` registers the `nativewind` JSX pragma so `className` props on React
 *     Native components are compiled through react-native-css-interop.
 *
 * The `jsxImportSource: 'nativewind'` option on the preset is required for NativeWind v4 —
 * without it, `className` is silently dropped on the New Architecture.
 *
 * @type {import('@babel/core').ConfigFunction}
 */
module.exports = function babelConfig(api) {
  api.cache(true);

  return {
    presets: [['babel-preset-expo', { jsxImportSource: 'nativewind' }], 'nativewind/babel'],
  };
};
