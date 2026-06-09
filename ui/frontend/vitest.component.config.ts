import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: false,
      setupFiles: ['./tests/setup/vitest.setup.ts'],
      include: ['tests/component/**/*.test.ts'],
      exclude: ['tests/e2e/**', 'dist/**', 'node_modules/**'],
      restoreMocks: true,
      pool: 'forks'
    }
  })
)
