import { computed, onBeforeUnmount, ref } from 'vue'
import { createGameApi } from './gameApi.js'

const ROLE_META = {
  white_wolf_king: { label: '白狼王', image: '/role-badges/white-wolf-king.png' },
  werewolf: { label: '狼人', image: '/role-badges/werewolf.png' },
  villager: { label: '村民', image: '/role-badges/villager.png' },
  seer: { label: '预言家', image: '/role-badges/seer.png' },
  witch: { label: '女巫', image: '/role-badges/witch.png' },
  hunter: { label: '猎人', image: '/role-badges/hunter.png' },
  guard: { label: '守卫', image: '/role-badges/guard.png' }
}

const TERMINAL = new Set(['promoted', 'rejected', 'failed', 'completed'])
const ACTIVE = new Set([
  'queued',
  'running',
  'training',
  'consolidating',
  'applying',
  'battling',
  'combined_battling',
  'rate_limited'
])

function roleMeta(role) {
  return ROLE_META[role] || {
    label: role || '未知角色',
    image: '/role-badges/villager.png'
  }
}

function shortId(value, length = 8) {
  return value ? String(value).slice(0, length) : '—'
}

function pct(value) {
  const n = Number(value || 0)
  return Math.max(0, Math.min(100, Math.round(n * 100)))
}

function statusText(status) {
  return {
    queued: '排队',
    running: '运行中',
    training: '训练',
    consolidating: '归纳',
    applying: '应用',
    battling: '对战',
    combined_battling: '组合对战',
    reviewing: '待评审',
    promoted: '已晋升',
    rejected: '已拒绝',
    failed: '失败',
    completed: '已完成',
    paused: '已暂停',
    rate_limited: '限流重试'
  }[status] || status || '未知'
}

function normalizeRun(run) {
  const id = run?.run_id || run?.batch_id || ''
  const roleNames = run?.roles?.length
    ? run.roles.map((role) => roleMeta(role).label).join(', ')
    : roleMeta(run?.role).label
  return {
    ...run,
    id,
    entityType: run?.batch_id ? 'batch' : 'role',
    displayRole: roleNames,
    statusLabel: statusText(run?.status || run?.stage),
    candidateShort: shortId(run?.candidate_hash),
    parentShort: shortId(run?.parent_hash),
    isReviewing: run?.status === 'reviewing',
    isTerminal: TERMINAL.has(run?.status),
    isActive: ACTIVE.has(run?.status)
  }
}

function normalizeVersion(version) {
  return {
    ...version,
    short: shortId(version.version_id),
    createdLabel: version.created_at ? String(version.created_at).replace('T', ' ').slice(0, 19) : '—'
  }
}

function normalizeLeaderboardEntry(entry) {
  const score = Number(entry.target_role_role_weighted_score || 0)
  const winRate = Number(entry.target_side_win_rate || 0)
  return {
    ...entry,
    short: shortId(entry.hash),
    scorePct: pct(score),
    winRatePct: pct(winRate),
    deltaScore: Number(entry.delta_vs_baseline?.target_role_role_weighted_score || 0),
    fallbackPct: pct(entry.target_role_fallback_rate || 0)
  }
}

function normalizeSampleGame(game, bucket) {
  const id = game?.game_id || game?.id || ''
  return {
    ...game,
    id,
    bucket,
    short: shortId(id, 14),
    phaseLabel: game?.phase || (bucket === 'training' ? 'training' : 'battle'),
    winnerLabel: {
      good: '好人',
      werewolves: '狼人',
      wolf: '狼人',
      village: '好人'
    }[game?.winner] || game?.winner || (game?.in_progress ? '进行中' : '未知'),
    eventCount: Number(game?.event_count || game?.events?.length || 0),
    dayLabel: game?.day ? `D${game.day}` : '—'
  }
}

function useEvolutionWorkbench(options = {}) {
  const { apiFetch, apiBase } = options.apiFetch
    ? { apiFetch: options.apiFetch, apiBase: options.apiBase || '/api' }
    : createGameApi(options.apiBase)

  const loading = ref(false)
  const actionLoading = ref('')
  const error = ref('')
  const roles = ref([])
  const versionsByRole = ref({})
  const leaderboardsByRole = ref({})
  const runs = ref([])
  const batches = ref([])
  const selectedRole = ref('')
  const selectedRunId = ref('')
  const selectedRun = ref(null)
  const selectedDiff = ref([])
  const selectedDiffData = ref(null)
  const selectedGames = ref({ training: [], baseline: [], candidate: [] })
  const selectedGameBucket = ref('training')
  const selectedGameId = ref('')
  const selectedVersionId = ref('')
  const selectedVersionDetail = ref({
    loading: false,
    error: '',
    data: null
  })
  const versionDetailCache = ref({})
  const selectedGameDetail = ref({
    loading: false,
    error: '',
    archive: null,
    decisions: [],
    events: []
  })
  const selectedBatchRoles = ref([])
  const eventLog = ref([])
  const sse = ref(null)
  const runFilter = ref('')
  const sampleGameFilter = ref('')

  const form = ref({
    training_games: 20,
    battle_games: 10,
    role_concurrency: 2,
    game_concurrency: 1,
    llm_concurrency: 5,
    llm_rpm: 60
  })

  const roleRows = computed(() => roles.value.map((role) => {
    const meta = roleMeta(role)
    const versions = versionsByRole.value[role] || []
    const baseline = versions.find((item) => item.is_baseline)
    const leaderboard = leaderboardsByRole.value[role] || []
    const top = leaderboard.find((item) => item.is_baseline) || leaderboard[0]
    return {
      key: role,
      role,
      label: meta.label,
      image: meta.image,
      baseline: baseline?.version_id || '',
      baselineShort: shortId(baseline?.version_id),
      versionCount: versions.length,
      scorePct: top ? top.scorePct : 0,
      winRatePct: top ? top.winRatePct : 0,
      selected: selectedBatchRoles.value.includes(role)
    }
  }))

  const runRows = computed(() => [
    ...runs.value.map(normalizeRun),
    ...batches.value.map(normalizeRun)
  ].sort((a, b) => String(b.started_at || '').localeCompare(String(a.started_at || ''))))
  const filteredRunRows = computed(() => {
    const query = runFilter.value.trim().toLowerCase()
    if (!query) return runRows.value
    return runRows.value.filter((run) =>
      [
        run.id,
        run.role,
        run.displayRole,
        run.status,
        run.statusLabel,
        run.candidate_hash,
        run.parent_hash
      ].some((value) => String(value || '').toLowerCase().includes(query))
    )
  })
  const visibleRunRows = computed(() => filteredRunRows.value.slice(0, 120))

  const selectedRoleVersions = computed(() => versionsByRole.value[selectedRole.value] || [])
  const selectedVersion = computed(() =>
    selectedRoleVersions.value.find((version) => version.version_id === selectedVersionId.value) || null
  )
  const selectedRoleLeaderboard = computed(() => leaderboardsByRole.value[selectedRole.value] || [])
  const selectedRoleLabel = computed(() => roleMeta(selectedRole.value).label)
  const hasSelection = computed(() => Boolean(selectedRun.value))
  const sampleBuckets = computed(() => [
    { key: 'training', label: '训练', count: selectedGames.value.training.length },
    { key: 'baseline', label: '基线', count: selectedGames.value.baseline.length },
    { key: 'candidate', label: '候选', count: selectedGames.value.candidate.length }
  ])
  const selectedGameRows = computed(() =>
    (selectedGames.value[selectedGameBucket.value] || []).map((game) =>
      normalizeSampleGame(game, selectedGameBucket.value)
    )
  )
  const filteredSampleGameRows = computed(() => {
    const query = sampleGameFilter.value.trim().toLowerCase()
    if (!query) return selectedGameRows.value
    return selectedGameRows.value.filter((game) =>
      [
        game.id,
        game.short,
        game.phase,
        game.phaseLabel,
        game.winner,
        game.winnerLabel
      ].some((value) => String(value || '').toLowerCase().includes(query))
    )
  })
  const visibleSampleGameRows = computed(() => filteredSampleGameRows.value.slice(0, 160))

  function setError(message) {
    error.value = message || ''
  }

  function clearVersionDetail() {
    selectedVersionId.value = ''
    selectedVersionDetail.value = { loading: false, error: '', data: null }
  }

  function selectRole(role) {
    if (!role) return
    if (selectedRole.value !== role) clearVersionDetail()
    selectedRole.value = role
  }

  async function loadRoles() {
    const data = await apiFetch('/roles')
    roles.value = data.roles || []
    if (!selectedRole.value && roles.value.length) selectedRole.value = roles.value[0]
    if (!selectedBatchRoles.value.length) selectedBatchRoles.value = roles.value.slice()
    await Promise.all(roles.value.map(async (role) => {
      await Promise.all([loadVersions(role), loadLeaderboard(role)])
    }))
  }

  async function loadVersions(role) {
    if (!role) return
    try {
      const data = await apiFetch(`/roles/${encodeURIComponent(role)}/versions`)
      versionsByRole.value = {
        ...versionsByRole.value,
        [role]: (data.versions || []).map(normalizeVersion)
      }
    } catch {
      versionsByRole.value = { ...versionsByRole.value, [role]: [] }
    }
  }

  async function loadLeaderboard(role) {
    if (!role) return
    try {
      const data = await apiFetch(`/roles/${encodeURIComponent(role)}/leaderboard`)
      leaderboardsByRole.value = {
        ...leaderboardsByRole.value,
        [role]: (data.entries || []).map(normalizeLeaderboardEntry)
      }
    } catch {
      leaderboardsByRole.value = { ...leaderboardsByRole.value, [role]: [] }
    }
  }

  async function loadRuns() {
    const data = await apiFetch('/evolution-runs')
    runs.value = data.runs || []
    batches.value = data.batches || []
    if (!selectedRunId.value && runRows.value.length) {
      await selectRun(runRows.value[0].id)
    } else if (selectedRunId.value) {
      const current = runRows.value.find((item) => item.id === selectedRunId.value)
      if (current) selectedRun.value = current
    }
  }

  async function refreshAll({ silent = false } = {}) {
    if (!silent) loading.value = true
    setError('')
    try {
      await loadRoles()
      await loadRuns()
    } catch (err) {
      setError(err?.message || '自进化数据读取失败')
    } finally {
      loading.value = false
    }
  }

  async function selectRun(id) {
    if (!id) return
    selectedRunId.value = id
    const row = runRows.value.find((item) => item.id === id)
    selectedRun.value = row || normalizeRun(await apiFetch(`/evolution-runs/${encodeURIComponent(id)}`))
    if (selectedRun.value?.role) selectRole(selectedRun.value.role)
    await Promise.all([loadDiff(id), loadRunGames(id)])
    if (selectedRun.value?.isActive || selectedRun.value?.status === 'reviewing') {
      connect(id)
    }
  }

  async function loadDiff(id = selectedRunId.value) {
    if (!id) return
    try {
      const data = await apiFetch(`/evolution-runs/${encodeURIComponent(id)}/diff`)
      // Legacy flat array format
      selectedDiff.value = data.diffs || data.diff || []
      // Full structured KnowledgeDiff object (may coexist with legacy fields)
      if (data.skill_changes || data.patterns_added || data.patterns_removed || data.patterns_updated || data.metrics_delta) {
        selectedDiffData.value = {
          skill_changes: data.skill_changes || [],
          patterns_added: data.patterns_added || [],
          patterns_removed: data.patterns_removed || [],
          patterns_updated: data.patterns_updated || [],
          metrics_delta: data.metrics_delta || null
        }
      } else if (data.diff_data) {
        // Nested diff_data wrapper
        selectedDiffData.value = {
          skill_changes: data.diff_data.skill_changes || [],
          patterns_added: data.diff_data.patterns_added || [],
          patterns_removed: data.diff_data.patterns_removed || [],
          patterns_updated: data.diff_data.patterns_updated || [],
          metrics_delta: data.diff_data.metrics_delta || null
        }
      } else {
        selectedDiffData.value = null
      }
    } catch {
      selectedDiff.value = []
      selectedDiffData.value = null
    }
  }

  async function loadRunGames(id = selectedRunId.value) {
    if (!id) return
    const load = async (query) => {
      try {
        const data = await apiFetch(`/evolution-runs/${encodeURIComponent(id)}/games${query}`)
        return data.games || []
      } catch {
        return []
      }
    }
    const [training, baseline, candidate] = await Promise.all([
      load('?phase=training'),
      load('?phase=battle&side=baseline'),
      load('?phase=battle&side=candidate')
    ])
    selectedGames.value = { training, baseline, candidate }
    const buckets = ['training', 'baseline', 'candidate']
    const currentList = selectedGames.value[selectedGameBucket.value] || []
    const hasCurrent = currentList.some((game) => (game.game_id || game.id) === selectedGameId.value)
    if (!hasCurrent) {
      const nextBucket = buckets.find((bucket) => selectedGames.value[bucket]?.length) || 'training'
      selectedGameBucket.value = nextBucket
      selectedGameId.value = selectedGames.value[nextBucket]?.[0]?.game_id || ''
    }
    if (selectedGameId.value) {
      await loadSampleGameDetail(selectedGameBucket.value, selectedGameId.value)
    } else {
      selectedGameDetail.value = { loading: false, error: '', archive: null, decisions: [], events: [] }
    }
  }

  function sampleGameQuery(bucket = selectedGameBucket.value) {
    if (bucket === 'training') return 'phase=training'
    return `phase=battle&side=${encodeURIComponent(bucket)}`
  }

  async function loadSampleGameDetail(bucket = selectedGameBucket.value, gameId = selectedGameId.value) {
    const runId = selectedRunId.value
    if (!runId || !gameId) return
    selectedGameDetail.value = {
      ...selectedGameDetail.value,
      loading: true,
      error: ''
    }
    const base = `/evolution-runs/${encodeURIComponent(runId)}/games/${encodeURIComponent(gameId)}`
    const query = sampleGameQuery(bucket)
    try {
      const [archive, decisions, events] = await Promise.all([
        apiFetch(`${base}/archive?${query}`).catch(() => null),
        apiFetch(`${base}/decisions?${query}`).catch(() => ({ decisions: [] })),
        apiFetch(`${base}/events?${query}`).catch(() => ({ events: [] }))
      ])
      selectedGameDetail.value = {
        loading: false,
        error: '',
        archive,
        decisions: decisions?.decisions || [],
        events: events?.events || []
      }
    } catch (err) {
      selectedGameDetail.value = {
        loading: false,
        error: err?.message || '样本局详情读取失败',
        archive: null,
        decisions: [],
        events: []
      }
    }
  }

  async function selectSampleGame(bucket, gameId) {
    if (!bucket) return
    selectedGameBucket.value = bucket
    const rows = selectedGames.value[bucket] || []
    selectedGameId.value = gameId || rows[0]?.game_id || rows[0]?.id || ''
    if (selectedGameId.value) {
      await loadSampleGameDetail(bucket, selectedGameId.value)
    } else {
      selectedGameDetail.value = { loading: false, error: '', archive: null, decisions: [], events: [] }
    }
  }

  async function loadVersionDetail(role = selectedRole.value, versionId = selectedVersionId.value) {
    if (!role || !versionId) return
    const key = `${role}:${versionId}`
    selectedVersionId.value = versionId
    if (versionDetailCache.value[key]) {
      selectedVersionDetail.value = {
        loading: false,
        error: '',
        data: versionDetailCache.value[key]
      }
      return
    }
    selectedVersionDetail.value = {
      loading: true,
      error: '',
      data: selectedVersionDetail.value.data?.version_id === versionId ? selectedVersionDetail.value.data : null
    }
    try {
      const data = await apiFetch(`/roles/${encodeURIComponent(role)}/versions/${encodeURIComponent(versionId)}`)
      versionDetailCache.value = {
        ...versionDetailCache.value,
        [key]: data
      }
      selectedVersionDetail.value = { loading: false, error: '', data }
    } catch (err) {
      selectedVersionDetail.value = {
        loading: false,
        error: err?.message || '版本详情读取失败',
        data: null
      }
    }
  }

  let retryDelay = 1000
  const maxRetryDelay = 30000

  function connect(id) {
    if (!id || typeof EventSource === 'undefined') return
    if (String(id).startsWith('mock-')) return
    sse.value?.close?.()
    const source = new EventSource(`${apiBase}/evolution-runs/${encodeURIComponent(id)}/events`)
    sse.value = source

    const handle = async (event) => {
      retryDelay = 1000  // reset backoff on successful event
      let payload = {}
      try { payload = JSON.parse(event.data || '{}') } catch {}
      eventLog.value = [
        { id: `${Date.now()}-${event.type}`, type: event.type, payload },
        ...eventLog.value
      ].slice(0, 24)
      await loadRuns()
      if (selectedRunId.value === id) {
        const current = runRows.value.find((item) => item.id === id)
        if (current) selectedRun.value = current
        await Promise.all([loadDiff(id), loadRunGames(id)])
      }
      if (['promoted', 'rejected', 'failed'].includes(event.type)) {
        source.close()
      }
    }

    ;['progress', 'reviewing', 'promoted', 'rejected', 'failed'].forEach((name) => {
      source.addEventListener(name, handle)
    })

    source.addEventListener('error', () => {
      source.close()
      if (sse.value === source) sse.value = null
      // auto-reconnect with exponential backoff
      setTimeout(() => {
        if (selectedRunId.value === id) {  // user still viewing this run
          retryDelay = Math.min(retryDelay * 2, maxRetryDelay)
          connect(id)
        }
      }, retryDelay)
    })
  }

  function toggleBatchRole(role) {
    const current = selectedBatchRoles.value
    selectedBatchRoles.value = current.includes(role)
      ? current.filter((item) => item !== role)
      : [...current, role]
  }

  function numberField(name, fallback) {
    const value = Number(form.value[name])
    return Number.isFinite(value) && value > 0 ? value : fallback
  }

  async function startSingle() {
    if (!selectedRole.value) {
      setError('请选择一个有 baseline 的角色')
      return
    }
    actionLoading.value = 'start-single'
    setError('')
    try {
      const created = await apiFetch('/evolution-runs', {
        method: 'POST',
        body: JSON.stringify({
          roles: [selectedRole.value],
          training_games: numberField('training_games', 20),
          battle_games: numberField('battle_games', 10),
          game_concurrency: numberField('game_concurrency', 1),
          llm_concurrency: numberField('llm_concurrency', 5),
          llm_rpm: numberField('llm_rpm', 60)
        })
      })
      await loadRuns()
      await selectRun(created.run_id || created.batch_id)
    } catch (err) {
      setError(err?.message || '启动单角色进化失败')
    } finally {
      actionLoading.value = ''
    }
  }

  async function startBatch() {
    if (!selectedBatchRoles.value.length) {
      setError('请选择至少一个角色')
      return
    }
    actionLoading.value = 'start-batch'
    setError('')
    try {
      const created = await apiFetch('/evolution-runs', {
        method: 'POST',
        body: JSON.stringify({
          roles: selectedBatchRoles.value,
          role_concurrency: numberField('role_concurrency', 2),
          training_games: numberField('training_games', 20),
          battle_games: numberField('battle_games', 10),
          game_concurrency: numberField('game_concurrency', 1),
          llm_concurrency: numberField('llm_concurrency', 5),
          llm_rpm: numberField('llm_rpm', 60)
        })
      })
      await loadRuns()
      await selectRun(created.batch_id || created.run_id)
    } catch (err) {
      setError(err?.message || '启动批量进化失败')
    } finally {
      actionLoading.value = ''
    }
  }

  async function runAction(id, action) {
    if (!id || !action) return
    actionLoading.value = `${action}:${id}`
    setError('')
    try {
      const result = await apiFetch(`/evolution-runs/${encodeURIComponent(id)}/actions`, {
        method: 'POST',
        body: JSON.stringify({ action })
      })
      await loadRuns()
      await selectRun(result.run_id || result.batch_id || id)
      await loadRoles()
    } catch (err) {
      setError(err?.message || '操作失败')
    } finally {
      actionLoading.value = ''
    }
  }

  async function rollback(role, versionId) {
    if (!role || !versionId) return
    actionLoading.value = `rollback:${role}:${versionId}`
    setError('')
    try {
      await apiFetch(`/roles/${encodeURIComponent(role)}/rollback/${encodeURIComponent(versionId)}`, {
        method: 'POST'
      })
      await Promise.all([loadVersions(role), loadLeaderboard(role), loadRuns()])
    } catch (err) {
      setError(err?.message || '回滚 baseline 失败')
    } finally {
      actionLoading.value = ''
    }
  }

  onBeforeUnmount(() => {
    sse.value?.close?.()
  })

  return {
    loading,
    actionLoading,
    error,
    roles,
    roleRows,
    versionsByRole,
    leaderboardsByRole,
    runs,
    batches,
    runRows,
    filteredRunRows,
    visibleRunRows,
    runFilter,
    selectedRole,
    selectRole,
    selectedRoleLabel,
    selectedRoleVersions,
    selectedVersion,
    selectedVersionId,
    selectedVersionDetail,
    selectedRoleLeaderboard,
    selectedRunId,
    selectedRun,
    selectedDiff,
    selectedDiffData,
    selectedGames,
    sampleBuckets,
    selectedGameBucket,
    selectedGameId,
    selectedGameRows,
    filteredSampleGameRows,
    visibleSampleGameRows,
    sampleGameFilter,
    selectedGameDetail,
    selectedBatchRoles,
    eventLog,
    form,
    hasSelection,
    refreshAll,
    selectRun,
    startSingle,
    startBatch,
    runAction,
    rollback,
    selectSampleGame,
    loadSampleGameDetail,
    loadVersionDetail,
    toggleBatchRole,
    shortId,
    statusText,
    roleMeta
  }
}

export { useEvolutionWorkbench, statusText, shortId, roleMeta }
