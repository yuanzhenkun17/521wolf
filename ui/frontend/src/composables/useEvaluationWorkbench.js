import { computed, onBeforeUnmount, ref } from 'vue'
import { createGameApi } from './gameApi.js'
import { createLatestOnlyMap, createLatestOnlyTracker } from './latestOnly.js'
import { createResumableEventSource } from './resumableEventSource.js'
import {
  isBenchmarkBatch,
  normalizeLeaderboardEntry,
  pct,
  roleMeta,
  shortId,
  statusText
} from './workbenchShared.js'

const BENCHMARK_TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'interrupted'])
const BENCHMARK_ACTIVE_STATUSES = new Set(['queued', 'running', 'rate_limited'])

function normalizeBatchRun(run) {
  const id = run?.run_id || run?.batch_id || ''
  const roleKeys = Array.isArray(run?.roles) && run.roles.length
    ? run.roles
    : (run?.role ? [run.role] : [])
  const roleNames = roleKeys.length
    ? roleKeys.map((role) => roleMeta(role).label).join('、')
    : '未知角色'
  return {
    ...run,
    id,
    roleKeys,
    displayRole: roleNames,
    statusLabel: statusText(run?.status),
    isActive: BENCHMARK_ACTIVE_STATUSES.has(run?.status),
    isTerminal: BENCHMARK_TERMINAL_STATUSES.has(run?.status)
  }
}

function upsertBatchRun(runs, patch) {
  const id = patch?.batch_id || patch?.run_id || ''
  if (!id) return runs
  const next = [...runs]
  const index = next.findIndex((run) => (run?.batch_id || run?.run_id) === id)
  if (index >= 0) {
    next[index] = { ...next[index], ...patch }
  } else {
    next.unshift(patch)
  }
  return next
}

function useEvaluationWorkbench(options = {}) {
  const { apiFetch, apiBase } = options.apiFetch
    ? { apiFetch: options.apiFetch, apiBase: options.apiBase || '/api' }
    : createGameApi(options.apiBase)

  const roles = ref([])
  const modelLeaderboard = ref({})
  const roleLeaderboard = ref({})
  const batchRuns = ref([])
  const selectedRole = ref('')
  const error = ref('')
  const loading = ref(false)
  const actionLoading = ref('')
  const benchmarkEvents = ref([])
  const roleRequests = createLatestOnlyTracker()
  const roleBoardRequests = createLatestOnlyMap()
  const runRequests = createLatestOnlyTracker()
  const refreshRequests = createLatestOnlyTracker()
  const actionRequests = createLatestOnlyTracker()

  const form = ref({
    battle_games: 10,
    max_days: 5
  })

  const roleRows = computed(() => roles.value.map((role) => {
    const meta = roleMeta(role)
    return {
      key: role,
      role,
      label: meta.label,
      image: meta.image
    }
  }))

  const modelLeaderboardRows = computed(() => modelLeaderboard.value[selectedRole.value] || [])
  const roleLeaderboardRows = computed(() => roleLeaderboard.value[selectedRole.value] || [])

  const batchRunRows = computed(() =>
    batchRuns.value.map(normalizeBatchRun).sort((a, b) =>
      String(b.started_at || '').localeCompare(String(a.started_at || ''))
    )
  )

  const filteredBatchRunRows = computed(() => {
    if (!selectedRole.value) return batchRunRows.value
    return batchRunRows.value.filter((run) => run.roleKeys?.includes(selectedRole.value))
  })

  const visibleBatchRunRows = computed(() => filteredBatchRunRows.value.slice(0, 120))

  const selectedRoleLabel = computed(() => roleMeta(selectedRole.value).label)

  async function loadRoles() {
    const token = roleRequests.next()
    const data = await apiFetch('/roles')
    if (!token.isLatest()) return false
    roles.value = data.roles || []
    if (!selectedRole.value && roles.value.length) selectedRole.value = roles.value[0]
    await Promise.all(roles.value.map(async (role) => {
      const roleToken = roleBoardRequests.next(role)
      // The leaderboard endpoint now carries real benchmark scores
      // (benchmark_leaderboard table), keyed by target_version_id.
      let lbEntries = []
      try {
        const lbData = await apiFetch(`/roles/${encodeURIComponent(role)}/leaderboard`)
        if (!token.isLatest() || !roleToken.isLatest()) return
        lbEntries = (lbData.entries || []).map(normalizeLeaderboardEntry)
      } catch {
        lbEntries = []
      }
      if (!token.isLatest() || !roleToken.isLatest()) return
      modelLeaderboard.value = { ...modelLeaderboard.value, [role]: lbEntries }

      // Role-version board: join version metadata (id/source/baseline) with
      // the scored leaderboard entries so versions without scores still show.
      try {
        const rlData = await apiFetch(`/roles/${encodeURIComponent(role)}/versions`)
        if (!token.isLatest() || !roleToken.isLatest()) return
        const versions = rlData.versions || []
        const scoreByVersion = new Map(
          lbEntries
            .filter((e) => e.target_version_id)
            .map((e) => [e.target_version_id, e])
        )
        roleLeaderboard.value = {
          ...roleLeaderboard.value,
          [role]: versions.map((v) => {
            const score = scoreByVersion.get(v.version_id)
            const scoreValue = Number(score?.target_role_role_weighted_score || 0)
            const winRate = Number(score?.target_side_win_rate || 0)
            return {
              version_id: v.version_id,
              short: shortId(v.version_id),
              source: v.source || (v.is_baseline ? 'baseline' : 'version'),
              is_baseline: v.is_baseline || false,
              rankable: Boolean(score?.rankable),
              score: scoreValue,
              scorePct: pct(scoreValue),
              winRate,
              winRatePct: pct(winRate),
              games: Number(score?.game_count || 0)
            }
          })
        }
      } catch {
        if (token.isLatest() && roleToken.isLatest()) {
          roleLeaderboard.value = { ...roleLeaderboard.value, [role]: [] }
        }
      }
    }))
    return token.isLatest()
  }

  async function loadRuns() {
    const token = runRequests.next()
    try {
      const data = await apiFetch('/evolution-runs')
      if (!token.isLatest()) return false
      batchRuns.value = (data.batches || []).filter(isBenchmarkBatch)
      syncBenchmarkEventSources()
      return true
    } catch {
      if (token.isLatest()) {
        batchRuns.value = []
        syncBenchmarkEventSources()
      }
      return false
    }
  }

  async function refreshAll({ silent = false } = {}) {
    const token = refreshRequests.next()
    if (!silent) loading.value = true
    error.value = ''
    try {
      await loadRoles()
      if (!token.isLatest()) return
      await loadRuns()
    } catch (err) {
      if (token.isLatest()) error.value = err?.message || '评测数据读取失败'
    } finally {
      if (token.isLatest()) loading.value = false
    }
  }

  function selectRole(role) {
    if (role) selectedRole.value = role
  }

  function numberField(name, fallback, min = 1) {
    if (form.value[name] === '' || form.value[name] == null) return fallback
    const value = Number(form.value[name])
    return Number.isFinite(value) && value >= min ? Math.floor(value) : fallback
  }

  let abortController = null
  const benchmarkStream = createResumableEventSource({
    events: ['progress', 'completed', 'failed', 'cancelled', 'interrupted', 'ping'],
    makeUrl(batchId, lastEventId) {
      if (!lastEventId) return `${apiBase}/benchmark/batch/${encodeURIComponent(batchId)}/events`
      const base = `${apiBase}/benchmark/batch/${encodeURIComponent(batchId)}/events`
      return `${base}?lastEventId=${encodeURIComponent(lastEventId)}`
    },
    shouldReconnect(batchId) {
      return Boolean(batchRunRows.value.find((run) => run.id === batchId)?.isActive)
    },
    isTerminal(event, payload) {
      return BENCHMARK_TERMINAL_STATUSES.has(event.type) || BENCHMARK_TERMINAL_STATUSES.has(payload?.status)
    },
    async onEvent({ id: batchId, event, payload }) {
      benchmarkEvents.value = [
        { id: `${Date.now()}-${batchId}-${event.type}`, batchId, type: event.type, payload },
        ...benchmarkEvents.value
      ].slice(0, 32)
      if (payload?.batch_id === batchId) {
        batchRuns.value = upsertBatchRun(batchRuns.value, payload)
      }
      if (event.type !== 'ping') {
        await loadRuns()
      }
    }
  })

  function resetBatchEventId(batchId) {
    benchmarkStream.resetEventId(batchId)
  }

  function closeBenchmarkEventSource(batchId) {
    benchmarkStream.close(batchId)
  }

  function closeAllBenchmarkEventSources() {
    benchmarkStream.closeAll()
  }

  function connectBenchmarkEventSource(batchId) {
    if (!batchId || typeof EventSource === 'undefined') return
    if (String(batchId).startsWith('mock-')) return
    benchmarkStream.connect(batchId)
  }

  function syncBenchmarkEventSources() {
    const activeIds = new Set(batchRunRows.value.filter((run) => run.isActive).map((run) => run.id))
    for (const batchId of activeIds) connectBenchmarkEventSource(batchId)
    for (const batchId of benchmarkStream.ids()) {
      if (batchId && !activeIds.has(batchId)) closeBenchmarkEventSource(batchId)
    }
  }

  async function startEvaluation() {
    if (!selectedRole.value) {
      error.value = '请选择一个角色'
      return
    }
    const token = actionRequests.next()
    actionLoading.value = 'start'
    error.value = ''
    const controller = new AbortController()
    abortController = controller
    try {
      const created = await apiFetch('/benchmark', {
        method: 'POST',
        body: JSON.stringify({
          roles: [selectedRole.value],
          battle_games: numberField('battle_games', 10),
          max_days: numberField('max_days', 5)
        }),
        signal: controller.signal
      })
      if (!token.isLatest()) return
      resetBatchEventId(created?.batch_id)
      await refreshAll({ silent: true })
    } catch (err) {
      if (token.isLatest() && err?.name !== 'AbortError') {
        error.value = err?.message || '启动评测失败'
      }
    } finally {
      if (token.isLatest()) {
        actionLoading.value = ''
      }
      if (abortController === controller) {
        abortController = null
      }
    }
  }

  async function stopBatch(batchId) {
    if (!batchId) return
    const token = actionRequests.next()
    actionLoading.value = `stop:${batchId}`
    error.value = ''
    try {
      await apiFetch(`/benchmark/batch/${encodeURIComponent(batchId)}/stop`, { method: 'POST' })
      if (!token.isLatest()) return
      closeBenchmarkEventSource(batchId)
      await refreshAll({ silent: true })
    } catch (err) {
      if (token.isLatest()) error.value = err?.message || '停止评测失败'
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  if (options.installLifecycle !== false) {
    onBeforeUnmount(closeAllBenchmarkEventSources)
  }

  return {
    roles,
    roleMeta,
    roleRows,
    selectedRole,
    selectRole,
    selectedRoleLabel,
    modelLeaderboard,
    modelLeaderboardRows,
    roleLeaderboard,
    roleLeaderboardRows,
    batchRuns,
    benchmarkEvents,
    batchRunRows,
    filteredBatchRunRows,
    visibleBatchRunRows,
    form,
    error,
    loading,
    actionLoading,
    refreshAll,
    startEvaluation,
    stopBatch
  }
}

export { useEvaluationWorkbench }
