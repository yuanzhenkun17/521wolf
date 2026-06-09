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
const BENCHMARK_VIEW_STORAGE_PREFIX = 'benchmark-comparison-view'
const BENCHMARK_SUITE_LAUNCHABLE_STATUSES = new Set(['enabled', 'active'])
const BENCHMARK_BUDGET_REASON_LABELS = {
  estimated_units_exceed_limit_units: '预计调用单位超过预算上限',
  estimated_cost_exceed_limit_cost: '预计成本超过成本上限'
}
const BENCHMARK_BUDGET_METRIC_LABELS = {
  estimated_units: '预计调用单位',
  estimated_cost: '预计成本',
  estimated_tokens: '预计 token'
}

const BENCHMARK_SUITE_STATUS_LABELS = {
  enabled: '启用',
  active: '启用',
  draft: '草稿',
  deprecated: '废弃',
  disabled: '停用',
  archived: '归档'
}

const BENCHMARK_SUITE_DISABLED_REASONS = {
  draft: '该评测套件仍是草稿，启用后才能启动。',
  deprecated: '该评测套件已废弃，只保留历史审计，不能启动。',
  disabled: '该评测套件已停用，不能启动。',
  archived: '该评测套件已归档，只能查看历史结果。'
}

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

function normalizeBenchmarkSeedSet(raw) {
  const id = String(raw?.id || raw?.seed_set_id || '').trim()
  if (!id) return null
  const seedPreview = normalizeSeedPreview(raw)
  const seedCount = normalizeSeedCount(raw, seedPreview)
  const overlapWarnings = Array.isArray(raw?.overlap_warnings)
    ? raw.overlap_warnings.filter((item) => item && typeof item === 'object')
    : []
  return {
    ...raw,
    id,
    seed_set_id: id,
    purpose: String(raw?.purpose || '').trim(),
    version: raw?.version == null || raw.version === '' ? null : Number(raw.version),
    description: String(raw?.description || ''),
    target_type: raw?.target_type ? normalizeBenchmarkTargetType(raw.target_type) : '',
    tier: String(raw?.tier || '').trim().toLowerCase(),
    created_at: String(raw?.created_at || '').trim(),
    usage_boundary: String(raw?.usage_boundary || '').trim(),
    non_overlap_group: String(raw?.non_overlap_group || '').trim(),
    immutable: raw?.immutable !== false,
    seed_count: seedCount,
    seed_preview: seedPreview,
    config_hash: String(raw?.config_hash || '').trim(),
    enabled: raw?.enabled !== false,
    overlap_warnings: overlapWarnings
  }
}

function normalizeBenchmarkSeedRegistry(data) {
  const items = Array.isArray(data) ? data : (data?.items || data?.seed_sets || [])
  const normalizedItems = items.map(normalizeBenchmarkSeedSet).filter(Boolean)
  const summary = objectOrEmpty(data?.summary)
  const overlapWarnings = Array.isArray(summary.overlap_warnings) ? summary.overlap_warnings : []
  const warningsById = new Map()
  for (const warning of overlapWarnings) {
    if (!warning || typeof warning !== 'object') continue
    const ids = [
      warning.left_seed_set_id,
      warning.right_seed_set_id,
      ...(Array.isArray(warning.seed_set_ids) ? warning.seed_set_ids : [])
    ].map((item) => String(item || '').trim()).filter(Boolean)
    for (const id of ids) {
      const rows = warningsById.get(id) || []
      rows.push(warning)
      warningsById.set(id, rows)
    }
  }
  return {
    items: normalizedItems.map((item) => ({
      ...item,
      overlap_warnings: [
        ...(Array.isArray(item.overlap_warnings) ? item.overlap_warnings : []),
        ...(warningsById.get(item.id) || [])
      ]
    })),
    summary: {
      ...summary,
      total: Number.isFinite(Number(summary.total)) ? Number(summary.total) : normalizedItems.length,
      by_target_type: objectOrEmpty(summary.by_target_type),
      by_tier: objectOrEmpty(summary.by_tier),
      overlap_warnings: overlapWarnings
    }
  }
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

function normalizeBenchmarkSuiteStatus(raw) {
  const status = String(raw?.status || raw?.lifecycle_status || raw?.lifecycleStatus || '').trim().toLowerCase()
  if (status) return status
  if (raw?.deprecated) return 'deprecated'
  if (raw?.archived) return 'archived'
  if (raw?.enabled === false) return 'disabled'
  return 'enabled'
}

function benchmarkSuiteLaunchDisabledReason(raw, status, launchable) {
  const explicit = String(raw?.launch_disabled_reason || raw?.launchDisabledReason || '').trim()
  if (explicit && /[\u4e00-\u9fff]/.test(explicit)) return explicit
  if (launchable) return ''
  return BENCHMARK_SUITE_DISABLED_REASONS[status] || '该评测套件当前不可启动。'
}

function normalizeBenchmarkSuite(raw, seedRegistryById = new Map()) {
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
  const status = normalizeBenchmarkSuiteStatus(raw)
  const serverLaunchable = raw?.launchable == null ? null : raw.launchable !== false
  const launchable = serverLaunchable == null
    ? BENCHMARK_SUITE_LAUNCHABLE_STATUSES.has(status)
    : serverLaunchable && BENCHMARK_SUITE_LAUNCHABLE_STATUSES.has(status)
  const rawSeedSet = objectOrEmpty(raw?.seed_set)
  const seedSetId = String(raw?.seed_set_id || rawSeedSet.id || rawSeedSet.seed_set_id || '').trim()
  const registrySeedSet = seedRegistryById?.get?.(seedSetId) || null
  const seedSet = objectOrEmpty({
    ...objectOrEmpty(registrySeedSet),
    ...rawSeedSet
  })
  const seedSource = { ...raw, seed_set_id: seedSetId, seed_set: seedSet }
  const seedPreview = normalizeSeedPreview(seedSource)
  const seedCount = normalizeSeedCount(seedSource, seedPreview)
  const metrics = objectOrEmpty(raw?.metrics)
  const gates = objectOrEmpty(raw?.gates)
  const judge = objectOrEmpty(raw?.judge)
  const configHash = String(raw?.config_hash || raw?.benchmark_config_hash || '').trim()
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
    seed_set_id: seedSetId,
    seed_count: seedCount,
    seed_preview: seedPreview,
    seed_set: seedSet,
    paired_seed: Boolean(raw?.paired_seed),
    seed_start: raw?.seed_start ?? null,
    metrics,
    gates,
    judge,
    config_hash: configHash,
    benchmark_config_hash: String(raw?.benchmark_config_hash || configHash),
    cost_tier: normalizeCostTier(raw),
    evaluation_set_id: evaluationSetId,
    status,
    statusLabel: BENCHMARK_SUITE_STATUS_LABELS[status] || status || '未知',
    launchable,
    launch_disabled_reason: benchmarkSuiteLaunchDisabledReason(raw, status, launchable)
  }
}

function benchmarkErrorMessage(err, fallback) {
  const raw = String(err?.message || err || '').trim()
  const text = raw.toLowerCase()
  if (!raw) return fallback
  const budgetError = benchmarkBudgetExceededError(err)
  if (budgetError) return benchmarkBudgetExceededErrorMessage(budgetError)
  if (err?.code === 'benchmark_suite_not_launchable' || text.includes('benchmark suite cannot be launched')) {
    const detail = String(err?.detail || raw || '').toLowerCase()
    if (detail.includes('deprecated')) return BENCHMARK_SUITE_DISABLED_REASONS.deprecated
    if (detail.includes('archived')) return BENCHMARK_SUITE_DISABLED_REASONS.archived
    if (detail.includes('draft')) return BENCHMARK_SUITE_DISABLED_REASONS.draft
    if (detail.includes('disabled')) return BENCHMARK_SUITE_DISABLED_REASONS.disabled
    return '该评测套件当前不可启动。'
  }
  if (text.includes('batch not found')) return '评测批次不存在，已刷新列表。'
  if (text.includes('benchmark failed')) return '评测执行失败，请查看评测记录。'
  if (text.includes('invalid config') || text.includes('invalid benchmark config')) return '评测配置无效，请检查局数和天数。'
  if (text.includes('role not found')) return '角色不存在，请刷新后重试。'
  if (text.includes('rate limit') || text.includes('rate_limited')) return '评测请求被限流，请稍后重试。'
  return raw || fallback
}

function benchmarkBudgetExceededValue(budget = {}) {
  const exceeded = budget?.exceeded
  if (exceeded && typeof exceeded === 'object' && !Array.isArray(exceeded)) {
    return Boolean(exceeded.value)
  }
  return Boolean(exceeded)
}

function firstObject(...values) {
  return values.find((value) => value && typeof value === 'object' && !Array.isArray(value)) || {}
}

function firstArray(...values) {
  return values.find((value) => Array.isArray(value) && value.length) ||
    values.find((value) => Array.isArray(value)) ||
    []
}

function benchmarkBudgetExceededError(err) {
  const detail = firstObject(err?.detail)
  const payload = firstObject(err?.payload)
  const payloadDetail = firstObject(payload.detail)
  const detailBody = firstObject(detail.detail, payloadDetail.detail)
  const budget = firstObject(detailBody.budget, detail.budget, payloadDetail.budget)
  const diagnostics = firstArray(err?.diagnostics, detail.diagnostics, payloadDetail.diagnostics)
  const firstDiagnostic = firstObject(diagnostics[0])
  const exceeded = firstObject(budget.exceeded, detailBody.exceeded, firstDiagnostic.exceeded)
  const code = String(
    err?.code ||
    detail.code ||
    payload.code ||
    payloadDetail.code ||
    detailBody.code ||
    ''
  ).toLowerCase()
  const rawText = String(
    err?.message ||
    detail.message ||
    payloadDetail.message ||
    detailBody.message ||
    ''
  ).toLowerCase()
  const hasBudgetCode =
    code === 'benchmark_budget_exceeded' ||
    rawText.includes('benchmark budget exceeded') ||
    rawText.includes('benchmark_budget_exceeded') ||
    diagnostics.some((item) => String(item?.kind || '').toLowerCase() === 'budget_exceeded')
  if (!hasBudgetCode) return null

  const estimated = firstObject(detailBody.estimated)
  const limit = firstObject(detailBody.limit)
  return {
    budget,
    estimated,
    limit,
    diagnostics,
    reasons: firstArray(exceeded.reasons, firstDiagnostic.reasons),
    evidence: firstArray(exceeded.evidence, detailBody.evidence, firstDiagnostic.evidence),
    currency: budget.currency || estimated.currency || limit.currency || firstDiagnostic.currency || ''
  }
}

function formatBudgetEvidenceNumber(value, { metric = '', currency = '' } = {}) {
  const number = Number(value)
  if (!Number.isFinite(number)) return value == null || value === '' ? '未上报' : String(value)
  if (String(metric).includes('cost')) {
    const suffix = currency ? ` ${currency}` : ''
    return `${number.toLocaleString('zh-CN', { maximumFractionDigits: 6 })}${suffix}`
  }
  return number.toLocaleString('zh-CN')
}

function benchmarkBudgetEvidenceText(evidence, fallbackCurrency = '') {
  if (!evidence || typeof evidence !== 'object') return ''
  const metric = String(evidence.metric || '').trim()
  const label = BENCHMARK_BUDGET_METRIC_LABELS[metric] || metric || '预算指标'
  const currency = String(evidence.unit || fallbackCurrency || '').trim()
  const estimated = formatBudgetEvidenceNumber(evidence.estimated, { metric, currency })
  const limit = formatBudgetEvidenceNumber(evidence.limit, { metric, currency })
  const delta = evidence.delta == null
    ? ''
    : `，超出 ${formatBudgetEvidenceNumber(evidence.delta, { metric, currency })}`
  return `${label} ${estimated} > 上限 ${limit}${delta}`
}

function benchmarkBudgetFallbackEvidence(error) {
  const rows = []
  const currency = error.currency
  const unitsEstimated = error.estimated.units ?? error.budget.estimated_units
  const unitsLimit = error.limit.units ?? error.budget.limit_units
  if (unitsEstimated != null || unitsLimit != null) {
    rows.push(`预计调用单位 ${formatBudgetEvidenceNumber(unitsEstimated)} / 上限 ${formatBudgetEvidenceNumber(unitsLimit)}`)
  }
  const costEstimated = error.estimated.cost ?? error.budget.estimated_cost
  const costLimit = error.limit.cost ?? error.budget.limit_cost
  if (costEstimated != null || costLimit != null) {
    rows.push(
      `预计成本 ${formatBudgetEvidenceNumber(costEstimated, { metric: 'estimated_cost', currency })} / 上限 ${formatBudgetEvidenceNumber(costLimit, { metric: 'estimated_cost', currency })}`
    )
  }
  const estimatedTokens = error.estimated.tokens ?? error.budget.estimated_tokens
  if (estimatedTokens != null) {
    rows.push(`预计 token ${formatBudgetEvidenceNumber(estimatedTokens)}`)
  }
  return rows
}

function benchmarkBudgetExceededErrorMessage(error) {
  const evidenceRows = error.evidence
    .map((item) => benchmarkBudgetEvidenceText(item, error.currency))
    .filter(Boolean)
  const detailRows = evidenceRows.length ? evidenceRows : benchmarkBudgetFallbackEvidence(error)
  const reasonRows = error.reasons
    .map((reason) => BENCHMARK_BUDGET_REASON_LABELS[String(reason)] || String(reason || '').trim())
    .filter(Boolean)
  const suffix = [...detailRows, ...reasonRows].slice(0, 5).join('；')
  return suffix ? `评测预算超过上限：${suffix}。` : '评测预算超过上限，请提高预算或选择更小的套件。'
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
    return '影子版本需先晋升金丝雀后才能评测。'
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
    rankableLabel: rankable == null ? '未知' : (rankable ? '可入榜' : '未入榜'),
    rankableReason: String(row?.rankable_reason || row?.reason || row?.gate_reason || '').trim()
  }
}

function normalizeBenchmarkSnapshotIdList(...values) {
  for (const value of values) {
    if (Array.isArray(value)) {
      return value.map((item) => String(item || '').trim()).filter(Boolean)
    }
    if (typeof value === 'string') {
      return value.split(/[,\s]+/).map((item) => item.trim()).filter(Boolean)
    }
  }
  return []
}

function metricNumberOrNull(value) {
  if (value == null || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function normalizeBenchmarkSnapshotSummary(snapshot, rows = []) {
  const summary = objectOrEmpty(snapshot?.summary)
  const linkedRunIds = normalizeBenchmarkSnapshotIdList(snapshot?.linked_run_ids, summary.linked_run_ids)
  const linkedReportIds = normalizeBenchmarkSnapshotIdList(snapshot?.linked_report_ids, summary.linked_report_ids)
  const linkedResultBatchIds = normalizeBenchmarkSnapshotIdList(
    snapshot?.linked_result_batch_ids,
    summary.linked_result_batch_ids
  )
  const rawRankableCount = metricNumberOrNull(snapshot?.rankable_count ?? summary.rankable_count)
  const rawUnrankableCount = metricNumberOrNull(snapshot?.unrankable_count ?? summary.unrankable_count)
  const rawRowCount = metricNumberOrNull(snapshot?.row_count ?? summary.row_count)
  const countedRowTotal = rawRankableCount != null && rawUnrankableCount != null
    ? rawRankableCount + rawUnrankableCount
    : rows.length
  const rowCount = rawRowCount ?? countedRowTotal
  const rankableCount = rawRankableCount ?? (
    rawUnrankableCount != null
      ? Math.max(rowCount - rawUnrankableCount, 0)
      : (rows.length ? rows.filter((row) => row.rankable !== false).length : rowCount)
  )
  const unrankableCount = rawUnrankableCount ?? (
    rawRankableCount != null
      ? Math.max(rowCount - rawRankableCount, 0)
      : (rows.length ? rows.filter((row) => row.rankable === false).length : 0)
  )
  return {
    ...summary,
    linked_run_ids: linkedRunIds,
    linked_report_ids: linkedReportIds,
    linked_result_batch_ids: linkedResultBatchIds,
    source_run_count: metricNumberOrNull(
      snapshot?.source_run_count ?? summary.source_run_count
    ) ?? linkedRunIds.length,
    source_report_count: metricNumberOrNull(
      snapshot?.source_report_count ?? summary.source_report_count
    ) ?? linkedReportIds.length,
    source_result_batch_count: metricNumberOrNull(
      snapshot?.source_result_batch_count ?? summary.source_result_batch_count
    ) ?? linkedResultBatchIds.length,
    rankable_count: rankableCount,
    unrankable_count: unrankableCount,
    row_count: rowCount,
    content_hash: String(snapshot?.content_hash || summary.content_hash || '')
  }
}

function normalizeBenchmarkSnapshot(snapshot, scopeFallback = 'role_version') {
  if (!snapshot || typeof snapshot !== 'object') return null
  const scope = normalizeBenchmarkTargetType(snapshot.scope || scopeFallback)
  const rows = Array.isArray(snapshot.rows)
    ? snapshot.rows.map((row, index) => normalizeBenchmarkLeaderboardRow(row, index, scope))
    : []
  const summary = normalizeBenchmarkSnapshotSummary(snapshot, rows)
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
    linked_run_ids: summary.linked_run_ids,
    linked_report_ids: summary.linked_report_ids,
    linked_result_batch_ids: summary.linked_result_batch_ids,
    source_run_count: summary.source_run_count,
    source_report_count: summary.source_report_count,
    source_result_batch_count: summary.source_result_batch_count,
    row_count: summary.row_count,
    rankable_count: summary.rankable_count,
    unrankable_count: summary.unrankable_count,
    content_hash: summary.content_hash,
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

function normalizeBenchmarkSnapshotServerCompare(compare, scopeFallback = 'role_version') {
  if (!compare || typeof compare !== 'object' || compare.kind !== 'benchmark_snapshot_compare') return null
  const snapshotMeta = Array.isArray(compare.snapshot)
    ? objectOrEmpty(compare.snapshot_meta || {
      snapshot_id: compare.snapshot_id,
      scope: compare.scope,
      benchmark_id: compare.benchmark_id,
      evaluation_set_id: compare.evaluation_set_id,
      target_role: compare.target_role,
      summary: compare.summary
    })
    : objectOrEmpty(compare.snapshot)
  const snapshot = normalizeBenchmarkSnapshot(
    Array.isArray(compare.snapshot) && !Array.isArray(snapshotMeta.rows)
      ? { ...snapshotMeta, rows: compare.snapshot }
      : snapshotMeta,
    scopeFallback
  )
  const againstSnapshot = normalizeBenchmarkSnapshot(compare.against_snapshot, snapshot?.scope || scopeFallback)
  const scope = normalizeBenchmarkTargetType(snapshot?.scope || compare.scope || compare.summary?.scope || scopeFallback)
  const normalizeRow = (row, index) => normalizeBenchmarkLeaderboardRow(row || {}, index, scope)
  const normalizeDelta = (row, index) => {
    const current = normalizeRow(row?.current || {}, index)
    const frozen = normalizeRow(row?.snapshot || row?.frozen || {}, index)
    return {
      ...row,
      key: String(row?.key || current.key || frozen.key || `changed-${index}`),
      current,
      snapshot: frozen,
      scoreDelta: metricNumber(row?.scoreDelta ?? row?.score_delta),
      winRateDelta: metricNumber(row?.winRateDelta ?? row?.win_rate_delta),
      gamesDelta: metricNumber(row?.gamesDelta ?? row?.games_delta),
      rankableChanged: Boolean(row?.rankableChanged ?? row?.rankable_changed),
      boundary_warnings: Array.isArray(row?.boundary_warnings) ? row.boundary_warnings : []
    }
  }
  const changed = Array.isArray(compare.changed) ? compare.changed.map(normalizeDelta) : []
  const added = Array.isArray(compare.added) ? compare.added.map(normalizeRow) : []
  const removed = Array.isArray(compare.removed) ? compare.removed.map(normalizeRow) : []
  const rawCurrentRows = Array.isArray(compare.current)
    ? compare.current
    : (Array.isArray(compare.current?.rows) ? compare.current.rows : [])
  const currentRows = rawCurrentRows.map(normalizeRow)
  const frozenRows = Array.isArray(compare.frozen?.rows)
    ? compare.frozen.rows.map(normalizeRow)
    : (Array.isArray(compare.snapshot) ? compare.snapshot.map(normalizeRow) : (snapshot?.rows || []))
  const summary = {
    ...objectOrEmpty(compare.summary),
    ...objectOrEmpty(snapshot?.summary),
    snapshot_id: String(snapshot?.snapshot_id || compare.summary?.snapshot_id || ''),
    snapshot_row_count: metricNumber(
      compare.summary?.snapshot_row_count ?? snapshot?.summary?.row_count,
      frozenRows.length
    )
  }
  return {
    ...compare,
    compare_mode: String(compare.compare_mode || compare.summary?.compare_mode || (againstSnapshot ? 'snapshot_to_snapshot' : 'current_vs_snapshot')),
    snapshot_meta: snapshot,
    against_snapshot_meta: againstSnapshot,
    scope,
    current: currentRows,
    snapshot: frozenRows,
    changed,
    added,
    removed,
    boundary_warnings: Array.isArray(compare.boundary_warnings) ? compare.boundary_warnings : [],
    summary
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
    targetTypeLabel: targetType === 'model' ? '模型评测' : '角色版本',
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
    replayHash: replayAvailable && historyGameId ? `#logs?workspace=archive&game_id=${encodeURIComponent(historyGameId)}` : '',
    replayAvailableLabel: replayAvailable ? '可回放' : '无回放'
  }
}

function normalizeBenchmarkDiagnostic(entry) {
  const targetRole = entry?.target_role || ''
  const kind = String(entry?.kind || 'diagnostic')
  const level = String(entry?.level || 'info').toLowerCase()
  const historyGameId = String(entry?.history_game_id || entry?.historyGameId || entry?.game_id || '')
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
    history_game_id: historyGameId,
    seedLabel: entry?.seed == null ? '' : String(entry.seed),
    replayHash: historyGameId ? `#logs?workspace=archive&game_id=${encodeURIComponent(historyGameId)}` : ''
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
    benchmarkTargetTypeLabel: benchmarkTargetType === 'model' ? '模型评测' : '角色版本',
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

function defaultBenchmarkViewPreferences(overrides = {}) {
  const viewConfig = normalizeBenchmarkViewConfig(overrides.view_config || overrides)
  return {
    kind: 'benchmark_saved_view',
    schema_version: 1,
    view_key: String(overrides.view_key || ''),
    name: String(overrides.name || '默认视图'),
    scope: normalizeBenchmarkTargetType(overrides.scope),
    benchmark_id: overrides.benchmark_id || null,
    evaluation_set_id: overrides.evaluation_set_id || null,
    target_role: overrides.target_role || null,
    view_config: viewConfig,
    created_at: overrides.created_at || null,
    updated_at: overrides.updated_at || null
  }
}

function normalizeBenchmarkViewConfig(raw = {}) {
  const config = raw && typeof raw === 'object' ? raw : {}
  const columns = Array.isArray(config.columns)
    ? config.columns.map((item) => String(item || '').trim()).filter(Boolean)
    : []
  const rankFilter = ['all', 'rankable', 'unrankable'].includes(config.rank_filter)
    ? config.rank_filter
    : 'all'
  return {
    mode: normalizeBenchmarkTargetType(config.mode || config.scope),
    rank_filter: rankFilter,
    columns,
    sort: String(config.sort || 'score_desc'),
    search: String(config.search || ''),
    density: String(config.density || 'standard')
  }
}

function normalizeBenchmarkView(raw, scopeFallback = 'role_version') {
  if (!raw || typeof raw !== 'object') return null
  const viewKey = String(raw.view_key || '').trim()
  if (!viewKey) return null
  return defaultBenchmarkViewPreferences({
    ...raw,
    view_key: viewKey,
    name: String(raw.name || '默认视图'),
    scope: normalizeBenchmarkTargetType(raw.scope || scopeFallback),
    view_config: normalizeBenchmarkViewConfig(raw.view_config || {})
  })
}

function useEvaluationWorkbench(options = {}) {
  const { apiFetch, apiBase } = options.apiFetch
    ? { apiFetch: options.apiFetch, apiBase: options.apiBase || '/api' }
    : createGameApi(options.apiBase)

  const benchmarkSuites = ref([])
  const benchmarkSeedSets = ref([])
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
  const legacyBenchmarkTargetType = ref('role_version')
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
  const benchmarkBatchGamesLoading = ref(false)
  const benchmarkBatchGamePagination = ref({ total: 0, offset: 0, limit: 20, returned: 0, has_more: false })
  const benchmarkBatchDiagnosticsLoading = ref(false)
  const benchmarkBatchDiagnostics = ref([])
  const benchmarkBatchDiagnosticSummary = ref({})
  const benchmarkBatchReport = ref(null)
  const benchmarkBatchReportLoading = ref(false)
  const benchmarkBatchReportError = ref('')
  const benchmarkBatchReportExports = ref({})
  const benchmarkReportHistory = ref([])
  const benchmarkReportHistoryLoading = ref(false)
  const benchmarkReportHistoryError = ref('')
  const benchmarkReportHistorySummary = ref({})
  const benchmarkReportHistoryPagination = ref({ total: 0, offset: 0, limit: 50, returned: 0, has_more: false })
  const benchmarkDiagnosticAggregateLoading = ref(false)
  const benchmarkDiagnosticAggregateError = ref('')
  const benchmarkDiagnosticAggregateDiagnostics = ref([])
  const benchmarkDiagnosticAggregateSummary = ref({})
  const benchmarkDiagnosticAggregateRuns = ref([])
  const benchmarkDiagnosticAggregateGames = ref([])
  const benchmarkDiagnosticAggregatePagination = ref({ total: 0, offset: 0, limit: 200, returned: 0, has_more: false })
  const benchmarkGameStatusFilter = ref('problem')
  const benchmarkGameSeedFilter = ref('')
  const benchmarkDiagnosticKindFilter = ref('')
  const benchmarkDiagnosticLevelFilter = ref('')
  const benchmarkDiagnosticStatusFilter = ref('')
  const benchmarkDiagnosticStageFilter = ref('')
  const benchmarkDiagnosticSeedFilter = ref('')
  const benchmarkSnapshots = ref([])
  const benchmarkSnapshotDetail = ref(null)
  const benchmarkSnapshotDetails = ref({})
  const benchmarkSnapshotLoading = ref(false)
  const benchmarkSnapshotError = ref('')
  const benchmarkSnapshotServerCompare = ref(null)
  const benchmarkSnapshotCompareLoading = ref(false)
  const benchmarkSnapshotCompareError = ref('')
  const selectedBenchmarkSnapshotId = ref('')
  const benchmarkLeaderboardCompare = ref(null)
  const benchmarkLeaderboardCompareLoading = ref(false)
  const benchmarkLeaderboardCompareError = ref('')
  const benchmarkSavedViews = ref([])
  const benchmarkSavedViewsLoading = ref(false)
  const benchmarkSavedViewsError = ref('')
  const benchmarkViewPreferences = ref(defaultBenchmarkViewPreferences())
  const benchmarkViewDirty = ref(false)
  const selectedBenchmarkViewKey = ref('')
  const suiteRequests = createLatestOnlyTracker()
  const seedSetRequests = createLatestOnlyTracker()
  const roleRequests = createLatestOnlyTracker()
  const roleBoardRequests = createLatestOnlyMap()
  const planRequests = createLatestOnlyTracker()
  const runRequests = createLatestOnlyTracker()
  const detailRequests = createLatestOnlyTracker()
  const batchGameRequests = createLatestOnlyTracker()
  const batchDiagnosticRequests = createLatestOnlyTracker()
  const reportRequests = createLatestOnlyTracker()
  const reportExportRequests = createLatestOnlyTracker()
  const reportHistoryRequests = createLatestOnlyTracker()
  const diagnosticAggregateRequests = createLatestOnlyTracker()
  const refreshRequests = createLatestOnlyTracker()
  const actionRequests = createLatestOnlyTracker()
  const snapshotRequests = createLatestOnlyTracker()
  const snapshotDetailRequests = createLatestOnlyTracker()
  const snapshotCompareRequests = createLatestOnlyTracker()
  const snapshotActionRequests = createLatestOnlyTracker()
  const leaderboardCompareRequests = createLatestOnlyTracker()
  const benchmarkViewRequests = createLatestOnlyTracker()
  const benchmarkViewActionRequests = createLatestOnlyTracker()
  let lastRunsError = null

  const form = ref({
    battle_games: 10,
    max_days: 5,
    budget_limit_units: '',
    budget_limit_cost: '',
    stop_after_budget_units: '',
    target_version_id: '',
    model_id: '',
    model_config_hash: ''
  })

  const selectedBenchmarkSuite = computed(() =>
    benchmarkSuites.value.find((suite) => suite.id === selectedBenchmarkId.value) || null
  )
  const selectedBenchmarkTargetType = computed(() =>
    selectedBenchmarkSuite.value?.target_type || legacyBenchmarkTargetType.value || 'role_version'
  )
  const selectedBenchmarkIsModelSuite = computed(() => selectedBenchmarkTargetType.value === 'model')
  const benchmarkPlanBudgetExceeded = computed(() => benchmarkBudgetExceededValue(benchmarkPlan.value?.budget || {}))
  const selectedBenchmarkEvaluationSetId = computed(() => selectedBenchmarkSuite.value?.evaluation_set_id || '')
  const selectedBenchmarkSuiteLabel = computed(() => {
    if (selectedBenchmarkSuite.value?.label) return selectedBenchmarkSuite.value.label
    return selectedBenchmarkIsModelSuite.value ? '临时模型评测' : '临时角色评测'
  })
  const selectedBenchmarkSuiteLaunchDisabledReason = computed(() => {
    const suite = selectedBenchmarkSuite.value
    if (!suite || suite.launchable !== false) return ''
    return suite.launch_disabled_reason || '该评测套件当前不可启动。'
  })
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
    !selectedBenchmarkSuiteLaunchDisabledReason.value &&
    !benchmarkPlanBudgetExceeded.value &&
    !selectedRoleTargetVersionBlockedReason.value
  )
  const currentBenchmarkLeaderboardRows = computed(() =>
    selectedBenchmarkIsModelSuite.value ? modelLeaderboardRows.value : roleLeaderboardRows.value
  )
  const benchmarkSnapshotScope = computed(() =>
    selectedBenchmarkIsModelSuite.value ? 'model' : 'role_version'
  )
  const currentBenchmarkViewKey = computed(() => {
    const suite = selectedBenchmarkId.value || 'ad-hoc'
    const evaluationSet = selectedBenchmarkEvaluationSetId.value || 'no-eval-set'
    const subject = benchmarkSnapshotScope.value === 'model' ? 'model' : (selectedRole.value || 'role')
    return `${BENCHMARK_VIEW_STORAGE_PREFIX}:${benchmarkSnapshotScope.value}:${suite}:${evaluationSet}:${subject}`
  })
  const activeBenchmarkViewConfig = computed(() =>
    normalizeBenchmarkViewConfig(benchmarkViewPreferences.value?.view_config || {})
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
    const serverCompare = benchmarkSnapshotServerCompare.value
    const activeSnapshotId = String(activeBenchmarkSnapshotDetail.value?.snapshot_id || selectedBenchmarkSnapshotId.value || '')
    const serverSnapshotId = String(serverCompare?.snapshot_meta?.snapshot_id || serverCompare?.summary?.snapshot_id || '')
    if (serverCompare && (!activeSnapshotId || !serverSnapshotId || activeSnapshotId === serverSnapshotId)) {
      return serverCompare
    }
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

  const unscopedBenchmarkRunRows = computed(() =>
    batchRunRows.value.filter((run) => !run.benchmarkId && !run.evaluationSetId)
  )

  const selectedSuiteBatchRunRows = computed(() => {
    const suite = selectedBenchmarkSuite.value
    if (!suite) return batchRunRows.value
    return batchRunRows.value.filter((run) =>
      run.benchmarkId === suite.id ||
      (suite.evaluation_set_id && run.evaluationSetId === suite.evaluation_set_id)
    )
  })

  const selectedBenchmarkUsingLegacyRuns = computed(() =>
    Boolean(selectedBenchmarkSuite.value) &&
    selectedSuiteBatchRunRows.value.length === 0 &&
    unscopedBenchmarkRunRows.value.length > 0
  )

  const filteredBatchRunRows = computed(() => {
    let rows = selectedBenchmarkUsingLegacyRuns.value
      ? unscopedBenchmarkRunRows.value
      : selectedSuiteBatchRunRows.value
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

  function budgetLimitCost() {
    if (form.value.budget_limit_cost === '' || form.value.budget_limit_cost == null) return null
    const value = Number(form.value.budget_limit_cost)
    return Number.isFinite(value) && value >= 0 ? value : null
  }

  function stopAfterBudgetUnits() {
    if (form.value.stop_after_budget_units === '' || form.value.stop_after_budget_units == null) return null
    const value = Number(form.value.stop_after_budget_units)
    return Number.isFinite(value) && value >= 0 ? Math.floor(value) : null
  }

  function benchmarkRequestPayload() {
    const budgetLimit = budgetLimitUnits()
    const costLimit = budgetLimitCost()
    const stopAfterUnits = stopAfterBudgetUnits()
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
      ...(budgetLimit == null ? {} : { budget_limit_units: budgetLimit }),
      ...(costLimit == null ? {} : { budget_limit_cost: costLimit }),
      ...(stopAfterUnits == null ? {} : { stop_after_budget_units: stopAfterUnits })
    }
  }

  function benchmarkSnapshotRequestPayload(overrides = {}) {
    const suite = selectedBenchmarkSuite.value || {}
    const benchmarkVersion = Number(suite.version)
    const evaluationSetId = selectedBenchmarkEvaluationSetId.value
    const scope = benchmarkSnapshotScope.value
    const activeView = normalizeBenchmarkViewConfig({
      ...activeBenchmarkViewConfig.value,
      ...(overrides.view_config || overrides.viewConfig || {}),
      mode: scope
    })
    const defaultColumns = scope === 'model'
      ? ['model_id', 'model_config_hash', 'strength_score', 'target_side_win_rate', 'rankable']
      : ['target_version_id', 'avg_role_score', 'target_side_win_rate', 'rankable']
    const snapshotColumns = activeView.columns.length ? activeView.columns : defaultColumns
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
        view_key: selectedBenchmarkViewKey.value || currentBenchmarkViewKey.value,
        view_name: benchmarkViewPreferences.value?.name || '默认视图',
        rank_filter: activeView.rank_filter,
        sort: activeView.sort,
        search: activeView.search,
        density: activeView.density,
        suite_id: selectedBenchmarkId.value || '',
        role: scope === 'role_version' ? selectedRole.value : '',
        columns: snapshotColumns
      },
      limit: Number(overrides.limit || 100)
    }
  }

  function defaultSnapshotTitle() {
    const suite = selectedBenchmarkSuiteLabel.value || '评测'
    const scope = benchmarkSnapshotScope.value === 'model' ? '模型' : selectedRoleLabel.value
    return `${suite} / ${scope} 快照`
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

  function benchmarkSnapshotComparePath(snapshotId, limit = 100, againstSnapshotId = '') {
    const query = new URLSearchParams()
    if (againstSnapshotId) query.set('against_snapshot_id', String(againstSnapshotId))
    query.set('limit', String(limit))
    return `/benchmark/snapshots/${encodeURIComponent(snapshotId)}/compare?${query.toString()}`
  }

  function benchmarkLeaderboardComparePath(limit = 100) {
    const query = new URLSearchParams()
    query.set('scope', benchmarkSnapshotScope.value)
    if (selectedBenchmarkEvaluationSetId.value) {
      query.set('evaluation_set_id', selectedBenchmarkEvaluationSetId.value)
    }
    if (benchmarkSnapshotScope.value === 'role_version' && selectedRole.value) {
      query.set('target_role', selectedRole.value)
    }
    query.set('limit', String(limit))
    return `/leaderboards/compare?${query.toString()}`
  }

  function benchmarkViewBoundaryPayload() {
    return {
      scope: benchmarkSnapshotScope.value,
      benchmark_id: selectedBenchmarkId.value || null,
      evaluation_set_id: selectedBenchmarkEvaluationSetId.value || null,
      target_role: benchmarkSnapshotScope.value === 'model' ? null : (selectedRole.value || null)
    }
  }

  function currentDefaultBenchmarkView() {
    return defaultBenchmarkViewPreferences({
      ...benchmarkViewBoundaryPayload(),
      view_key: currentBenchmarkViewKey.value,
      name: '默认视图',
      view_config: {
        mode: benchmarkSnapshotScope.value,
        rank_filter: 'all',
        columns: []
      }
    })
  }

  function benchmarkViewListPath(limit = 50) {
    const query = new URLSearchParams()
    const boundary = benchmarkViewBoundaryPayload()
    query.set('scope', boundary.scope)
    if (boundary.evaluation_set_id) query.set('evaluation_set_id', boundary.evaluation_set_id)
    if (boundary.benchmark_id) query.set('benchmark_id', boundary.benchmark_id)
    if (boundary.target_role) query.set('target_role', boundary.target_role)
    query.set('limit', String(limit))
    return `/benchmark/views?${query.toString()}`
  }

  function benchmarkViewStorage() {
    try {
      return typeof window === 'undefined' ? null : window.localStorage
    } catch {
      return null
    }
  }

  function writeLocalBenchmarkView(view) {
    const storage = benchmarkViewStorage()
    if (!storage || !view?.view_key) return
    try {
      storage.setItem(view.view_key, JSON.stringify(view))
    } catch {}
  }

  function readLocalBenchmarkView(viewKey = currentBenchmarkViewKey.value) {
    const key = String(viewKey || '').trim()
    const storage = benchmarkViewStorage()
    if (!storage || !key) return null
    try {
      return normalizeBenchmarkView(JSON.parse(storage.getItem(key) || 'null'), benchmarkSnapshotScope.value)
    } catch {
      return null
    }
  }

  function removeLocalBenchmarkView(viewKey = currentBenchmarkViewKey.value) {
    const key = String(viewKey || '').trim()
    const storage = benchmarkViewStorage()
    if (!storage || !key) return
    try {
      storage.removeItem(key)
    } catch {}
  }

  function applyBenchmarkViewPreferences(raw, { dirty = false } = {}) {
    const view = normalizeBenchmarkView(raw, benchmarkSnapshotScope.value) || currentDefaultBenchmarkView()
    const boundary = benchmarkViewBoundaryPayload()
    selectedBenchmarkViewKey.value = view.view_key || currentBenchmarkViewKey.value
    benchmarkViewPreferences.value = {
      ...view,
      ...boundary,
      view_key: selectedBenchmarkViewKey.value,
      view_config: {
        ...normalizeBenchmarkViewConfig(view.view_config || {}),
        mode: boundary.scope
      }
    }
    benchmarkViewDirty.value = dirty
    return benchmarkViewPreferences.value
  }

  function setBenchmarkViewPreference(patch = {}) {
    const current = benchmarkViewPreferences.value?.view_key
      ? benchmarkViewPreferences.value
      : currentDefaultBenchmarkView()
    const boundary = benchmarkViewBoundaryPayload()
    const { name, view_config: viewConfigPatch, ...configPatch } = patch || {}
    const nextConfig = normalizeBenchmarkViewConfig({
      ...current.view_config,
      ...configPatch,
      ...(viewConfigPatch && typeof viewConfigPatch === 'object' ? viewConfigPatch : {}),
      mode: boundary.scope
    })
    benchmarkViewPreferences.value = {
      ...current,
      ...boundary,
      view_key: selectedBenchmarkViewKey.value || currentBenchmarkViewKey.value,
      name: name == null ? current.name : String(name || '默认视图'),
      view_config: nextConfig
    }
    selectedBenchmarkViewKey.value = benchmarkViewPreferences.value.view_key
    benchmarkViewDirty.value = true
    return benchmarkViewPreferences.value
  }

  async function loadBenchmarkLeaderboardCompare({ limit = 100, silent = false } = {}) {
    if (benchmarkSnapshotScope.value === 'role_version' && !selectedRole.value) {
      benchmarkLeaderboardCompare.value = null
      benchmarkLeaderboardCompareError.value = ''
      return false
    }
    const token = leaderboardCompareRequests.next()
    if (!silent) benchmarkLeaderboardCompareLoading.value = true
    benchmarkLeaderboardCompareError.value = ''
    try {
      const data = await apiFetch(benchmarkLeaderboardComparePath(limit))
      if (!token.isLatest()) return false
      benchmarkLeaderboardCompare.value = data?.kind === 'benchmark_leaderboard_compare' ? data : null
      return Boolean(benchmarkLeaderboardCompare.value)
    } catch (err) {
      if (token.isLatest()) {
        benchmarkLeaderboardCompare.value = null
        benchmarkLeaderboardCompareError.value = benchmarkErrorMessage(err, '榜单比较 API 不可用，已使用本地比较。')
      }
      return false
    } finally {
      if (token.isLatest() && !silent) benchmarkLeaderboardCompareLoading.value = false
    }
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

  function setNotice(type, message, extra = {}) {
    notice.value = { type, message, ...(extra && typeof extra === 'object' ? extra : {}) }
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
    if (filter === 'problem') return 'problem'
    return filter
  }

  function defaultBenchmarkGamePagination(offset = 0, limit = 20) {
    return { total: 0, offset, limit, returned: 0, has_more: false }
  }

  function benchmarkBatchGamesPath(batchId, { offset = 0, limit = 20 } = {}) {
    const query = new URLSearchParams()
    const statusFilter = gameStatusFilterQuery()
    const seedFilter = String(benchmarkGameSeedFilter.value || '').trim()
    if (statusFilter) query.set('status', statusFilter)
    if (seedFilter) query.set('seed', seedFilter)
    query.set('limit', String(limit))
    query.set('offset', String(offset))
    return `/benchmark/batch/${encodeURIComponent(batchId)}/games?${query.toString()}`
  }

  function benchmarkBatchDiagnosticsPath(batchId) {
    const query = new URLSearchParams()
    const filters = [
      ['kind', benchmarkDiagnosticKindFilter.value],
      ['level', benchmarkDiagnosticLevelFilter.value],
      ['status', benchmarkDiagnosticStatusFilter.value],
      ['stage', benchmarkDiagnosticStageFilter.value],
      ['seed', benchmarkDiagnosticSeedFilter.value]
    ]
    for (const [key, value] of filters) {
      const text = String(value || '').trim()
      if (text) query.set(key, text)
    }
    const suffix = query.toString()
    return `/benchmark/batch/${encodeURIComponent(batchId)}/diagnostics${suffix ? `?${suffix}` : ''}`
  }

  function mergeBenchmarkGames(current, next) {
    const rows = []
    const seen = new Set()
    for (const game of [...current, ...next]) {
      const key = `${game?.result_batch_id || ''}:${game?.game_id || game?.id || ''}:${game?.seedLabel || ''}`
      if (seen.has(key)) continue
      seen.add(key)
      rows.push(game)
    }
    return rows
  }

  function clearBenchmarkBatchDetail() {
    benchmarkDetailError.value = ''
    benchmarkBatchDetail.value = null
    benchmarkBatchGames.value = []
    benchmarkBatchGamesLoading.value = false
    benchmarkBatchGamePagination.value = defaultBenchmarkGamePagination()
    benchmarkBatchDiagnosticsLoading.value = false
    benchmarkBatchDiagnostics.value = []
    benchmarkBatchDiagnosticSummary.value = {}
    benchmarkBatchReport.value = null
    benchmarkBatchReportLoading.value = false
    benchmarkBatchReportError.value = ''
    benchmarkBatchReportExports.value = {}
  }

  function benchmarkBatchReportPath(batchId, format = 'json') {
    const path = `/benchmark/batch/${encodeURIComponent(batchId)}/report`
    const normalized = String(format || 'json').toLowerCase()
    if (!normalized || normalized === 'json') return path
    const query = new URLSearchParams()
    query.set('format', normalized)
    return `${path}?${query.toString()}`
  }

  function normalizeBenchmarkBatchReport(report) {
    if (!report || typeof report !== 'object' || Array.isArray(report)) return null
    if (report.kind && report.kind !== 'benchmark_run_report') return null
    return report
  }

  function reportExportCacheKey(batchId, format) {
    return `${batchId}:${String(format || 'markdown').toLowerCase()}`
  }

  function benchmarkReportHistoryPath(limit = 50, offset = 0) {
    const query = new URLSearchParams()
    query.set('scope', selectedBenchmarkTargetType.value)
    if (selectedBenchmarkEvaluationSetId.value) {
      query.set('evaluation_set_id', selectedBenchmarkEvaluationSetId.value)
    }
    if (selectedBenchmarkId.value) {
      query.set('benchmark_id', selectedBenchmarkId.value)
    }
    if (!selectedBenchmarkIsModelSuite.value && selectedRole.value) {
      query.set('target_role', selectedRole.value)
    }
    if (selectedBenchmarkIsModelSuite.value && form.value.model_id) {
      query.set('model_id', form.value.model_id)
    }
    if (selectedBenchmarkIsModelSuite.value && form.value.model_config_hash) {
      query.set('model_config_hash', form.value.model_config_hash)
    }
    query.set('limit', String(limit))
    query.set('offset', String(offset))
    return `/benchmark/reports?${query.toString()}`
  }

  function normalizeBenchmarkReportSummary(item) {
    if (!item || typeof item !== 'object') return null
    const batchId = String(item.batch_id || item.run_id || '').trim()
    if (!batchId) return null
    const suite = objectOrEmpty(item.suite)
    const subject = objectOrEmpty(item.subject)
    const summary = objectOrEmpty(item.summary)
    return {
      ...item,
      report_id: String(item.report_id || `benchmark_report:${batchId}`),
      run_id: String(item.run_id || batchId),
      batch_id: batchId,
      id: batchId,
      status: String(item.status || '').trim(),
      statusLabel: statusText(item.status),
      scope: normalizeBenchmarkTargetType(item.scope || item.target_type || suite.target_type),
      target_type: normalizeBenchmarkTargetType(item.target_type || item.scope || suite.target_type),
      benchmark_id: String(item.benchmark_id || suite.benchmark_id || ''),
      evaluation_set_id: String(item.evaluation_set_id || suite.evaluation_set_id || ''),
      seed_set_id: String(item.seed_set_id || suite.seed_set_id || ''),
      benchmark_config_hash: String(item.benchmark_config_hash || suite.benchmark_config_hash || ''),
      suite,
      subject,
      subjectLabel: String(subject.label || subject.model_id || subject.target_version_id || subject.target_role || 'benchmark subject'),
      suiteLabel: String(suite.label || item.benchmark_id || item.evaluation_set_id || 'ad-hoc benchmark'),
      summary,
      result_count: metricNumber(item.result_count ?? summary.result_count),
      rankable_count: metricNumber(item.rankable_count ?? summary.rankable_count),
      unrankable_count: metricNumber(item.unrankable_count ?? summary.unrankable_count),
      problem_game_count: metricNumber(item.problem_game_count ?? summary.problem_game_count),
      diagnostic_count: metricNumber(item.diagnostic_count ?? summary.diagnostic_summary?.total),
      content_hash: String(item.content_hash || ''),
      created_at: String(item.created_at || item.generated_at || item.finished_at || item.started_at || ''),
      generated_at: String(item.generated_at || '')
    }
  }

  async function loadBenchmarkBatchReport(batchId = selectedBenchmarkBatchId.value, { silent = false } = {}) {
    const id = String(batchId || '').trim()
    if (!id) {
      benchmarkBatchReport.value = null
      benchmarkBatchReportError.value = ''
      benchmarkBatchReportExports.value = {}
      return false
    }
    const token = reportRequests.next()
    if (!silent) benchmarkBatchReportLoading.value = true
    benchmarkBatchReportError.value = ''
    try {
      const report = normalizeBenchmarkBatchReport(await apiFetch(benchmarkBatchReportPath(id)))
      if (!token.isLatest()) return false
      if (!report) throw new Error('invalid benchmark report payload')
      benchmarkBatchReport.value = report
      benchmarkBatchReportExports.value = {}
      return true
    } catch (err) {
      if (token.isLatest()) {
        benchmarkBatchReport.value = null
        benchmarkBatchReportExports.value = {}
        benchmarkBatchReportError.value = benchmarkErrorMessage(err, '评测报告读取失败，已使用本地报告。')
      }
      return false
    } finally {
      if (token.isLatest() && !silent) benchmarkBatchReportLoading.value = false
    }
  }

  async function loadBenchmarkBatchReportExport(format = 'markdown', batchId = selectedBenchmarkBatchId.value) {
    const id = String(batchId || '').trim()
    const normalized = String(format || 'markdown').toLowerCase()
    if (!id) return ''
    if (normalized === 'json') {
      if (!benchmarkBatchReport.value || String(benchmarkBatchReport.value.batch_id || benchmarkBatchReport.value.run_id || '') !== id) {
        await loadBenchmarkBatchReport(id, { silent: true })
      }
      return benchmarkBatchReport.value ? JSON.stringify(benchmarkBatchReport.value, null, 2) : ''
    }
    if (!['markdown', 'csv'].includes(normalized)) return ''
    const cacheKey = reportExportCacheKey(id, normalized)
    if (benchmarkBatchReportExports.value[cacheKey]) return benchmarkBatchReportExports.value[cacheKey]
    const token = reportExportRequests.next()
    try {
      const data = await apiFetch(benchmarkBatchReportPath(id, normalized))
      if (!token.isLatest()) return ''
      const content = typeof data?.content === 'string' ? data.content : ''
      if (!content) throw new Error('invalid benchmark report export payload')
      benchmarkBatchReportExports.value = {
        ...benchmarkBatchReportExports.value,
        [cacheKey]: content
      }
      if (data?.report) benchmarkBatchReport.value = normalizeBenchmarkBatchReport(data.report) || benchmarkBatchReport.value
      benchmarkBatchReportError.value = ''
      return content
    } catch (err) {
      if (token.isLatest()) {
        benchmarkBatchReportError.value = benchmarkErrorMessage(err, '评测报告导出失败，已使用本地导出。')
      }
      return ''
    }
  }

  async function loadBenchmarkReportHistory({ limit = 50, offset = 0, silent = false } = {}) {
    const token = reportHistoryRequests.next()
    if (!silent) benchmarkReportHistoryLoading.value = true
    benchmarkReportHistoryError.value = ''
    try {
      const data = await apiFetch(benchmarkReportHistoryPath(limit, offset))
      if (!token.isLatest()) return false
      const items = Array.isArray(data?.items) ? data.items : []
      benchmarkReportHistory.value = items.map(normalizeBenchmarkReportSummary).filter(Boolean)
      benchmarkReportHistorySummary.value = objectOrEmpty(data?.summary)
      benchmarkReportHistoryPagination.value = data?.pagination || {
        total: benchmarkReportHistory.value.length,
        offset,
        limit,
        returned: benchmarkReportHistory.value.length,
        has_more: false
      }
      return true
    } catch (err) {
      if (token.isLatest()) {
        benchmarkReportHistory.value = []
        benchmarkReportHistorySummary.value = {}
        benchmarkReportHistoryPagination.value = { total: 0, offset, limit, returned: 0, has_more: false }
        benchmarkReportHistoryError.value = benchmarkErrorMessage(err, '评测报告历史不可用。')
      }
      return false
    } finally {
      if (token.isLatest() && !silent) benchmarkReportHistoryLoading.value = false
    }
  }

  function benchmarkDiagnosticsAggregatePath(limit = 200) {
    const query = new URLSearchParams()
    query.set('scope', selectedBenchmarkTargetType.value)
    if (selectedBenchmarkEvaluationSetId.value) {
      query.set('evaluation_set_id', selectedBenchmarkEvaluationSetId.value)
    }
    if (selectedBenchmarkId.value) {
      query.set('benchmark_id', selectedBenchmarkId.value)
    }
    if (!selectedBenchmarkIsModelSuite.value && selectedRole.value) {
      query.set('target_role', selectedRole.value)
    }
    const filters = [
      ['kind', benchmarkDiagnosticKindFilter.value],
      ['level', benchmarkDiagnosticLevelFilter.value],
      ['status', benchmarkDiagnosticStatusFilter.value],
      ['stage', benchmarkDiagnosticStageFilter.value],
      ['seed', benchmarkDiagnosticSeedFilter.value]
    ]
    for (const [key, value] of filters) {
      const text = String(value || '').trim()
      if (text) query.set(key, text)
    }
    query.set('limit', String(limit))
    query.set('offset', '0')
    return `/benchmark/diagnostics?${query.toString()}`
  }

  async function loadBenchmarkDiagnosticsAggregate({ limit = 200, silent = false } = {}) {
    const token = diagnosticAggregateRequests.next()
    if (!silent) benchmarkDiagnosticAggregateLoading.value = true
    benchmarkDiagnosticAggregateError.value = ''
    try {
      const data = await apiFetch(benchmarkDiagnosticsAggregatePath(limit))
      if (!token.isLatest()) return false
      benchmarkDiagnosticAggregateDiagnostics.value = (data?.diagnostics || []).map(normalizeBenchmarkDiagnostic)
      benchmarkDiagnosticAggregateSummary.value = data?.summary || {}
      benchmarkDiagnosticAggregateRuns.value = (data?.affected_runs || []).map(normalizeBatchRun)
      benchmarkDiagnosticAggregateGames.value = (data?.affected_games || []).map(normalizeBenchmarkGame)
      benchmarkDiagnosticAggregatePagination.value = data?.pagination || {
        total: benchmarkDiagnosticAggregateDiagnostics.value.length,
        offset: 0,
        limit,
        returned: benchmarkDiagnosticAggregateDiagnostics.value.length,
        has_more: false
      }
      return true
    } catch (err) {
      if (token.isLatest()) {
        benchmarkDiagnosticAggregateDiagnostics.value = []
        benchmarkDiagnosticAggregateSummary.value = {}
        benchmarkDiagnosticAggregateRuns.value = []
        benchmarkDiagnosticAggregateGames.value = []
        benchmarkDiagnosticAggregatePagination.value = { total: 0, offset: 0, limit, returned: 0, has_more: false }
        benchmarkDiagnosticAggregateError.value = benchmarkErrorMessage(err, '评测 diagnostics 聚合不可用。')
      }
      return false
    } finally {
      if (token.isLatest() && !silent) benchmarkDiagnosticAggregateLoading.value = false
    }
  }

  function benchmarkSeedRegistryById() {
    return new Map(
      benchmarkSeedSets.value
        .map((seedSet) => [String(seedSet?.id || seedSet?.seed_set_id || '').trim(), seedSet])
        .filter(([id]) => id)
    )
  }

  async function loadBenchmarkSeedSets() {
    const token = seedSetRequests.next()
    try {
      const registry = normalizeBenchmarkSeedRegistry(await apiFetch('/benchmark/seed-sets'))
      if (!token.isLatest()) return false
      benchmarkSeedSets.value = registry.items
      return true
    } catch {
      if (token.isLatest()) benchmarkSeedSets.value = []
      return false
    }
  }

  async function loadBenchmarkSuites() {
    const token = suiteRequests.next()
    benchmarkSuiteError.value = ''
    try {
      await loadBenchmarkSeedSets()
      if (!token.isLatest()) return false
      const seedRegistryById = benchmarkSeedRegistryById()
      const data = await apiFetch('/benchmarks')
      if (!token.isLatest()) return false
      const items = Array.isArray(data) ? data : (data?.items || data?.benchmarks || [])
      benchmarkSuites.value = items.map((item) => normalizeBenchmarkSuite(item, seedRegistryById)).filter(Boolean)
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
    if (selectedBenchmarkSuiteLaunchDisabledReason.value) {
      benchmarkPlan.value = null
      benchmarkPlanError.value = selectedBenchmarkSuiteLaunchDisabledReason.value
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
      const gamesPath = benchmarkBatchGamesPath(id)
      benchmarkBatchReportLoading.value = true
      benchmarkBatchDiagnosticsLoading.value = true
      benchmarkBatchReportError.value = ''
      const reportRequest = apiFetch(benchmarkBatchReportPath(id))
        .then((report) => ({ ok: true, report: normalizeBenchmarkBatchReport(report) }))
        .catch((err) => ({ ok: false, err }))
      const [detail, games, diagnostics, reportResult] = await Promise.all([
        apiFetch(`/benchmark/batch/${encodeURIComponent(id)}`),
        apiFetch(gamesPath),
        apiFetch(benchmarkBatchDiagnosticsPath(id)),
        reportRequest
      ])
      if (!token.isLatest()) return false
      benchmarkBatchDetail.value = normalizeBenchmarkBatchDetail(detail)
      benchmarkBatchGames.value = (games?.games || []).map(normalizeBenchmarkGame)
      benchmarkBatchGamePagination.value = games?.pagination || defaultBenchmarkGamePagination()
      benchmarkBatchDiagnostics.value = (diagnostics?.diagnostics || []).map(normalizeBenchmarkDiagnostic)
      benchmarkBatchDiagnosticSummary.value = diagnostics?.summary || {}
      if (reportResult?.ok && reportResult.report) {
        benchmarkBatchReport.value = reportResult.report
        benchmarkBatchReportError.value = ''
        benchmarkBatchReportExports.value = {}
      } else {
        benchmarkBatchReport.value = null
        benchmarkBatchReportExports.value = {}
        benchmarkBatchReportError.value = benchmarkErrorMessage(reportResult?.err, '评测报告读取失败，已使用本地报告。')
      }
      return true
    } catch (err) {
      if (token.isLatest()) {
        benchmarkDetailError.value = benchmarkErrorMessage(err, '评测详情读取失败。')
        benchmarkBatchDetail.value = null
        benchmarkBatchGames.value = []
        benchmarkBatchGamePagination.value = defaultBenchmarkGamePagination()
        benchmarkBatchDiagnosticsLoading.value = false
        benchmarkBatchDiagnostics.value = []
        benchmarkBatchDiagnosticSummary.value = {}
        benchmarkBatchReport.value = null
        benchmarkBatchReportError.value = ''
        benchmarkBatchReportExports.value = {}
      }
      return false
    } finally {
      if (token.isLatest()) {
        benchmarkDetailLoading.value = false
        benchmarkBatchReportLoading.value = false
        benchmarkBatchDiagnosticsLoading.value = false
      }
    }
  }

  async function loadBenchmarkBatchDiagnostics(batchId = selectedBenchmarkBatchId.value) {
    const id = String(batchId || '').trim()
    if (!id) {
      benchmarkBatchDiagnostics.value = []
      benchmarkBatchDiagnosticSummary.value = {}
      return false
    }
    const token = batchDiagnosticRequests.next()
    benchmarkBatchDiagnosticsLoading.value = true
    benchmarkDetailError.value = ''
    try {
      const data = await apiFetch(benchmarkBatchDiagnosticsPath(id))
      if (!token.isLatest()) return false
      benchmarkBatchDiagnostics.value = (data?.diagnostics || []).map(normalizeBenchmarkDiagnostic)
      benchmarkBatchDiagnosticSummary.value = data?.summary || {}
      return true
    } catch (err) {
      if (token.isLatest()) {
        benchmarkDetailError.value = benchmarkErrorMessage(err, '评测诊断读取失败。')
        benchmarkBatchDiagnostics.value = []
        benchmarkBatchDiagnosticSummary.value = {}
      }
      return false
    } finally {
      if (token.isLatest()) benchmarkBatchDiagnosticsLoading.value = false
    }
  }

  async function loadBenchmarkBatchGamesPage({ offset = 0, limit = 20, append = false } = {}) {
    const id = String(selectedBenchmarkBatchId.value || '').trim()
    if (!id) {
      benchmarkBatchGames.value = []
      benchmarkBatchGamePagination.value = defaultBenchmarkGamePagination()
      return false
    }
    const token = batchGameRequests.next()
    benchmarkBatchGamesLoading.value = true
    benchmarkDetailError.value = ''
    try {
      const data = await apiFetch(benchmarkBatchGamesPath(id, { offset, limit }))
      if (!token.isLatest()) return false
      const rows = (data?.games || []).map(normalizeBenchmarkGame)
      benchmarkBatchGames.value = append ? mergeBenchmarkGames(benchmarkBatchGames.value, rows) : rows
      benchmarkBatchGamePagination.value = data?.pagination || defaultBenchmarkGamePagination(offset, limit)
      return true
    } catch (err) {
      if (token.isLatest()) {
        benchmarkDetailError.value = benchmarkErrorMessage(err, '评测对局读取失败。')
        if (!append) {
          benchmarkBatchGames.value = []
          benchmarkBatchGamePagination.value = defaultBenchmarkGamePagination()
        }
      }
      return false
    } finally {
      if (token.isLatest()) benchmarkBatchGamesLoading.value = false
    }
  }

  function loadNextBenchmarkBatchGamesPage() {
    const pagination = benchmarkBatchGamePagination.value || {}
    if (!pagination.has_more || benchmarkBatchGamesLoading.value) return false
    const offset = Number(pagination.offset || 0) + Number(pagination.returned || benchmarkBatchGames.value.length || 0)
    const limit = Number(pagination.limit || 20) || 20
    void loadBenchmarkBatchGamesPage({ offset, limit, append: true })
    return true
  }

  function selectBenchmarkBatch(batchId) {
    const id = String(batchId || '').trim()
    if (!id) {
      selectedBenchmarkBatchId.value = ''
      clearBenchmarkBatchDetail()
      void loadBenchmarkDiagnosticsAggregate({ silent: true })
      return false
    }
    return loadBenchmarkBatchDetail(id)
  }

  function setBenchmarkGameStatusFilter(status) {
    benchmarkGameStatusFilter.value = String(status || 'problem')
    if (selectedBenchmarkBatchId.value) {
      void loadBenchmarkBatchGamesPage({ offset: 0, append: false })
    }
  }

  function setBenchmarkGameSeedFilter(seed) {
    benchmarkGameSeedFilter.value = String(seed || '').trim()
    if (selectedBenchmarkBatchId.value) {
      void loadBenchmarkBatchGamesPage({ offset: 0, append: false })
    }
  }

  function setBenchmarkDiagnosticFilter(name, value) {
    const text = String(value || '').trim()
    if (name === 'kind') benchmarkDiagnosticKindFilter.value = text
    if (name === 'level') benchmarkDiagnosticLevelFilter.value = text
    if (name === 'status') benchmarkDiagnosticStatusFilter.value = text
    if (name === 'stage') benchmarkDiagnosticStageFilter.value = text
    if (name === 'seed') benchmarkDiagnosticSeedFilter.value = text
    if (selectedBenchmarkBatchId.value) {
      void loadBenchmarkBatchDiagnostics(selectedBenchmarkBatchId.value)
    } else {
      void loadBenchmarkDiagnosticsAggregate({ silent: true })
    }
  }

  function clearBenchmarkDiagnosticFilters() {
    benchmarkDiagnosticKindFilter.value = ''
    benchmarkDiagnosticLevelFilter.value = ''
    benchmarkDiagnosticStatusFilter.value = ''
    benchmarkDiagnosticStageFilter.value = ''
    benchmarkDiagnosticSeedFilter.value = ''
    if (selectedBenchmarkBatchId.value) {
      void loadBenchmarkBatchDiagnostics(selectedBenchmarkBatchId.value)
    } else {
      void loadBenchmarkDiagnosticsAggregate({ silent: true })
    }
  }

  async function loadBenchmarkSnapshots({ limit = 50, silent = false } = {}) {
    if (benchmarkSnapshotScope.value === 'role_version' && !selectedRole.value) {
      benchmarkSnapshots.value = []
      selectedBenchmarkSnapshotId.value = ''
      benchmarkSnapshotDetail.value = null
      benchmarkSnapshotServerCompare.value = null
      benchmarkSnapshotCompareError.value = ''
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
        benchmarkSnapshotServerCompare.value = null
        benchmarkSnapshotCompareError.value = ''
      }
      return true
    } catch (err) {
      if (token.isLatest()) {
        benchmarkSnapshots.value = []
        selectedBenchmarkSnapshotId.value = ''
        benchmarkSnapshotDetail.value = null
        benchmarkSnapshotServerCompare.value = null
        benchmarkSnapshotCompareError.value = ''
        benchmarkSnapshotError.value = benchmarkErrorMessage(err, '评测快照列表不可用。')
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
      benchmarkSnapshotServerCompare.value = null
      benchmarkSnapshotCompareError.value = ''
      return false
    }
    const cached = benchmarkSnapshotDetails.value[id]
    selectedBenchmarkSnapshotId.value = id
    if (!force && cached?.rows?.length) {
      benchmarkSnapshotDetail.value = cached
      await loadBenchmarkSnapshotCompare(id, { silent: true })
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
      await loadBenchmarkSnapshotCompare(detail.snapshot_id, { silent: true })
      return true
    } catch (err) {
      if (token.isLatest()) {
        benchmarkSnapshotError.value = benchmarkErrorMessage(err, '评测快照详情读取失败。')
        benchmarkSnapshotDetail.value = null
        benchmarkSnapshotServerCompare.value = null
        benchmarkSnapshotCompareError.value = ''
      }
      return false
    } finally {
      if (token.isLatest()) benchmarkSnapshotLoading.value = false
    }
  }

  async function selectBenchmarkSnapshot(snapshotId) {
    return loadBenchmarkSnapshotDetail(snapshotId, { force: true })
  }

  async function loadBenchmarkSnapshotCompare(snapshotId = selectedBenchmarkSnapshotId.value, { againstSnapshotId = '', limit = 100, silent = false } = {}) {
    const id = String(snapshotId || '').trim()
    if (!id) {
      benchmarkSnapshotServerCompare.value = null
      benchmarkSnapshotCompareError.value = ''
      return false
    }
    const token = snapshotCompareRequests.next()
    if (!silent) benchmarkSnapshotCompareLoading.value = true
    benchmarkSnapshotCompareError.value = ''
    try {
      const data = await apiFetch(benchmarkSnapshotComparePath(id, limit, againstSnapshotId))
      if (!token.isLatest()) return false
      const compare = normalizeBenchmarkSnapshotServerCompare(data, benchmarkSnapshotScope.value)
      benchmarkSnapshotServerCompare.value = compare
      if (!compare) throw new Error('invalid benchmark snapshot compare payload')
      return true
    } catch (err) {
      if (token.isLatest()) {
        benchmarkSnapshotServerCompare.value = null
        benchmarkSnapshotCompareError.value = benchmarkErrorMessage(err, '评测快照对比 API 不可用，已使用本地比较。')
      }
      return false
    } finally {
      if (token.isLatest() && !silent) benchmarkSnapshotCompareLoading.value = false
    }
  }

  async function createBenchmarkSnapshot(overrides = {}) {
    if (benchmarkSnapshotScope.value === 'role_version' && !selectedRole.value) {
      const message = '请选择一个角色后再创建快照。'
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
      await loadBenchmarkSnapshotCompare(detail.snapshot_id, { silent: true })
      setNotice('success', '评测快照已创建。')
      return detail
    } catch (err) {
      if (token.isLatest()) {
        const message = benchmarkErrorMessage(err, '创建评测快照失败。')
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
      return normalizeBenchmarkView(await apiFetch(`/benchmark/views/${encodeURIComponent(key)}`), benchmarkSnapshotScope.value)
    } catch {
      return null
    }
  }

  async function loadBenchmarkViews({ limit = 50, silent = false } = {}) {
    const token = benchmarkViewRequests.next()
    if (!silent) benchmarkSavedViewsLoading.value = true
    benchmarkSavedViewsError.value = ''
    try {
      const data = await apiFetch(benchmarkViewListPath(limit))
      if (!token.isLatest()) return false
      const items = Array.isArray(data?.items) ? data.items : []
      benchmarkSavedViews.value = items.map((item) => normalizeBenchmarkView(item, benchmarkSnapshotScope.value)).filter(Boolean)
      return true
    } catch (err) {
      if (token.isLatest()) {
        benchmarkSavedViews.value = []
        benchmarkSavedViewsError.value = benchmarkErrorMessage(err, '评测保存视图不可用。')
      }
      return false
    } finally {
      if (token.isLatest() && !silent) benchmarkSavedViewsLoading.value = false
    }
  }

  async function loadCurrentBenchmarkView(viewKey = currentBenchmarkViewKey.value) {
    const key = String(viewKey || '').trim() || currentBenchmarkViewKey.value
    selectedBenchmarkViewKey.value = key
    applyBenchmarkViewPreferences(readLocalBenchmarkView(key) || { ...currentDefaultBenchmarkView(), view_key: key })
    const serverView = await loadBenchmarkView(key)
    if (serverView) {
      applyBenchmarkViewPreferences(serverView)
      writeLocalBenchmarkView(serverView)
      return serverView
    }
    return benchmarkViewPreferences.value
  }

  async function selectBenchmarkView(viewKey) {
    return loadCurrentBenchmarkView(viewKey)
  }

  async function saveBenchmarkView(payload = {}) {
    const viewKey = String(payload.view_key || '').trim()
    if (!viewKey) return null
    const saved = normalizeBenchmarkView(await apiFetch('/benchmark/views', {
      method: 'POST',
      body: JSON.stringify(payload)
    }), benchmarkSnapshotScope.value)
    if (saved) {
      writeLocalBenchmarkView(saved)
      benchmarkSavedViews.value = [
        saved,
        ...benchmarkSavedViews.value.filter((view) => view.view_key !== saved.view_key)
      ]
      if (selectedBenchmarkViewKey.value === saved.view_key || currentBenchmarkViewKey.value === saved.view_key) {
        applyBenchmarkViewPreferences(saved)
      }
    }
    return saved
  }

  async function saveCurrentBenchmarkView(overrides = {}) {
    const token = benchmarkViewActionRequests.next()
    const boundary = benchmarkViewBoundaryPayload()
    const current = setBenchmarkViewPreference({
      ...(overrides.name == null ? {} : { name: overrides.name }),
      ...(overrides.view_config || {})
    })
    const viewKey = String(overrides.view_key || current.view_key || currentBenchmarkViewKey.value).trim()
    const payload = {
      view_key: viewKey,
      name: String(overrides.name || current.name || '默认视图'),
      ...boundary,
      view_config: normalizeBenchmarkViewConfig({
        ...current.view_config,
        ...(overrides.view_config || {}),
        mode: boundary.scope
      })
    }
    writeLocalBenchmarkView(payload)
    try {
      const saved = await saveBenchmarkView(payload)
      if (!token.isLatest() || !saved) return payload
      benchmarkViewDirty.value = false
      return saved
    } catch {
      benchmarkViewDirty.value = true
      return payload
    }
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

  async function resetCurrentBenchmarkView(defaultConfig = {}) {
    const key = selectedBenchmarkViewKey.value || currentBenchmarkViewKey.value
    removeLocalBenchmarkView(key)
    await deleteBenchmarkView(key)
    const defaults = currentDefaultBenchmarkView()
    applyBenchmarkViewPreferences({
      ...defaults,
      view_config: {
        ...defaults.view_config,
        ...normalizeBenchmarkViewConfig(defaultConfig),
        mode: benchmarkSnapshotScope.value
      }
    })
    benchmarkSavedViews.value = benchmarkSavedViews.value.filter((view) => view.view_key !== key)
    benchmarkViewDirty.value = false
    return benchmarkViewPreferences.value
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
      await loadBenchmarkLeaderboardCompare({ silent: true })
      if (!token.isLatest()) return false
      await loadBenchmarkViews({ silent: true })
      if (!token.isLatest()) return false
      await loadCurrentBenchmarkView()
      if (!token.isLatest()) return false
      const runsLoaded = await loadRuns()
      if (!token.isLatest()) return false
      await loadBenchmarkReportHistory({ silent: true })
      if (!token.isLatest()) return false
      await loadBenchmarkDiagnosticsAggregate({ silent: true })
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

  function selectLegacyBenchmarkScope(targetType = 'role_version') {
    legacyBenchmarkTargetType.value = normalizeBenchmarkTargetType(targetType)
    selectBenchmarkSuite('')
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
    if (selectedBenchmarkSuiteLaunchDisabledReason.value) {
      const message = selectedBenchmarkSuiteLaunchDisabledReason.value
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
      const message = '评测预算超过上限，请提高预算或选择更小的套件。'
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
        setNotice('error', message, { error: err })
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
      form.value.budget_limit_cost,
      form.value.stop_after_budget_units,
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
    benchmarkSeedSets,
    benchmarkSuiteError,
    benchmarkPlan,
    benchmarkPlanError,
    benchmarkPlanBudgetExceeded,
    roles,
    roleMeta,
    roleRows,
    launchableRoles,
    selectedBenchmarkId,
    legacyBenchmarkTargetType,
    selectedBenchmarkSuite,
    selectedBenchmarkTargetType,
    selectedBenchmarkIsModelSuite,
    selectedBenchmarkCanLaunch,
    selectedBenchmarkSuiteLaunchDisabledReason,
    selectedBenchmarkSuiteLabel,
    selectedBenchmarkEvaluationSetId,
    selectBenchmarkSuite,
    selectLegacyBenchmarkScope,
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
    loadBenchmarkLeaderboardCompare,
    loadBenchmarkSeedSets,
    benchmarkSavedViews,
    benchmarkSavedViewsLoading,
    benchmarkSavedViewsError,
    benchmarkViewPreferences,
    benchmarkViewDirty,
    selectedBenchmarkViewKey,
    currentBenchmarkViewKey,
    activeBenchmarkViewConfig,
    loadBenchmarkViews,
    loadCurrentBenchmarkView,
    selectBenchmarkView,
    saveCurrentBenchmarkView,
    resetCurrentBenchmarkView,
    setBenchmarkViewPreference,
    loadBenchmarkSnapshots,
    loadBenchmarkSnapshotDetail,
    loadBenchmarkSnapshotCompare,
    selectBenchmarkSnapshot,
    createBenchmarkSnapshot,
    loadBenchmarkView,
    saveBenchmarkView,
    deleteBenchmarkView,
    batchRuns,
    benchmarkEvents,
    batchRunRows,
    unscopedBenchmarkRunRows,
    selectedSuiteBatchRunRows,
    selectedBenchmarkUsingLegacyRuns,
    filteredBatchRunRows,
    visibleBatchRunRows,
    selectedBenchmarkBatchId,
    selectedBenchmarkBatchRun,
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
    loadBenchmarkReportHistory,
    benchmarkDiagnosticAggregateLoading,
    benchmarkDiagnosticAggregateError,
    benchmarkDiagnosticAggregateDiagnostics,
    benchmarkDiagnosticAggregateSummary,
    benchmarkDiagnosticAggregateRuns,
    benchmarkDiagnosticAggregateGames,
    benchmarkDiagnosticAggregatePagination,
    loadBenchmarkDiagnosticsAggregate,
    benchmarkGameStatusFilter,
    benchmarkGameSeedFilter,
    benchmarkDiagnosticKindFilter,
    benchmarkDiagnosticLevelFilter,
    benchmarkDiagnosticStatusFilter,
    benchmarkDiagnosticStageFilter,
    benchmarkDiagnosticSeedFilter,
    selectBenchmarkBatch,
    loadBenchmarkBatchDetail,
    loadBenchmarkBatchGamesPage,
    loadNextBenchmarkBatchGamesPage,
    loadBenchmarkBatchDiagnostics,
    loadBenchmarkBatchReport,
    loadBenchmarkBatchReportExport,
    setBenchmarkGameStatusFilter,
    setBenchmarkGameSeedFilter,
    setBenchmarkDiagnosticFilter,
    clearBenchmarkDiagnosticFilters,
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
