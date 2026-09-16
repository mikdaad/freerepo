// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require('eslint/config');
const expoConfig = require('eslint-config-expo/flat');

module.exports = defineConfig([
  expoConfig,
  {
    ignores: ['dist/**', 'node_modules/**', '.expo/**', 'supabase/**'],
    rules: {
      // Offline-first code flips a lot of state inside `useEffect` + async callbacks; the
      // exhaustive-deps rule is the one that actually catches bugs here.
      'react-hooks/exhaustive-deps': 'warn',
      // The background task registry re-exports a task name constant that consumers must
      // be able to read at module scope.
      'import/no-unresolved': 'off',
    },
  },
  {
    files: [
      'scripts/**/*.ts',
      '*.config.js',
      'babel.config.js',
      'metro.config.js',
      'tailwind.config.js',
    ],
    languageOptions: { sourceType: 'commonjs' },
  },
]);
