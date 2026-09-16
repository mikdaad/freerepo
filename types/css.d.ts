// `import '../global.css'` is the NativeWind v4 entry point: Metro intercepts the import, compiles
// the Tailwind sheet and injects it. Nothing is exported at runtime.
//
// Expo ships `declare module '*.css';` (a *bodyless* ambient declaration), which TypeScript 6 no
// longer accepts for side-effect imports (TS2882). Declaring a real module here — with the export
// shape a CSS file would have if it ever were imported for its value — keeps the import type-safe
// without weakening anything else.

declare module '*.css' {
  /** Class names available to this module (only meaningful on web). */
  const styles: Record<string, string>;
  export default styles;
  export const unstable_styles: Record<string, object>;
}
