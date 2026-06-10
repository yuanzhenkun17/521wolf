import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, test, vi } from 'vitest'
import { useBenchmarkStore } from '../../../src/stores/benchmark'
import type { BenchmarkRun, BenchmarkSuite } from '../../../src/types/benchmark'

afterEach(() => {
  vi.restoreAllMocks()
})

function benchmarkSuiteFixture(id: string, overrides: Partial<BenchmarkSuite> = {}): BenchmarkSuite {
  return {
    id,
    version: 1,
    name: id,
    label: `Suite ${id}`,
    description: '',
    target_type: 'role_version',
    roles: ['werewolf'],
    game_count: 10,
    max_days: 5,
    seed_set_id: 'seed-1',
    seed_count: 10,
    seed_preview: [],
    seed_set: {},
    paired_seed: false,
    metrics: {},
    gates: {},
    judge: {},
    config_hash: '',
    benchmark_config_hash: '',
    cost_tier: 'smoke',
    evaluation_set_id: 'eval-1',
    status: 'enabled',
    launchable: true,
    launch_disabled_reason: '',
    ...overrides
  }
}

function benchmarkRunFixture(id: string, overrides: Partial<BenchmarkRun> = {}): BenchmarkRun {
  return {
    id,
    run_id: id,
    batch_id: id,
    status: 'completed',
    roles: ['werewolf'],
    roleKeys: ['werewolf'],
    displayRole: '狼人',
    benchmarkId: 'suite-1',
    benchmarkVersion: 1,
    benchmarkTargetType: 'role_version',
    evaluationSetId: 'eval-1',
    resultRows: [],
    isActive: false,
    isTerminal: true,
    benchmarkLabel: `Run ${id}`,
    statusLabel: '已完成',
    ...overrides
  }
}

test('benchmark store hydrates workbench selection and visible run state', () => {
  setActivePinia(createPinia())
  const store = useBenchmarkStore()
  const selectedRun = benchmarkRunFixture('run-1')
  const activeRun = benchmarkRunFixture('active-1', {
    status: 'running',
    isActive: true,
    isTerminal: false
  })

  store.hydrateFromWorkbench({
    suites: [benchmarkSuiteFixture('suite-1')],
    runs: [selectedRun, activeRun],
    runRows: [activeRun, selectedRun],
    selectedBenchmarkId: 'suite-1',
    selectedBenchmarkBatchId: 'run-1',
    loading: true,
    actionLoading: 'start',
    error: 'refresh failed',
    notice: { type: 'warning', message: 'stale data' }
  })

  assert.equal(store.loading, true)
  assert.equal(store.actionLoading, 'start')
  assert.equal(store.error, 'refresh failed')
  assert.deepEqual(store.notice, { type: 'warning', message: 'stale data' })
  assert.equal(store.selectedSuite?.id, 'suite-1')
  assert.equal(store.selectedBatchId, 'run-1')
  assert.equal(store.selectedBenchmarkBatchId, 'run-1')
  assert.equal(store.selectedBenchmarkBatchRun?.id, 'run-1')
  assert.deepEqual(store.activeRunRows.map((run) => run.id), ['active-1'])
  assert.deepEqual(store.recentRunRows.map((run) => run.id), ['active-1', 'run-1'])
  assert.equal(store.hasSelection, true)

  store.hydrateFromWorkbench({
    selectedBenchmarkBatchId: 'detail-1',
    selectedBenchmarkBatchRun: benchmarkRunFixture('detail-1', { benchmarkLabel: 'Loaded detail' })
  })

  assert.equal(store.selectedBenchmarkBatchRun?.id, 'detail-1')
  assert.equal(store.selectedBenchmarkBatchRun?.benchmarkLabel, 'Loaded detail')
})

test('benchmark store owns active tab and forwards runtime actions', () => {
  setActivePinia(createPinia())
  const store = useBenchmarkStore()
  const selectBenchmarkBatch = vi.fn().mockReturnValue('batch-loaded')
  const refreshAll = vi.fn().mockReturnValue('refreshed')

  store.hydrateFromWorkbench({
    runRows: [benchmarkRunFixture('run-2')]
  })
  store.setActiveView('runs')

  assert.equal(store.activeView, 'runs')

  store.setActiveView('unknown')

  assert.equal(store.activeView, 'overview')

  store.bindRuntimeActions({ refreshAll, selectBenchmarkBatch })

  assert.equal(store.hasRuntimeActions, true)
  assert.equal(store.hasRuntimeAction('selectBenchmarkBatch'), true)
  assert.equal(store.selectBenchmarkBatch('run-2'), 'batch-loaded')
  assert.equal(store.selectedBenchmarkBatchId, 'run-2')
  assert.equal(store.selectedBenchmarkBatchRun?.id, 'run-2')
  assert.deepEqual(selectBenchmarkBatch.mock.calls[0], ['run-2'])
  assert.equal(store.refreshAll({ notify: true }), 'refreshed')
  assert.deepEqual(refreshAll.mock.calls[0], [{ notify: true }])

  store.clearRuntimeActions()

  assert.equal(store.hasRuntimeActions, false)
  assert.equal(store.hasRuntimeAction('selectBenchmarkBatch'), false)
  assert.equal(store.selectBenchmarkBatch(''), undefined)
})

test('benchmark store hydrates deep workbench state and exposes a runtime facade', async () => {
  setActivePinia(createPinia())
  const store = useBenchmarkStore()
  const loadBenchmarkSnapshots = vi.fn().mockResolvedValue('snapshots-loaded')
  const setBenchmarkDiagnosticFilter = vi.fn().mockReturnValue('filter-set')
  const clearBenchmarkDiagnosticFilters = vi.fn().mockReturnValue('filters-cleared')
  const startEvaluation = vi.fn().mockResolvedValue('started')

  store.hydrateFromWorkbench({
    suites: [benchmarkSuiteFixture('suite-release', { cost_tier: 'release' })],
    seedSets: [{ id: 'seed-1' }],
    suiteError: 'suite warning',
    plan: { total_games: 12, budget: { exceeded: { value: true } } },
    planError: 'plan failed',
    planBudgetExceeded: true,
    roles: ['werewolf', 'seer'],
    roleRows: [{ key: 'werewolf', label: '狼人' }],
    launchableRoles: ['werewolf'],
    selectedBenchmarkId: 'suite-release',
    selectedBenchmarkSuite: benchmarkSuiteFixture('suite-release', { label: 'Release Suite' }),
    selectedBenchmarkTargetType: 'role_version',
    selectedBenchmarkCanLaunch: false,
    selectedBenchmarkSuiteLabel: 'Release Suite',
    selectedBenchmarkEvaluationSetId: 'eval-release',
    selectedRole: 'werewolf',
    selectedRoleLabel: '狼人',
    modelLeaderboardRows: [{ key: 'model-a' }],
    roleLeaderboardRows: [{ key: 'role-a' }],
    roleTargetVersionRows: [{ version_id: 'v1' }],
    snapshots: [{ snapshot_id: 'snap-1', title: 'Frozen' }],
    selectedBenchmarkSnapshotId: 'snap-1',
    selectedBenchmarkSnapshot: { snapshot_id: 'snap-1' },
    activeBenchmarkSnapshotDetail: { snapshot_id: 'snap-1', rows: [] },
    snapshotScope: 'role_version',
    savedViews: [{ view_key: 'view-1' }],
    viewPreferences: { name: 'Release view' },
    viewDirty: true,
    selectedBenchmarkViewKey: 'view-1',
    batchRuns: [{ id: 'raw-run-1' }],
    runs: [benchmarkRunFixture('run-3')],
    runRows: [benchmarkRunFixture('run-3', { isActive: true, isTerminal: false })],
    unscopedRunRows: [{ id: 'legacy-run' }],
    selectedSuiteRunRows: [{ id: 'suite-run' }],
    usingLegacyRuns: true,
    selectedBenchmarkBatchId: 'run-3',
    batchDetail: { id: 'run-3', status: 'completed' },
    batchGames: [{ id: 'game-1' }],
    batchDiagnostics: [{ id: 'diag-1', kind: 'timeout' }],
    batchDiagnosticSummary: { total: 1 },
    reportHistory: [{ report_id: 'report-1' }],
    diagnosticAggregateDiagnostics: [{ id: 'agg-1' }],
    diagnosticAggregateSummary: { total: 2 },
    gameStatusFilter: 'failed',
    gameSeedFilter: 'seed-42',
    diagnosticKindFilter: 'timeout',
    form: { battle_games: 30, max_days: 7 },
    launchConfirmationOpen: true
  })

  assert.equal(store.benchmarkPlan?.total_games, 12)
  assert.equal(store.benchmarkPlanBudgetExceeded, true)
  assert.equal(store.selectedBenchmarkSuite?.label, 'Release Suite')
  assert.equal(store.selectedBenchmarkCanLaunch, false)
  assert.equal(store.selectedBenchmarkSuiteLabel, 'Release Suite')
  assert.deepEqual(store.roleTargetVersionRows, [{ version_id: 'v1' }])
  assert.equal(store.benchmarkSnapshots.length, 1)
  assert.equal(store.selectedBenchmarkSnapshotId, 'snap-1')
  assert.equal(store.activeBenchmarkSnapshotDetail?.snapshot_id, 'snap-1')
  assert.equal(store.benchmarkViewDirty, true)
  assert.equal(store.selectedBenchmarkViewKey, 'view-1')
  assert.equal(store.selectedBenchmarkUsingLegacyRuns, true)
  assert.equal(store.selectedBenchmarkBatchRun?.id, 'run-3')
  assert.deepEqual(store.benchmarkBatchDiagnosticSummary, { total: 1 })
  assert.equal(store.benchmarkDiagnosticAggregateDiagnostics.length, 1)
  assert.equal(store.benchmarkGameStatusFilter, 'failed')
  assert.equal(store.benchmarkGameSeedFilter, 'seed-42')
  assert.equal(store.form.battle_games, 30)
  assert.equal(store.launchConfirmationOpen, true)

  store.bindRuntimeActions({
    loadBenchmarkSnapshots,
    setBenchmarkDiagnosticFilter,
    clearBenchmarkDiagnosticFilters,
    startEvaluation
  })

  assert.equal(await store.loadBenchmarkSnapshots({ force: true }), 'snapshots-loaded')
  assert.deepEqual(loadBenchmarkSnapshots.mock.calls[0], [{ force: true }])
  assert.equal(store.setBenchmarkDiagnosticFilter('level', 'error'), 'filter-set')
  assert.equal(store.benchmarkDiagnosticLevelFilter, 'error')
  assert.equal(store.clearBenchmarkDiagnosticFilters(), 'filters-cleared')
  assert.equal(store.benchmarkDiagnosticLevelFilter, '')
  assert.equal(await store.startEvaluation(), 'started')
})
