import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'node',
      globals: false,
      setupFiles: ['./tests/setup/vitest.setup.ts'],
      include: ['tests/frontend-backend-smoke.test.js', 'tests/mobile-layout-contract.test.js'],
      exclude: ['dist/**', 'node_modules/**'],
      restoreMocks: true,
      pool: 'forks',
      testTimeout: 30_000
    }
  })
)
