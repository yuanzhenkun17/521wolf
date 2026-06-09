import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'node',
      globals: false,
      setupFiles: ['./tests/setup/vitest.setup.ts'],
      include: ['tests/*.test.js', 'tests/unit/**/*.test.ts'],
      exclude: [
        'tests/component/**',
        'tests/e2e/**',
        'tests/frontend-backend-smoke.test.js',
        'tests/mobile-layout-contract.test.js',
        'dist/**',
        'node_modules/**'
      ],
      restoreMocks: true,
      pool: 'forks'
    }
  })
)
