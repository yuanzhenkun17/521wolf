import type { BenchmarkDiagnostic, BenchmarkDiagnosticsResponse, BenchmarkGame, BenchmarkLeaderboardRow, BenchmarkListResponse, BenchmarkRequest, BenchmarkResult, BenchmarkRun, BenchmarkSeedSet, BenchmarkSeedRegistryResponse, BenchmarkSnapshot, BenchmarkSuite, BenchmarkTargetType, BenchmarkView } from '../../types/benchmark'
import { arrayOrEmpty, booleanValue, firstNumber, firstString, integerValue, normalizePagination, nullableNumber, numberValue, objectOrEmpty, shortId, stringValue } from '../common'

const BENCHMARK_TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'interrupted'])
const BENCHMARK_ACTIVE_STATUSES = new Set(['queued', 'running', 'rate_limited'])
const BENCHMARK_SUITE_LAUNCHABLE_STATUSES = new Set(['enabled', 'active'])
const BENCHMARK_SUITE_DISABLED_REASONS: Record<string, string> = {
  draft: '该评测套件仍是草稿，启用后才能启动。',
  deprecated: '该评测套件已废弃，只保留历史审计，不能启动。',
  disabled: '该评测套件已停用，不能启动。',
  archived: '该评测套件已归档，只能查看历史结果。'
}

export function normalizeBenchmarkTargetType(value: unknown): BenchmarkTargetType {
  return stringValue(value).toLowerCase() === 'model' ? 'model' : 'role_version'
}

export function normalizeSeedPreview(raw: unknown): string[] {
  const source = objectOrEmpty(raw)
  const seedSet = objectOrEmpty(source.seed_set)
  const registry = objectOrEmpty(source.seed_registry)
  const registrySummary = objectOrEmpty(source.seed_registry_summary)
  const candidates = [source.seed_preview, source.seedPreview, seedSet.seed_preview, registry.seed_preview, registrySummary.seed_preview, source.seeds, seedSet.seeds, registry.seeds]
  const arrayValue = candidates.find(Array.isArray)
  if (arrayValue) {
    return arrayValue
      .map((seed) => stringValue(seed))
      .filter(Boolean)
      .slice(0, 6)
  }
  const stringSeed = candidates.find((value) => typeof value === 'string')
  if (stringSeed) {
    return String(stringSeed)
      .split(/[,\s]+/)
      .map((seed) => seed.trim())
      .filter(Boolean)
      .slice(0, 6)
  }
  return []
}

export function normalizeSeedCount(raw: unknown, seedPreview: string[] = normalizeSeedPreview(raw)): number | null {
  const source = objectOrEmpty(raw)
  const seedSet = objectOrEmpty(source.seed_set)
  const registry = objectOrEmpty(source.seed_registry)
  const registrySummary = objectOrEmpty(source.seed_registry_summary)
  const value = firstNumber(source.seed_count, source.seedCount, seedSet.seed_count, seedSet.count, registry.seed_count, registry.count, registrySummary.seed_count, registrySummary.count)
  if (value != null && value >= 0) return Math.floor(value)
  return seedPreview.length ? seedPreview.length : null
}

export function normalizeBenchmarkSeedSet(raw: unknown): BenchmarkSeedSet | null {
  const source = objectOrEmpty(raw)
  const id = firstString(source.id, source.seed_set_id)
  if (!id) return null
  const seedPreview = normalizeSeedPreview(source)
  return {
    ...source,
    id,
    seed_set_id: id,
    purpose: stringValue(source.purpose),
    version: nullableNumber(source.version),
    description: stringValue(source.description),
    target_type: source.target_type ? normalizeBenchmarkTargetType(source.target_type) : '',
    tier: stringValue(source.tier).toLowerCase(),
    seed_count: normalizeSeedCount(source, seedPreview),
    seed_preview: seedPreview,
    config_hash: stringValue(source.config_hash),
    enabled: source.enabled !== false,
    overlap_warnings: arrayOrEmpty(source.overlap_warnings).filter((item) => typeof item === 'object') as BenchmarkSeedSet['overlap_warnings']
  }
}

export function normalizeBenchmarkSeedRegistry(data: unknown): BenchmarkSeedRegistryResponse {
  const source = objectOrEmpty(data)
  const items = (Array.isArray(data) ? data : arrayOrEmpty(source.items ?? source.seed_sets)).map(normalizeBenchmarkSeedSet).filter((item): item is BenchmarkSeedSet => Boolean(item))
  const summary = objectOrEmpty(source.summary)
  return {
    items,
    summary: {
      ...summary,
      total: integerValue(summary.total, items.length)
    }
  }
}

export function normalizeBenchmarkSuiteList(data: unknown, seedRegistryById: Map<string, BenchmarkSeedSet> = new Map()): BenchmarkSuite[] {
  const source = objectOrEmpty(data)
  return (Array.isArray(data) ? data : arrayOrEmpty(source.items ?? source.benchmarks)).map((item) => normalizeBenchmarkSuite(item, seedRegistryById)).filter((item): item is BenchmarkSuite => Boolean(item))
}

export function normalizeBenchmarkSuiteStatus(raw: unknown): string {
  const source = objectOrEmpty(raw)
  const status = firstString(source.status, source.lifecycle_status, source.lifecycleStatus).toLowerCase()
  if (status) return status
  if (source.deprecated) return 'deprecated'
  if (source.archived) return 'archived'
  if (source.enabled === false) return 'disabled'
  return 'enabled'
}

export function normalizeBenchmarkSuite(raw: unknown, seedRegistryById: Map<string, BenchmarkSeedSet> = new Map()): BenchmarkSuite | null {
  const source = objectOrEmpty(raw)
  const id = firstString(source.id, source.benchmark_id)
  if (!id) return null
  const version = nullableNumber(source.version)
  const rawSeedSet = objectOrEmpty(source.seed_set)
  const seedSetId = firstString(source.seed_set_id, rawSeedSet.id, rawSeedSet.seed_set_id)
  const seedSet = {
    ...objectOrEmpty(seedRegistryById.get(seedSetId)),
    ...rawSeedSet
  }
  const seedSource = { ...source, seed_set_id: seedSetId, seed_set: seedSet }
  const seedPreview = normalizeSeedPreview(seedSource)
  const status = normalizeBenchmarkSuiteStatus(source)
  const serverLaunchable = source.launchable == null ? null : source.launchable !== false
  const launchable = (serverLaunchable == null ? true : serverLaunchable) && BENCHMARK_SUITE_LAUNCHABLE_STATUSES.has(status)
  const name = firstString(source.name, source.label, id)
  const benchmarkConfigHash = firstString(source.benchmark_config_hash, source.config_hash)
  return {
    ...source,
    id,
    version,
    name,
    label: version == null ? name : `${name} v${version}`,
    description: stringValue(source.description),
    target_type: normalizeBenchmarkTargetType(source.target_type ?? source.scope),
    roles: arrayOrEmpty(source.roles)
      .map((role) => stringValue(role))
      .filter(Boolean),
    game_count: nullableNumber(source.game_count ?? source.battle_games ?? source.games),
    max_days: nullableNumber(source.max_days),
    seed_set_id: seedSetId,
    seed_count: normalizeSeedCount(seedSource, seedPreview),
    seed_preview: seedPreview,
    seed_set: seedSet,
    paired_seed: booleanValue(source.paired_seed, false),
    metrics: objectOrEmpty(source.metrics),
    gates: objectOrEmpty(source.gates),
    judge: objectOrEmpty(source.judge),
    config_hash: firstString(source.config_hash, benchmarkConfigHash),
    benchmark_config_hash: benchmarkConfigHash,
    cost_tier: stringValue(source.cost_tier ?? objectOrEmpty(source.cost).tier ?? objectOrEmpty(source.metadata).cost_tier).toLowerCase(),
    evaluation_set_id: firstString(source.evaluation_set_id, version == null ? '' : `${id}@v${version}`),
    status,
    launchable,
    launch_disabled_reason: launchable ? '' : firstString(source.launch_disabled_reason, BENCHMARK_SUITE_DISABLED_REASONS[status], '该评测套件当前不可启动。')
  }
}

export function normalizeBenchmarkRequest(raw: Partial<BenchmarkRequest> = {}): BenchmarkRequest {
  return {
    ...raw,
    target_type: normalizeBenchmarkTargetType(raw.target_type),
    roles: arrayOrEmpty(raw.roles)
      .map((role) => stringValue(role).toLowerCase())
      .filter(Boolean),
    target_versions: objectOrEmpty(raw.target_versions) as Record<string, string>
  }
}

export function normalizeBenchmarkResult(raw: unknown): BenchmarkResult {
  const source = objectOrEmpty(raw)
  const config = objectOrEmpty(source.config)
  const scoreSummary = objectOrEmpty(source.score_summary)
  return {
    ...source,
    result_batch_id: firstString(source.result_batch_id, source.batch_id, config.batch_id),
    target_role: firstString(source.target_role, config.target_role),
    target_version_id: firstString(config.target_version_id, source.target_version_id),
    completed: integerValue(source.completed, 0),
    errored: integerValue(source.errored, 0),
    game_count: integerValue(source.game_count, 0),
    attempted_game_count: integerValue(source.attempted_game_count, integerValue(source.game_count, 0)),
    rankable: source.rankable !== false,
    diagnostic_count: integerValue(source.diagnostic_count, 0),
    warning_count: integerValue(source.warning_count, 0),
    score_summary: scoreSummary
  }
}

export function normalizeBenchmarkRun(raw: unknown): BenchmarkRun {
  const source = objectOrEmpty(raw)
  const id = firstString(source.run_id, source.batch_id, source.id)
  const benchmark = objectOrEmpty(source.benchmark ?? objectOrEmpty(source.config).benchmark)
  const roles = arrayOrEmpty(source.roles)
    .map((role) => stringValue(role))
    .filter(Boolean)
  const roleKeys = roles.length ? roles : source.role ? [stringValue(source.role)] : []
  const benchmarkTargetType = normalizeBenchmarkTargetType(benchmark.target_type ?? source.target_type ?? objectOrEmpty(source.config).target_type)
  const status = stringValue(source.status)
  return {
    ...source,
    id,
    roleKeys,
    displayRole: roleKeys.join(', ') || 'unknown',
    benchmarkId: firstString(benchmark.id, source.benchmark_id, objectOrEmpty(source.config).benchmark_id),
    benchmarkVersion: (benchmark.version ?? source.benchmark_version ?? objectOrEmpty(source.config).benchmark_version ?? null) as string | number | null,
    benchmarkTargetType,
    evaluationSetId: firstString(benchmark.evaluation_set_id, source.evaluation_set_id, objectOrEmpty(source.config).evaluation_set_id),
    resultRows: arrayOrEmpty(source.results).map(normalizeBenchmarkResult),
    isActive: BENCHMARK_ACTIVE_STATUSES.has(status),
    isTerminal: BENCHMARK_TERMINAL_STATUSES.has(status)
  }
}

export function normalizeBenchmarkRunResponse(raw: unknown): BenchmarkRun {
  const source = objectOrEmpty(raw)
  return normalizeBenchmarkRun(source.run ?? source.batch ?? source.data ?? raw)
}

export function normalizeBenchmarkRunsResponse(raw: unknown): BenchmarkListResponse<BenchmarkRun> {
  const source = objectOrEmpty(raw)
  const rows = Array.isArray(raw) ? raw : arrayOrEmpty(source.runs).length ? arrayOrEmpty(source.runs) : arrayOrEmpty(source.batches).length ? arrayOrEmpty(source.batches) : arrayOrEmpty(source.items)
  const items = rows.map(normalizeBenchmarkRun)
  return {
    items,
    pagination: source.pagination ? normalizePagination(source.pagination, items) : undefined,
    raw
  }
}

export function normalizeBenchmarkGame(raw: unknown): BenchmarkGame {
  const source = objectOrEmpty(raw)
  const historyGameId = firstString(source.history_game_id, source.historyGameId, source.game_id, source.id)
  const replayAvailable = source.replay_available == null ? Boolean(historyGameId) : Boolean(source.replay_available)
  return {
    ...source,
    id: firstString(source.id, source.game_id),
    game_id: firstString(source.game_id, source.id),
    history_game_id: historyGameId,
    result_batch_id: firstString(source.result_batch_id, source.batch_id),
    target_role: stringValue(source.target_role),
    status: stringValue(source.status, 'unknown'),
    event_count: integerValue(source.event_count, 0),
    decision_count: integerValue(source.decision_count, 0),
    diagnostic_count: integerValue(source.diagnostic_count, 0),
    replay_available: replayAvailable,
    replayHash: replayAvailable && historyGameId ? `#logs?workspace=archive&game_id=${encodeURIComponent(historyGameId)}` : ''
  }
}

export function normalizeBenchmarkDiagnostic(raw: unknown): BenchmarkDiagnostic {
  const source = objectOrEmpty(raw)
  const kind = stringValue(source.kind, 'diagnostic')
  const historyGameId = firstString(source.history_game_id, source.historyGameId, source.game_id)
  return {
    ...source,
    id: [source.origin, source.result_batch_id, source.game_id, kind, source.stage, source.message].map((item) => stringValue(item)).join(':'),
    kind,
    level: stringValue(source.level, 'info').toLowerCase(),
    origin: stringValue(source.origin, 'run'),
    stage: stringValue(source.stage),
    message: stringValue(source.message),
    target_role: stringValue(source.target_role),
    result_batch_id: stringValue(source.result_batch_id),
    game_id: stringValue(source.game_id),
    history_game_id: historyGameId,
    replayHash: historyGameId ? `#logs?workspace=archive&game_id=${encodeURIComponent(historyGameId)}` : ''
  }
}

export function normalizeBenchmarkDiagnosticsResponse(raw: unknown): BenchmarkDiagnosticsResponse {
  const source = objectOrEmpty(raw)
  const diagnostics = arrayOrEmpty(source.diagnostics ?? source.items).map(normalizeBenchmarkDiagnostic)
  return {
    diagnostics,
    summary: objectOrEmpty(source.summary),
    pagination: source.pagination ? normalizePagination(source.pagination, diagnostics) : undefined,
    raw
  }
}

export function normalizeBenchmarkLeaderboardRow(raw: unknown, index = 0, scope: BenchmarkTargetType = 'role_version'): BenchmarkLeaderboardRow {
  const source = objectOrEmpty(raw)
  const targetRole = stringValue(source.target_role ?? source.role)
  const targetVersionId = firstString(source.target_version_id, source.version_id, source.hash)
  const modelId = firstString(source.model_id, source.subject_id)
  const modelConfigHash = firstString(source.model_config_hash, source.hash)
  const key = scope === 'model' ? firstString(source.key, modelConfigHash, modelId, `model-${index}`) : firstString(source.key, targetVersionId, `${targetRole}-${index}`)
  return {
    ...source,
    key,
    rank: integerValue(source.rank, index + 1),
    primary: scope === 'model' ? firstString(modelId, modelConfigHash, key) : firstString(targetRole, 'unknown'),
    secondary: scope === 'model' ? shortId(modelConfigHash, 12) : shortId(targetVersionId, 12),
    score: numberValue(source.score ?? source.target_role_role_weighted_score ?? source.avg_role_score ?? source.strength_score, 0),
    winRate: numberValue(source.winRate ?? source.win_rate ?? source.target_side_win_rate, 0),
    games: integerValue(source.games ?? source.game_count ?? source.games_played, 0),
    rankable: source.rankable !== false,
    target_role: targetRole,
    target_version_id: targetVersionId,
    model_id: modelId,
    model_config_hash: modelConfigHash
  }
}

export function normalizeBenchmarkLeaderboardResponse(raw: unknown, scopeFallback: BenchmarkTargetType = 'role_version'): BenchmarkLeaderboardRow[] {
  const source = objectOrEmpty(raw)
  const scope = normalizeBenchmarkTargetType(source.scope ?? scopeFallback)
  return (Array.isArray(raw) ? raw : arrayOrEmpty(source.rows ?? source.items ?? source.leaderboard)).map((row, index) => normalizeBenchmarkLeaderboardRow(row, index, scope))
}

export function normalizeBenchmarkSnapshot(raw: unknown, scopeFallback: BenchmarkTargetType = 'role_version'): BenchmarkSnapshot | null {
  const source = objectOrEmpty(raw)
  const snapshotId = firstString(source.snapshot_id, source.id)
  if (!snapshotId) return null
  const scope = normalizeBenchmarkTargetType(source.scope ?? scopeFallback)
  const rows = arrayOrEmpty(source.rows).map((row, index) => normalizeBenchmarkLeaderboardRow(row, index, scope))
  return {
    ...source,
    snapshot_id: snapshotId,
    title: firstString(source.title, snapshotId),
    release_notes: stringValue(source.release_notes),
    scope,
    benchmark_id: stringValue(source.benchmark_id),
    benchmark_version: (source.benchmark_version ?? null) as string | number | null,
    evaluation_set_id: stringValue(source.evaluation_set_id),
    seed_set_id: stringValue(source.seed_set_id),
    benchmark_config_hash: stringValue(source.benchmark_config_hash),
    target_role: stringValue(source.target_role),
    source_filter: objectOrEmpty(source.source_filter),
    view_config: objectOrEmpty(source.view_config),
    summary: objectOrEmpty(source.summary),
    release_gate: objectOrEmpty(source.release_gate),
    release_manifest: objectOrEmpty(source.release_manifest),
    rows,
    created_at: stringValue(source.created_at)
  }
}

export function normalizeBenchmarkSnapshotsResponse(raw: unknown, scopeFallback: BenchmarkTargetType = 'role_version'): BenchmarkSnapshot[] {
  const source = objectOrEmpty(raw)
  return (Array.isArray(raw) ? raw : arrayOrEmpty(source.items ?? source.snapshots)).map((snapshot) => normalizeBenchmarkSnapshot(snapshot, scopeFallback)).filter((snapshot): snapshot is BenchmarkSnapshot => Boolean(snapshot))
}

export function normalizeBenchmarkViewConfig(raw: unknown = {}): BenchmarkView['view_config'] {
  const config = objectOrEmpty(raw)
  const rankFilter = stringValue(config.rank_filter)
  return {
    mode: normalizeBenchmarkTargetType(config.mode ?? config.scope),
    rank_filter: ['all', 'rankable', 'unrankable'].includes(rankFilter) ? (rankFilter as BenchmarkView['view_config']['rank_filter']) : 'all',
    columns: arrayOrEmpty(config.columns)
      .map((item) => stringValue(item))
      .filter(Boolean),
    sort: stringValue(config.sort, 'score_desc'),
    search: stringValue(config.search),
    density: stringValue(config.density, 'standard')
  }
}

export function normalizeBenchmarkView(raw: unknown, scopeFallback: BenchmarkTargetType = 'role_version'): BenchmarkView | null {
  const source = objectOrEmpty(raw)
  const viewKey = stringValue(source.view_key)
  if (!viewKey) return null
  return {
    ...source,
    kind: 'benchmark_saved_view',
    schema_version: integerValue(source.schema_version, 1),
    view_key: viewKey,
    name: stringValue(source.name, '默认视图'),
    scope: normalizeBenchmarkTargetType(source.scope ?? scopeFallback),
    benchmark_id: source.benchmark_id == null ? null : stringValue(source.benchmark_id),
    evaluation_set_id: source.evaluation_set_id == null ? null : stringValue(source.evaluation_set_id),
    target_role: source.target_role == null ? null : stringValue(source.target_role),
    view_config: normalizeBenchmarkViewConfig(source.view_config),
    created_at: source.created_at == null ? null : stringValue(source.created_at),
    updated_at: source.updated_at == null ? null : stringValue(source.updated_at)
  }
}
