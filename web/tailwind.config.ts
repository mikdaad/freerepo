import type { Config } from "tailwindcss";

/**
 * Blueprint-scanner theme.
 *
 * Colours are declared as `hsl(var(--token) / <alpha-value>)` so Tailwind's
 * opacity modifiers (`bg-neon-red/12`) keep working on the CSS variables that
 * `app/globals.css` defines for light and dark.
 */
const config: Config = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  future: { hoverOnlyWhenSupported: true },
  theme: {
    container: { center: true, padding: "1rem" },
    extend: {
      colors: {
        border: "hsl(var(--border) / <alpha-value>)",
        input: "hsl(var(--input) / <alpha-value>)",
        ring: "hsl(var(--ring) / <alpha-value>)",
        background: "hsl(var(--background) / <alpha-value>)",
        foreground: "hsl(var(--foreground) / <alpha-value>)",
        primary: {
          DEFAULT: "hsl(var(--primary) / <alpha-value>)",
          foreground: "hsl(var(--primary-foreground) / <alpha-value>)",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary) / <alpha-value>)",
          foreground: "hsl(var(--secondary-foreground) / <alpha-value>)",
        },
        muted: {
          DEFAULT: "hsl(var(--muted) / <alpha-value>)",
          foreground: "hsl(var(--muted-foreground) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "hsl(var(--accent) / <alpha-value>)",
          foreground: "hsl(var(--accent-foreground) / <alpha-value>)",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive) / <alpha-value>)",
          foreground: "hsl(var(--destructive-foreground) / <alpha-value>)",
        },
        card: {
          DEFAULT: "hsl(var(--card) / <alpha-value>)",
          foreground: "hsl(var(--card-foreground) / <alpha-value>)",
        },
        popover: {
          DEFAULT: "hsl(var(--popover) / <alpha-value>)",
          foreground: "hsl(var(--popover-foreground) / <alpha-value>)",
        },
        "neon-red": "hsl(var(--neon-red) / <alpha-value>)",
        "neon-amber": "hsl(var(--neon-amber) / <alpha-value>)",
        "neon-cyan": "hsl(var(--neon-cyan) / <alpha-value>)",
        "neon-green": "hsl(var(--neon-green) / <alpha-value>)",
        "neon-violet": "hsl(var(--neon-violet) / <alpha-value>)",
        "grid-line": "hsl(var(--grid-line) / <alpha-value>)",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        glow: "0 0 0 1px hsl(var(--primary) / 0.25), 0 0 30px -12px hsl(var(--primary) / 0.55)",
        "glow-red": "0 0 0 1px hsl(var(--neon-red) / 0.4), 0 0 34px -10px hsl(var(--neon-red) / 0.75)",
        "glow-green": "0 0 0 1px hsl(var(--neon-green) / 0.4), 0 0 34px -10px hsl(var(--neon-green) / 0.7)",
        inset: "inset 0 1px 0 0 hsl(var(--foreground) / 0.04)",
      },
      backgroundImage: {
        blueprint:
          "linear-gradient(to right, hsl(var(--grid-line) / 0.55) 1px, transparent 1px), linear-gradient(to bottom, hsl(var(--grid-line) / 0.55) 1px, transparent 1px)",
        "scan-sweep":
          "linear-gradient(180deg, transparent 0%, hsl(var(--neon-cyan) / 0.16) 48%, transparent 100%)",
      },
      backgroundSize: {
        // `bg-grid` (not `bg-blueprint`, which would collide with the
        // backgroundImage utility of the same name).
        grid: "28px 28px",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0", opacity: "0" },
          to: { height: "var(--radix-accordion-content-height)", opacity: "1" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)", opacity: "1" },
          to: { height: "0", opacity: "0" },
        },
        "glow-pulse": {
          "0%, 100%": { boxShadow: "0 0 0 1px hsl(var(--neon-red) / 0.55), 0 0 30px -8px hsl(var(--neon-red) / 0.85)" },
          "50%": { boxShadow: "0 0 0 1px hsl(var(--neon-red) / 0.25), 0 0 12px -6px hsl(var(--neon-red) / 0.35)" },
        },
        sweep: {
          "0%": { transform: "translateY(-100%)", opacity: "0" },
          "35%": { opacity: "1" },
          "100%": { transform: "translateY(320%)", opacity: "0" },
        },
        "blink-caret": {
          "0%, 49%": { opacity: "1" },
          "50%, 100%": { opacity: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 220ms cubic-bezier(0.32, 0.72, 0, 1)",
        "accordion-up": "accordion-up 180ms cubic-bezier(0.32, 0.72, 0, 1)",
        "glow-pulse": "glow-pulse 2.2s ease-in-out infinite",
        sweep: "sweep 5.5s linear infinite",
        "blink-caret": "blink-caret 1.1s steps(1) infinite",
      },
      transitionTimingFunction: {
        cadence: "cubic-bezier(0.22, 1, 0.36, 1)",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
