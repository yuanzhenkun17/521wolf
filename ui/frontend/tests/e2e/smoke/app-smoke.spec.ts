import { expect, test, type Page } from 'playwright/test'

const benchmarkSmokeSuite = {
  id: 'smoke-release-gate',
  name: 'Smoke Release Gate',
  description: 'Playwright smoke fixture for release readiness.',
  target_type: 'role_version',
  roles: ['werewolf'],
  game_count: 1,
  max_days: 1,
  seed_set_id: 'smoke-seeds',
  seed_set: {
    id: 'smoke-seeds',
    seed_set_id: 'smoke-seeds',
    seed_count: 1,
    seed_preview: ['smoke-001'],
    target_type: 'role_version',
    tier: 'smoke',
    usage_boundary: 'smoke'
  },
  status: 'enabled',
  launchable: true,
  cost_tier: 'smoke',
  evaluation_set_id: 'smoke-release-gate@v1',
  config_hash: 'smoke-config'
}

function benchmarkApiPayload(pathname: string) {
  const path = pathname.replace(/^\/api/, '')
  if (path === '/benchmark/seed-sets') {
    return { items: [benchmarkSmokeSuite.seed_set], summary: { total: 1 } }
  }
  if (path === '/benchmarks') {
    return { items: [benchmarkSmokeSuite] }
  }
  if (path === '/roles/overview') {
    return {
      roles: ['werewolf'],
      versions: {
        werewolf: [
          {
            role: 'werewolf',
            version_id: 'werewolf-baseline',
            status: 'active',
            source: 'baseline',
            is_baseline: true
          }
        ]
      },
      leaderboards: {
        werewolf: { entries: [] }
      }
    }
  }
  if (path === '/benchmark/plan') {
    return {
      total_games: 1,
      max_days: 1,
      launchable: true,
      dry_run: true,
      budget: {
        estimated_units: 1,
        limit_units: 10,
        estimated_cost: 0.01,
        limit_cost: 1,
        currency: 'USD',
        exceeded: { value: false, reasons: [], evidence: [] }
      },
      estimates: {
        estimated_llm_call_units: 1,
        expected_duration_seconds: 30,
        currency: 'USD'
      },
      judge: {
        estimated_decisions: 1,
        concurrency: 1
      },
      concurrency_policy: {
        game_concurrency: 1,
        judge_concurrency: 1
      },
      warnings: []
    }
  }
  if (path === '/leaderboards/compare') {
    return { kind: 'benchmark_leaderboard_compare', rows: [], summary: {} }
  }
  if (path === '/evolution-runs') {
    return { batches: [] }
  }
  if (path === '/benchmark/reports') {
    return { items: [], summary: {}, pagination: { total: 0, offset: 0, limit: 50, returned: 0, has_more: false } }
  }
  if (path === '/benchmark/diagnostics') {
    return {
      diagnostics: [],
      summary: {},
      affected_runs: [],
      affected_games: [],
      pagination: { total: 0, offset: 0, limit: 200, returned: 0, has_more: false }
    }
  }
  if (path === '/benchmark/snapshots') {
    return { items: [], snapshots: [] }
  }
  if (path === '/benchmark/views') {
    return { items: [] }
  }
  if (path.startsWith('/benchmark/views/')) {
    return null
  }
  return {}
}

async function stubBenchmarkApi(page: Page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(benchmarkApiPayload(url.pathname))
    })
  })
}

test('renders the app shell on the home page', async ({ page }) => {
  await page.goto('/')

  await expect(page.locator('#app')).toBeVisible()
  await expect(page.locator('#app > *')).toHaveCount(1)
  await expect(page.locator('main.lycan-app')).toBeVisible()

  const primaryNav = page.getByRole('navigation', { name: '主导航' })
  await expect(primaryNav).toBeVisible()
  await expect(primaryNav.getByRole('button', { name: /大厅/ })).toBeVisible()
  await expect(primaryNav.getByRole('button', { name: /评测/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'The Night Approaches' })).toBeVisible()
})

test('opens the benchmark workbench from a direct release smoke route', async ({ page }) => {
  await stubBenchmarkApi(page)
  await page.goto('/benchmark')

  const appShell = page.locator('main.lycan-app')
  const primaryNav = page.getByRole('navigation', { name: '主导航' })
  const workbenchTabs = page.getByRole('navigation', { name: '评测工作台视图' })

  await expect(appShell).toBeVisible()
  await expect(appShell).toHaveClass(/benchmark/)
  await expect(primaryNav).toBeVisible()
  await expect(primaryNav.getByRole('button', { name: /评测/ })).toHaveAttribute('aria-current', 'page')
  await expect(page.getByRole('heading', { name: '评测工作台' })).toBeVisible()
  await expect(workbenchTabs.getByRole('button', { name: '总览' })).toBeVisible()
  await expect(workbenchTabs.getByRole('button', { name: '运行' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Smoke Release Gate' })).toBeVisible()
  await expect(page.locator('.toast')).toHaveCount(0)
})
