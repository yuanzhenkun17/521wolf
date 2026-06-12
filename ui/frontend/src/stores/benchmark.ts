import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { BenchmarkRun, BenchmarkSuite } from '../types/benchmark'

type BenchmarkNotice = {
  type?: string
  message?: string
  [key: string]: unknown
}

type RuntimeAction = (...args: unknown[]) => unknown

type BenchmarkRuntimeActions = {
  refreshAll?: RuntimeAction
  selectBenchmarkBatch?: RuntimeAction
  loadBenchmarkBatchSection?: RuntimeAction
  [key: string]: RuntimeAction | undefined
}

type BenchmarkRunLike = Partial<BenchmarkRun> & Record<string, unknown>
type LooseRecord = Record<string, unknown>

type BenchmarkWorkbenchSnapshot = {
  suites?: BenchmarkSuite[]
  seedSets?: LooseRecord[]
  suiteError?: string
  plan?: LooseRecord | null
  planError?: string
  planBudgetExceeded?: boolean
  roles?: string[]
  roleRows?: LooseRecord[]
  launchableRoles?: string[]
  legacyBenchmarkTargetType?: string
  selectedBenchmarkSuite?: LooseRecord | null
  selectedBenchmarkTargetType?: string
  selectedBenchmarkIsModelSuite?: boolean
  selectedBenchmarkCanLaunch?: boolean
  selectedBenchmarkSuiteLaunchDisabledReason?: string
  selectedBenchmarkSuiteLabel?: string
  selectedBenchmarkEvaluationSetId?: string
  launchBattleGames?: number
  launchMaxDays?: number
  selectedRole?: string
  selectedRoleLabel?: string
  modelLeaderboard?: LooseRecord
  modelLeaderboardRows?: LooseRecord[]
  roleLeaderboard?: LooseRecord
  roleLeaderboardRows?: LooseRecord[]
  roleTargetVersions?: LooseRecord
  roleTargetVersionRows?: LooseRecord[]
  selectedRoleTargetVersion?: LooseRecord | null
  selectedRoleTargetVersionBlockedReason?: string
  currentBenchmarkLeaderboardRows?: LooseRecord[]
  normalizedCurrentBenchmarkLeaderboardRows?: LooseRecord[]
  snapshots?: LooseRecord[]
  snapshotDetail?: LooseRecord | null
  snapshotDetails?: LooseRecord
  snapshotExports?: LooseRecord
  snapshotLoading?: boolean
  snapshotError?: string
  snapshotServerCompare?: LooseRecord | null
  snapshotCompareLoading?: boolean
  snapshotCompareError?: string
  selectedBenchmarkSnapshotId?: string
  selectedBenchmarkSnapshot?: LooseRecord | null
  activeBenchmarkSnapshotDetail?: LooseRecord | null
  snapshotCompare?: LooseRecord
  snapshotScope?: string
  leaderboardCompare?: LooseRecord | null
  leaderboardCompareLoading?: boolean
  leaderboardCompareError?: string
  savedViews?: LooseRecord[]
  savedViewsLoading?: boolean
  savedViewsError?: string
  viewPreferences?: LooseRecord
  viewDirty?: boolean
  selectedBenchmarkViewKey?: string
  currentBenchmarkViewKey?: string
  activeBenchmarkViewConfig?: LooseRecord
  batchRuns?: LooseRecord[]
  events?: LooseRecord[]
  unscopedRunRows?: LooseRecord[]
  selectedSuiteRunRows?: LooseRecord[]
  usingLegacyRuns?: boolean
  runs?: BenchmarkRunLike[]
  runRows?: BenchmarkRunLike[]
  selectedBenchmarkId?: string
  selectedBenchmarkBatchId?: string
  selectedBatchId?: string
  selectedBenchmarkBatchRun?: BenchmarkRunLike | null
  detailLoading?: boolean
  detailError?: string
  batchDetail?: LooseRecord | null
  batchGames?: LooseRecord[]
  batchGamesLoading?: boolean
  batchGamePagination?: LooseRecord
  batchDiagnosticsLoading?: boolean
  batchDiagnostics?: LooseRecord[]
  batchDiagnosticSummary?: LooseRecord
  batchReport?: LooseRecord | null
  batchReportLoading?: boolean
  batchReportError?: string
  reportHistory?: LooseRecord[]
  reportHistoryLoading?: boolean
  reportHistoryError?: string
  reportHistorySummary?: LooseRecord
  reportHistoryPagination?: LooseRecord
  diagnosticAggregateLoading?: boolean
  diagnosticAggregateError?: string
  diagnosticAggregateDiagnostics?: LooseRecord[]
  diagnosticAggregateSummary?: LooseRecord
  diagnosticAggregateRuns?: LooseRecord[]
  diagnosticAggregateGames?: LooseRecord[]
  diagnosticAggregatePagination?: LooseRecord
  gameStatusFilter?: string
  gameSeedFilter?: string
  diagnosticKindFilter?: string
  diagnosticLevelFilter?: string
  diagnosticStatusFilter?: string
  diagnosticStageFilter?: string
  diagnosticSeedFilter?: string
  form?: LooseRecord
  loading?: boolean
  actionLoading?: string
  error?: string
  notice?: BenchmarkNotice | null
  launchConfirmationOpen?: boolean
}

const benchmarkTabs = new Set(['overview', 'leaderboards', 'runs', 'diagnostics', 'reports'])

function runIdentity(run: BenchmarkRunLike | null | undefined): string {
  return String(run?.id || run?.batch_id || run?.run_id || '')
}

function arrayOrEmpty<T>(value: T[] | undefined): T[] {
  return Array.isArray(value) ? value : []
}

function noticeOrEmpty(value: BenchmarkNotice | null | undefined): BenchmarkNotice {
  return value && typeof value === 'object' ? value : { type: '', message: '' }
}

function recordOrEmpty<T extends Record<string, unknown>>(value: T | undefined | null): T {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : ({} as T)
}

function runtimeMethod(actions: BenchmarkRuntimeActions, name: string): RuntimeAction | undefined {
  return typeof actions[name] === 'function' ? actions[name] : undefined
}

export const useBenchmarkStore = defineStore('benchmark', () => {
  const suites = ref<BenchmarkSuite[]>([])
  const benchmarkSeedSets = ref<LooseRecord[]>([])
  const benchmarkSuiteError = ref('')
  const benchmarkPlan = ref<LooseRecord | null>(null)
  const benchmarkPlanError = ref('')
  const benchmarkPlanBudgetExceeded = ref(false)
  const roles = ref<string[]>([])
  const roleRows = ref<LooseRecord[]>([])
  const launchableRoles = ref<string[]>([])
  const runs = ref<BenchmarkRunLike[]>([])
  const batchRuns = ref<LooseRecord[]>([])
  const runRows = ref<BenchmarkRunLike[]>([])
  const unscopedBenchmarkRunRows = ref<LooseRecord[]>([])
  const selectedSuiteBatchRunRows = ref<LooseRecord[]>([])
  const selectedBenchmarkUsingLegacyRuns = ref(false)
  const selectedBenchmarkId = ref('')
  const legacyBenchmarkTargetType = ref('role_version')
  const selectedBenchmarkSuite = ref<LooseRecord | null>(null)
  const selectedBenchmarkTargetType = ref('role_version')
  const selectedBenchmarkIsModelSuite = ref(false)
  const selectedBenchmarkCanLaunch = ref(false)
  const selectedBenchmarkSuiteLaunchDisabledReason = ref('')
  const selectedBenchmarkSuiteLabel = ref('')
  const selectedBenchmarkEvaluationSetId = ref('')
  const launchBattleGames = ref(0)
  const launchMaxDays = ref(0)
  const selectedRole = ref('')
  const selectedRoleLabel = ref('')
  const modelLeaderboard = ref<LooseRecord>({})
  const modelLeaderboardRows = ref<LooseRecord[]>([])
  const roleLeaderboard = ref<LooseRecord>({})
  const roleLeaderboardRows = ref<LooseRecord[]>([])
  const roleTargetVersions = ref<LooseRecord>({})
  const roleTargetVersionRows = ref<LooseRecord[]>([])
  const selectedRoleTargetVersion = ref<LooseRecord | null>(null)
  const selectedRoleTargetVersionBlockedReason = ref('')
  const currentBenchmarkLeaderboardRows = ref<LooseRecord[]>([])
  const normalizedCurrentBenchmarkLeaderboardRows = ref<LooseRecord[]>([])
  const benchmarkSnapshots = ref<LooseRecord[]>([])
  const benchmarkSnapshotDetail = ref<LooseRecord | null>(null)
  const benchmarkSnapshotDetails = ref<LooseRecord>({})
  const benchmarkSnapshotExports = ref<LooseRecord>({})
  const benchmarkSnapshotLoading = ref(false)
  const benchmarkSnapshotError = ref('')
  const benchmarkSnapshotServerCompare = ref<LooseRecord | null>(null)
  const benchmarkSnapshotCompareLoading = ref(false)
  const benchmarkSnapshotCompareError = ref('')
  const selectedBenchmarkSnapshotId = ref('')
  const selectedBenchmarkSnapshot = ref<LooseRecord | null>(null)
  const activeBenchmarkSnapshotDetail = ref<LooseRecord | null>(null)
  const benchmarkSnapshotCompare = ref<LooseRecord>({})
  const benchmarkSnapshotScope = ref('role_version')
  const benchmarkLeaderboardCompare = ref<LooseRecord | null>(null)
  const benchmarkLeaderboardCompareLoading = ref(false)
  const benchmarkLeaderboardCompareError = ref('')
  const benchmarkSavedViews = ref<LooseRecord[]>([])
  const benchmarkSavedViewsLoading = ref(false)
  const benchmarkSavedViewsError = ref('')
  const benchmarkViewPreferences = ref<LooseRecord>({})
  const benchmarkViewDirty = ref(false)
  const selectedBenchmarkViewKey = ref('')
  const currentBenchmarkViewKey = ref('')
  const activeBenchmarkViewConfig = ref<LooseRecord>({})
  const benchmarkEvents = ref<LooseRecord[]>([])
  const selectedBatchId = ref('')
  const selectedRunDetail = ref<BenchmarkRunLike | null>(null)
  const activeView = ref('overview')
  const launchConfirmationOpen = ref(false)
  const benchmarkDetailLoading = ref(false)
  const benchmarkDetailError = ref('')
  const benchmarkBatchDetail = ref<LooseRecord | null>(null)
  const benchmarkBatchGames = ref<LooseRecord[]>([])
  const benchmarkBatchGamesLoading = ref(false)
  const benchmarkBatchGamePagination = ref<LooseRecord>({})
  const benchmarkBatchDiagnosticsLoading = ref(false)
  const benchmarkBatchDiagnostics = ref<LooseRecord[]>([])
  const benchmarkBatchDiagnosticSummary = ref<LooseRecord>({})
  const benchmarkBatchReport = ref<LooseRecord | null>(null)
  const benchmarkBatchReportLoading = ref(false)
  const benchmarkBatchReportError = ref('')
  const benchmarkReportHistory = ref<LooseRecord[]>([])
  const benchmarkReportHistoryLoading = ref(false)
  const benchmarkReportHistoryError = ref('')
  const benchmarkReportHistorySummary = ref<LooseRecord>({})
  const benchmarkReportHistoryPagination = ref<LooseRecord>({})
  const benchmarkDiagnosticAggregateLoading = ref(false)
  const benchmarkDiagnosticAggregateError = ref('')
  const benchmarkDiagnosticAggregateDiagnostics = ref<LooseRecord[]>([])
  const benchmarkDiagnosticAggregateSummary = ref<LooseRecord>({})
  const benchmarkDiagnosticAggregateRuns = ref<LooseRecord[]>([])
  const benchmarkDiagnosticAggregateGames = ref<LooseRecord[]>([])
  const benchmarkDiagnosticAggregatePagination = ref<LooseRecord>({})
  const benchmarkGameStatusFilter = ref('problem')
  const benchmarkGameSeedFilter = ref('')
  const benchmarkDiagnosticKindFilter = ref('')
  const benchmarkDiagnosticLevelFilter = ref('')
  const benchmarkDiagnosticStatusFilter = ref('')
  const benchmarkDiagnosticStageFilter = ref('')
  const benchmarkDiagnosticSeedFilter = ref('')
  const form = ref<LooseRecord>({})
  const loading = ref(false)
  const actionLoading = ref('')
  const error = ref('')
  const notice = ref<BenchmarkNotice>({ type: '', message: '' })
  const runtimeActions = ref<BenchmarkRuntimeActions>({})

  const selectedSuite = computed(() => suites.value.find((suite) => suite.id === selectedBenchmarkId.value) || null)
  const selectedBenchmarkBatchRun = computed(() => {
    const id = selectedBatchId.value
    const detailId = runIdentity(selectedRunDetail.value)
    if (selectedRunDetail.value && (!id || detailId === id)) return selectedRunDetail.value
    return (
      runRows.value.find((run) => runIdentity(run) === id) ||
      runs.value.find((run) => runIdentity(run) === id) ||
      null
    )
  })
  const activeRunRows = computed(() => runRows.value.filter((run) => Boolean(run.isActive)))
  const recentRunRows = computed(() => runRows.value.slice(0, 5))
  const hasSelection = computed(() => Boolean(selectedBenchmarkBatchRun.value || selectedBatchId.value))
  const hasRuntimeActions = computed(() => Object.keys(runtimeActions.value).length > 0)

  function setActiveView(view: string): void {
    const nextView = String(view || '').trim()
    activeView.value = benchmarkTabs.has(nextView) ? nextView : 'overview'
  }

  function setSelectedBatchId(batchId: string): void {
    const nextId = String(batchId || '').trim()
    selectedBatchId.value = nextId
    selectedRunDetail.value =
      runRows.value.find((run) => runIdentity(run) === nextId) ||
      runs.value.find((run) => runIdentity(run) === nextId) ||
      null
  }

  function hydrateFromWorkbench(snapshot: BenchmarkWorkbenchSnapshot = {}): void {
    suites.value = arrayOrEmpty(snapshot.suites)
    benchmarkSeedSets.value = arrayOrEmpty(snapshot.seedSets)
    benchmarkSuiteError.value = String(snapshot.suiteError || '')
    benchmarkPlan.value = snapshot.plan || null
    benchmarkPlanError.value = String(snapshot.planError || '')
    benchmarkPlanBudgetExceeded.value = Boolean(snapshot.planBudgetExceeded)
    roles.value = arrayOrEmpty(snapshot.roles)
    roleRows.value = arrayOrEmpty(snapshot.roleRows)
    launchableRoles.value = arrayOrEmpty(snapshot.launchableRoles)
    runs.value = arrayOrEmpty(snapshot.runs)
    batchRuns.value = arrayOrEmpty(snapshot.batchRuns)
    runRows.value = arrayOrEmpty(snapshot.runRows || snapshot.runs)
    unscopedBenchmarkRunRows.value = arrayOrEmpty(snapshot.unscopedRunRows)
    selectedSuiteBatchRunRows.value = arrayOrEmpty(snapshot.selectedSuiteRunRows)
    selectedBenchmarkUsingLegacyRuns.value = Boolean(snapshot.usingLegacyRuns)
    legacyBenchmarkTargetType.value = String(snapshot.legacyBenchmarkTargetType || 'role_version')
    selectedBenchmarkSuite.value = snapshot.selectedBenchmarkSuite || null
    selectedBenchmarkTargetType.value = String(snapshot.selectedBenchmarkTargetType || 'role_version')
    selectedBenchmarkIsModelSuite.value = Boolean(snapshot.selectedBenchmarkIsModelSuite)
    selectedBenchmarkCanLaunch.value = Boolean(snapshot.selectedBenchmarkCanLaunch)
    selectedBenchmarkSuiteLaunchDisabledReason.value = String(snapshot.selectedBenchmarkSuiteLaunchDisabledReason || '')
    selectedBenchmarkSuiteLabel.value = String(snapshot.selectedBenchmarkSuiteLabel || '')
    selectedBenchmarkEvaluationSetId.value = String(snapshot.selectedBenchmarkEvaluationSetId || '')
    launchBattleGames.value = Number(snapshot.launchBattleGames || 0)
    launchMaxDays.value = Number(snapshot.launchMaxDays || 0)
    selectedRole.value = String(snapshot.selectedRole || '')
    selectedRoleLabel.value = String(snapshot.selectedRoleLabel || '')
    modelLeaderboard.value = recordOrEmpty(snapshot.modelLeaderboard)
    modelLeaderboardRows.value = arrayOrEmpty(snapshot.modelLeaderboardRows)
    roleLeaderboard.value = recordOrEmpty(snapshot.roleLeaderboard)
    roleLeaderboardRows.value = arrayOrEmpty(snapshot.roleLeaderboardRows)
    roleTargetVersions.value = recordOrEmpty(snapshot.roleTargetVersions)
    roleTargetVersionRows.value = arrayOrEmpty(snapshot.roleTargetVersionRows)
    selectedRoleTargetVersion.value = snapshot.selectedRoleTargetVersion || null
    selectedRoleTargetVersionBlockedReason.value = String(snapshot.selectedRoleTargetVersionBlockedReason || '')
    currentBenchmarkLeaderboardRows.value = arrayOrEmpty(snapshot.currentBenchmarkLeaderboardRows)
    normalizedCurrentBenchmarkLeaderboardRows.value = arrayOrEmpty(snapshot.normalizedCurrentBenchmarkLeaderboardRows)
    benchmarkSnapshots.value = arrayOrEmpty(snapshot.snapshots)
    benchmarkSnapshotDetail.value = snapshot.snapshotDetail || null
    benchmarkSnapshotDetails.value = recordOrEmpty(snapshot.snapshotDetails)
    benchmarkSnapshotExports.value = recordOrEmpty(snapshot.snapshotExports)
    benchmarkSnapshotLoading.value = Boolean(snapshot.snapshotLoading)
    benchmarkSnapshotError.value = String(snapshot.snapshotError || '')
    benchmarkSnapshotServerCompare.value = snapshot.snapshotServerCompare || null
    benchmarkSnapshotCompareLoading.value = Boolean(snapshot.snapshotCompareLoading)
    benchmarkSnapshotCompareError.value = String(snapshot.snapshotCompareError || '')
    selectedBenchmarkSnapshotId.value = String(snapshot.selectedBenchmarkSnapshotId || '')
    selectedBenchmarkSnapshot.value = snapshot.selectedBenchmarkSnapshot || null
    activeBenchmarkSnapshotDetail.value = snapshot.activeBenchmarkSnapshotDetail || null
    benchmarkSnapshotCompare.value = recordOrEmpty(snapshot.snapshotCompare)
    benchmarkSnapshotScope.value = String(snapshot.snapshotScope || 'role_version')
    benchmarkLeaderboardCompare.value = snapshot.leaderboardCompare || null
    benchmarkLeaderboardCompareLoading.value = Boolean(snapshot.leaderboardCompareLoading)
    benchmarkLeaderboardCompareError.value = String(snapshot.leaderboardCompareError || '')
    benchmarkSavedViews.value = arrayOrEmpty(snapshot.savedViews)
    benchmarkSavedViewsLoading.value = Boolean(snapshot.savedViewsLoading)
    benchmarkSavedViewsError.value = String(snapshot.savedViewsError || '')
    benchmarkViewPreferences.value = recordOrEmpty(snapshot.viewPreferences)
    benchmarkViewDirty.value = Boolean(snapshot.viewDirty)
    selectedBenchmarkViewKey.value = String(snapshot.selectedBenchmarkViewKey || '')
    currentBenchmarkViewKey.value = String(snapshot.currentBenchmarkViewKey || '')
    activeBenchmarkViewConfig.value = recordOrEmpty(snapshot.activeBenchmarkViewConfig)
    benchmarkEvents.value = arrayOrEmpty(snapshot.events)
    benchmarkDetailLoading.value = Boolean(snapshot.detailLoading)
    benchmarkDetailError.value = String(snapshot.detailError || '')
    benchmarkBatchDetail.value = snapshot.batchDetail || null
    benchmarkBatchGames.value = arrayOrEmpty(snapshot.batchGames)
    benchmarkBatchGamesLoading.value = Boolean(snapshot.batchGamesLoading)
    benchmarkBatchGamePagination.value = recordOrEmpty(snapshot.batchGamePagination)
    benchmarkBatchDiagnosticsLoading.value = Boolean(snapshot.batchDiagnosticsLoading)
    benchmarkBatchDiagnostics.value = arrayOrEmpty(snapshot.batchDiagnostics)
    benchmarkBatchDiagnosticSummary.value = recordOrEmpty(snapshot.batchDiagnosticSummary)
    benchmarkBatchReport.value = snapshot.batchReport || null
    benchmarkBatchReportLoading.value = Boolean(snapshot.batchReportLoading)
    benchmarkBatchReportError.value = String(snapshot.batchReportError || '')
    benchmarkReportHistory.value = arrayOrEmpty(snapshot.reportHistory)
    benchmarkReportHistoryLoading.value = Boolean(snapshot.reportHistoryLoading)
    benchmarkReportHistoryError.value = String(snapshot.reportHistoryError || '')
    benchmarkReportHistorySummary.value = recordOrEmpty(snapshot.reportHistorySummary)
    benchmarkReportHistoryPagination.value = recordOrEmpty(snapshot.reportHistoryPagination)
    benchmarkDiagnosticAggregateLoading.value = Boolean(snapshot.diagnosticAggregateLoading)
    benchmarkDiagnosticAggregateError.value = String(snapshot.diagnosticAggregateError || '')
    benchmarkDiagnosticAggregateDiagnostics.value = arrayOrEmpty(snapshot.diagnosticAggregateDiagnostics)
    benchmarkDiagnosticAggregateSummary.value = recordOrEmpty(snapshot.diagnosticAggregateSummary)
    benchmarkDiagnosticAggregateRuns.value = arrayOrEmpty(snapshot.diagnosticAggregateRuns)
    benchmarkDiagnosticAggregateGames.value = arrayOrEmpty(snapshot.diagnosticAggregateGames)
    benchmarkDiagnosticAggregatePagination.value = recordOrEmpty(snapshot.diagnosticAggregatePagination)
    benchmarkGameStatusFilter.value = String(snapshot.gameStatusFilter || 'problem')
    benchmarkGameSeedFilter.value = String(snapshot.gameSeedFilter || '')
    benchmarkDiagnosticKindFilter.value = String(snapshot.diagnosticKindFilter || '')
    benchmarkDiagnosticLevelFilter.value = String(snapshot.diagnosticLevelFilter || '')
    benchmarkDiagnosticStatusFilter.value = String(snapshot.diagnosticStatusFilter || '')
    benchmarkDiagnosticStageFilter.value = String(snapshot.diagnosticStageFilter || '')
    benchmarkDiagnosticSeedFilter.value = String(snapshot.diagnosticSeedFilter || '')
    form.value = recordOrEmpty(snapshot.form)
    loading.value = Boolean(snapshot.loading)
    actionLoading.value = String(snapshot.actionLoading || '')
    error.value = String(snapshot.error || '')
    notice.value = noticeOrEmpty(snapshot.notice)
    if ('launchConfirmationOpen' in snapshot) launchConfirmationOpen.value = Boolean(snapshot.launchConfirmationOpen)

    if ('selectedBenchmarkId' in snapshot) selectedBenchmarkId.value = String(snapshot.selectedBenchmarkId || '')
    if ('selectedBenchmarkBatchId' in snapshot || 'selectedBatchId' in snapshot) {
      setSelectedBatchId(String(snapshot.selectedBenchmarkBatchId ?? snapshot.selectedBatchId ?? ''))
    }
    if ('selectedBenchmarkBatchRun' in snapshot) {
      selectedRunDetail.value = snapshot.selectedBenchmarkBatchRun || null
      if (selectedRunDetail.value && !selectedBatchId.value) selectedBatchId.value = runIdentity(selectedRunDetail.value)
    }
  }

  function bindRuntimeActions(actions: BenchmarkRuntimeActions = {}): void {
    runtimeActions.value = { ...actions }
  }

  function clearRuntimeActions(): void {
    runtimeActions.value = {}
  }

  function runRuntimeAction(action: string, ...args: unknown[]): unknown {
    return runtimeMethod(runtimeActions.value, action)?.(...args)
  }

  function hasRuntimeAction(action: keyof BenchmarkRuntimeActions): boolean {
    return typeof runtimeActions.value[action] === 'function'
  }

  function refreshAll(...args: unknown[]): unknown {
    return runtimeActions.value.refreshAll?.(...args)
  }

  function selectBenchmarkBatch(batchId: string): unknown {
    const nextId = String(batchId || '').trim()
    setSelectedBatchId(nextId)
    if (!nextId) return undefined
    return runRuntimeAction('selectBenchmarkBatch', nextId)
  }

  function setLaunchConfirmationOpen(open: boolean): void {
    launchConfirmationOpen.value = Boolean(open)
  }

  function selectBenchmarkSuite(id: string): unknown {
    selectedBenchmarkId.value = String(id || '')
    return runRuntimeAction('selectBenchmarkSuite', id)
  }

  function selectLegacyBenchmarkScope(targetType: string): unknown {
    legacyBenchmarkTargetType.value = String(targetType || 'role_version')
    return runRuntimeAction('selectLegacyBenchmarkScope', targetType)
  }

  function selectRole(role: string): unknown {
    selectedRole.value = String(role || '')
    return runRuntimeAction('selectRole', role)
  }

  function selectBenchmarkSnapshot(snapshotId: string): unknown {
    selectedBenchmarkSnapshotId.value = String(snapshotId || '')
    return runRuntimeAction('selectBenchmarkSnapshot', snapshotId)
  }

  function selectBenchmarkView(key: string): unknown {
    selectedBenchmarkViewKey.value = String(key || '')
    return runRuntimeAction('selectBenchmarkView', key)
  }

  function setBenchmarkGameStatusFilter(value: string): unknown {
    benchmarkGameStatusFilter.value = String(value || '')
    return runRuntimeAction('setBenchmarkGameStatusFilter', value)
  }

  function setBenchmarkGameSeedFilter(value: string): unknown {
    benchmarkGameSeedFilter.value = String(value || '')
    return runRuntimeAction('setBenchmarkGameSeedFilter', value)
  }

  function setBenchmarkDiagnosticFilter(name: string, value: string): unknown {
    const nextValue = String(value || '')
    const key = String(name || '')
    if (key === 'kind') benchmarkDiagnosticKindFilter.value = nextValue
    if (key === 'level') benchmarkDiagnosticLevelFilter.value = nextValue
    if (key === 'status') benchmarkDiagnosticStatusFilter.value = nextValue
    if (key === 'stage') benchmarkDiagnosticStageFilter.value = nextValue
    if (key === 'seed') benchmarkDiagnosticSeedFilter.value = nextValue
    return runRuntimeAction('setBenchmarkDiagnosticFilter', name, value)
  }

  function clearBenchmarkDiagnosticFilters(): unknown {
    benchmarkDiagnosticKindFilter.value = ''
    benchmarkDiagnosticLevelFilter.value = ''
    benchmarkDiagnosticStatusFilter.value = ''
    benchmarkDiagnosticStageFilter.value = ''
    benchmarkDiagnosticSeedFilter.value = ''
    return runRuntimeAction('clearBenchmarkDiagnosticFilters')
  }

  function clearNotice(): unknown {
    notice.value = { type: '', message: '' }
    return runRuntimeAction('clearNotice')
  }

  return {
    suites,
    benchmarkSuites: suites,
    benchmarkSeedSets,
    benchmarkSuiteError,
    benchmarkPlan,
    benchmarkPlanError,
    benchmarkPlanBudgetExceeded,
    roles,
    roleRows,
    launchableRoles,
    runs,
    batchRuns,
    runRows,
    batchRunRows: runs,
    filteredBatchRunRows: runRows,
    visibleBatchRunRows: runRows,
    unscopedBenchmarkRunRows,
    selectedSuiteBatchRunRows,
    selectedBenchmarkUsingLegacyRuns,
    selectedBenchmarkId,
    legacyBenchmarkTargetType,
    selectedBenchmarkSuite,
    selectedBenchmarkTargetType,
    selectedBenchmarkIsModelSuite,
    selectedBenchmarkCanLaunch,
    selectedBenchmarkSuiteLaunchDisabledReason,
    selectedBenchmarkSuiteLabel,
    selectedBenchmarkEvaluationSetId,
    launchBattleGames,
    launchMaxDays,
    selectedRole,
    selectedRoleLabel,
    modelLeaderboard,
    modelLeaderboardRows,
    roleLeaderboard,
    roleLeaderboardRows,
    roleTargetVersions,
    roleTargetVersionRows,
    selectedRoleTargetVersion,
    selectedRoleTargetVersionBlockedReason,
    currentBenchmarkLeaderboardRows,
    normalizedCurrentBenchmarkLeaderboardRows,
    benchmarkSnapshots,
    benchmarkSnapshotDetail,
    benchmarkSnapshotDetails,
    benchmarkSnapshotExports,
    benchmarkSnapshotLoading,
    benchmarkSnapshotError,
    benchmarkSnapshotServerCompare,
    benchmarkSnapshotCompareLoading,
    benchmarkSnapshotCompareError,
    selectedBenchmarkSnapshotId,
    selectedBenchmarkSnapshot,
    activeBenchmarkSnapshotDetail,
    benchmarkSnapshotCompare,
    benchmarkSnapshotScope,
    benchmarkLeaderboardCompare,
    benchmarkLeaderboardCompareLoading,
    benchmarkLeaderboardCompareError,
    benchmarkSavedViews,
    benchmarkSavedViewsLoading,
    benchmarkSavedViewsError,
    benchmarkViewPreferences,
    benchmarkViewDirty,
    selectedBenchmarkViewKey,
    currentBenchmarkViewKey,
    activeBenchmarkViewConfig,
    benchmarkEvents,
    selectedBatchId,
    selectedBenchmarkBatchId: selectedBatchId,
    selectedRunDetail,
    activeView,
    launchConfirmationOpen,
    benchmarkDetailLoading,
    benchmarkDetailError,
    benchmarkBatchDetail,
    benchmarkBatchGames,
    benchmarkBatchGamesLoading,
    benchmarkBatchGamePagination,
    benchmarkBatchDiagnosticsLoading,
    benchmarkBatchDiagnostics,
    benchmarkBatchDiagnosticSummary,
    benchmarkBatchReport,
    benchmarkBatchReportLoading,
    benchmarkBatchReportError,
    benchmarkReportHistory,
    benchmarkReportHistoryLoading,
    benchmarkReportHistoryError,
    benchmarkReportHistorySummary,
    benchmarkReportHistoryPagination,
    benchmarkDiagnosticAggregateLoading,
    benchmarkDiagnosticAggregateError,
    benchmarkDiagnosticAggregateDiagnostics,
    benchmarkDiagnosticAggregateSummary,
    benchmarkDiagnosticAggregateRuns,
    benchmarkDiagnosticAggregateGames,
    benchmarkDiagnosticAggregatePagination,
    benchmarkGameStatusFilter,
    benchmarkGameSeedFilter,
    benchmarkDiagnosticKindFilter,
    benchmarkDiagnosticLevelFilter,
    benchmarkDiagnosticStatusFilter,
    benchmarkDiagnosticStageFilter,
    benchmarkDiagnosticSeedFilter,
    form,
    loading,
    actionLoading,
    error,
    notice,
    selectedSuite,
    selectedBenchmarkBatchRun,
    activeRunRows,
    recentRunRows,
    hasSelection,
    hasRuntimeActions,
    setActiveView,
    setSelectedBatchId,
    setLaunchConfirmationOpen,
    hydrateFromWorkbench,
    bindRuntimeActions,
    clearRuntimeActions,
    runRuntimeAction,
    hasRuntimeAction,
    refreshAll,
    selectBenchmarkBatch,
    selectBenchmarkSuite,
    selectLegacyBenchmarkScope,
    selectRole,
    selectBenchmarkSnapshot,
    selectBenchmarkView,
    setBenchmarkGameStatusFilter,
    setBenchmarkGameSeedFilter,
    setBenchmarkDiagnosticFilter,
    clearBenchmarkDiagnosticFilters,
    clearNotice,
    loadBenchmarkLeaderboardCompare: (...args: unknown[]) => runRuntimeAction('loadBenchmarkLeaderboardCompare', ...args),
    loadBenchmarkSeedSets: (...args: unknown[]) => runRuntimeAction('loadBenchmarkSeedSets', ...args),
    loadBenchmarkViews: (...args: unknown[]) => runRuntimeAction('loadBenchmarkViews', ...args),
    loadCurrentBenchmarkView: (...args: unknown[]) => runRuntimeAction('loadCurrentBenchmarkView', ...args),
    saveCurrentBenchmarkView: (...args: unknown[]) => runRuntimeAction('saveCurrentBenchmarkView', ...args),
    resetCurrentBenchmarkView: (...args: unknown[]) => runRuntimeAction('resetCurrentBenchmarkView', ...args),
    setBenchmarkViewPreference: (...args: unknown[]) => runRuntimeAction('setBenchmarkViewPreference', ...args),
    loadBenchmarkSnapshots: (...args: unknown[]) => runRuntimeAction('loadBenchmarkSnapshots', ...args),
    loadBenchmarkSnapshotDetail: (...args: unknown[]) => runRuntimeAction('loadBenchmarkSnapshotDetail', ...args),
    loadBenchmarkSnapshotCompare: (...args: unknown[]) => runRuntimeAction('loadBenchmarkSnapshotCompare', ...args),
    loadBenchmarkSnapshotExport: (...args: unknown[]) => runRuntimeAction('loadBenchmarkSnapshotExport', ...args),
    createBenchmarkSnapshot: (...args: unknown[]) => runRuntimeAction('createBenchmarkSnapshot', ...args),
    loadBenchmarkView: (...args: unknown[]) => runRuntimeAction('loadBenchmarkView', ...args),
    saveBenchmarkView: (...args: unknown[]) => runRuntimeAction('saveBenchmarkView', ...args),
    deleteBenchmarkView: (...args: unknown[]) => runRuntimeAction('deleteBenchmarkView', ...args),
    loadBenchmarkReportHistory: (...args: unknown[]) => runRuntimeAction('loadBenchmarkReportHistory', ...args),
    loadBenchmarkDiagnosticsAggregate: (...args: unknown[]) => runRuntimeAction('loadBenchmarkDiagnosticsAggregate', ...args),
    loadBenchmarkBatchDetail: (...args: unknown[]) => runRuntimeAction('loadBenchmarkBatchDetail', ...args),
    loadBenchmarkBatchSection: (...args: unknown[]) => runRuntimeAction('loadBenchmarkBatchSection', ...args),
    loadBenchmarkBatchGamesPage: (...args: unknown[]) => runRuntimeAction('loadBenchmarkBatchGamesPage', ...args),
    loadNextBenchmarkBatchGamesPage: (...args: unknown[]) => runRuntimeAction('loadNextBenchmarkBatchGamesPage', ...args),
    loadBenchmarkBatchDiagnostics: (...args: unknown[]) => runRuntimeAction('loadBenchmarkBatchDiagnostics', ...args),
    loadBenchmarkBatchReport: (...args: unknown[]) => runRuntimeAction('loadBenchmarkBatchReport', ...args),
    loadBenchmarkBatchReportExport: (...args: unknown[]) => runRuntimeAction('loadBenchmarkBatchReportExport', ...args),
    startEvaluation: (...args: unknown[]) => runRuntimeAction('startEvaluation', ...args),
    stopBatch: (...args: unknown[]) => runRuntimeAction('stopBatch', ...args)
  }
})
