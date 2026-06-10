import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { UnknownRecord } from '../types/api'
import type { EvolutionRun, RoleVersion } from '../types/evolution'

type EvolutionNotice = {
  type?: string
  message?: string
  [key: string]: unknown
}

type RuntimeAction = (...args: unknown[]) => unknown

type EvolutionRuntimeActions = {
  refreshAll?: RuntimeAction
  selectRole?: RuntimeAction
  selectRun?: RuntimeAction
  [key: string]: RuntimeAction | undefined
}

type EvolutionRunLike = Partial<EvolutionRun> & UnknownRecord

type EvolutionWorkbenchSnapshot = {
  loading?: boolean
  actionLoading?: string
  error?: string
  notice?: EvolutionNotice | null
  activeTab?: string
  roles?: string[]
  roleRows?: UnknownRecord[]
  runs?: EvolutionRun[]
  batches?: EvolutionRun[]
  runRows?: EvolutionRun[]
  filteredRunRows?: EvolutionRun[]
  visibleRunRows?: EvolutionRun[]
  runPagination?: UnknownRecord
  runLoadingMore?: boolean
  runHasMore?: boolean
  runFilter?: string
  versionsByRole?: Record<string, RoleVersion[]>
  leaderboardsByRole?: Record<string, UnknownRecord[]>
  selectedRole?: string
  selectedRoleLabel?: string
  selectedVersion?: UnknownRecord | null
  selectedVersionId?: string
  selectedVersionDetail?: UnknownRecord
  evolutionDeepLinkTarget?: UnknownRecord | null
  trustBundleDrawerOpen?: boolean
  trustBundleAudit?: UnknownRecord
  trustBundleAuditLoading?: boolean
  trustBundleAuditError?: string
  selectedRoleLeaderboard?: UnknownRecord[]
  selectedRunId?: string
  selectedRun?: EvolutionRunLike | null
  selectedRunSummary?: UnknownRecord | null
  selectedDiff?: unknown[]
  selectedDiffData?: UnknownRecord | null
  selectedProposalReview?: UnknownRecord | null
  selectedProposalRows?: UnknownRecord[]
  selectedGames?: UnknownRecord
  sampleBuckets?: UnknownRecord[]
  selectedGameBucket?: string
  selectedGameId?: string
  selectedGameRows?: UnknownRecord[]
  selectedSampleGame?: UnknownRecord | null
  selectedSampleHistoryGameId?: string
  filteredSampleGameRows?: UnknownRecord[]
  visibleSampleGameRows?: UnknownRecord[]
  sampleGamePagination?: UnknownRecord
  selectedSamplePagination?: UnknownRecord
  sampleGameHasMore?: boolean
  sampleGameLoadingMore?: boolean
  sampleGameFilter?: string
  selectedGameDetail?: UnknownRecord
  selectedSampleState?: UnknownRecord
  selectedSampleBucketError?: string
  selectedSampleHistoryUnavailableReason?: string
  selectedBatchRoles?: string[]
  eventLog?: UnknownRecord[]
  form?: UnknownRecord
  selectedCanPromote?: boolean
  selectedPromoteDisabledReason?: string
  selectedCanReject?: boolean
  selectedRejectDisabledReason?: string
  selectedCanTerminate?: boolean
  selectedTerminateDisabledReason?: string
  selectedRollbackDisabledReason?: string
  baselinePromoteTrustDisabledReason?: string
}

function runIdentity(run: EvolutionRunLike | null | undefined): string {
  return String(run?.id || run?.run_id || run?.batch_id || '')
}

function arrayOrEmpty<T>(value: T[] | undefined): T[] {
  return Array.isArray(value) ? value : []
}

function recordOrEmpty<T extends Record<string, unknown>>(value: T | undefined | null): T {
  return value && typeof value === 'object' ? value : ({} as T)
}

function runtimeMethod(actions: EvolutionRuntimeActions, name: string): RuntimeAction | undefined {
  return typeof actions[name] === 'function' ? actions[name] : undefined
}

const evolutionTabs = new Set(['console', 'review', 'runs', 'leaderboard', 'versions', 'events', 'samples'])

export const useEvolutionStore = defineStore('evolution', () => {
  const roles = ref<string[]>([])
  const roleRows = ref<UnknownRecord[]>([])
  const runs = ref<EvolutionRun[]>([])
  const batches = ref<EvolutionRun[]>([])
  const runRows = ref<EvolutionRun[]>([])
  const filteredRunRows = ref<EvolutionRun[]>([])
  const visibleRunRows = ref<EvolutionRun[]>([])
  const runPagination = ref<UnknownRecord>({})
  const runLoadingMore = ref(false)
  const runHasMore = ref(false)
  const runFilter = ref('')
  const versionsByRole = ref<Record<string, RoleVersion[]>>({})
  const leaderboardsByRole = ref<Record<string, UnknownRecord[]>>({})
  const activeTab = ref('console')
  const selectedRole = ref('')
  const selectedRoleLabel = ref('')
  const selectedVersion = ref<UnknownRecord | null>(null)
  const selectedVersionId = ref('')
  const selectedVersionDetail = ref<UnknownRecord>({})
  const evolutionDeepLinkTarget = ref<UnknownRecord | null>(null)
  const trustBundleDrawerOpen = ref(false)
  const trustBundleAudit = ref<UnknownRecord>({})
  const trustBundleAuditLoading = ref(false)
  const trustBundleAuditError = ref('')
  const selectedRoleLeaderboard = ref<UnknownRecord[]>([])
  const selectedRunId = ref('')
  const selectedRunDetail = ref<EvolutionRunLike | null>(null)
  const selectedRunSummary = ref<UnknownRecord | null>(null)
  const selectedDiff = ref<unknown[]>([])
  const selectedDiffData = ref<UnknownRecord | null>(null)
  const selectedProposalReview = ref<UnknownRecord | null>(null)
  const selectedProposalRows = ref<UnknownRecord[]>([])
  const selectedGames = ref<UnknownRecord>({})
  const sampleBuckets = ref<UnknownRecord[]>([])
  const selectedGameBucket = ref('training')
  const selectedGameId = ref('')
  const selectedGameRows = ref<UnknownRecord[]>([])
  const selectedSampleGame = ref<UnknownRecord | null>(null)
  const selectedSampleHistoryGameId = ref('')
  const filteredSampleGameRows = ref<UnknownRecord[]>([])
  const visibleSampleGameRows = ref<UnknownRecord[]>([])
  const sampleGamePagination = ref<UnknownRecord>({})
  const selectedSamplePagination = ref<UnknownRecord>({})
  const sampleGameHasMore = ref(false)
  const sampleGameLoadingMore = ref(false)
  const sampleGameFilter = ref('')
  const selectedGameDetail = ref<UnknownRecord>({})
  const selectedSampleState = ref<UnknownRecord>({})
  const selectedSampleBucketError = ref('')
  const selectedSampleHistoryUnavailableReason = ref('')
  const selectedBatchRoles = ref<string[]>([])
  const eventLog = ref<UnknownRecord[]>([])
  const form = ref<UnknownRecord>({})
  const loading = ref(false)
  const actionLoading = ref('')
  const error = ref('')
  const notice = ref<EvolutionNotice>({ type: '', message: '' })
  const selectedCanPromote = ref(false)
  const selectedPromoteDisabledReason = ref('')
  const selectedCanReject = ref(false)
  const selectedRejectDisabledReason = ref('')
  const selectedCanTerminate = ref(false)
  const selectedTerminateDisabledReason = ref('')
  const selectedRollbackDisabledReason = ref('')
  const baselinePromoteTrustDisabledReason = ref('')
  const runtimeActions = ref<EvolutionRuntimeActions>({})

  const selectedRun = computed(() => {
    const id = selectedRunId.value
    const detailId = runIdentity(selectedRunDetail.value)
    if (selectedRunDetail.value && (!id || detailId === id)) return selectedRunDetail.value
    return (
      runRows.value.find((run) => runIdentity(run) === id) ||
      runs.value.find((run) => runIdentity(run) === id) ||
      null
    )
  })
  const selectedRoleVersions = computed(() => versionsByRole.value[selectedRole.value] || [])
  const selectedIsBatch = computed(() => selectedRun.value?.entityType === 'batch')
  const selectedIsRun = computed(() => selectedRun.value?.entityType === 'run')
  const hasSelection = computed(() => Boolean(selectedRun.value))
  const hasRuntimeActions = computed(() => Object.keys(runtimeActions.value).length > 0)

  function setActiveTab(tab: string): void {
    const nextTab = String(tab || '').trim()
    activeTab.value = evolutionTabs.has(nextTab) ? nextTab : 'console'
  }

  function hydrateFromWorkbench(snapshot: EvolutionWorkbenchSnapshot = {}) {
    roles.value = arrayOrEmpty(snapshot.roles)
    roleRows.value = arrayOrEmpty(snapshot.roleRows)
    runs.value = arrayOrEmpty(snapshot.runs)
    batches.value = arrayOrEmpty(snapshot.batches)
    runRows.value = arrayOrEmpty(snapshot.runRows)
    filteredRunRows.value = arrayOrEmpty(snapshot.filteredRunRows || snapshot.runRows)
    visibleRunRows.value = arrayOrEmpty(snapshot.visibleRunRows || snapshot.filteredRunRows || snapshot.runRows)
    runPagination.value = recordOrEmpty(snapshot.runPagination)
    runLoadingMore.value = Boolean(snapshot.runLoadingMore)
    runHasMore.value = Boolean(snapshot.runHasMore)
    runFilter.value = String(snapshot.runFilter || '')
    versionsByRole.value = recordOrEmpty(snapshot.versionsByRole)
    leaderboardsByRole.value = recordOrEmpty(snapshot.leaderboardsByRole)
    loading.value = Boolean(snapshot.loading)
    actionLoading.value = String(snapshot.actionLoading || '')
    error.value = String(snapshot.error || '')
    notice.value = recordOrEmpty(snapshot.notice) as EvolutionNotice
    if ('activeTab' in snapshot) setActiveTab(String(snapshot.activeTab || 'console'))
    selectedRoleLabel.value = String(snapshot.selectedRoleLabel || '')
    selectedVersion.value = snapshot.selectedVersion || null
    selectedVersionId.value = String(snapshot.selectedVersionId || '')
    selectedVersionDetail.value = recordOrEmpty(snapshot.selectedVersionDetail)
    evolutionDeepLinkTarget.value = snapshot.evolutionDeepLinkTarget || null
    trustBundleDrawerOpen.value = Boolean(snapshot.trustBundleDrawerOpen)
    trustBundleAudit.value = recordOrEmpty(snapshot.trustBundleAudit)
    trustBundleAuditLoading.value = Boolean(snapshot.trustBundleAuditLoading)
    trustBundleAuditError.value = String(snapshot.trustBundleAuditError || '')
    selectedRoleLeaderboard.value = arrayOrEmpty(snapshot.selectedRoleLeaderboard)
    selectedRunSummary.value = snapshot.selectedRunSummary || null
    selectedDiff.value = arrayOrEmpty(snapshot.selectedDiff)
    selectedDiffData.value = snapshot.selectedDiffData || null
    selectedProposalReview.value = snapshot.selectedProposalReview || null
    selectedProposalRows.value = arrayOrEmpty(snapshot.selectedProposalRows)
    selectedGames.value = recordOrEmpty(snapshot.selectedGames)
    sampleBuckets.value = arrayOrEmpty(snapshot.sampleBuckets)
    selectedGameBucket.value = String(snapshot.selectedGameBucket || 'training')
    selectedGameId.value = String(snapshot.selectedGameId || '')
    selectedGameRows.value = arrayOrEmpty(snapshot.selectedGameRows)
    selectedSampleGame.value = snapshot.selectedSampleGame || null
    selectedSampleHistoryGameId.value = String(snapshot.selectedSampleHistoryGameId || '')
    filteredSampleGameRows.value = arrayOrEmpty(snapshot.filteredSampleGameRows)
    visibleSampleGameRows.value = arrayOrEmpty(snapshot.visibleSampleGameRows)
    sampleGamePagination.value = recordOrEmpty(snapshot.sampleGamePagination)
    selectedSamplePagination.value = recordOrEmpty(snapshot.selectedSamplePagination)
    sampleGameHasMore.value = Boolean(snapshot.sampleGameHasMore)
    sampleGameLoadingMore.value = Boolean(snapshot.sampleGameLoadingMore)
    sampleGameFilter.value = String(snapshot.sampleGameFilter || '')
    selectedGameDetail.value = recordOrEmpty(snapshot.selectedGameDetail)
    selectedSampleState.value = recordOrEmpty(snapshot.selectedSampleState)
    selectedSampleBucketError.value = String(snapshot.selectedSampleBucketError || '')
    selectedSampleHistoryUnavailableReason.value = String(snapshot.selectedSampleHistoryUnavailableReason || '')
    selectedBatchRoles.value = arrayOrEmpty(snapshot.selectedBatchRoles)
    eventLog.value = arrayOrEmpty(snapshot.eventLog)
    form.value = recordOrEmpty(snapshot.form)
    selectedCanPromote.value = Boolean(snapshot.selectedCanPromote)
    selectedPromoteDisabledReason.value = String(snapshot.selectedPromoteDisabledReason || '')
    selectedCanReject.value = Boolean(snapshot.selectedCanReject)
    selectedRejectDisabledReason.value = String(snapshot.selectedRejectDisabledReason || '')
    selectedCanTerminate.value = Boolean(snapshot.selectedCanTerminate)
    selectedTerminateDisabledReason.value = String(snapshot.selectedTerminateDisabledReason || '')
    selectedRollbackDisabledReason.value = String(snapshot.selectedRollbackDisabledReason || '')
    baselinePromoteTrustDisabledReason.value = String(snapshot.baselinePromoteTrustDisabledReason || '')

    if ('selectedRole' in snapshot) selectedRole.value = String(snapshot.selectedRole || '')
    if ('selectedRunId' in snapshot) selectedRunId.value = String(snapshot.selectedRunId || '')
    if ('selectedRun' in snapshot) {
      selectedRunDetail.value = snapshot.selectedRun || null
      if (selectedRunDetail.value && !selectedRunId.value) selectedRunId.value = runIdentity(selectedRunDetail.value)
    }
  }

  function bindRuntimeActions(actions: EvolutionRuntimeActions = {}) {
    runtimeActions.value = { ...actions }
  }

  function clearRuntimeActions() {
    runtimeActions.value = {}
  }

  function hasRuntimeAction(action: keyof EvolutionRuntimeActions): boolean {
    return typeof runtimeActions.value[action] === 'function'
  }

  function runRuntimeAction(action: string, ...args: unknown[]): unknown {
    return runtimeMethod(runtimeActions.value, action)?.(...args)
  }

  function refreshAll() {
    return runRuntimeAction('refreshAll')
  }

  function selectRole(role: string) {
    const nextRole = String(role || '')
    if (!nextRole) return undefined
    selectedRole.value = nextRole
    return runRuntimeAction('selectRole', nextRole)
  }

  function selectRun(id: string) {
    const nextId = String(id || '')
    if (!nextId) return undefined
    selectedRunId.value = nextId
    selectedRunDetail.value =
      runRows.value.find((run) => runIdentity(run) === nextId) ||
      runs.value.find((run) => runIdentity(run) === nextId) ||
      null
    return runRuntimeAction('selectRun', nextId)
  }

  function setRunFilter(value: string): void {
    runFilter.value = String(value || '')
  }

  function setSampleGameFilter(value: string): void {
    sampleGameFilter.value = String(value || '')
  }

  return {
    activeTab,
    roles,
    roleRows,
    runs,
    batches,
    runRows,
    filteredRunRows,
    visibleRunRows,
    runPagination,
    runLoadingMore,
    runHasMore,
    runFilter,
    versionsByRole,
    leaderboardsByRole,
    selectedRole,
    selectedRoleLabel,
    selectedVersion,
    selectedVersionId,
    selectedVersionDetail,
    evolutionDeepLinkTarget,
    trustBundleDrawerOpen,
    trustBundleAudit,
    trustBundleAuditLoading,
    trustBundleAuditError,
    selectedRoleLeaderboard,
    selectedRunId,
    selectedRunDetail,
    selectedRunSummary,
    selectedDiff,
    selectedDiffData,
    selectedProposalReview,
    selectedProposalRows,
    selectedGames,
    sampleBuckets,
    selectedGameBucket,
    selectedGameId,
    selectedGameRows,
    selectedSampleGame,
    selectedSampleHistoryGameId,
    filteredSampleGameRows,
    visibleSampleGameRows,
    sampleGamePagination,
    selectedSamplePagination,
    sampleGameHasMore,
    sampleGameLoadingMore,
    sampleGameFilter,
    selectedGameDetail,
    selectedSampleState,
    selectedSampleBucketError,
    selectedSampleHistoryUnavailableReason,
    selectedBatchRoles,
    eventLog,
    form,
    loading,
    actionLoading,
    error,
    notice,
    selectedCanPromote,
    selectedPromoteDisabledReason,
    selectedCanReject,
    selectedRejectDisabledReason,
    selectedCanTerminate,
    selectedTerminateDisabledReason,
    selectedRollbackDisabledReason,
    baselinePromoteTrustDisabledReason,
    selectedRun,
    selectedRoleVersions,
    selectedIsBatch,
    selectedIsRun,
    hasSelection,
    hasRuntimeActions,
    setActiveTab,
    setRunFilter,
    setSampleGameFilter,
    hydrateFromWorkbench,
    bindRuntimeActions,
    clearRuntimeActions,
    runRuntimeAction,
    hasRuntimeAction,
    refreshAll,
    selectRole,
    selectRun,
    loadMoreRuns: (...args: unknown[]) => runRuntimeAction('loadMoreRuns', ...args),
    startSingle: (...args: unknown[]) => runRuntimeAction('startSingle', ...args),
    startBatch: (...args: unknown[]) => runRuntimeAction('startBatch', ...args),
    runAction: (...args: unknown[]) => runRuntimeAction('runAction', ...args),
    loadProposalReview: (...args: unknown[]) => runRuntimeAction('loadProposalReview', ...args),
    consumeEvolutionDeepLink: (...args: unknown[]) => runRuntimeAction('consumeEvolutionDeepLink', ...args),
    applyEvolutionDeepLink: (...args: unknown[]) => runRuntimeAction('applyEvolutionDeepLink', ...args),
    acceptProposal: (...args: unknown[]) => runRuntimeAction('acceptProposal', ...args),
    rejectProposal: (...args: unknown[]) => runRuntimeAction('rejectProposal', ...args),
    applyAcceptedProposals: (...args: unknown[]) => runRuntimeAction('applyAcceptedProposals', ...args),
    rollback: (...args: unknown[]) => runRuntimeAction('rollback', ...args),
    selectSampleGame: (...args: unknown[]) => runRuntimeAction('selectSampleGame', ...args),
    loadMoreSampleGames: (...args: unknown[]) => runRuntimeAction('loadMoreSampleGames', ...args),
    loadSampleGameDetail: (...args: unknown[]) => runRuntimeAction('loadSampleGameDetail', ...args),
    loadVersionDetail: (...args: unknown[]) => runRuntimeAction('loadVersionDetail', ...args),
    openTrustBundleDrawer: (...args: unknown[]) => runRuntimeAction('openTrustBundleDrawer', ...args),
    refreshTrustBundleAudit: (...args: unknown[]) => runRuntimeAction('refreshTrustBundleAudit', ...args),
    closeTrustBundleDrawer: (...args: unknown[]) => runRuntimeAction('closeTrustBundleDrawer', ...args),
    toggleBatchRole: (...args: unknown[]) => runRuntimeAction('toggleBatchRole', ...args)
  }
})
