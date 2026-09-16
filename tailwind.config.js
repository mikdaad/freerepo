const { platformSelect } = require('nativewind/theme');

/**
 * Tailwind configuration — NativeWind v4 (Tailwind CSS v3 engine).
 *
 * The palette is a *semantic token* system backed by CSS variables declared in `global.css`.
 * Two themes ship:
 *   • default  — dark "night platform" theme, OLED friendly, WCAG AA+ on every pair below.
 *   • outdoor  — the same tokens at maximum contrast (near-black on near-white, heavier type)
 *                for direct sunlight. Applied by putting `className="theme-outdoor"` on the
 *                root view; every `bg-surface` / `text-primary` utility re-resolves instantly.
 *
 * @type {import('tailwindcss').Config}
 */
module.exports = {
  content: ['./app/**/*.{js,jsx,ts,tsx}', './src/**/*.{js,jsx,ts,tsx}'],
  presets: [require('nativewind/preset')],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // ---- semantic tokens (change with the active theme) ------------------------------------
        canvas: 'rgb(var(--color-canvas) / <alpha-value>)',
        surface: 'rgb(var(--color-surface) / <alpha-value>)',
        elevated: 'rgb(var(--color-elevated) / <alpha-value>)',
        hairline: 'rgb(var(--color-hairline) / <alpha-value>)',
        primary: 'rgb(var(--color-primary) / <alpha-value>)',
        secondary: 'rgb(var(--color-secondary) / <alpha-value>)',
        inverse: 'rgb(var(--color-inverse) / <alpha-value>)',
        accent: 'rgb(var(--color-accent) / <alpha-value>)',
        'accent-ink': 'rgb(var(--color-accent-ink) / <alpha-value>)',
        live: 'rgb(var(--color-live) / <alpha-value>)',
        caution: 'rgb(var(--color-caution) / <alpha-value>)',
        offline: 'rgb(var(--color-offline) / <alpha-value>)',
        // ---- fixed brand ramp: identical in every theme -----------------------------------------
        brand: {
          50: '#EFF6FF',
          100: '#DBEAFE',
          300: '#93C5FD',
          400: '#60A5FA',
          500: '#3B82F6',
          600: '#2563EB',
          700: '#1D4ED8',
          900: '#1E3A8A',
        },
      },
      fontSize: {
        // Deliberately larger floor than Tailwind's defaults: this is a glance-and-go UI read
        // while walking, running for a bus, in bright light.
        '2xs': ['11px', { lineHeight: '14px', letterSpacing: '0.06em' }],
        xs: ['13px', { lineHeight: '18px' }],
        sm: ['15px', { lineHeight: '20px' }],
        base: ['17px', { lineHeight: '24px' }],
        lg: ['20px', { lineHeight: '26px' }],
        xl: ['24px', { lineHeight: '30px', letterSpacing: '-0.01em' }],
        '2xl': ['30px', { lineHeight: '36px', letterSpacing: '-0.02em' }],
        board: ['44px', { lineHeight: '48px', letterSpacing: '-0.03em' }],
      },
      borderRadius: {
        card: '20px',
        pill: '999px',
      },
      spacing: {
        // Extra tap-target helper: 48pt minimum is the Apple HIG floor, 56 is glove-friendly.
        tap: '48px',
        'tap-lg': '56px',
        safe: '16px',
      },
      fontFamily: {
        sans: platformSelect({ ios: 'System', android: 'sans-serif', default: 'System' }),
        mono: platformSelect({
          ios: 'Menlo',
          android: 'monospace',
          default: 'monospace',
        }),
      },
    },
  },
  plugins: [],
};
