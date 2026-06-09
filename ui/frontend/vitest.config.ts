import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'node',
      globals: false,
      setupFiles: ['./tests/setup/vitest.setup.ts'],
      include: ['tests/*.test.js', 'tests/unit/**/*.test.ts', 'tests/component/**/*.test.ts'],
      exclude: ['tests/e2e/**', 'dist/**', 'node_modules/**'],
      restoreMocks: true,
      pool: 'forks'
    }
  })
)
