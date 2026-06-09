import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { createGameApi } from './gameApi.js'
import { createLatestOnlyMap, createLatestOnlyTracker } from './latestOnly.js'
import { createNoticeAutoDismiss } from './noticeAutoDismiss.js'
import { createResumableEventSource } from './resumableEventSource.js'
import {
  isBenchmarkBatch,
  normalizeLeaderboardEntry,
  pct,
  roleMeta,
  shortId,
  sourceText,
  statusText
} from './workbenchShared.js'

const BENCHMARK_TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'interrupted'])
const BENCHMARK_ACTIVE_STATUSES = new Set(['queued', 'running', 'rate_limited'])
const MODEL_LEADERBOARD_KEY = '__model__'
const BENCHMARK_TARGET_BLOCKED_RELEASE_STAGES = new Set(['shadow'])
const BENCHMARK_FORMAL_BLOCKED_RELEASE_STAGES = new Set(['shadow', 'canary'])

const DIAGNOSTIC_LEVEL_LABELS = {
  error: '错误',
  warning: '警告',
  info: '信息'
}

const DIAGNOSTIC_KIND_LABELS = {
  rankable_failed: '未入榜',
  fairness_failed: '公平性',
  leaderboard_gate_failed: '门禁失败',
  decision_judge_degraded: 'Judge 降级',
  game_failure: '失败局',
  game_error: '对局错误',
  result_warning: '结果警告',
  result_error: '结果错误',
  benchmark_error: '批次错误',
  timeout: '超时'
}

function normalizeBenchmarkTargetType(value) {
  const raw = String(value || '').trim().toLowerCase()
  return raw === 'model' ? 'model' : 'role_version'
}

function normalizeSeedPreview(raw) {
  const candidates = [
    raw?.seed_preview,
    raw?.seedPreview,
    raw?.seed_set?.seed_preview,
    raw?.seed_registry?.seed_preview,
    raw?.seed_registry_summary?.seed_preview,
    raw?.seeds,
    raw?.seed_set?.seeds,
    raw?.seed_registry?.seeds
  ]
  const arrayValue = candidates.find((value) => Array.isArray(value))
  if (arrayValue) {
    return arrayValue.map((seed) => String(seed ?? '').trim()).filter(Boolean).slice(0, 6)
  }
  const stringValue = candidates.find((value) => typeof value === 'string')
  if (stringValue) {
    return stringValue.split(/[,\s]+/).map((seed) => seed.trim()).filter(Boolean).slice(0, 6)
  }
  return []
}

function normalizeSeedCount(raw, seedPreview) {
  const candidates = [
    raw?.seed_count,
    raw?.seedCount,
    raw?.seed_set?.seed_count,
    raw?.seed_set?.count,
    raw?.seed_registry?.seed_count,
    raw?.seed_registry?.count,
    raw?.seed_registry_summary?.seed_count,
    raw?.seed_registry_summary?.count
  ]
  const value = candidates.map(Number).find((item) => Number.isFinite(item) && item >= 0)
  if (value != null) return Math.floor(value)
  return Array.isArray(seedPreview) && seedPreview.length ? seedPreview.length : null
}

function normalizeCostTier(raw) {
  return String(
    raw?.cost_tier ??
    raw?.costTier ??
    raw?.cost?.tier ??
    raw?.metadata?.cost_tier ??
    ''
  ).trim().toLowerCase()
}

function normalizeBenchmarkSuite(raw) {
  const id = String(raw?.id || raw?.benchmark_id || '').trim()
  if (!id) return null
  const version = raw?.version == null ? null : Number(raw.version)
  const versionIsValid = Number.isFinite(version)
  const roles = Array.isArray(raw?.roles)
    ? raw.roles.map((role) => String(role || '').trim()).filter(Boolean)
    : []
  const gameCount = raw?.game_count ?? raw?.battle_games ?? raw?.games ?? null
  const maxDays = raw?.max_days ?? null
  const name = String(raw?.name || raw?.label || id)
  const evaluationSetId = String(raw?.evaluation_set_id || (versionIsValid ? `${id}@v${version}` : ''))
  const seedPreview = normalizeSeedPreview(raw)
  const seedCount = normalizeSeedCount(raw, seedPreview)
  return {
    ...raw,
    id,
    version: versionIsValid ? version : null,
    name,
    label: versionIsValid ? `${name} v${version}` : name,
    description: String(raw?.description || ''),
    target_type: normalizeBenchmarkTargetType(raw?.target_type || raw?.scope),
    roles,
    game_count: gameCount == null ? null : Number(gameCount),
    max_days: maxDays == null ? null : Number(maxDays),
    seed_set_id: String(raw?.seed_set_id || ''),
    seed_count: seedCount,
    seed_preview: seedPreview,
    cost_tier: normalizeCostTier(raw),
    evaluation_set_id: evaluationSetId
  }
}

function benchmarkErrorMessage(err, fallback) {
  const raw = String(err?.message || err || '').trim()
  const text = raw.toLowerCase()
  if (!raw) return fallback
  if (text.includes('batch not found')) return '评测批次不存在，已刷新列表。'
  if (text.includes('benchmark failed')) return '评测执行失败，请查看评测记录。'
  if (text.includes('invalid config') || text.includes('invalid benchmark config')) return '评测配置无效，请检查局数和天数。'
  if (text.includes('role not found')) return '角色不存在，请刷新后重试。'
  if (text.includes('rate limit') || text.includes('rate_limited')) return '评测请求被限流，请稍后重试。'
  return raw || fallback
}

function normalizeModelLeaderboardEntry(entry) {
  const score = Number(entry?.strength_score ?? entry?.avg_role_score ?? entry?.target_role_role_weighted_score ?? 0)
  const winRate = Number(entry?.target_side_win_rate ?? entry?.summary?.target_side_win_rate ?? entry?.summary?.win_rate ?? 0)
  return normalizeLeaderboardEntry({
    ...entry,
    hash: entry?.hash || entry?.subject_id || entry?.model_config_hash || entry?.model_id || '',
    target_role_role_weighted_score: score,
    target_side_win_rate: winRate
  })
}

function normalizeBenchmarkRoleVersionReleaseStage(version) {
  return String(
    version?.releaseStage ||
    version?.release_stage ||
    version?.provenance?.releaseStage ||
    version?.provenance?.release_stage ||
    ''
  ).trim().toLowerCase()
}

function benchmarkTargetVersionDisabledReason(version) {
  const releaseStage = normalizeBenchmarkRoleVersionReleaseStage(version)
  if (BENCHMARK_TARGET_BLOCKED_RELEASE_STAGES.has(releaseStage)) {
    return 'Shadow 版本需先晋升 canary 后才能评测。'
  }
  return ''
}

function objectOrEmpty(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function leaderboardVersionKey(entry) {
  return String(entry?.target_version_id || entry?.version_id || entry?.hash || entry?.subject_id || '').trim()
}

function normalizeBenchmarkRoleVersion(version, score = null) {
  const versionId = String(version?.version_id || version?.target_version_id || version?.hash || '').trim()
  const releaseStage = normalizeBenchmarkRoleVersionReleaseStage(version) || normalizeBenchmarkRoleVersionReleaseStage(score)
  const provenance = objectOrEmpty(version?.provenance || score?.provenance)
  const metrics = {
    ...objectOrEmpty(version?.metrics),
    ...objectOrEmpty(score?.metrics)
  }
  const scoreValue = metricNumber(
    score?.target_role_role_weighted_score ??
    score?.avg_role_score ??
    metrics.score ??
    metrics.avg_role_score
  )
  const winRate = metricNumber(
    score?.target_side_win_rate ??
    score?.summary?.target_side_win_rate ??
    score?.summary?.win_rate ??
    metrics.win_rate
  )
  const games = metricNumber(
    score?.game_count ??
    score?.games_played ??
    score?.total_games ??
    metrics.games_played
  )
  const targetDisabledReason = benchmarkTargetVersionDisabledReason({
    ...version,
    release_stage: releaseStage,
    provenance
  })
  return {
    ...version,
    version_id: versionId,
    target_version_id: versionId,
    hash: versionId,
    short: shortId(versionId),
    source: version?.source || provenance.source || (version?.is_baseline ? 'baseline' : 'version'),
    is_baseline: Boolean(version?.is_baseline),
    status: String(version?.status ?? score?.status ?? '').trim(),
    release_stage: releaseStage,
    releaseStage,
    releaseStageLabel: releaseStage ? sourceText(releaseStage) : '未标记',
    provenance,
    metrics,
    rankable: score?.rankable == null ? false : score.rankable !== false,
    rankable_reason: String(score?.rankable_reason || score?.reason || score?.gate_reason || '').trim(),
    score: scoreValue,
    scorePct: pct(scoreValue),
    winRate,
    winRatePct: pct(winRate),
    games,
    game_count: games,
    target_role_role_weighted_score: scoreValue,
    target_side_win_rate: winRate,
    targetDisabled: Boolean(targetDisabledReason),
    targetDisabledReason
  }
}

function normalizeBenchmarkRoleVersions(versions = [], leaderboardEntries = []) {
  const scoreByVersion = new Map(
    leaderboardEntries
      .map((entry) => [leaderboardVersionKey(entry), entry])
      .filter(([versionId]) => versionId)
  )
  return versions.map((version) =>
    normalizeBenchmarkRoleVersion(version, scoreByVersion.get(String(version?.version_id || '').trim()))
  )
}

function normalizeBenchmarkRoleLeaderboardRows(leaderboardEntries = [], versions = []) {
  const versionById = new Map(
    versions
      .map((version) => [String(version?.version_id || '').trim(), version])
      .filter(([versionId]) => versionId)
  )
  return leaderboardEntries
    .map((entry) => {
      const versionId = leaderboardVersionKey(entry)
      return normalizeBenchmarkRoleVersion(versionById.get(versionId) || { ...entry, version_id: versionId }, entry)
    })
    .filter((row) => !BENCHMARK_FORMAL_BLOCKED_RELEASE_STAGES.has(row.release_stage))
}

function benchmarkRowKey(row, index, scope) {
  const value = scope === 'model'
    ? row?.model_config_hash || row?.subject_id || row?.hash || row?.model_id
    : row?.target_version_id || row?.version_id || row?.subject_id || row?.hash || row?.short
  return String(value || `${scope}-${index}`)
}

function benchmarkRowPrimary(row, index, scope) {
  if (scope === 'model') {
    return String(
      row?.model_id ||
      row?.model_config_hash ||
      row?.subject_id ||
      row?.hash ||
      `model-${index + 1}`
    )
  }
  if (row?.is_baseline || row?.isBaseline) return 'Baseline Version'
  return String(row?.short || row?.target_version_id || row?.version_id || row?.subject_id || `version-${index + 1}`)
}

function benchmarkRowSecondary(row, scope) {
  const parts = scope === 'model'
    ? [row?.model_config_hash || row?.subject_id || row?.hash, row?.provider, row?.runtime || row?.runtime_id]
    : [row?.target_version_id || row?.version_id || row?.subject_id || row?.hash, row?.source]
  return parts.map((value) => String(value || '').trim()).filter(Boolean).join(' / ')
}

function benchmarkRowNumber(...values) {
  for (const value of values) {
    const number = Number(value)
    if (Number.isFinite(number)) return number
  }
  return 0
}

function normalizeBenchmarkLeaderboardRow(row, index, scope) {
  const score = benchmarkRowNumber(
    row?.score,
    row?.strength_score,
    row?.avg_role_score,
    row?.target_role_role_weighted_score
  )
  const winRate = benchmarkRowNumber(
    row?.winRate,
    row?.target_side_win_rate,
    row?.summary?.target_side_win_rate,
    row?.summary?.win_rate
  )
  const games = benchmarkRowNumber(row?.games, row?.game_count, row?.games_played, row?.total_games)
  const key = benchmarkRowKey(row, index, scope)
  const rankable = row?.rankable == null ? null : row.rankable !== false
  return {
    ...row,
    key,
    primary: benchmarkRowPrimary(row, index, scope),
    secondary: benchmarkRowSecondary(row, scope),
    score,
    scorePct: pct(score),
    winRate,
    winRatePct: pct(winRate),
    games,
    game_count: games,
    rankable,
    rankableLabel: rankable == null ? 'Unknown' : (rankable ? 'Rankable' : 'Unrankable'),
    rankableReason: String(row?.rankable_reason || row?.reason || row?.gate_reason || '').trim()
  }
}

function normalizeBenchmarkSnapshot(snapshot, scopeFallback = 'role_version') {
  if (!snapshot || typeof snapshot !== 'object') return null
  const scope = normalizeBenchmarkTargetType(snapshot.scope || scopeFallback)
  const rows = Array.isArray(snapshot.rows)
    ? snapshot.rows.map((row, index) => normalizeBenchmarkLeaderboardRow(row, index, scope))
    : []
  const summary = objectOrEmpty(snapshot.summary)
  const snapshotId = String(snapshot.snapshot_id || snapshot.id || '').trim()
  if (!snapshotId) return null
  return {
    ...snapshot,
    snapshot_id: snapshotId,
    title: String(snapshot.title || snapshotId),
    release_notes: String(snapshot.release_notes || ''),
    scope,
    benchmark_id: String(snapshot.benchmark_id || ''),
    benchmark_version: snapshot.benchmark_version ?? null,
    evaluation_set_id: String(snapshot.evaluation_set_id || ''),
    seed_set_id: String(snapshot.seed_set_id || ''),
    benchmark_config_hash: String(snapshot.benchmark_config_hash || ''),
    target_role: String(snapshot.target_role || ''),
    source_filter: objectOrEmpty(snapshot.source_filter),
    view_config: objectOrEmpty(snapshot.view_config),
    summary,
    row_count: metricNumber(snapshot.row_count ?? summary.row_count ?? rows.length),
    rankable_count: metricNumber(summary.rankable_count ?? rows.filter((row) => row.rankable !== false).length),
    content_hash: String(snapshot.content_hash || ''),
    created_at: String(snapshot.created_at || ''),
    rows
  }
}

function compareBenchmarkSnapshotRows(currentRows, snapshotRows, scope) {
  const current = currentRows.map((row, index) => normalizeBenchmarkLeaderboardRow(row, index, scope))
  const frozen = snapshotRows.map((row, index) => normalizeBenchmarkLeaderboardRow(row, index, scope))
  const currentByKey = new Map(current.map((row) => [row.key, row]))
  const frozenByKey = new Map(frozen.map((row) => [row.key, row]))
  const changed = []
  const added = []
  const removed = []
  for (const row of current) {
    const previous = frozenByKey.get(row.key)
    if (!previous) {
      added.push(row)
      continue
    }
    changed.push({
      key: row.key,
      current: row,
      snapshot: previous,
      scoreDelta: row.score - previous.score,
      winRateDelta: row.winRate - previous.winRate,
      gamesDelta: row.games - previous.games,
      rankableChanged: row.rankable !== previous.rankable
    })
  }
  for (const row of frozen) {
    if (!currentByKey.has(row.key)) removed.push(row)
  }
  return {
    current,
    snapshot: frozen,
    added,
    removed,
    changed: changed
      .filter((row) =>
        Math.abs(row.scoreDelta) > 0.000001 ||
        Math.abs(row.winRateDelta) > 0.000001 ||
        row.gamesDelta !== 0 ||
        row.rankableChanged
      )
      .sort((a, b) => Math.abs(b.scoreDelta) - Math.abs(a.scoreDelta) || a.current.primary.localeCompare(b.current.primary))
  }
}

function metricNumber(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function summaryCountRows(summary, key = 'by_kind', labelFor = null) {
  const source = summary?.[key]
  if (!source || typeof source !== 'object') return []
  return Object.entries(source)
    .map(([name, count]) => ({
      key: name,
      label: labelFor ? labelFor(name) : (DIAGNOSTIC_KIND_LABELS[name] || name),
      count: metricNumber(count)
    }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
}

function normalizeBenchmarkResult(result) {
  const config = result?.config || {}
  const scoreSummary = result?.score_summary || {}
  const judge = scoreSummary?.decision_judge_aggregate || {}
  const targetRole = result?.target_role || config?.target_role || ''
  const targetVersionId = config?.target_version_id || result?.target_version_id || ''
  const score = metricNumber(
    scoreSummary?.avg_role_score ??
    scoreSummary?.target_role_role_weighted_score ??
    result?.target_role_role_weighted_score
  )
  const winRate = metricNumber(
    scoreSummary?.target_side_win_rate ??
    result?.target_side_win_rate ??
    result?.candidate_win_rate
  )
  return {
    ...result,
    result_batch_id: String(result?.result_batch_id || result?.batch_id || config?.batch_id || ''),
    target_role: targetRole,
    targetRoleLabel: targetRole ? roleMeta(targetRole).label : '全部角色',
    target_version_id: targetVersionId,
    targetVersionShort: shortId(targetVersionId),
    completed: metricNumber(result?.completed),
    errored: metricNumber(result?.errored),
    game_count: metricNumber(result?.game_count),
    attempted_game_count: metricNumber(result?.attempted_game_count ?? result?.game_count),
    scorePct: pct(score),
    winRatePct: pct(winRate),
    rankable: result?.rankable !== false,
    rankableLabel: result?.rankable === false ? '未入榜' : '可入榜',
    rankableReason: String(result?.rankable_reason || ''),
    judgeScoreLabel: judge?.avg_score == null ? '—' : metricNumber(judge.avg_score).toFixed(1),
    judgeDecisionCount: metricNumber(judge?.judged_decisions ?? judge?.metrics?.judged),
    diagnostic_count: metricNumber(result?.diagnostic_count),
    warning_count: metricNumber(result?.warning_count)
  }
}

function normalizeBenchmarkBatchDetail(detail) {
  if (!detail || typeof detail !== 'object') return null
  const benchmarkMeta = detail.benchmark || detail.batch?.benchmark || null
  const benchmarkId = String(benchmarkMeta?.id || '')
  const benchmarkVersion = benchmarkMeta?.version ?? null
  const targetType = normalizeBenchmarkTargetType(benchmarkMeta?.target_type || detail.target_type)
  const results = Array.isArray(detail.results) ? detail.results.map(normalizeBenchmarkResult) : []
  const gameSummary = detail.game_summary || {}
  const diagnosticSummary = detail.diagnostic_summary || {}
  return {
    ...detail,
    batch_id: String(detail.batch_id || detail.batch?.batch_id || ''),
    benchmark: benchmarkMeta,
    target_type: targetType,
    targetTypeLabel: targetType === 'model' ? 'Model Benchmark' : 'Role Version',
    benchmarkLabel: benchmarkId ? `${benchmarkId}${benchmarkVersion ? `@v${benchmarkVersion}` : ''}` : '临时评测',
    statusLabel: statusText(detail.status),
    resultRows: results,
    gameSummary,
    diagnosticSummary,
    gameStatusRows: summaryCountRows(gameSummary, 'by_status', (name) => {
      const label = statusText(name)
      return label === '未知' ? name : label
    }),
    diagnosticKindRows: summaryCountRows(diagnosticSummary, 'by_kind'),
    diagnosticOriginRows: summaryCountRows(diagnosticSummary, 'by_origin')
  }
}

function normalizeBenchmarkGame(game) {
  const targetRole = game?.target_role || ''
  const historyGameId = String(game?.history_game_id || game?.historyGameId || game?.game_id || game?.id || '')
  const replayAvailable = game?.replay_available == null ? Boolean(historyGameId) : Boolean(game.replay_available)
  return {
    ...game,
    id: String(game?.id || game?.game_id || ''),
    game_id: String(game?.game_id || game?.id || ''),
    history_game_id: historyGameId,
    result_batch_id: String(game?.result_batch_id || game?.batch_id || ''),
    target_role: targetRole,
    targetRoleLabel: targetRole ? roleMeta(targetRole).label : '全部角色',
    status: String(game?.status || 'unknown'),
    statusLabel: statusText(game?.status) === '未知' ? String(game?.status || '未知') : statusText(game?.status),
    seedLabel: game?.seed == null ? '—' : String(game.seed),
    event_count: metricNumber(game?.event_count),
    decision_count: metricNumber(game?.decision_count),
    diagnostic_count: metricNumber(game?.diagnostic_count),
    replay_available: replayAvailable,
    replayHash: replayAvailable && historyGameId ? `#logs?game_id=${encodeURIComponent(historyGameId)}` : '',
    replayAvailableLabel: replayAvailable ? '可回放' : '无回放'
  }
}

function normalizeBenchmarkDiagnostic(entry) {
  const targetRole = entry?.target_role || ''
  const kind = String(entry?.kind || 'diagnostic')
  const level = String(entry?.level || 'info').toLowerCase()
  return {
    ...entry,
    id: [
      entry?.origin,
      entry?.result_batch_id,
      entry?.game_id,
      kind,
      entry?.stage,
      entry?.message
    ].map((item) => String(item || '')).join(':'),
    kind,
    kindLabel: DIAGNOSTIC_KIND_LABELS[kind] || kind,
    level,
    levelLabel: DIAGNOSTIC_LEVEL_LABELS[level] || level,
    origin: String(entry?.origin || 'run'),
    stage: String(entry?.stage || ''),
    message: String(entry?.message || ''),
    target_role: targetRole,
    targetRoleLabel: targetRole ? roleMeta(targetRole).label : '全部角色',
    result_batch_id: String(entry?.result_batch_id || ''),
    game_id: String(entry?.game_id || ''),
    seedLabel: entry?.seed == null ? '' : String(entry.seed)
  }
}

function normalizeBatchRun(run) {
  const id = run?.run_id || run?.batch_id || ''
  const benchmarkMeta = run?.benchmark || run?.config?.benchmark || null
  const benchmarkId = String(benchmarkMeta?.id || run?.benchmark_id || run?.config?.benchmark_id || '')
  const benchmarkVersion = benchmarkMeta?.version ?? run?.benchmark_version ?? run?.config?.benchmark_version ?? null
  const benchmarkTargetType = normalizeBenchmarkTargetType(benchmarkMeta?.target_type || run?.target_type || run?.config?.target_type)
  const evaluationSetId = String(benchmarkMeta?.evaluation_set_id || run?.evaluation_set_id || run?.config?.evaluation_set_id || '')
  const roleKeys = Array.isArray(run?.roles) && run.roles.length
    ? run.roles
    : (run?.role ? [run.role] : [])
  const roleNames = roleKeys.length
    ? roleKeys.map((role) => roleMeta(role).label).join('、')
    : '未知角色'
  const scoreSummary = run?.result?.score_summary || run?.score_summary || {}
  const judgeAggregate = scoreSummary?.decision_judge_aggregate || run?.decision_judge_aggregate || null
  const judgeTags = Array.isArray(judgeAggregate?.top_mistake_tags)
    ? judgeAggregate.top_mistake_tags.slice(0, 3).map((item) => ({
      tag: String(item?.tag || ''),
      count: Number(item?.count || 0)
    })).filter((item) => item.tag)
    : []
  return {
    ...run,
    id,
    roleKeys,
    displayRole: roleNames,
    scoreSummary,
    judgeAggregate,
    judgeTags,
    judgeScoreLabel: judgeAggregate?.avg_score == null ? '—' : Number(judgeAggregate.avg_score).toFixed(1),
    judgeBadRatePct: judgeAggregate?.bad_rate == null ? null : pct(judgeAggregate.bad_rate),
    judgeDecisionCount: Number(judgeAggregate?.judged_decisions || 0),
    benchmarkId,
    benchmarkVersion,
    benchmarkTargetType,
    evaluationSetId,
    benchmarkLabel: benchmarkId ? `${benchmarkId}${benchmarkVersion ? `@v${benchmarkVersion}` : ''}` : '临时评测',
    benchmarkTargetTypeLabel: benchmarkTargetType === 'model' ? 'Model Benchmark' : 'Role Version',
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

  const benchmarkSuites = ref([])
  const roles = ref([])
  const modelLeaderboard = ref({})
  const roleLeaderboard = ref({})
  const roleTargetVersions = ref({})
  const batchRuns = ref([])
  const benchmarkPlan = ref(null)
  const benchmarkPlanError = ref('')
  const selectedBenchmarkId = ref('')
  const selectedBenchmarkBatchId = ref('')
  const preferLegacyBenchmark = ref(false)
  const selectedRole = ref('')
  const error = ref('')
  const notice = ref({ type: '', message: '' })
  const noticeAutoDismiss = createNoticeAutoDismiss(notice, {
    enabled: options.installLifecycle !== false,
    onDismiss(dismissed) {
      if (dismissed.type !== 'error' && error.value === dismissed.message) error.value = ''
    }
  })
  const loading = ref(false)
  const actionLoading = ref('')
  const benchmarkSuiteError = ref('')
  const benchmarkEvents = ref([])
  const benchmarkDetailLoading = ref(false)
  const benchmarkDetailError = ref('')
  const benchmarkBatchDetail = ref(null)
  const benchmarkBatchGames = ref([])
  const benchmarkBatchGamePagination = ref({ total: 0, offset: 0, limit: 20, returned: 0, has_more: false })
  const benchmarkBatchDiagnostics = ref([])
  const benchmarkBatchDiagnosticSummary = ref({})
  const benchmarkGameStatusFilter = ref('problem')
  const benchmarkSnapshots = ref([])
  const benchmarkSnapshotDetail = ref(null)
  const benchmarkSnapshotDetails = ref({})
  const benchmarkSnapshotLoading = ref(false)
  const benchmarkSnapshotError = ref('')
  const selectedBenchmarkSnapshotId = ref('')
  const suiteRequests = createLatestOnlyTracker()
  const roleRequests = createLatestOnlyTracker()
  const roleBoardRequests = createLatestOnlyMap()
  const planRequests = createLatestOnlyTracker()
  const runRequests = createLatestOnlyTracker()
  const detailRequests = createLatestOnlyTracker()
  const refreshRequests = createLatestOnlyTracker()
  const actionRequests = createLatestOnlyTracker()
  const snapshotRequests = createLatestOnlyTracker()
  const snapshotDetailRequests = createLatestOnlyTracker()
  const snapshotActionRequests = createLatestOnlyTracker()
  let lastRunsError = null

  const form = ref({
    battle_games: 10,
    max_days: 5,
    budget_limit_units: '',
    target_version_id: '',
    model_id: '',
    model_config_hash: ''
  })

  const selectedBenchmarkSuite = computed(() =>
    benchmarkSuites.value.find((suite) => suite.id === selectedBenchmarkId.value) || null
  )
  const selectedBenchmarkTargetType = computed(() =>
    selectedBenchmarkSuite.value?.target_type || 'role_version'
  )
  const selectedBenchmarkIsModelSuite = computed(() => selectedBenchmarkTargetType.value === 'model')
  const benchmarkPlanBudgetExceeded = computed(() => Boolean(benchmarkPlan.value?.budget?.exceeded))
  const selectedBenchmarkEvaluationSetId = computed(() => selectedBenchmarkSuite.value?.evaluation_set_id || '')
  const selectedBenchmarkSuiteLabel = computed(() => selectedBenchmarkSuite.value?.label || '临时评测')
  const selectedSuiteRoleKeys = computed(() => selectedBenchmarkSuite.value?.roles || [])
  const leaderboardQuery = computed(() => {
    const evaluationSetId = selectedBenchmarkEvaluationSetId.value
    return evaluationSetId ? `?evaluation_set_id=${encodeURIComponent(evaluationSetId)}` : ''
  })
  const launchableRoles = computed(() => {
    const suiteRoles = selectedSuiteRoleKeys.value
    if (!suiteRoles.length) return roles.value
    const allowed = new Set(suiteRoles)
    const filtered = roles.value.filter((role) => allowed.has(role))
    return filtered.length ? filtered : roles.value
  })
  const launchBattleGames = computed(() => {
    const value = Number(selectedBenchmarkSuite.value?.game_count)
    return Number.isFinite(value) && value >= 0 ? Math.floor(value) : numberField('battle_games', 10)
  })
  const launchMaxDays = computed(() => {
    const value = Number(selectedBenchmarkSuite.value?.max_days)
    return Number.isFinite(value) && value >= 1 ? Math.floor(value) : numberField('max_days', 5)
  })

  const roleRows = computed(() => launchableRoles.value.map((role) => {
    const meta = roleMeta(role)
    return {
      key: role,
      role,
      label: meta.label,
      image: meta.image
    }
  }))

  const modelLeaderboardRows = computed(() =>
    selectedBenchmarkIsModelSuite.value
      ? (modelLeaderboard.value[MODEL_LEADERBOARD_KEY] || [])
      : (modelLeaderboard.value[selectedRole.value] || [])
  )
  const roleLeaderboardRows = computed(() => roleLeaderboard.value[selectedRole.value] || [])
  const roleTargetVersionRows = computed(() => roleTargetVersions.value[selectedRole.value] || [])
  const selectedRoleTargetVersion = computed(() => {
    const targetVersionId = String(form.value.target_version_id || '').trim()
    if (!targetVersionId) return null
    return roleTargetVersionRows.value.find((version) => version.version_id === targetVersionId) || null
  })
  const selectedRoleTargetVersionBlockedReason = computed(() => {
    const targetVersionId = String(form.value.target_version_id || '').trim()
    if (!targetVersionId) return ''
    if (selectedRoleTargetVersion.value) {
      return selectedRoleTargetVersion.value.targetDisabledReason || ''
    }
    return ''
  })
  const selectedBenchmarkCanLaunch = computed(() =>
    (selectedBenchmarkIsModelSuite.value || Boolean(selectedRole.value)) &&
    !benchmarkPlanBudgetExceeded.value &&
    !selectedRoleTargetVersionBlockedReason.value
  )
  const currentBenchmarkLeaderboardRows = computed(() =>
    selectedBenchmarkIsModelSuite.value ? modelLeaderboardRows.value : roleLeaderboardRows.value
  )
  const benchmarkSnapshotScope = computed(() =>
    selectedBenchmarkIsModelSuite.value ? 'model' : 'role_version'
  )
  const normalizedCurrentBenchmarkLeaderboardRows = computed(() =>
    currentBenchmarkLeaderboardRows.value.map((row, index) =>
      normalizeBenchmarkLeaderboardRow(row, index, benchmarkSnapshotScope.value)
    )
  )
  const selectedBenchmarkSnapshot = computed(() =>
    benchmarkSnapshots.value.find((snapshot) => snapshot.snapshot_id === selectedBenchmarkSnapshotId.value) || null
  )
  const activeBenchmarkSnapshotDetail = computed(() =>
    benchmarkSnapshotDetail.value || selectedBenchmarkSnapshot.value
  )
  const benchmarkSnapshotCompare = computed(() => {
    const detail = activeBenchmarkSnapshotDetail.value
    if (!detail?.rows?.length) {
      return {
        current: normalizedCurrentBenchmarkLeaderboardRows.value,
        snapshot: [],
        added: [],
        removed: [],
        changed: []
      }
    }
    return compareBenchmarkSnapshotRows(
      currentBenchmarkLeaderboardRows.value,
      detail.rows,
      benchmarkSnapshotScope.value
    )
  })

  const batchRunRows = computed(() =>
    batchRuns.value.map(normalizeBatchRun).sort((a, b) =>
      String(b.started_at || '').localeCompare(String(a.started_at || ''))
    )
  )

  const filteredBatchRunRows = computed(() => {
    let rows = batchRunRows.value
    const suite = selectedBenchmarkSuite.value
    if (suite) {
      rows = rows.filter((run) =>
        run.benchmarkId === suite.id ||
        (suite.evaluation_set_id && run.evaluationSetId === suite.evaluation_set_id)
      )
    }
    if (selectedBenchmarkIsModelSuite.value || !selectedRole.value) return rows
    return rows.filter((run) => run.roleKeys?.includes(selectedRole.value))
  })

  const visibleBatchRunRows = computed(() => filteredBatchRunRows.value.slice(0, 120))
  const selectedBenchmarkBatchRun = computed(() =>
    batchRunRows.value.find((run) => run.id === selectedBenchmarkBatchId.value) || null
  )

  const selectedRoleLabel = computed(() => roleMeta(selectedRole.value).label)

  function normalizeTargetVersionId(value) {
    const versionId = String(value || '').trim()
    if (!versionId) return ''
    const version = roleTargetVersionRows.value.find((item) => item.version_id === versionId)
    if (!version) return versionId
    return version.targetDisabled ? '' : version.version_id
  }

  function budgetLimitUnits() {
    if (form.value.budget_limit_units === '' || form.value.budget_limit_units == null) return null
    const value = Number(form.value.budget_limit_units)
    return Number.isFinite(value) && value >= 0 ? Math.floor(value) : null
  }

  function benchmarkRequestPayload() {
    const budgetLimit = budgetLimitUnits()
    const targetVersionId = normalizeTargetVersionId(form.value.target_version_id)
    const modelId = String(form.value.model_id || '').trim()
    const modelConfigHash = String(form.value.model_config_hash || '').trim()
    return {
      ...(selectedBenchmarkId.value ? { benchmark_id: selectedBenchmarkId.value } : {}),
      ...(selectedBenchmarkIsModelSuite.value
        ? {
            target_type: 'model',
            ...(modelId ? { model_id: modelId } : {}),
            ...(modelConfigHash ? { model_config_hash: modelConfigHash } : {})
          }
        : {
            ...(selectedRole.value ? { roles: [selectedRole.value] } : {}),
            ...(selectedRole.value && targetVersionId ? { target_versions: { [selectedRole.value]: targetVersionId } } : {})
          }),
      battle_games: launchBattleGames.value,
      max_days: launchMaxDays.value,
      ...(budgetLimit == null ? {} : { budget_limit_units: budgetLimit })
    }
  }

  function benchmarkSnapshotRequestPayload(overrides = {}) {
    const suite = selectedBenchmarkSuite.value || {}
    const benchmarkVersion = Number(suite.version)
    const evaluationSetId = selectedBenchmarkEvaluationSetId.value
    const scope = benchmarkSnapshotScope.value
    return {
      title: String(overrides.title || '').trim() || defaultSnapshotTitle(),
      release_notes: String(overrides.release_notes || overrides.releaseNotes || '').trim(),
      scope,
      ...(selectedBenchmarkId.value ? { benchmark_id: selectedBenchmarkId.value } : {}),
      ...(Number.isFinite(benchmarkVersion) ? { benchmark_version: benchmarkVersion } : {}),
      evaluation_set_id: evaluationSetId,
      seed_set_id: suite.seed_set_id || benchmarkPlan.value?.seed_set_id || '',
      benchmark_config_hash:
        suite.config_hash ||
        suite.benchmark_config_hash ||
        benchmarkPlan.value?.benchmark?.config_hash ||
        benchmarkPlan.value?.benchmark_config_hash ||
        '',
      ...(scope === 'role_version' && selectedRole.value ? { target_role: selectedRole.value } : {}),
      source_filter: {
        rankable: 'all',
        target_role: scope === 'role_version' ? selectedRole.value : null,
        evaluation_set_id: evaluationSetId
      },
      view_config: {
        view: 'leaderboard',
        mode: scope,
        suite_id: selectedBenchmarkId.value || '',
        role: scope === 'role_version' ? selectedRole.value : '',
        columns: scope === 'model'
          ? ['model_id', 'model_config_hash', 'strength_score', 'target_side_win_rate', 'rankable']
          : ['target_version_id', 'avg_role_score', 'target_side_win_rate', 'rankable']
      },
      limit: Number(overrides.limit || 100)
    }
  }

  function defaultSnapshotTitle() {
    const suite = selectedBenchmarkSuiteLabel.value || 'Benchmark'
    const scope = benchmarkSnapshotScope.value === 'model' ? 'Model' : selectedRoleLabel.value
    return `${suite} / ${scope} snapshot`
  }

  function benchmarkSnapshotListPath(limit = 50) {
    const query = new URLSearchParams()
    query.set('scope', benchmarkSnapshotScope.value)
    if (selectedBenchmarkEvaluationSetId.value) {
      query.set('evaluation_set_id', selectedBenchmarkEvaluationSetId.value)
    }
    if (selectedBenchmarkId.value) {
      query.set('benchmark_id', selectedBenchmarkId.value)
    }
    if (benchmarkSnapshotScope.value === 'role_version' && selectedRole.value) {
      query.set('target_role', selectedRole.value)
    }
    query.set('limit', String(limit))
    return `/benchmark/snapshots?${query.toString()}`
  }

  function upsertBenchmarkSnapshot(snapshot) {
    if (!snapshot?.snapshot_id) return
    const next = benchmarkSnapshots.value.filter((item) => item.snapshot_id !== snapshot.snapshot_id)
    next.unshift(snapshot)
    benchmarkSnapshots.value = next.sort((a, b) =>
      String(b.created_at || '').localeCompare(String(a.created_at || '')) ||
      String(b.snapshot_id || '').localeCompare(String(a.snapshot_id || ''))
    )
  }

  function setNotice(type, message) {
    notice.value = { type, message }
  }

  function clearNotice() {
    notice.value = { type: '', message: '' }
  }

  function syncFormFromSelectedSuite() {
    const suite = selectedBenchmarkSuite.value
    if (!suite) return
    const next = { ...form.value }
    if (Number.isFinite(suite.game_count)) next.battle_games = suite.game_count
    if (Number.isFinite(suite.max_days)) next.max_days = suite.max_days
    form.value = next
  }

  function ensureSelectedRoleAllowed() {
    if (selectedRole.value && launchableRoles.value.includes(selectedRole.value)) return
    selectedRole.value = launchableRoles.value[0] || roles.value[0] || ''
  }

  function gameStatusFilterQuery() {
    const filter = String(benchmarkGameStatusFilter.value || '').trim()
    if (!filter || filter === 'all') return ''
    if (filter === 'problem') return 'failed,timeout,abnormal'
    return filter
  }

  function clearBenchmarkBatchDetail() {
    benchmarkDetailError.value = ''
    benchmarkBatchDetail.value = null
    benchmarkBatchGames.value = []
    benchmarkBatchGamePagination.value = { total: 0, offset: 0, limit: 20, returned: 0, has_more: false }
    benchmarkBatchDiagnostics.value = []
    benchmarkBatchDiagnosticSummary.value = {}
  }

  async function loadBenchmarkSuites() {
    const token = suiteRequests.next()
    benchmarkSuiteError.value = ''
    try {
      const data = await apiFetch('/benchmarks')
      if (!token.isLatest()) return false
      const items = Array.isArray(data) ? data : (data?.items || data?.benchmarks || [])
      benchmarkSuites.value = items.map(normalizeBenchmarkSuite).filter(Boolean)
      if (
        selectedBenchmarkId.value &&
        !benchmarkSuites.value.some((suite) => suite.id === selectedBenchmarkId.value)
      ) {
        selectedBenchmarkId.value = ''
      }
      if (!selectedBenchmarkId.value && !preferLegacyBenchmark.value && benchmarkSuites.value.length) {
        selectedBenchmarkId.value = benchmarkSuites.value[0].id
      }
      syncFormFromSelectedSuite()
      ensureSelectedRoleAllowed()
      return true
    } catch (err) {
      if (token.isLatest()) {
        benchmarkSuites.value = []
        selectedBenchmarkId.value = ''
        preferLegacyBenchmark.value = true
        benchmarkSuiteError.value = benchmarkErrorMessage(err, 'Benchmark suite 列表不可用，已使用临时评测。')
        ensureSelectedRoleAllowed()
      }
      return false
    }
  }

  async function loadRoles() {
    const token = roleRequests.next()
    if (selectedBenchmarkIsModelSuite.value) {
      const data = await apiFetch('/roles')
      if (!token.isLatest()) return false
      roles.value = data.roles || []
      ensureSelectedRoleAllowed()
      roleLeaderboard.value = Object.fromEntries(roles.value.map((role) => [role, []]))
      roleTargetVersions.value = Object.fromEntries(roles.value.map((role) => [role, []]))
      await loadModelLeaderboard(token)
      return token.isLatest()
    }
    try {
      const overview = await apiFetch(`/roles/overview${leaderboardQuery.value}`)
      if (!token.isLatest()) return false
      roles.value = overview.roles || []
      ensureSelectedRoleAllowed()
      const overviewVersions = overview.versions || {}
      const overviewLeaderboards = overview.leaderboards || {}
      const nextModelLeaderboard = {}
      const nextRoleLeaderboard = {}
      const nextRoleTargetVersions = {}
      roles.value.forEach((role) => {
        const lbEntries = (overviewLeaderboards[role]?.entries || []).map(normalizeLeaderboardEntry)
        const versions = overviewVersions[role] || []
        nextModelLeaderboard[role] = lbEntries
        nextRoleLeaderboard[role] = normalizeBenchmarkRoleLeaderboardRows(lbEntries, versions)
        nextRoleTargetVersions[role] = normalizeBenchmarkRoleVersions(versions, lbEntries)
      })
      modelLeaderboard.value = nextModelLeaderboard
      roleLeaderboard.value = nextRoleLeaderboard
      roleTargetVersions.value = nextRoleTargetVersions
      return token.isLatest()
    } catch {
      // Older mock/backend builds do not expose the batched overview endpoint.
    }

    const data = await apiFetch('/roles')
    if (!token.isLatest()) return false
    roles.value = data.roles || []
    ensureSelectedRoleAllowed()
    await Promise.all(roles.value.map(async (role) => {
      const roleToken = roleBoardRequests.next(role)
      // The leaderboard endpoint now carries real benchmark scores
      // (benchmark_leaderboard table), keyed by target_version_id.
      let lbEntries = []
      try {
        const lbData = await apiFetch(`/roles/${encodeURIComponent(role)}/leaderboard${leaderboardQuery.value}`)
        if (!token.isLatest() || !roleToken.isLatest()) return
        lbEntries = (lbData.entries || []).map(normalizeLeaderboardEntry)
      } catch {
        lbEntries = []
      }
      if (!token.isLatest() || !roleToken.isLatest()) return
      modelLeaderboard.value = { ...modelLeaderboard.value, [role]: lbEntries }

      try {
        const rlData = await apiFetch(`/roles/${encodeURIComponent(role)}/versions`)
        if (!token.isLatest() || !roleToken.isLatest()) return
        const versions = rlData.versions || []
        roleTargetVersions.value = {
          ...roleTargetVersions.value,
          [role]: normalizeBenchmarkRoleVersions(versions, lbEntries)
        }
        roleLeaderboard.value = {
          ...roleLeaderboard.value,
          [role]: normalizeBenchmarkRoleLeaderboardRows(lbEntries, versions)
        }
      } catch {
        if (token.isLatest() && roleToken.isLatest()) {
          roleTargetVersions.value = { ...roleTargetVersions.value, [role]: [] }
          roleLeaderboard.value = {
            ...roleLeaderboard.value,
            [role]: normalizeBenchmarkRoleLeaderboardRows(lbEntries, [])
          }
        }
      }
    }))
    return token.isLatest()
  }

  async function loadBenchmarkPlan() {
    const token = planRequests.next()
    benchmarkPlanError.value = ''
    if (!selectedBenchmarkIsModelSuite.value && !selectedRole.value) {
      benchmarkPlan.value = null
      return false
    }
    if (!selectedBenchmarkIsModelSuite.value && selectedRoleTargetVersionBlockedReason.value) {
      benchmarkPlan.value = null
      benchmarkPlanError.value = selectedRoleTargetVersionBlockedReason.value
      return false
    }
    try {
      const data = await apiFetch('/benchmark/plan', {
        method: 'POST',
        body: JSON.stringify(benchmarkRequestPayload())
      })
      if (!token.isLatest()) return false
      benchmarkPlan.value = data || null
      return true
    } catch (err) {
      if (token.isLatest()) {
        benchmarkPlan.value = null
        benchmarkPlanError.value = benchmarkErrorMessage(err, 'Benchmark run plan 不可用。')
      }
      return false
    }
  }

  async function loadModelLeaderboard(parentToken) {
    try {
      const data = await apiFetch(`/models/leaderboard${leaderboardQuery.value}`)
      if (parentToken && !parentToken.isLatest()) return false
      const rows = (data.entries || []).map(normalizeModelLeaderboardEntry)
      modelLeaderboard.value = { [MODEL_LEADERBOARD_KEY]: rows }
      return true
    } catch {
      if (!parentToken || parentToken.isLatest()) {
        modelLeaderboard.value = { [MODEL_LEADERBOARD_KEY]: [] }
      }
      return false
    }
  }

  async function loadRuns() {
    const token = runRequests.next()
    lastRunsError = null
    try {
      const data = await apiFetch('/evolution-runs')
      if (!token.isLatest()) return false
      batchRuns.value = (data.batches || []).filter(isBenchmarkBatch)
      if (
        selectedBenchmarkBatchId.value &&
        !batchRuns.value.some((run) => (run?.batch_id || run?.run_id) === selectedBenchmarkBatchId.value)
      ) {
        selectedBenchmarkBatchId.value = ''
        clearBenchmarkBatchDetail()
      }
      syncBenchmarkEventSources()
      return true
    } catch (err) {
      if (token.isLatest()) {
        lastRunsError = err
        batchRuns.value = []
        syncBenchmarkEventSources()
      }
      return false
    }
  }

  async function loadBenchmarkBatchDetail(batchId = selectedBenchmarkBatchId.value) {
    const id = String(batchId || '').trim()
    if (!id) {
      selectedBenchmarkBatchId.value = ''
      clearBenchmarkBatchDetail()
      return false
    }
    const token = detailRequests.next()
    selectedBenchmarkBatchId.value = id
    benchmarkDetailLoading.value = true
    benchmarkDetailError.value = ''
    try {
      const query = new URLSearchParams()
      const statusFilter = gameStatusFilterQuery()
      if (statusFilter) query.set('status', statusFilter)
      query.set('limit', '20')
      query.set('offset', '0')
      const gamesPath = `/benchmark/batch/${encodeURIComponent(id)}/games?${query.toString()}`
      const [detail, games, diagnostics] = await Promise.all([
        apiFetch(`/benchmark/batch/${encodeURIComponent(id)}`),
        apiFetch(gamesPath),
        apiFetch(`/benchmark/batch/${encodeURIComponent(id)}/diagnostics`)
      ])
      if (!token.isLatest()) return false
      benchmarkBatchDetail.value = normalizeBenchmarkBatchDetail(detail)
      benchmarkBatchGames.value = (games?.games || []).map(normalizeBenchmarkGame)
      benchmarkBatchGamePagination.value = games?.pagination || { total: 0, offset: 0, limit: 20, returned: 0, has_more: false }
      benchmarkBatchDiagnostics.value = (diagnostics?.diagnostics || []).map(normalizeBenchmarkDiagnostic)
      benchmarkBatchDiagnosticSummary.value = diagnostics?.summary || {}
      return true
    } catch (err) {
      if (token.isLatest()) {
        benchmarkDetailError.value = benchmarkErrorMessage(err, '评测详情读取失败。')
        benchmarkBatchDetail.value = null
        benchmarkBatchGames.value = []
        benchmarkBatchGamePagination.value = { total: 0, offset: 0, limit: 20, returned: 0, has_more: false }
        benchmarkBatchDiagnostics.value = []
        benchmarkBatchDiagnosticSummary.value = {}
      }
      return false
    } finally {
      if (token.isLatest()) benchmarkDetailLoading.value = false
    }
  }

  function selectBenchmarkBatch(batchId) {
    const id = String(batchId || '').trim()
    if (!id) {
      selectedBenchmarkBatchId.value = ''
      clearBenchmarkBatchDetail()
      return
    }
    void loadBenchmarkBatchDetail(id)
  }

  function setBenchmarkGameStatusFilter(status) {
    benchmarkGameStatusFilter.value = String(status || 'problem')
    if (selectedBenchmarkBatchId.value) {
      void loadBenchmarkBatchDetail(selectedBenchmarkBatchId.value)
    }
  }

  async function loadBenchmarkSnapshots({ limit = 50, silent = false } = {}) {
    if (benchmarkSnapshotScope.value === 'role_version' && !selectedRole.value) {
      benchmarkSnapshots.value = []
      selectedBenchmarkSnapshotId.value = ''
      benchmarkSnapshotDetail.value = null
      benchmarkSnapshotError.value = ''
      return false
    }
    const token = snapshotRequests.next()
    if (!silent) benchmarkSnapshotLoading.value = true
    benchmarkSnapshotError.value = ''
    try {
      const data = await apiFetch(benchmarkSnapshotListPath(limit))
      if (!token.isLatest()) return false
      const items = Array.isArray(data) ? data : (data?.items || data?.snapshots || [])
      benchmarkSnapshots.value = items
        .map((snapshot) => normalizeBenchmarkSnapshot(snapshot, benchmarkSnapshotScope.value))
        .filter(Boolean)
      if (
        selectedBenchmarkSnapshotId.value &&
        !benchmarkSnapshots.value.some((snapshot) => snapshot.snapshot_id === selectedBenchmarkSnapshotId.value)
      ) {
        selectedBenchmarkSnapshotId.value = ''
        benchmarkSnapshotDetail.value = null
      }
      return true
    } catch (err) {
      if (token.isLatest()) {
        benchmarkSnapshots.value = []
        selectedBenchmarkSnapshotId.value = ''
        benchmarkSnapshotDetail.value = null
        benchmarkSnapshotError.value = benchmarkErrorMessage(err, 'Benchmark snapshot 列表不可用。')
      }
      return false
    } finally {
      if (token.isLatest() && !silent) benchmarkSnapshotLoading.value = false
    }
  }

  async function loadBenchmarkSnapshotDetail(snapshotId = selectedBenchmarkSnapshotId.value, { force = false } = {}) {
    const id = String(snapshotId || '').trim()
    if (!id) {
      selectedBenchmarkSnapshotId.value = ''
      benchmarkSnapshotDetail.value = null
      return false
    }
    const cached = benchmarkSnapshotDetails.value[id]
    selectedBenchmarkSnapshotId.value = id
    if (!force && cached?.rows?.length) {
      benchmarkSnapshotDetail.value = cached
      return true
    }
    const token = snapshotDetailRequests.next()
    benchmarkSnapshotLoading.value = true
    benchmarkSnapshotError.value = ''
    try {
      const data = await apiFetch(`/benchmark/snapshots/${encodeURIComponent(id)}`)
      if (!token.isLatest()) return false
      const detail = normalizeBenchmarkSnapshot(data, benchmarkSnapshotScope.value)
      if (!detail) throw new Error('invalid benchmark snapshot payload')
      benchmarkSnapshotDetails.value = {
        ...benchmarkSnapshotDetails.value,
        [detail.snapshot_id]: detail
      }
      upsertBenchmarkSnapshot(detail)
      selectedBenchmarkSnapshotId.value = detail.snapshot_id
      benchmarkSnapshotDetail.value = detail
      return true
    } catch (err) {
      if (token.isLatest()) {
        benchmarkSnapshotError.value = benchmarkErrorMessage(err, 'Benchmark snapshot 详情读取失败。')
        benchmarkSnapshotDetail.value = null
      }
      return false
    } finally {
      if (token.isLatest()) benchmarkSnapshotLoading.value = false
    }
  }

  async function selectBenchmarkSnapshot(snapshotId) {
    return loadBenchmarkSnapshotDetail(snapshotId, { force: true })
  }

  async function createBenchmarkSnapshot(overrides = {}) {
    if (benchmarkSnapshotScope.value === 'role_version' && !selectedRole.value) {
      const message = '请选择一个角色后再创建 snapshot。'
      benchmarkSnapshotError.value = message
      setNotice('warning', message)
      return null
    }
    const token = snapshotActionRequests.next()
    benchmarkSnapshotLoading.value = true
    benchmarkSnapshotError.value = ''
    clearNotice()
    try {
      const created = await apiFetch('/benchmark/snapshots', {
        method: 'POST',
        body: JSON.stringify(benchmarkSnapshotRequestPayload(overrides))
      })
      if (!token.isLatest()) return null
      const detail = normalizeBenchmarkSnapshot(created, benchmarkSnapshotScope.value)
      if (!detail) throw new Error('invalid benchmark snapshot payload')
      benchmarkSnapshotDetails.value = {
        ...benchmarkSnapshotDetails.value,
        [detail.snapshot_id]: detail
      }
      upsertBenchmarkSnapshot(detail)
      selectedBenchmarkSnapshotId.value = detail.snapshot_id
      benchmarkSnapshotDetail.value = detail
      setNotice('success', 'Benchmark snapshot 已创建。')
      return detail
    } catch (err) {
      if (token.isLatest()) {
        const message = benchmarkErrorMessage(err, '创建 Benchmark snapshot 失败。')
        benchmarkSnapshotError.value = message
        setNotice('error', message)
      }
      return null
    } finally {
      if (token.isLatest()) benchmarkSnapshotLoading.value = false
    }
  }

  async function loadBenchmarkView(viewKey) {
    const key = String(viewKey || '').trim()
    if (!key) return null
    try {
      return await apiFetch(`/benchmark/views/${encodeURIComponent(key)}`)
    } catch {
      return null
    }
  }

  async function saveBenchmarkView(payload = {}) {
    const viewKey = String(payload.view_key || '').trim()
    if (!viewKey) return null
    return apiFetch('/benchmark/views', {
      method: 'POST',
      body: JSON.stringify(payload)
    })
  }

  async function deleteBenchmarkView(viewKey) {
    const key = String(viewKey || '').trim()
    if (!key) return null
    try {
      return await apiFetch(`/benchmark/views/${encodeURIComponent(key)}`, { method: 'DELETE' })
    } catch {
      return null
    }
  }

  async function refreshAll({ silent = false, notify = false } = {}) {
    const token = refreshRequests.next()
    if (!silent) loading.value = true
    error.value = ''
    if (notify) clearNotice()
    try {
      await loadBenchmarkSuites()
      if (!token.isLatest()) return false
      const rolesLoaded = await loadRoles()
      if (!token.isLatest()) return false
      await loadBenchmarkPlan()
      if (!token.isLatest()) return false
      const runsLoaded = await loadRuns()
      if (!token.isLatest()) return false
      await loadBenchmarkSnapshots({ silent: true })
      if (!token.isLatest()) return false
      if (!rolesLoaded || !runsLoaded) {
        const message = benchmarkErrorMessage(lastRunsError, '评测数据刷新不完整，请手动刷新。')
        error.value = message
        if (notify) setNotice('warning', message)
        return false
      }
      if (notify) setNotice('success', '评测数据已刷新。')
      return true
    } catch (err) {
      if (token.isLatest()) {
        const message = benchmarkErrorMessage(err, '评测数据读取失败')
        error.value = message
        if (notify) setNotice('error', message)
      }
      return false
    } finally {
      if (token.isLatest()) loading.value = false
    }
  }

  function selectRole(role) {
    if (!role) return
    if (selectedRole.value !== role) {
      form.value = { ...form.value, target_version_id: '' }
      selectedBenchmarkBatchId.value = ''
      clearBenchmarkBatchDetail()
    }
    selectedRole.value = role
  }

  function selectBenchmarkSuite(benchmarkId) {
    selectedBenchmarkId.value = String(benchmarkId || '')
    preferLegacyBenchmark.value = !selectedBenchmarkId.value
    form.value = {
      ...form.value,
      target_version_id: '',
      model_id: '',
      model_config_hash: ''
    }
    syncFormFromSelectedSuite()
    ensureSelectedRoleAllowed()
    modelLeaderboard.value = {}
    roleLeaderboard.value = {}
    roleTargetVersions.value = {}
    selectedBenchmarkBatchId.value = ''
    clearBenchmarkBatchDetail()
    void refreshAll({ silent: true })
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
    if (!selectedBenchmarkIsModelSuite.value && !selectedRole.value) {
      const message = '请选择一个角色'
      error.value = message
      setNotice('warning', message)
      return
    }
    if (!selectedBenchmarkIsModelSuite.value && selectedRoleTargetVersionBlockedReason.value) {
      const message = selectedRoleTargetVersionBlockedReason.value
      error.value = message
      setNotice('warning', message)
      return
    }
    if (benchmarkPlanBudgetExceeded.value) {
      const message = '评测预算超过上限，请提高预算或选择更小的 suite。'
      error.value = message
      setNotice('warning', message)
      return
    }
    const token = actionRequests.next()
    actionLoading.value = 'start'
    error.value = ''
    clearNotice()
    const controller = new AbortController()
    abortController = controller
    try {
      const created = await apiFetch('/benchmark', {
        method: 'POST',
        body: JSON.stringify(benchmarkRequestPayload()),
        signal: controller.signal
      })
      if (!token.isLatest()) return
      resetBatchEventId(created?.batch_id)
      const refreshed = await refreshAll({ silent: true })
      if (!token.isLatest()) return
      setNotice(
        refreshed ? 'success' : 'warning',
        refreshed ? '评测已启动。' : '评测已启动，但列表刷新失败，请手动刷新。'
      )
    } catch (err) {
      if (token.isLatest() && err?.name !== 'AbortError') {
        const message = benchmarkErrorMessage(err, '启动评测失败')
        error.value = message
        setNotice('error', message)
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
    clearNotice()
    try {
      await apiFetch(`/benchmark/batch/${encodeURIComponent(batchId)}/stop`, { method: 'POST' })
      if (!token.isLatest()) return
      closeBenchmarkEventSource(batchId)
      const refreshed = await refreshAll({ silent: true })
      if (!token.isLatest()) return
      setNotice(
        refreshed ? 'success' : 'warning',
        refreshed ? '评测已停止。' : '评测已停止，但列表刷新失败，请手动刷新。'
      )
    } catch (err) {
      if (token.isLatest()) {
        const message = benchmarkErrorMessage(err, '停止评测失败')
        const isMissingBatch = String(err?.message || err || '').toLowerCase().includes('batch not found')
        error.value = message
        if (isMissingBatch) await refreshAll({ silent: true })
        if (token.isLatest()) setNotice(isMissingBatch ? 'warning' : 'error', message)
      }
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  if (options.installLifecycle !== false) {
    onBeforeUnmount(() => {
      closeAllBenchmarkEventSources()
      noticeAutoDismiss.dispose()
    })
  }

  watch(
    () => [
      selectedBenchmarkId.value,
      selectedBenchmarkTargetType.value,
      selectedRole.value,
      form.value.battle_games,
      form.value.max_days,
      form.value.budget_limit_units,
      form.value.target_version_id,
      form.value.model_id,
      form.value.model_config_hash
    ],
    () => {
      void loadBenchmarkPlan()
    }
  )

  return {
    benchmarkSuites,
    benchmarkSuiteError,
    benchmarkPlan,
    benchmarkPlanError,
    benchmarkPlanBudgetExceeded,
    roles,
    roleMeta,
    roleRows,
    launchableRoles,
    selectedBenchmarkId,
    selectedBenchmarkSuite,
    selectedBenchmarkTargetType,
    selectedBenchmarkIsModelSuite,
    selectedBenchmarkCanLaunch,
    selectedBenchmarkSuiteLabel,
    selectedBenchmarkEvaluationSetId,
    selectBenchmarkSuite,
    launchBattleGames,
    launchMaxDays,
    selectedRole,
    selectRole,
    selectedRoleLabel,
    modelLeaderboard,
    modelLeaderboardRows,
    roleLeaderboard,
    roleLeaderboardRows,
    roleTargetVersionRows,
    selectedRoleTargetVersion,
    selectedRoleTargetVersionBlockedReason,
    currentBenchmarkLeaderboardRows,
    normalizedCurrentBenchmarkLeaderboardRows,
    benchmarkSnapshots,
    benchmarkSnapshotDetail,
    benchmarkSnapshotDetails,
    benchmarkSnapshotLoading,
    benchmarkSnapshotError,
    selectedBenchmarkSnapshotId,
    selectedBenchmarkSnapshot,
    activeBenchmarkSnapshotDetail,
    benchmarkSnapshotCompare,
    benchmarkSnapshotScope,
    loadBenchmarkSnapshots,
    loadBenchmarkSnapshotDetail,
    selectBenchmarkSnapshot,
    createBenchmarkSnapshot,
    loadBenchmarkView,
    saveBenchmarkView,
    deleteBenchmarkView,
    batchRuns,
    benchmarkEvents,
    batchRunRows,
    filteredBatchRunRows,
    visibleBatchRunRows,
    selectedBenchmarkBatchId,
    selectedBenchmarkBatchRun,
    benchmarkDetailLoading,
    benchmarkDetailError,
    benchmarkBatchDetail,
    benchmarkBatchGames,
    benchmarkBatchGamePagination,
    benchmarkBatchDiagnostics,
    benchmarkBatchDiagnosticSummary,
    benchmarkGameStatusFilter,
    selectBenchmarkBatch,
    loadBenchmarkBatchDetail,
    setBenchmarkGameStatusFilter,
    form,
    error,
    notice,
    clearNotice,
    loading,
    actionLoading,
    refreshAll,
    startEvaluation,
    stopBatch
  }
}

export { useEvaluationWorkbench }
