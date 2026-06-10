import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { UnknownRecord } from '../types/api'
import type { EvolutionRun, RoleVersion } from '../types/evolution'

type EvolutionNotice = {
  type?: string
  message?: string
  [key: string]: unknown
}

type EvolutionRuntimeActions = {
  refreshAll?: () => unknown
  selectRole?: (role: string) => unknown
  selectRun?: (id: string) => unknown
}

type EvolutionRunLike = Partial<EvolutionRun> & UnknownRecord

type EvolutionWorkbenchSnapshot = {
  loading?: boolean
  error?: string
  notice?: EvolutionNotice | null
  roles?: string[]
  roleRows?: UnknownRecord[]
  runs?: EvolutionRun[]
  runRows?: EvolutionRun[]
  versionsByRole?: Record<string, RoleVersion[]>
  selectedRole?: string
  selectedRunId?: string
  selectedRun?: EvolutionRunLike | null
  selectedRunSummary?: UnknownRecord | null
  selectedProposalReview?: UnknownRecord | null
  selectedGames?: UnknownRecord
  selectedCanPromote?: boolean
  selectedPromoteDisabledReason?: string
  selectedCanReject?: boolean
  selectedRejectDisabledReason?: string
  selectedCanTerminate?: boolean
  selectedTerminateDisabledReason?: string
  selectedRollbackDisabledReason?: string
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

export const useEvolutionStore = defineStore('evolution', () => {
  const roles = ref<string[]>([])
  const roleRows = ref<UnknownRecord[]>([])
  const runs = ref<EvolutionRun[]>([])
  const runRows = ref<EvolutionRun[]>([])
  const versionsByRole = ref<Record<string, RoleVersion[]>>({})
  const selectedRole = ref('')
  const selectedRunId = ref('')
  const selectedRunDetail = ref<EvolutionRunLike | null>(null)
  const selectedRunSummary = ref<UnknownRecord | null>(null)
  const selectedProposalReview = ref<UnknownRecord | null>(null)
  const selectedGames = ref<UnknownRecord>({})
  const loading = ref(false)
  const error = ref('')
  const notice = ref<EvolutionNotice>({ type: '', message: '' })
  const selectedCanPromote = ref(false)
  const selectedPromoteDisabledReason = ref('')
  const selectedCanReject = ref(false)
  const selectedRejectDisabledReason = ref('')
  const selectedCanTerminate = ref(false)
  const selectedTerminateDisabledReason = ref('')
  const selectedRollbackDisabledReason = ref('')
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

  function hydrateFromWorkbench(snapshot: EvolutionWorkbenchSnapshot = {}) {
    roles.value = arrayOrEmpty(snapshot.roles)
    roleRows.value = arrayOrEmpty(snapshot.roleRows)
    runs.value = arrayOrEmpty(snapshot.runs)
    runRows.value = arrayOrEmpty(snapshot.runRows)
    versionsByRole.value = recordOrEmpty(snapshot.versionsByRole)
    loading.value = Boolean(snapshot.loading)
    error.value = String(snapshot.error || '')
    notice.value = recordOrEmpty(snapshot.notice) as EvolutionNotice
    selectedRunSummary.value = snapshot.selectedRunSummary || null
    selectedProposalReview.value = snapshot.selectedProposalReview || null
    selectedGames.value = recordOrEmpty(snapshot.selectedGames)
    selectedCanPromote.value = Boolean(snapshot.selectedCanPromote)
    selectedPromoteDisabledReason.value = String(snapshot.selectedPromoteDisabledReason || '')
    selectedCanReject.value = Boolean(snapshot.selectedCanReject)
    selectedRejectDisabledReason.value = String(snapshot.selectedRejectDisabledReason || '')
    selectedCanTerminate.value = Boolean(snapshot.selectedCanTerminate)
    selectedTerminateDisabledReason.value = String(snapshot.selectedTerminateDisabledReason || '')
    selectedRollbackDisabledReason.value = String(snapshot.selectedRollbackDisabledReason || '')

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

  function refreshAll() {
    return runtimeActions.value.refreshAll?.()
  }

  function selectRole(role: string) {
    const nextRole = String(role || '')
    if (!nextRole) return undefined
    selectedRole.value = nextRole
    return runtimeActions.value.selectRole?.(nextRole)
  }

  function selectRun(id: string) {
    const nextId = String(id || '')
    if (!nextId) return undefined
    selectedRunId.value = nextId
    selectedRunDetail.value =
      runRows.value.find((run) => runIdentity(run) === nextId) ||
      runs.value.find((run) => runIdentity(run) === nextId) ||
      null
    return runtimeActions.value.selectRun?.(nextId)
  }

  return {
    roles,
    roleRows,
    runs,
    runRows,
    versionsByRole,
    selectedRole,
    selectedRunId,
    selectedRunDetail,
    selectedRunSummary,
    selectedProposalReview,
    selectedGames,
    loading,
    error,
    notice,
    selectedCanPromote,
    selectedPromoteDisabledReason,
    selectedCanReject,
    selectedRejectDisabledReason,
    selectedCanTerminate,
    selectedTerminateDisabledReason,
    selectedRollbackDisabledReason,
    selectedRun,
    selectedRoleVersions,
    selectedIsBatch,
    selectedIsRun,
    hasSelection,
    hasRuntimeActions,
    hydrateFromWorkbench,
    bindRuntimeActions,
    clearRuntimeActions,
    hasRuntimeAction,
    refreshAll,
    selectRole,
    selectRun
  }
})
