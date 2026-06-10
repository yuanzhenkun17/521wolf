import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { BenchmarkRun, BenchmarkSuite } from '../types/benchmark'

type BenchmarkNotice = {
  type?: string
  message?: string
  [key: string]: unknown
}

type BenchmarkRuntimeActions = {
  refreshAll?: (...args: unknown[]) => unknown
  selectBenchmarkBatch?: (batchId: string) => unknown
}

type BenchmarkRunLike = Partial<BenchmarkRun> & Record<string, any>

type BenchmarkWorkbenchSnapshot = {
  suites?: BenchmarkSuite[]
  runs?: BenchmarkRunLike[]
  runRows?: BenchmarkRunLike[]
  selectedBenchmarkId?: string
  selectedBenchmarkBatchId?: string
  selectedBatchId?: string
  selectedBenchmarkBatchRun?: BenchmarkRunLike | null
  loading?: boolean
  actionLoading?: string
  error?: string
  notice?: BenchmarkNotice | null
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

export const useBenchmarkStore = defineStore('benchmark', () => {
  const suites = ref<BenchmarkSuite[]>([])
  const runs = ref<BenchmarkRunLike[]>([])
  const runRows = ref<BenchmarkRunLike[]>([])
  const selectedBenchmarkId = ref('')
  const selectedBatchId = ref('')
  const selectedRunDetail = ref<BenchmarkRunLike | null>(null)
  const activeView = ref('overview')
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
    runs.value = arrayOrEmpty(snapshot.runs)
    runRows.value = arrayOrEmpty(snapshot.runRows || snapshot.runs)
    loading.value = Boolean(snapshot.loading)
    actionLoading.value = String(snapshot.actionLoading || '')
    error.value = String(snapshot.error || '')
    notice.value = noticeOrEmpty(snapshot.notice)

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
    return runtimeActions.value.selectBenchmarkBatch?.(nextId)
  }

  return {
    suites,
    runs,
    runRows,
    selectedBenchmarkId,
    selectedBatchId,
    selectedBenchmarkBatchId: selectedBatchId,
    selectedRunDetail,
    activeView,
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
    hydrateFromWorkbench,
    bindRuntimeActions,
    clearRuntimeActions,
    hasRuntimeAction,
    refreshAll,
    selectBenchmarkBatch
  }
})
