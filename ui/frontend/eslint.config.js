import js from '@eslint/js'
import tseslint from 'typescript-eslint'

const browserGlobals = {
  Audio: 'readonly',
  Blob: 'readonly',
  EventSource: 'readonly',
  FormData: 'readonly',
  Image: 'readonly',
  URL: 'readonly',
  URLSearchParams: 'readonly',
  WebSocket: 'readonly',
  clearInterval: 'readonly',
  clearTimeout: 'readonly',
  console: 'readonly',
  document: 'readonly',
  fetch: 'readonly',
  globalThis: 'readonly',
  import: 'readonly',
  localStorage: 'readonly',
  navigator: 'readonly',
  performance: 'readonly',
  requestAnimationFrame: 'readonly',
  setInterval: 'readonly',
  setTimeout: 'readonly',
  window: 'readonly'
}

const nodeGlobals = {
  Buffer: 'readonly',
  process: 'readonly'
}

export default tseslint.config(
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'coverage/**',
      'src/**/*.vue',
      'tests/**/*.js',
      'src/CouncilHallScene.ts',
      'src/mockAgentGame.ts',
      'src/components/history/evidenceLinks.ts',
      'src/components/history/historyDisplay.ts',
      'src/composables/**/*.ts'
    ]
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: [
      'eslint.config.js',
      'vite.config.ts',
      'src/**/*.ts'
    ],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: {
        ...browserGlobals,
        ...nodeGlobals
      }
    },
    rules: {
      'no-console': 'off',
      'no-empty': ['error', { allowEmptyCatch: true }],
      'no-undef': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      '@typescript-eslint/no-require-imports': 'off'
    }
  }
)
