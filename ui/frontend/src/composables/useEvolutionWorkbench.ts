// @ts-nocheck
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { createGameApi } from './gameApi.ts'
import { createLatestOnlyMap, createLatestOnlyTracker } from './latestOnly.ts'
import { createNoticeAutoDismiss } from './noticeAutoDismiss.ts'
import { createResumableEventSource } from './resumableEventSource.ts'
import { currentLegacyHash } from '../router/legacyViewNavigation'
import {
  evolutionDeepLinkFromHash as routeEvolutionDeepLinkFromHash,
  evolutionDeepLinkFromRoute as routeEvolutionDeepLinkFromRoute,
  evolutionDeepLinkPanel as routeEvolutionDeepLinkPanel
} from '../router/workbenchDeepLinks.ts'
import {
  EVOLUTION_ACTIVE_STATUSES,
  EVOLUTION_TERMINAL_STATUSES,
  isEvolutionBatch,
  normalizeLeaderboardEntry,
  recommendationText,
  roleMeta,
  shortId,
  sourceText,
  statusText
} from './workbenchShared.ts'

const DEFAULT_RUN_PAGE_SIZE = 80
const DEFAULT_SAMPLE_GAME_PAGE_SIZE = 80
const SAMPLE_GAME_BUCKETS = ['training', 'baseline', 'candidate']
const SAMPLE_BUCKET_LABELS = {
  training: '训练',
  baseline: '基线',
  candidate: '候选'
}
const ROLLBACK_BLOCKED_RELEASE_STAGES = new Set(['shadow', 'canary'])

function createPagination(limit) {
  return {
    total: 0,
    offset: 0,
    limit,
    returned: 0,
    has_more: false
  }
}

function paginationFromResponse(data, rows, { offset, limit }) {
  const raw = data?.pagination || {}
  const returned = Number(raw.returned ?? rows.length ?? 0)
  const total = Number(raw.total ?? (offset + returned))
  return {
    total: Number.isFinite(total) ? total : rows.length,
    offset: Number(raw.offset ?? offset) || 0,
    limit: raw.limit == null ? limit : Number(raw.limit),
    returned: Number.isFinite(returned) ? returned : rows.length,
    has_more: Boolean(raw.has_more)
  }
}

function mergeById(existing, incoming, idFields) {
  const fields = Array.isArray(idFields) ? idFields : [idFields]
  const seen = new Set()
  return [...existing, ...incoming].filter((item) => {
    const key = fields.map((field) => item?.[field]).find((value) => value != null && value !== '')
    if (key == null || key === '') return true
    const normalized = String(key)
    if (seen.has(normalized)) return false
    seen.add(normalized)
    return true
  })
}

function samplePaginationMap(limit) {
  return Object.fromEntries(SAMPLE_GAME_BUCKETS.map((bucket) => [bucket, createPagination(limit)]))
}

function emptySampleGames() {
  return Object.fromEntries(SAMPLE_GAME_BUCKETS.map((bucket) => [bucket, []]))
}

function percentValue(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return null
  const pct = number <= 1 ? number * 100 : number
  return Math.max(0, Math.min(100, Math.round(pct)))
}

function stageText(value) {
  const status = statusText(value)
  if (status !== '未知') return status
  const source = sourceText(value)
  if (source !== '未知') return source
  return value || '未知'
}

function normalizeReleaseStage(value) {
  return String(value || '').trim().toLowerCase()
}

function rollbackDisabledReason(version, releaseStage) {
  if (version?.is_baseline) return '当前基线'
  if (ROLLBACK_BLOCKED_RELEASE_STAGES.has(releaseStage)) return `${stageText(releaseStage)}不可回滚`
  return ''
}

function timeLabel(value) {
  return value ? String(value).replace('T', ' ').slice(0, 19) : '—'
}

function finiteNumber(value) {
  if (value == null || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function firstFinite(...values) {
  for (const value of values) {
    const number = finiteNumber(value)
    if (number != null) return number
  }
  return null
}

function firstBoolean(...values) {
  for (const value of values) {
    if (typeof value === 'boolean') return value
    if (typeof value === 'number' && Number.isFinite(value)) return value !== 0
    if (typeof value === 'string') {
      const key = value.trim().toLowerCase()
      if (['true', 'yes', '1', 'saved', 'persisted'].includes(key)) return true
      if (['false', 'no', '0', 'not_saved', 'unsaved', 'failed'].includes(key)) return false
    }
  }
  return null
}

function maxFinite(...values) {
  const numbers = values.map(finiteNumber).filter((value) => value != null)
  return numbers.length ? Math.max(...numbers) : 0
}

function arrayLength(value) {
  return Array.isArray(value) ? value.length : null
}

function isCompletedPipelineStatus(status) {
  return ['reviewing', 'promoted', 'rejected', 'completed'].includes(status)
}

function isBattleStage(stage) {
  return ['battling', 'combined_battling', 'battle'].includes(String(stage || ''))
}

function isTrainingStage(stage) {
  return String(stage || '') === 'training'
}

function isAfterTrainingStage(stage, status) {
  return [
    'consolidating',
    'applying',
    'scenario_replay',
    'battling',
    'combined_battling',
    'reviewing',
    'promoted',
    'rejected',
    'completed'
  ].includes(String(stage || status || ''))
}

function isAfterBattleStage(stage, status) {
  return ['reviewing', 'promoted', 'rejected', 'completed'].includes(String(stage || status || ''))
}

function progressFromCount(completed, target, fallbackLabel = '等待') {
  const done = finiteNumber(completed)
  const total = finiteNumber(target)
  if (total != null && total > 0) {
    const normalizedDone = Math.max(0, Math.min(total, done ?? 0))
    return {
      percent: Math.max(0, Math.min(100, Math.round((normalizedDone / total) * 100))),
      label: `${normalizedDone} / ${total}`
    }
  }
  return { percent: 0, label: fallbackLabel }
}

function progressWithExplicit(explicit, completed, target, fallbackLabel = '等待') {
  const pct = percentValue(explicit)
  const counted = progressFromCount(completed, target, fallbackLabel)
  if (pct == null) return counted
  return {
    percent: pct,
    label: counted.label === fallbackLabel ? `${pct}%` : counted.label
  }
}

function normalizeChildRun(child) {
  if (typeof child === 'string') {
    return {
      id: child,
      run_id: child,
      displayRole: '—',
      status: '',
      statusLabel: '—',
      progressPercent: 0,
      progressLabel: '等待'
    }
  }
  const progress = child?.progress && typeof child.progress === 'object' ? child.progress : {}
  const overall = child?.overall_progress && typeof child.overall_progress === 'object' ? child.overall_progress : {}
  const stage = child?.stage_progress && typeof child.stage_progress === 'object' ? child.stage_progress : progress
  const trainingTarget = firstFinite(overall.training_total, child?.training_total, child?.training_game_count)
  const trainingCompleted = firstFinite(overall.training_completed, child?.training_completed)
  const battleTarget = firstFinite(overall.battle_total, child?.battle_total, child?.battle_game_count)
  const battleCompleted = firstFinite(overall.battle_completed, child?.battle_completed)
  const explicit = percentValue(overall.percent ?? progress.overall_percent ?? child?.overall_percent ?? stage.percent)
  return {
    ...child,
    id: child?.run_id || child?.id || '',
    run_id: child?.run_id || child?.id || '',
    displayRole: roleMeta(child?.role).label,
    statusLabel: statusText(child?.status || child?.stage),
    trainingTarget: trainingTarget ?? 0,
    trainingCompleted: trainingCompleted ?? 0,
    battleTarget: battleTarget ?? 0,
    battleCompleted: battleCompleted ?? 0,
    progressPercent: explicit ?? 0,
    progressLabel: explicit == null ? '等待' : `${explicit}%`
  }
}

function buildBatchProgress(run, childRuns) {
  const progress = run?.progress && typeof run.progress === 'object' ? run.progress : {}
  const overallProgress = run?.overall_progress && typeof run.overall_progress === 'object' ? run.overall_progress : {}
  const stageProgress = run?.stage_progress && typeof run.stage_progress === 'object' ? run.stage_progress : progress
  const childTrainingTarget = childRuns.reduce((total, child) => total + (finiteNumber(child.trainingTarget) ?? 0), 0)
  const childTrainingCompleted = childRuns.reduce((total, child) => total + (finiteNumber(child.trainingCompleted) ?? 0), 0)
  const childBattleTarget = childRuns.reduce((total, child) => total + (finiteNumber(child.battleTarget) ?? 0), 0)
  const childBattleCompleted = childRuns.reduce((total, child) => total + (finiteNumber(child.battleCompleted) ?? 0), 0)
  const roleCount = maxFinite(
    overallProgress.total_roles,
    progress.total_roles,
    progress.role_count,
    run?.total_roles,
    run?.role_count,
    arrayLength(run?.roles),
    childRuns.length
  )
  const completedChildren = childRuns.filter((child) =>
    isCompletedPipelineStatus(child?.status) || EVOLUTION_TERMINAL_STATUSES.has(child?.status)
  ).length
  const completedRoles = firstFinite(overallProgress.completed_roles, progress.completed_roles, run?.completed_roles, completedChildren) ?? 0
  const overall = progressWithExplicit(
    overallProgress.percent ?? progress.overall_percent ?? run?.overall_percent ?? progress.percent,
    completedRoles,
    roleCount,
    '等待'
  )
  const stage = progressWithExplicit(stageProgress.percent ?? progress.percent, completedRoles, roleCount, '等待')
  const trainingTarget = maxFinite(
    overallProgress.training_total,
    progress.training_total,
    run?.training_total,
    run?.training_target,
    childTrainingTarget,
    run?.config?.training_games && roleCount ? Number(run.config.training_games) * roleCount : null
  )
  const battleTarget = maxFinite(
    overallProgress.battle_total,
    progress.battle_total,
    run?.battle_total,
    run?.battle_target,
    childBattleTarget,
    run?.config?.battle_games && roleCount ? Number(run.config.battle_games) * roleCount * 2 : null
  )
  const trainingCompleted = firstFinite(overallProgress.training_completed, run?.training_completed, progress.training_completed, childTrainingCompleted) ?? 0
  const battleCompleted = firstFinite(overallProgress.battle_completed, run?.battle_completed, progress.battle_completed, childBattleCompleted) ?? 0
  return {
    roleCount,
    completedRoles,
    overall,
    stage,
    training: progressFromCount(trainingCompleted, trainingTarget),
    battle: progressFromCount(battleCompleted, battleTarget),
    trainingTarget,
    trainingCompleted,
    battleTarget,
    battleCompleted
  }
}

function buildRunProgress(run, trainingSamples, battleSamples, currentStage) {
  const progress = run?.progress && typeof run.progress === 'object' ? run.progress : {}
  const overallProgress = run?.overall_progress && typeof run.overall_progress === 'object' ? run.overall_progress : {}
  const stageProgress = run?.stage_progress && typeof run.stage_progress === 'object' ? run.stage_progress : progress
  const trainingStageTarget = isTrainingStage(currentStage) ? progress.target_games : null
  const battleStageTarget = isBattleStage(currentStage) ? progress.target_games : null
  const requestedBattle = firstFinite(run?.battle_requested, run?.config?.battle_games)
  const trainingTarget = maxFinite(
    overallProgress.training_total,
    progress.training_total,
    run?.training_total,
    run?.training_target,
    run?.training_game_total,
    run?.training_game_count,
    run?.training_requested,
    run?.config?.training_games,
    trainingStageTarget,
    arrayLength(trainingSamples)
  )
  const battleTarget = maxFinite(
    overallProgress.battle_total,
    progress.battle_total,
    run?.battle_total,
    run?.battle_target,
    run?.battle_game_total,
    battleStageTarget,
    run?.battle_requested,
    arrayLength(battleSamples),
    requestedBattle != null ? requestedBattle * 2 : null,
    run?.battle_game_count
  )
  let trainingCompleted = firstFinite(
    overallProgress.training_completed,
    run?.training_completed,
    run?.training_game_completed,
    progress.training_completed,
    isTrainingStage(currentStage) ? progress.completed_games : null,
    arrayLength(trainingSamples)
  )
  let battleCompleted = firstFinite(
    overallProgress.battle_completed,
    run?.battle_completed,
    run?.battle_game_completed,
    progress.battle_completed,
    isBattleStage(currentStage) ? progress.completed_games : null,
    arrayLength(battleSamples)
  )
  if ((trainingCompleted == null || trainingCompleted === 0) && trainingTarget > 0 && isAfterTrainingStage(currentStage, run?.status)) {
    trainingCompleted = trainingTarget
  }
  if ((battleCompleted == null || battleCompleted === 0) && battleTarget > 0 && isAfterBattleStage(currentStage, run?.status)) {
    battleCompleted = battleTarget
  }
  const training = progressFromCount(trainingCompleted ?? 0, trainingTarget)
  const battle = progressFromCount(battleCompleted ?? 0, battleTarget)
  const stage = progressWithExplicit(
    stageProgress.percent ?? progress.percent,
    stageProgress.completed_games ?? progress.completed_games,
    stageProgress.target_games ?? progress.target_games,
    '等待'
  )
  const overallTarget = maxFinite(
    overallProgress.total,
    overallProgress.target,
    overallProgress.overall_total,
    progress.overall_total,
    run?.overall_total,
    trainingTarget + battleTarget
  )
  const overallCompleted = firstFinite(
    overallProgress.completed,
    overallProgress.overall_completed,
    progress.overall_completed,
    run?.overall_completed,
    (trainingCompleted ?? 0) + (battleCompleted ?? 0)
  )
  let overall = progressWithExplicit(
    overallProgress.percent ?? progress.overall_percent ?? run?.overall_percent,
    overallCompleted,
    overallTarget,
    stage.label
  )
  if (isCompletedPipelineStatus(run?.status) && overall.percent < 100) {
    overall = { percent: 100, label: overallTarget > 0 ? `${overallTarget} / ${overallTarget}` : '完成' }
  }
  if (!overallTarget && progress.percent != null) overall = stage
  return {
    overall,
    stage,
    training,
    battle,
    trainingTarget,
    trainingCompleted: trainingCompleted ?? 0,
    battleTarget,
    battleCompleted: battleCompleted ?? 0
  }
}

function normalizeRun(run) {
  const id = run?.run_id || run?.batch_id || ''
  const entityType = run?.batch_id ? 'batch' : 'run'
  const rawChildRuns = entityType === 'batch'
    ? (Array.isArray(run?.run_summaries) && run.run_summaries.length
        ? run.run_summaries
        : (Array.isArray(run?.runs) ? run.runs : []))
    : []
  const childRuns = rawChildRuns.length
    ? rawChildRuns.map(normalizeChildRun)
    : []
  const roleNames = run?.roles?.length
    ? run.roles.map((role) => roleMeta(role).label).join(', ')
    : roleMeta(run?.role).label
  const trainingSamples = Array.isArray(run?.training_games) ? run.training_games : []
  const battleSamples = Array.isArray(run?.battle_games) ? run.battle_games : []
  // Decide-stage verdict from the new evolve pipeline.
  const battle = run?.battle_result || {}
  const recommendation = run?.recommendation || ''
  const recommendationLabel = recommendation ? recommendationText(recommendation) : ''
  const winRateDelta = Number(
    battle?.win_rate_delta ??
    ((battle?.candidate_win_rate ?? 0) - (battle?.baseline_win_rate ?? 0))
  )
  const currentStage = run?.current_stage || run?.progress?.stage || run?.stage || run?.status
  const publishedReleaseStage = run?.published_release_stage || run?.release_stage || ''
  const progress = entityType === 'batch'
    ? buildBatchProgress(run, childRuns)
    : buildRunProgress(run, trainingSamples, battleSamples, currentStage)
  return {
    ...run,
    id,
    entityType,
    entityLabel: entityType === 'batch' ? '批量' : '单角色',
    isBatch: entityType === 'batch',
    childRuns,
    childRunCount: childRuns.length,
    roleCount: progress.roleCount ?? arrayLength(run?.roles) ?? 0,
    completedRoleCount: progress.completedRoles ?? 0,
    displayRole: roleNames,
    recommendation,
    recommendationLabel,
    battleSignificant: Boolean(battle?.significant),
    battleSkipped: Boolean(battle?.skipped),
    winRateDelta: Number.isFinite(winRateDelta) ? winRateDelta : 0,
    winRateDeltaPct: Math.round((Number.isFinite(winRateDelta) ? winRateDelta : 0) * 100),
    publishedVersionId: run?.published_version_id || null,
    publishedShort: shortId(run?.published_version_id),
    publishedReleaseStage,
    publishedReleaseStageLabel: publishedReleaseStage ? stageText(publishedReleaseStage) : '—',
    promotedVersionId: run?.promoted_version_id || null,
    promotedShort: shortId(run?.promoted_version_id),
    statusLabel: statusText(run?.status || run?.stage),
    currentStage,
    currentStageLabel: stageText(currentStage),
    progressPercent: progress.overall?.percent ?? 0,
    progressLabel: progress.overall?.label ?? '等待',
    overallProgressPercent: progress.overall?.percent ?? 0,
    overallProgressLabel: progress.overall?.label ?? '等待',
    stageProgressPercent: progress.stage?.percent ?? 0,
    stageProgressLabel: progress.stage?.label ?? '等待',
    trainingProgressPercent: progress.training?.percent ?? 0,
    trainingProgressLabel: progress.training?.label ?? '等待',
    battleProgressPercent: progress.battle?.percent ?? 0,
    battleProgressLabel: progress.battle?.label ?? '等待',
    startedLabel: timeLabel(run?.started_at),
    finishedLabel: timeLabel(run?.finished_at),
    heartbeatLabel: timeLabel(run?.last_heartbeat_at || run?.progress?.updated_at),
    candidateShort: shortId(run?.candidate_hash),
    parentShort: shortId(run?.parent_hash),
    trainingGameRequested: progress.trainingTarget ?? 0,
    trainingGameCompleted: progress.trainingCompleted ?? 0,
    battleGameRequested: progress.battleTarget ?? 0,
    battleGameCompleted: progress.battleCompleted ?? 0,
    proposalCount: Number(run?.proposal_count ?? (Array.isArray(run?.proposals) ? run.proposals.length : 0)),
    diffCount: Number(run?.diff_count ?? (Array.isArray(run?.diff) ? run.diff.length : 0)),
    diagnosticCount: Array.isArray(run?.diagnostics) ? run.diagnostics.length : 0,
    warningCount: Array.isArray(run?.warnings) ? run.warnings.length : 0,
    errorCount: Number(run?.error_count ?? (Array.isArray(run?.errors) ? run.errors.length : 0)),
    isReviewing: run?.status === 'reviewing',
    isTerminal: EVOLUTION_TERMINAL_STATUSES.has(run?.status),
    isActive: EVOLUTION_ACTIVE_STATUSES.has(run?.status)
  }
}

function normalizeVersion(version) {
  const releaseStage = normalizeReleaseStage(
    version?.release_stage ||
    version?.releaseStage ||
    version?.provenance?.release_stage ||
    version?.provenance?.releaseStage ||
    ''
  )
  const disabledReason = rollbackDisabledReason(version, releaseStage)
  return {
    ...version,
    releaseStage,
    releaseStageLabel: releaseStage ? stageText(releaseStage) : '—',
    rollbackDisabled: Boolean(disabledReason),
    rollbackDisabledReason: disabledReason,
    rollbackLabel: disabledReason || '回滚',
    short: shortId(version.version_id),
    createdLabel: version.created_at ? String(version.created_at).replace('T', ' ').slice(0, 19) : '—'
  }
}

function normalizeSampleGame(game, bucket) {
  const id = game?.game_id || game?.id || ''
  return {
    ...game,
    id,
    bucket,
    short: shortId(id, 14),
    phaseLabel: sourceText(game?.phase || bucket),
    winnerLabel: {
      good: '好人',
      werewolves: '狼人',
      wolf: '狼人',
      village: '好人'
    }[game?.winner] || game?.winner || (game?.in_progress ? '进行中' : '未知'),
    eventCount: Number(game?.event_count || game?.events?.length || 0),
    decisionCount: Number(game?.decision_count || game?.decisions?.length || 0),
    dayLabel: game?.day ? `第${game.day}天` : '—'
  }
}

function asArray(value) {
  if (Array.isArray(value)) return value
  if (value && typeof value === 'object') return Object.values(value)
  return []
}

function firstArray(...values) {
  for (const value of values) {
    if (Array.isArray(value)) return value
  }
  return []
}

function firstObject(...values) {
  for (const value of values) {
    if (value && typeof value === 'object' && !Array.isArray(value)) return value
  }
  return {}
}

function uniqueText(values) {
  const seen = new Set()
  return asArray(values)
    .map((value) => String(value ?? '').trim())
    .filter((value) => {
      if (!value || seen.has(value)) return false
      seen.add(value)
      return true
    })
}

function textItems(...values) {
  const items = []
  const visit = (value) => {
    if (value == null || value === '') return
    if (Array.isArray(value)) {
      value.forEach(visit)
      return
    }
    if (typeof value === 'object') {
      Object.values(value).forEach(visit)
      return
    }
    items.push(value)
  }
  values.forEach(visit)
  return uniqueText(items)
}

function shortText(value, fallback = '—') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function firstTextValue(...values) {
  for (const value of values) {
    const text = String(value ?? '').trim()
    if (text) return text
  }
  return ''
}

function structuredText(value, fallback = '') {
  if (value == null || value === '') return fallback
  if (Array.isArray(value)) {
    return value.map((item) => structuredText(item)).filter(Boolean).join('; ') || fallback
  }
  if (typeof value === 'object') {
    return Object.entries(value)
      .map(([key, item]) => {
        const text = structuredText(item)
        return text ? `${key}: ${text}` : ''
      })
      .filter(Boolean)
      .join('; ') || fallback
  }
  return shortText(value, fallback)
}

function metricTargetRows(value) {
  if (Array.isArray(value)) {
    return value
      .map((item, index) => {
        if (item && typeof item === 'object') {
          const name = shortText(item.metric || item.name || item.key || item.id, `metric_${index + 1}`)
          const target = item.target ?? item.value ?? item.expected ?? item.threshold ?? item.delta ?? item
          return { name, value: structuredText(target, '—') }
        }
        return { name: `metric_${index + 1}`, value: structuredText(item, '—') }
      })
      .filter((item) => item.value && item.value !== '—')
  }
  const metrics = firstObject(value)
  return Object.entries(metrics)
    .map(([name, target]) => ({ name, value: structuredText(target, '—') }))
    .filter((item) => item.value && item.value !== '—')
}

function gateDecisionText(value) {
  return {
    promote: '允许晋升',
    promoted: '已晋升',
    review: '需要复核',
    review_required: '需要复核',
    reject: '拒绝',
    rejected: '已拒绝',
    block: '阻断',
    blocked: '阻断',
    shadow_candidate: '影子候选',
    canary_candidate: '灰度候选',
    baseline_promote: '基线晋升',
    pending: '待评审',
    allow: '允许'
  }[String(value || '').toLowerCase()] || shortText(value)
}

function proposalStatusText(value) {
  return {
    accepted: '已接受',
    accept: '已接受',
    rejected: '已拒绝',
    reject: '已拒绝',
    pending: '待处理',
    review: '待处理',
    review_required: '待处理',
    applied: '已应用',
    skipped: '已跳过'
  }[String(value || '').toLowerCase()] || shortText(value, '待处理')
}

function preflightStatusText(value) {
  return {
    pass: '通过',
    passed: '通过',
    ok: '通过',
    allow: '通过',
    allowed: '通过',
    fail: '未通过',
    failed: '未通过',
    reject: '未通过',
    rejected: '未通过',
    block: '阻断',
    blocked: '阻断',
    review: '需复核',
    review_required: '需复核',
    warning: '需复核',
    pending: '待预检',
    skipped: '已跳过'
  }[String(value || '').toLowerCase()] || shortText(value, '')
}

function attributionStatusText(value, reviewRequired = false) {
  const status = String(value || '').toLowerCase()
  if (reviewRequired) return '需复核'
  return {
    attributed: '已归因',
    attribution_ready: '已归因',
    attribution_inconclusive: '归因不足',
    inconclusive: '归因不足',
    skipped: '已跳过',
    pending: '待归因',
    review_required: '需复核',
    failed: '失败',
    error: '失败'
  }[status] || shortText(value, '')
}

function normalizePairedSeed(row, index = 0) {
  const record = row && typeof row === 'object' ? row : {}
  const primitiveSeed = row != null && typeof row !== 'object' ? row : ''
  const baseline = firstObject(record.baseline, record.baseline_result)
  const candidate = firstObject(record.candidate, record.candidate_result)
  const baselineScore = firstFinite(record.baseline_score, record.baseline_role_score, baseline.score, baseline.role_score)
  const candidateScore = firstFinite(record.candidate_score, record.candidate_role_score, candidate.score, candidate.role_score)
  const scoreDelta = firstFinite(
    record.score_delta,
    record.role_score_delta,
    baselineScore != null && candidateScore != null ? candidateScore - baselineScore : null
  )
  return {
    ...record,
    id: shortText(record.id || record.pair_id || record.seed || record.battle_seed || primitiveSeed || index, String(index)),
    seed: shortText(record.seed || record.battle_seed || record.paired_seed || primitiveSeed || index + 1),
    baselineScore,
    candidateScore,
    scoreDelta,
    winnerSide: shortText(record.winner_side || record.winner || record.side, '—'),
    status: shortText(record.status || record.result || (record.rankable === false ? 'unrankable' : 'rankable'), '—'),
    failureReason: shortText(record.failure_reason || record.reason || record.error, ''),
    baselineGameId: record.baseline_game_id || baseline.game_id || '',
    candidateGameId: record.candidate_game_id || candidate.game_id || ''
  }
}

function normalizeProposalAttributionReport(source = {}, gate = {}, run = {}) {
  const report = firstObject(
    source.proposal_attribution_report,
    source.proposalAttributionReport,
    source.proposal_attribution,
    source.proposalAttribution,
    gate.proposal_attribution_report,
    gate.proposalAttributionReport,
    gate.proposal_attribution,
    gate.proposalAttribution,
    run?.proposal_attribution_report,
    run?.proposalAttributionReport,
    run?.proposal_attribution,
    run?.proposalAttribution,
    run?.battle_result?.proposal_attribution_report,
    run?.battle_result?.proposalAttributionReport,
    run?.battle_result?.proposal_attribution,
    run?.battle_result?.proposalAttribution
  )
  const rows = firstArray(report.rows, report.proposals, report.proposal_rows, report.proposalRows)
  const status = shortText(report.status || report.verdict || report.decision, '')
  const reviewRequired = Boolean(report.review_required || report.reviewRequired)
  return {
    ...report,
    status,
    statusLabel: attributionStatusText(status, reviewRequired),
    reviewRequired,
    rowCount: firstFinite(report.row_count, report.rowCount, rows.length) ?? rows.length,
    budget: firstFinite(report.budget, report.max_ablation_runs, report.maxAblationRuns),
    rows
  }
}

function normalizeGateReport(source = {}, run = {}) {
  const gate = firstObject(
    source.gate_report,
    source.promotion_gate,
    source.gate,
    source.gateReport,
    run?.gate_report,
    run?.promotion_gate,
    run?.gate,
    run?.battle_result?.gate_report,
    run?.combined_battle_result?.gate_report
  )
  const metrics = firstObject(gate.metrics, gate.metric_summary, source.metrics, source.metric_summary)
  const proposalAttribution = normalizeProposalAttributionReport(source, gate, run)
  const releaseGate = firstObject(
    source.release_gate,
    source.releaseGate,
    gate.release_gate,
    gate.releaseGate,
    run?.release_gate,
    run?.releaseGate,
    run?.battle_result?.release_gate
  )
  const scenario = firstObject(
    source.scenario_replay_summary,
    source.scenarioReplaySummary,
    gate.scenario_replay,
    gate.scenarioReplay,
    run?.scenario_replay_summary,
    run?.scenarioReplaySummary,
    run?.battle_result?.scenario_replay_summary
  )
  const trustCompleteness = firstObject(
    source.trust_bundle?.completeness,
    source.trustBundle?.completeness,
    gate.trust_bundle_completeness,
    gate.trustBundleCompleteness,
    run?.trust_bundle?.completeness,
    run?.trustBundle?.completeness
  )
  const blockedReasons = uniqueText(firstArray(
    gate.blocked_reasons,
    releaseGate.block_reasons,
    gate.reasons,
    releaseGate.reasons,
    gate.fail_reasons,
    source.blocked_reasons,
    source.reasons
  ))
  const riskTags = uniqueText([
    ...firstArray(gate.risk_tags, source.risk_tags),
    ...firstArray(gate.overfit_risk_tags, source.overfit_risk_tags)
  ])
  const decision = shortText(
    gate.decision ||
      gate.release_decision ||
      releaseGate.decision ||
      gate.status ||
      source.decision ||
      source.release_decision ||
      source.gate_decision ||
      run?.gate_decision ||
      run?.release_decision ||
      run?.recommendation,
    ''
  )
  return {
    ...gate,
    decision,
    decisionLabel: gateDecisionText(decision),
    releaseGate,
    releaseDecision: shortText(gate.release_decision || source.release_decision || releaseGate.decision, ''),
    releaseLabel: gateDecisionText(gate.release_decision || source.release_decision || releaseGate.decision),
    scenario,
    proposalAttribution,
    scenarioCount: firstFinite(metrics.scenario_count, scenario.scenario_count, source.scenario_count),
    scenarioPolicyViolationCount: firstFinite(
      metrics.scenario_policy_violation_count,
      scenario.policy_violation_count,
      source.scenario_policy_violation_count
    ),
    trustCompleteness,
    trustCompletenessScore: firstFinite(trustCompleteness.score, metrics.trust_bundle_completeness),
    proposalAttributionStatus: proposalAttribution.status,
    proposalAttributionLabel: proposalAttribution.statusLabel,
    proposalAttributionRowCount: proposalAttribution.rowCount,
    proposalAttributionReviewRequired: proposalAttribution.reviewRequired,
    blockedReasons,
    riskTags,
    metrics,
    pairedValidCount: firstFinite(metrics.paired_valid_count, metrics.valid_pairs, gate.paired_valid_count, source.paired_valid_count),
    roleScoreDelta: firstFinite(metrics.role_score_delta, gate.role_score_delta, source.role_score_delta),
    winRateDelta: firstFinite(metrics.win_rate_delta, gate.win_rate_delta, source.win_rate_delta, run?.winRateDelta),
    qualityDelta: firstFinite(metrics.decision_quality_delta, metrics.quality_delta, gate.decision_quality_delta)
  }
}

function proposalRiskTags(proposal) {
  const risk = firstObject(proposal?.risk, proposal?.risk_summary, proposal?.overfit_risk)
  return textItems(
    proposal?.risk_tags,
    proposal?.riskTags,
    proposal?.overfit_risk_tags,
    proposal?.overfitRiskTags,
    risk.tags,
    risk.risk_tags,
    risk.riskTags,
    risk.overfit_risk_tags,
    risk.overfitRiskTags
  )
}

function normalizeRejectBuffer(proposal, risk = {}) {
  const buffer = firstObject(
    proposal?.reject_buffer,
    proposal?.rejectBuffer,
    proposal?.reject_result,
    proposal?.rejectResult,
    proposal?.rejection_result,
    proposal?.rejectionResult,
    proposal?.rejection,
    proposal?.rejected_proposal,
    proposal?.rejectedProposal
  )
  const similarity = firstObject(
    proposal?.reject_buffer_similarity,
    proposal?.rejectBufferSimilarity,
    proposal?.similarity,
    buffer.similarity,
    buffer.reject_buffer_similarity,
    buffer.rejectBufferSimilarity,
    risk.similarity
  )
  const matchedRejection = firstObject(
    similarity.matched_rejection,
    similarity.matchedRejection,
    buffer.matched_rejection,
    buffer.matchedRejection
  )
  const saved = firstBoolean(
    buffer.saved,
    buffer.saved_to_buffer,
    buffer.savedToBuffer,
    buffer.persisted,
    proposal?.reject_buffer_saved,
    proposal?.rejectBufferSaved
  )
  const duplicateRejected = firstBoolean(
    similarity.duplicate_rejected,
    similarity.duplicateRejected,
    buffer.duplicate_rejected,
    buffer.duplicateRejected
  )
  const status = shortText(
    buffer.status ||
      buffer.save_status ||
      buffer.saveStatus ||
      buffer.buffer_status ||
      buffer.bufferStatus ||
      (saved === true ? 'saved' : '') ||
      (saved === false ? 'not_saved' : ''),
    ''
  )
  const dedupeKey = shortText(buffer.dedupe_key || buffer.dedupeKey || buffer.key || proposal?.dedupe_key || proposal?.dedupeKey, '')
  const reason = structuredText(
    buffer.reason ||
      buffer.rejection_reason ||
      buffer.rejectionReason ||
      proposal?.rejection_reason ||
      proposal?.review_reason,
    ''
  )
  const scope = shortText(buffer.rejection_scope || buffer.rejectionScope || proposal?.rejection_scope || proposal?.rejectionScope, '')
  const similarityScore = firstFinite(
    similarity.similarity,
    similarity.score,
    similarity.best_score,
    similarity.bestScore,
    buffer.similarity_score,
    buffer.similarityScore
  )
  const overfitScore = firstFinite(
    proposal?.overfit_risk_score,
    proposal?.overfitRiskScore,
    risk.overfit_risk_score,
    risk.overfitRiskScore,
    risk.score,
    buffer.overfit_risk_score,
    buffer.overfitRiskScore
  )
  const tags = textItems(
    buffer.tags,
    buffer.reject_tags,
    buffer.rejectTags,
    buffer.risk_tags,
    buffer.riskTags,
    proposal?.reject_buffer_tags,
    proposal?.rejectBufferTags
  )
  const overfitEvidence = textItems(
    proposal?.overfit_evidence,
    proposal?.overfitEvidence,
    risk.overfit_evidence,
    risk.overfitEvidence,
    buffer.overfit_evidence,
    buffer.overfitEvidence
  )
  const matched = {
    proposalId: shortText(matchedRejection.proposal_id || matchedRejection.proposalId || matchedRejection.id, ''),
    sourceRunId: shortText(matchedRejection.source_run_id || matchedRejection.sourceRunId || matchedRejection.run_id || matchedRejection.runId, ''),
    reason: structuredText(matchedRejection.reason || matchedRejection.rejection_reason || matchedRejection.rejectionReason, '')
  }
  const visible = Boolean(
    status ||
      dedupeKey ||
      reason ||
      scope ||
      tags.length ||
      overfitEvidence.length ||
      saved !== null ||
      duplicateRejected !== null ||
      similarityScore !== null ||
      overfitScore !== null ||
      matched.proposalId ||
      matched.sourceRunId ||
      matched.reason
  )
  return {
    visible,
    saved,
    savedLabel: saved === true ? '已保存' : (saved === false ? '未保存' : ''),
    duplicateRejected,
    duplicateLabel: duplicateRejected === true ? '命中 rejected buffer' : (duplicateRejected === false ? '未命中重复' : ''),
    status,
    dedupeKey,
    reason,
    scope,
    similarityScore,
    overfitScore,
    tags,
    overfitEvidence,
    matched
  }
}

function normalizeProposal(proposal, index = 0) {
  const gate = firstObject(proposal?.gate, proposal?.gate_report, proposal?.promotion_gate)
  const risk = firstObject(proposal?.risk, proposal?.risk_summary, proposal?.overfit_risk)
  const rejectBuffer = normalizeRejectBuffer(proposal, risk)
  const preflight = firstObject(proposal?.preflight, proposal?.preflight_result, proposal?.preflight_check)
  const evidence = firstObject(proposal?.evidence, proposal?.evidence_summary)
  const counterEvidence = firstObject(proposal?.counter_evidence, proposal?.counterEvidence)
  const metricTargets = proposal?.metric_targets ||
    proposal?.metricTargets ||
    proposal?.metric_target ||
    proposal?.target_metrics ||
    proposal?.targets ||
    proposal?.expected_effect?.metric_targets ||
    proposal?.expectedEffect?.metricTargets
  const preflightStatus = shortText(
    proposal?.preflight_status ||
      proposal?.preflightStatus ||
      preflight.status ||
      preflight.decision ||
      preflight.result ||
      (proposal?.preflight_passed === true ? 'passed' : '') ||
      (proposal?.preflight_passed === false ? 'failed' : ''),
    ''
  )
  const apiId = String(proposal?.proposal_id || proposal?.id || '').trim()
  const status = shortText(proposal?.review_status || proposal?.status || proposal?.decision, 'pending')
  const targetFile = shortText(proposal?.target_file || proposal?.file || proposal?.path || proposal?.skill_file, '—')
  const hypothesis = shortText(proposal?.hypothesis || proposal?.strategy_hypothesis || proposal?.claim, '')
  const title = shortText(
    proposal?.title ||
      proposal?.summary ||
      hypothesis ||
      proposal?.name ||
      (targetFile !== '—' ? targetFile : ''),
    `提案 ${index + 1}`
  )
  return {
    ...proposal,
    apiId,
    id: apiId || `proposal-${index + 1}`,
    title,
    targetFile,
    operation: shortText(proposal?.operation || proposal?.action || proposal?.change_type, '变更'),
    status,
    statusLabel: proposalStatusText(status),
    summary: shortText(proposal?.summary || proposal?.description || proposal?.rationale || proposal?.reason || hypothesis),
    rationale: shortText(proposal?.rationale || proposal?.problem_observation || proposal?.evidence || proposal?.reason || proposal?.summary),
    hypothesis,
    triggerCondition: structuredText(
      proposal?.trigger_condition ??
        proposal?.triggerCondition ??
        proposal?.trigger ??
        proposal?.conditions ??
        proposal?.applicability,
      ''
    ),
    expectedEffect: structuredText(
      proposal?.expected_effect ??
        proposal?.expectedEffect ??
        proposal?.expected_outcome ??
        proposal?.expectedOutcome ??
        proposal?.expected_improvement,
      ''
    ),
    metricTargetRows: metricTargetRows(metricTargets),
    evidenceGameIds: textItems(
      proposal?.evidence_game_ids,
      proposal?.evidenceGameIds,
      proposal?.supporting_game_ids,
      proposal?.supportingGameIds,
      proposal?.training_game_ids,
      evidence.game_ids,
      evidence.gameIds
    ),
    counterEvidenceGameIds: textItems(
      proposal?.counter_evidence_game_ids,
      proposal?.counterEvidenceGameIds,
      proposal?.counter_game_ids,
      proposal?.counterGameIds,
      counterEvidence.game_ids,
      counterEvidence.gameIds
    ),
    preflightStatus,
    preflightLabel: preflightStatusText(preflightStatus),
    preflightReasons: textItems(
      proposal?.preflight_reasons,
      proposal?.preflightReasons,
      proposal?.preflight_reason,
      preflight.reasons,
      preflight.reason,
      preflight.blocked_reasons,
      preflight.fail_reasons
    ),
    riskTags: proposalRiskTags(proposal),
    riskLevel: shortText(proposal?.risk_level || risk.level || risk.risk_level || risk.severity, ''),
    riskScore: firstFinite(proposal?.risk_score, proposal?.overfit_risk_score, risk.score, risk.overfit_risk_score),
    rejectBuffer,
    gateDecision: shortText(proposal?.gate_decision || gate.decision || gate.status, ''),
    gateLabel: gateDecisionText(proposal?.gate_decision || gate.decision || gate.status),
    gateReasons: uniqueText(firstArray(proposal?.gate_reasons, gate.blocked_reasons, gate.reasons)),
    pairedSeeds: firstArray(proposal?.paired_seeds, proposal?.paired_seed_summary, proposal?.battle_pairs)
      .map(normalizePairedSeed)
      .slice(0, 6),
    diffPreview: shortText(proposal?.diff_preview || proposal?.patch || proposal?.diff || proposal?.after, '')
  }
}

function proposalSource(data, run) {
  if (Array.isArray(data)) return data
  return firstArray(
    data?.proposals,
    data?.items,
    data?.proposal_reviews,
    data?.proposalReview,
    run?.proposals,
    run?.proposal_reviews,
    run?.proposalReview
  )
}

function pairedSeedSource(data, run) {
  return firstArray(
    data?.paired_seed_summary,
    data?.paired_seeds,
    data?.battle_pairs,
    data?.gate_report?.paired_seed_summary,
    data?.gate_report?.paired_seeds,
    run?.paired_seed_summary,
    run?.paired_seeds,
    run?.battle_pairs,
    run?.battle_result?.paired_seed_summary,
    run?.battle_result?.paired_seeds,
    run?.combined_battle_result?.paired_seed_summary,
    run?.combined_battle_result?.paired_seeds
  )
}

function normalizeProposalReview(data = null, run = null, options = {}) {
  const source = Array.isArray(data) ? { proposals: data } : firstObject(data)
  const reviewSummary = firstObject(source.proposal_review, source.proposalReview, run?.proposal_review, run?.proposalReview)
  const proposals = proposalSource(source, run).map(normalizeProposal)
  const pairedSeeds = pairedSeedSource(source, run).map(normalizePairedSeed)
  const gate = normalizeGateReport(source, run || {})
  const proposalAttribution = firstObject(
    gate.proposalAttribution,
    normalizeProposalAttributionReport(source, gate, run || {})
  )
  const scenarioReplay = firstObject(
    source.scenario_replay_summary,
    source.scenarioReplaySummary,
    source.scenario_replay_report?.summary,
    source.scenarioReplayReport?.summary,
    run?.scenario_replay_summary,
    run?.scenarioReplaySummary,
    run?.scenario_replay_report?.summary
  )
  const trustBundle = firstObject(source.trust_bundle, source.trustBundle, run?.trust_bundle, run?.trustBundle)
  const acceptedCount = proposals.filter((proposal) => ['accepted', 'accept', 'applied'].includes(String(proposal.status).toLowerCase())).length
  const rejectedCount = proposals.filter((proposal) => ['rejected', 'reject'].includes(String(proposal.status).toLowerCase())).length
  const pendingCount = Math.max(0, proposals.length - acceptedCount - rejectedCount)
  const total = firstFinite(reviewSummary.total, reviewSummary.generated_count, proposals.length) ?? proposals.length
  const accepted = firstFinite(reviewSummary.accepted_count, acceptedCount) ?? acceptedCount
  const rejected = firstFinite(reviewSummary.rejected_count, rejectedCount) ?? rejectedCount
  const pending = firstFinite(reviewSummary.pending_count, pendingCount) ?? pendingCount
  const preflight = firstFinite(reviewSummary.preflight_passed_count, reviewSummary.counts?.preflight) ?? 0
  const applied = firstFinite(reviewSummary.applied_count, reviewSummary.applied_proposal_ids?.length) ?? 0
  return {
    loading: false,
    error: options.error || '',
    unsupported: Boolean(options.unsupported),
    source: options.source || (data ? 'api' : 'run-detail'),
    proposals,
    gate,
    proposalAttribution,
    scenarioReplay,
    trustBundle,
    pairedSeeds,
    summary: {
      total,
      generated: firstFinite(reviewSummary.generated_count, total) ?? total,
      preflight,
      accepted,
      rejected,
      pending,
      applied,
      riskTagCount: uniqueText(proposals.flatMap((proposal) => proposal.riskTags)).length,
      pairedSeedCount: pairedSeeds.length,
      scenarioCount: firstFinite(scenarioReplay.scenario_count, gate.scenarioCount) ?? 0,
      scenarioPolicyViolationCount: firstFinite(
        scenarioReplay.policy_violation_count,
        gate.scenarioPolicyViolationCount
      ) ?? 0,
      proposalAttributionStatus: proposalAttribution.status || '',
      proposalAttributionLabel: proposalAttribution.statusLabel || '',
      proposalAttributionRowCount: proposalAttribution.rowCount ?? 0,
      proposalAttributionReviewRequired: Boolean(proposalAttribution.reviewRequired),
      trustCompletenessScore: firstFinite(trustBundle.completeness?.score, gate.trustCompletenessScore)
    }
  }
}

function promotionTrustBundle(run = {}, review = {}) {
  return firstObject(
    review.trustBundle,
    review.trust_bundle,
    run?.trust_bundle,
    run?.trustBundle,
    run?.result?.trust_bundle,
    run?.result?.trustBundle,
    run?.battle_result?.trust_bundle,
    run?.battleResult?.trustBundle
  )
}

function promotionGateReport(run = {}, review = {}) {
  return firstObject(
    review.gate,
    run?.gate_report,
    run?.gateReport,
    run?.promotion_gate,
    run?.promotionGate,
    run?.release_gate,
    run?.releaseGate,
    run?.result?.gate_report,
    run?.result?.gateReport,
    run?.result?.promotion_gate,
    run?.result?.release_gate,
    run?.battle_result?.gate_report,
    run?.battle_result?.release_gate,
    run?.battleResult?.gateReport,
    run?.battleResult?.releaseGate
  )
}

function promotionReleaseDecision(run = {}, review = {}) {
  const gate = promotionGateReport(run, review)
  const releaseGate = firstObject(gate.releaseGate, gate.release_gate, run?.release_gate, run?.releaseGate)
  const trustBundle = promotionTrustBundle(run, review)
  const trustReleaseGate = firstObject(trustBundle.release_gate, trustBundle.releaseGate)
  return firstTextValue(
    run?.release_decision,
    run?.releaseDecision,
    review?.gate?.releaseDecision,
    review?.gate?.release_decision,
    gate.releaseDecision,
    gate.release_decision,
    releaseGate.decision,
    releaseGate.release_decision,
    run?.battle_result?.release_decision,
    run?.battle_result?.release_gate?.decision,
    run?.result?.release_decision,
    trustBundle.release_decision,
    trustBundle.releaseDecision,
    trustReleaseGate.decision
  ).toLowerCase()
}

function promoteRequiresCompleteTrust(run = {}, review = {}) {
  const releaseStage = normalizeReleaseStage(
    run?.published_release_stage ||
      run?.publishedReleaseStage ||
      run?.release_stage ||
      run?.releaseStage ||
      run?.target_release_stage ||
      run?.targetReleaseStage
  )
  const decision = promotionReleaseDecision(run, review)
  return ['baseline', 'official'].includes(releaseStage) || ['baseline_promote', 'official_publish'].includes(decision)
}

function promotionTrustCompleteness(run = {}, review = {}, trustBundle = {}, gate = {}) {
  return firstObject(
    trustBundle.completeness,
    trustBundle.trust_bundle_completeness,
    trustBundle.trustBundleCompleteness,
    review.trustBundle?.completeness,
    review.gate?.trustCompleteness,
    review.gate?.trust_bundle_completeness,
    gate.trustCompleteness,
    gate.trust_bundle_completeness,
    run?.trust_bundle_completeness,
    run?.trustBundleCompleteness,
    run?.result?.trust_bundle_completeness,
    run?.battle_result?.trust_bundle_completeness
  )
}

function hasPromotionGateReference(run = {}, trustBundle = {}, gate = {}) {
  const releaseGate = firstObject(gate.releaseGate, gate.release_gate, run?.release_gate, run?.releaseGate)
  return Boolean(
    trustBundle.gate_report_id ||
      trustBundle.gateReportId ||
      gate.gate_report_id ||
      gate.gateReportId ||
      releaseGate.decision ||
      releaseGate.release_decision ||
      gate.decision ||
      gate.releaseDecision ||
      gate.release_decision
  )
}

function hasPromotionTrainingEvidenceReference(trustBundle = {}) {
  return firstArray(
    trustBundle.training_game_ids,
    trustBundle.trainingGameIds,
    trustBundle.training_evidence_ids,
    trustBundle.trainingEvidenceIds,
    trustBundle.evidence_ids,
    trustBundle.evidenceIds
  ).length > 0
}

function hasPromotionProposalReference(trustBundle = {}) {
  return firstArray(
    trustBundle.proposal_ids,
    trustBundle.proposalIds,
    trustBundle.accepted_proposal_ids,
    trustBundle.acceptedProposalIds,
    trustBundle.applied_proposal_ids,
    trustBundle.appliedProposalIds
  ).length > 0
}

const TRUST_MISSING_ITEM_LABELS = {
  trust_bundle: '信任包',
  gate_report: '门禁报告',
  training_evidence: '训练证据',
  proposals: '提案证据',
  completeness: '完整性'
}

function trustMissingItemKey(item) {
  const key = String(item || '').trim().toLowerCase().replaceAll('-', '_').replaceAll(' ', '_')
  if ([
    'evidence',
    'training_evidence',
    'training_game',
    'training_games',
    'training_game_ids',
    'training_evidence_ids',
    'evidence_ids',
    'paired_seed_table',
    'paired_seed_pairs',
    'battle_pair_seeds'
  ].includes(key)) return 'training_evidence'
  if ([
    'proposal',
    'proposals',
    'proposal_ids',
    'accepted_proposal_ids',
    'applied_proposal_ids',
    'generated_proposal_ids',
    'preflight_passed_proposal_ids',
    'rejected_proposal_ids'
  ].includes(key)) return 'proposals'
  if ([
    'gate',
    'release_gate',
    'promotion_gate',
    'gate_report',
    'gate_report_id',
    'promotion_gate_report'
  ].includes(key)) return 'gate_report'
  if ([
    'bundle',
    'bundle_hash',
    'trust_bundle',
    'trust_bundle_id',
    'completeness',
    'trust_completeness',
    'trust_bundle_completeness'
  ].includes(key)) return 'trust_bundle'
  return key
}

function trustMissingItemLabel(item) {
  const key = trustMissingItemKey(item)
  return TRUST_MISSING_ITEM_LABELS[key] || key
}

function baselinePromoteTrustDisabledReason(run = {}, review = {}) {
  if (!promoteRequiresCompleteTrust(run, review)) return ''
  const trustBundle = promotionTrustBundle(run, review)
  if (!Object.keys(trustBundle).length) return '缺少完整信任包，不能晋升为基线。'
  const gate = promotionGateReport(run, review)
  const completeness = promotionTrustCompleteness(run, review, trustBundle, gate)
  const missing = uniqueText([
    ...firstArray(completeness.missing, completeness.missing_items, completeness.missingItems).map(trustMissingItemKey),
    ...(!Object.keys(completeness).length ? ['trust_bundle'] : []),
    ...(!(trustBundle.trust_bundle_id || trustBundle.trustBundleId) || !(trustBundle.bundle_hash || trustBundle.bundleHash) ? ['trust_bundle'] : []),
    ...(!hasPromotionGateReference(run, trustBundle, gate) ? ['gate_report'] : []),
    ...(!hasPromotionTrainingEvidenceReference(trustBundle) ? ['training_evidence'] : []),
    ...(!hasPromotionProposalReference(trustBundle) ? ['proposals'] : [])
  ])
  if (completeness.complete !== true || missing.length) {
    const suffix = missing.length ? `缺失：${missing.slice(0, 4).map(trustMissingItemLabel).join('、')}。` : '完整性未通过。'
    return `信任包不完整，不能晋升为基线。${suffix}`
  }
  return ''
}

function sourceRunIdFrom(run = {}, version = {}, input = {}) {
  return firstTextValue(
    input.run_id,
    input.runId,
    input.source_run_id,
    input.sourceRunId,
    version.source_run_id,
    version.sourceRunId,
    version.provenance?.source_run_id,
    version.provenance?.sourceRunId,
    run?.run_id,
    run?.id,
    run?.source_run_id,
    run?.sourceRunId
  )
}

function rollbackTargetFrom(...values) {
  for (const value of values) {
    if (value == null || value === '') continue
    if (typeof value === 'object') {
      const text = firstTextValue(
        value.version_id,
        value.versionId,
        value.target_version_id,
        value.targetVersionId,
        value.rollback_version_id,
        value.rollbackVersionId,
        value.id,
        value.hash,
        value.target
      )
      if (text) return text
      const structured = structuredText(value, '')
      if (structured) return structured
      continue
    }
    const text = String(value).trim()
    if (text) return text
  }
  return ''
}

function trustAuditSourceText(value) {
  return {
    authority: '权威信任包',
    review: '提案审核',
    run: '自进化运行',
    version: '版本详情'
  }[String(value || '').toLowerCase()] || shortText(value, '信任包')
}

function hashHref(view, params = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    const text = String(value ?? '').trim()
    if (text) query.set(key, text)
  }
  const suffix = query.toString()
  return suffix ? `#${view}?${suffix}` : `#${view}`
}

function evidenceHref(id) {
  const value = String(id || '').trim()
  return value ? hashHref('logs', { game_id: value, workspace: 'archive' }) : ''
}

function evolutionHref(params = {}) {
  return hashHref('evolution', params)
}

function evolutionDeepLinkPanel(target = {}) {
  return routeEvolutionDeepLinkPanel(target)
}

function evolutionDeepLinkFromHash(value = currentLegacyHash()) {
  return routeEvolutionDeepLinkFromHash(value)
}

function evolutionDeepLinkFromRoute(route) {
  return routeEvolutionDeepLinkFromRoute(route)
}

function auditEvidenceRows(ids, hrefForId) {
  return ids.map((id) => ({
    id,
    href: hrefForId(id)
  }))
}

const TRUST_CONSISTENCY_FIELDS = [
  { field: 'trust_bundle_id', label: 'trust_bundle_id', required: true },
  { field: 'bundle_hash', label: 'bundle_hash', required: true },
  { field: 'gate_report_id', label: 'gate_report_id', required: true },
  { field: 'source_run_id', label: 'source_run_id', required: true },
  { field: 'version_id', label: 'version_id', required: false },
  { field: 'role', label: 'role', required: false }
]

function auditText(value) {
  return String(value ?? '').trim()
}

function auditFieldValue(audit = {}, field) {
  return auditText(audit?.[field])
}

function trustConsistencyStatus(values = [], hasAuthority = false) {
  const cached = auditText(values.find((item) => item.source === 'cached')?.value)
  const authority = auditText(values.find((item) => item.source === 'authority')?.value)
  if (hasAuthority) {
    if (!cached || !authority) return 'missing'
    const known = uniqueText(values.map((item) => auditText(item.value)).filter(Boolean))
    return known.length > 1 ? 'mismatch' : 'match'
  }
  const known = values.map((item) => auditText(item.value)).filter(Boolean)
  if (!known.length) return 'missing'
  const unique = uniqueText(known)
  if (unique.length > 1) return 'mismatch'
  return known.length > 1 ? 'match' : 'unknown'
}

function trustConsistencyMessage(field, status, values = [], hasAuthority = false) {
  const cached = auditText(values.find((item) => item.source === 'cached')?.value)
  const authority = auditText(values.find((item) => item.source === 'authority')?.value)
  const registry = auditText(values.find((item) => item.source === 'registry')?.value)
  const sourceRun = auditText(values.find((item) => item.source === 'source_run')?.value)
  if (status === 'match') {
    return hasAuthority
      ? '缓存、版本库/来源运行与权威包一致。'
      : '版本库/来源运行已知值一致。'
  }
  if (status === 'mismatch') {
    if (hasAuthority) {
      return `缓存 ${cached || '—'}，版本库 ${registry || '—'}，来源运行 ${sourceRun || '—'}，权威包 ${authority || '—'}。`
    }
    return `版本库 ${registry || '—'}，来源运行 ${sourceRun || '—'}。`
  }
  if (status === 'missing') {
    if (hasAuthority && !authority) return '权威包缺少该字段。'
    if (hasAuthority && !cached) return '缓存或版本库/来源运行缺少该字段。'
    return `${field} 缺少可校验值。`
  }
  return '等待权威包校验。'
}

function trustAuditConsistencyChecks(cached = {}, authority = null) {
  const hasAuthority = Boolean(authority)
  return TRUST_CONSISTENCY_FIELDS.flatMap(({ field, label, required }) => {
    const cachedValue = auditFieldValue(cached, field)
    const authorityValue = hasAuthority ? auditFieldValue(authority, field) : ''
    const registryValue = auditText(authority?.registry_metadata?.[field] || cached?.registry_metadata?.[field])
    const sourceRunValue = auditText(authority?.source_run_metadata?.[field] || cached?.source_run_metadata?.[field])
    const bundleValue = auditText(authority?.bundle_metadata?.[field] || cached?.bundle_metadata?.[field])
    if (!required && !cachedValue && !authorityValue && !registryValue && !sourceRunValue && !bundleValue) return []
    const values = [
      { source: 'cached', value: cachedValue },
      { source: 'authority', value: authorityValue },
      { source: 'registry', value: registryValue },
      { source: 'source_run', value: sourceRunValue },
      { source: 'bundle', value: bundleValue }
    ]
    const status = trustConsistencyStatus(values, hasAuthority)
    return [{
      field,
      label,
      status,
      message: trustConsistencyMessage(label, status, values, hasAuthority),
      cached_value: cachedValue,
      authority_value: authorityValue,
      registry_value: registryValue,
      source_run_value: sourceRunValue,
      bundle_value: bundleValue
    }]
  })
}

function trustAuditMismatches(cached = {}, authority = {}) {
  return trustAuditConsistencyChecks(cached, authority)
    .filter((item) => item.status === 'mismatch')
    .map((item) => item.field)
}

function normalizeTrustCompleteness(completeness = {}, hasTrustBundle = false, explicitMissing = []) {
  const explicitComplete = completeness.complete ?? completeness.is_complete ?? completeness.isComplete
  const statusTextValue = firstTextValue(completeness.status, completeness.state, completeness.verdict).toLowerCase()
  const complete = hasTrustBundle
    ? (explicitComplete === true || ['complete', 'completed', 'pass', 'passed'].includes(statusTextValue)
        ? true
        : (explicitComplete === false || ['incomplete', 'missing', 'failed', 'fail'].includes(statusTextValue) ? false : null))
    : false
  const knownMissingKeys = uniqueText([
    ...explicitMissing.map(trustMissingItemKey),
    ...firstArray(completeness.missing, completeness.missing_items, completeness.missingItems).map(trustMissingItemKey),
    ...(!hasTrustBundle ? ['trust_bundle'] : [])
  ])
  const missingKeys = uniqueText([
    ...knownMissingKeys,
    ...(hasTrustBundle && complete === false && !knownMissingKeys.length ? ['completeness'] : [])
  ])
  const status = !hasTrustBundle ? 'missing' : (complete === true ? 'complete' : (complete === false ? 'incomplete' : 'unknown'))
  return {
    ...completeness,
    complete,
    score: firstFinite(completeness.score, completeness.completeness_score, completeness.completenessScore),
    status,
    statusLabel: {
      complete: '完整',
      incomplete: '不完整',
      missing: '缺失',
      unknown: '未上报'
    }[status],
    missingKeys,
    missingLabels: missingKeys.map(trustMissingItemLabel)
  }
}

function normalizeTrustBundleAudit(input = {}) {
  const run = firstObject(input.run)
  const review = firstObject(input.review)
  const version = firstObject(input.version)
  const source = shortText(input.source || 'review', 'review')
  const gate = firstObject(input.gate, promotionGateReport(run, review))
  const trustBundle = firstObject(
    input.trustBundle,
    input.trust_bundle,
    review.trustBundle,
    review.trust_bundle,
    run?.trust_bundle,
    run?.trustBundle,
    run?.result?.trust_bundle,
    run?.result?.trustBundle,
    run?.battle_result?.trust_bundle,
    run?.battleResult?.trustBundle,
    version.trust_bundle,
    version.trustBundle,
    version.provenance?.trust_bundle,
    version.provenance?.trustBundle
  )
  const trustBundleId = firstTextValue(
    input.trust_bundle_id,
    input.trustBundleId,
    trustBundle.trust_bundle_id,
    trustBundle.trustBundleId,
    version.trust_bundle_id,
    version.trustBundleId,
    version.provenance?.trust_bundle_id,
    version.provenance?.trustBundleId,
    run?.trust_bundle_id,
    run?.trustBundleId
  )
  const bundleHash = firstTextValue(
    input.bundle_hash,
    input.bundleHash,
    trustBundle.bundle_hash,
    trustBundle.bundleHash,
    trustBundle.hash,
    version.bundle_hash,
    version.bundleHash,
    version.provenance?.bundle_hash,
    version.provenance?.bundleHash,
    run?.bundle_hash,
    run?.bundleHash
  )
  const gateReportId = firstTextValue(
    input.gate_report_id,
    input.gateReportId,
    trustBundle.gate_report_id,
    trustBundle.gateReportId,
    gate.gate_report_id,
    gate.gateReportId,
    version.gate_report_id,
    version.gateReportId,
    version.provenance?.gate_report_id,
    version.provenance?.gateReportId,
    run?.gate_report_id,
    run?.gateReportId
  )
  const hasTrustBundle = Boolean(Object.keys(trustBundle).length || trustBundleId || bundleHash)
  const completenessSource = firstObject(
    input.completeness,
    trustBundle.completeness,
    trustBundle.trust_bundle_completeness,
    trustBundle.trustBundleCompleteness,
    promotionTrustCompleteness(run, review, trustBundle, gate)
  )
  const explicitMissing = textItems(
    input.missing,
    input.missing_items,
    input.missingItems,
    trustBundle.missing,
    trustBundle.missing_items,
    trustBundle.missingItems
  )
  const completeness = normalizeTrustCompleteness(completenessSource, hasTrustBundle, explicitMissing)
  const trainingGameIds = textItems(
    input.training_game_ids,
    input.trainingGameIds,
    trustBundle.training_game_ids,
    trustBundle.trainingGameIds,
    trustBundle.training_evidence_ids,
    trustBundle.trainingEvidenceIds,
    trustBundle.evidence_ids,
    trustBundle.evidenceIds,
    trustBundle.training_evidence?.game_ids,
    trustBundle.trainingEvidence?.gameIds
  )
  const proposalIds = textItems(
    input.proposal_ids,
    input.proposalIds,
    trustBundle.proposal_ids,
    trustBundle.proposalIds,
    trustBundle.accepted_proposal_ids,
    trustBundle.acceptedProposalIds,
    trustBundle.applied_proposal_ids,
    trustBundle.appliedProposalIds
  )
  const pairedSeeds = firstArray(
    input.pairedSeeds,
    input.paired_seeds,
    input.paired_seed_summary,
    input.paired_seed_pairs,
    input.pairedSeedPairs,
    input.battle_pair_seeds,
    input.battlePairSeeds,
    trustBundle.pairedSeeds,
    trustBundle.paired_seeds,
    trustBundle.paired_seed_summary,
    trustBundle.paired_seed_pairs,
    trustBundle.pairedSeedPairs,
    trustBundle.battle_pair_seeds,
    trustBundle.battlePairSeeds,
    trustBundle.seed_details,
    trustBundle.seedDetails,
    gate.pairedSeeds,
    gate.paired_seeds,
    gate.paired_seed_summary,
    gate.paired_seed_pairs,
    gate.battle_pair_seeds,
    review.pairedSeeds,
    review.paired_seeds,
    review.paired_seed_pairs,
    review.paired_seed_battle_table,
    review.battlePairs,
    run?.pairedSeeds,
    run?.paired_seeds,
    run?.paired_seed_pairs,
    run?.paired_seed_battle_table,
    run?.battle_pairs,
    run?.battle_result?.paired_seeds,
    run?.battle_result?.paired_seed_summary,
    run?.battle_result?.paired_seed_pairs,
    run?.battle_result?.battle_pair_seeds
  ).map(normalizePairedSeed)
  const sourceRunId = sourceRunIdFrom(run, version, input)
  const proposalHrefForId = (proposalId) => sourceRunId ? evolutionHref({ run_id: sourceRunId, proposal_id: proposalId }) : ''
  const role = firstTextValue(input.role, version.role, run?.role)
  const versionId = firstTextValue(input.version_id, input.versionId, version.version_id, version.versionId)
  const rollbackTarget = rollbackTargetFrom(
    input.rollback_target,
    input.rollbackTarget,
    trustBundle.rollback_target,
    trustBundle.rollbackTarget,
    trustBundle.rollback_version_id,
    trustBundle.rollbackVersionId,
    version.rollback_target,
    version.rollbackTarget,
    version.rollback_version_id,
    version.rollbackVersionId,
    version.provenance?.rollback_target,
    version.provenance?.rollbackTarget
  )
  const registryTrustBundle = firstObject(
    version.trust_bundle,
    version.trustBundle,
    version.provenance?.trust_bundle,
    version.provenance?.trustBundle
  )
  const sourceRunTrustBundle = firstObject(
    run?.trust_bundle,
    run?.trustBundle,
    run?.result?.trust_bundle,
    run?.result?.trustBundle,
    run?.battle_result?.trust_bundle,
    run?.battleResult?.trustBundle
  )
  const registryMetadata = {
    trust_bundle_id: firstTextValue(version.trust_bundle_id, version.trustBundleId, version.provenance?.trust_bundle_id, version.provenance?.trustBundleId, registryTrustBundle.trust_bundle_id, registryTrustBundle.trustBundleId),
    bundle_hash: firstTextValue(version.bundle_hash, version.bundleHash, version.provenance?.bundle_hash, version.provenance?.bundleHash, registryTrustBundle.bundle_hash, registryTrustBundle.bundleHash, registryTrustBundle.hash),
    gate_report_id: firstTextValue(version.gate_report_id, version.gateReportId, version.provenance?.gate_report_id, version.provenance?.gateReportId, registryTrustBundle.gate_report_id, registryTrustBundle.gateReportId),
    source_run_id: firstTextValue(version.source_run_id, version.sourceRunId, version.provenance?.source_run_id, version.provenance?.sourceRunId),
    version_id: firstTextValue(version.version_id, version.versionId),
    role: firstTextValue(version.role, version.provenance?.role)
  }
  const sourceRunMetadata = {
    trust_bundle_id: firstTextValue(run?.trust_bundle_id, run?.trustBundleId, sourceRunTrustBundle.trust_bundle_id, sourceRunTrustBundle.trustBundleId),
    bundle_hash: firstTextValue(run?.bundle_hash, run?.bundleHash, sourceRunTrustBundle.bundle_hash, sourceRunTrustBundle.bundleHash, sourceRunTrustBundle.hash),
    gate_report_id: firstTextValue(run?.gate_report_id, run?.gateReportId, sourceRunTrustBundle.gate_report_id, sourceRunTrustBundle.gateReportId),
    source_run_id: firstTextValue(run?.run_id, run?.id, run?.source_run_id, run?.sourceRunId),
    version_id: firstTextValue(run?.version_id, run?.versionId, run?.published_version_id, run?.publishedVersionId, run?.promoted_version_id, run?.promotedVersionId),
    role: firstTextValue(run?.role)
  }
  const bundleMetadata = {
    trust_bundle_id: trustBundleId,
    bundle_hash: bundleHash,
    gate_report_id: gateReportId,
    source_run_id: sourceRunId,
    version_id: versionId,
    role
  }
  const audit = {
    source,
    sourceLabel: trustAuditSourceText(source),
    authorityStatus: shortText(input.authorityStatus || input.authority_status || '', ''),
    authorityMessage: shortText(input.authorityMessage || input.authority_message || '', ''),
    mismatchLabels: textItems(input.mismatchLabels, input.mismatch_labels),
    hasTrustBundle,
    emptyMessage: hasTrustBundle ? '' : '缺少信任包：未收到 trust_bundle_id 或 bundle_hash。',
    trust_bundle_id: trustBundleId,
    bundle_hash: bundleHash,
    gate_report_id: gateReportId,
    gate_report_href: gateReportId && sourceRunId ? evolutionHref({ run_id: sourceRunId, gate_report_id: gateReportId }) : '',
    rollback_target: rollbackTarget,
    source_run_id: sourceRunId,
    source_run_href: sourceRunId ? evolutionHref({ run_id: sourceRunId }) : '',
    role,
    version_id: versionId,
    version_href: versionId
      ? evolutionHref({ role, version_id: versionId })
      : '',
    registry_metadata: registryMetadata,
    source_run_metadata: sourceRunMetadata,
    bundle_metadata: bundleMetadata,
    completeness,
    missingKeys: completeness.missingKeys,
    missingLabels: completeness.missingLabels,
    training_game_ids: trainingGameIds,
    training_evidence: auditEvidenceRows(trainingGameIds, evidenceHref),
    proposal_ids: proposalIds,
    proposal_evidence: auditEvidenceRows(proposalIds, proposalHrefForId),
    paired_seeds: pairedSeeds,
    raw: trustBundle
  }
  return {
    ...audit,
    consistency_checks: trustAuditConsistencyChecks(audit)
  }
}

function isMissingProposalEndpoint(error) {
  const message = String(error?.message || '').toLowerCase()
  return message.includes('404') || message.includes('not found') || message.includes('unexpected')
}

function errorText(error) {
  return String(error?.message || error || '').trim()
}

function evolutionNoticeFromError(error, fallback = '操作失败', context = '') {
  const raw = errorText(error)
  const message = raw.toLowerCase()
  const code = String(error?.code || error?.payload?.error?.code || '').toLowerCase()
  const notFound = message.includes('not found') || message.includes('404')
  if (message.includes('batch does not support')) {
    return { type: 'warning', message: '批量任务不支持该操作，请选择子运行。', reason: 'batchUnsupported' }
  }
  if (message.includes('no accepted proposals to apply')) {
    return { type: 'warning', message: '没有已接受提案可应用。', reason: 'noAcceptedProposals' }
  }
  if (message.includes('accepted or applied proposal') || message.includes('proposal review required')) {
    return { type: 'warning', message: '至少接受或应用一个提案后才能晋升。', reason: 'proposalReviewRequired' }
  }
  if (code === 'evolution_trust_bundle_required' || (context === 'run' && message.includes('trust bundle required'))) {
    return { type: 'warning', message: '缺少完整信任包，不能晋升为基线。', reason: 'trustBundleRequired' }
  }
  if (
    code === 'evolution_trust_bundle_incomplete' ||
    (context === 'run' && (message.includes('complete trust bundle') || message.includes('trust bundle/gate/evidence')))
  ) {
    return { type: 'warning', message: '信任包不完整，不能晋升为基线。', reason: 'trustBundleIncomplete' }
  }
  if (message.includes('proposal not found') || (context === 'proposal' && notFound)) {
    return { type: 'warning', message: '提案不存在，请刷新审核面板。', reason: 'proposalNotFound' }
  }
  if (message.includes('version not found') || (context === 'version' && notFound)) {
    return { type: 'warning', message: '版本不存在，请刷新版本列表。', reason: 'versionNotFound' }
  }
  if (message.includes('run not found') || message.includes('evolution run not found') || (context === 'run' && notFound)) {
    return { type: 'warning', message: '运行不存在，请刷新列表。', reason: 'runNotFound' }
  }
  return { type: 'error', message: raw || fallback, reason: 'error' }
}

function runActionSuccessMessage(action) {
  if (action === 'promote') return '运行已晋升。'
  if (action === 'reject') return '运行已拒绝。'
  if (action === 'terminate') return '运行已终止。'
  return '运行操作已完成。'
}

function proposalActionSuccessMessage(action) {
  if (action === 'accept') return '提案已接受。'
  if (action === 'reject') return '提案已拒绝。'
  return '提案操作已完成。'
}

function useEvolutionWorkbench(options = {}) {
  const { apiFetch, apiBase } = options.apiFetch
    ? { apiFetch: options.apiFetch, apiBase: options.apiBase || '/api' }
    : createGameApi(options.apiBase)

  const loading = ref(false)
  const actionLoading = ref('')
  const error = ref('')
  const notice = ref({ type: '', message: '' })
  const noticeAutoDismiss = createNoticeAutoDismiss(notice, {
    enabled: options.installLifecycle !== false,
    onDismiss(dismissed) {
      if (dismissed.type !== 'error' && error.value === dismissed.message) error.value = ''
    }
  })
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
  const selectedProposalReview = ref(normalizeProposalReview(null, null, { source: 'none' }))
  const selectedGames = ref(emptySampleGames())
  const selectedGameBucket = ref('training')
  const selectedGameId = ref('')
  const selectedVersionId = ref('')
  const selectedVersionDetail = ref({
    loading: false,
    error: '',
    data: null
  })
  const trustBundleDrawerOpen = ref(false)
  const trustBundleAudit = ref(normalizeTrustBundleAudit({ source: 'review' }))
  const trustBundleAuditLoading = ref(false)
  const trustBundleAuditError = ref('')
  const initialDeepLinkHash = Object.prototype.hasOwnProperty.call(options, 'initialHash')
    ? options.initialHash
    : currentLegacyHash()
  const initialDeepLinkTarget = Object.prototype.hasOwnProperty.call(options, 'initialRoute')
    ? evolutionDeepLinkFromRoute(options.initialRoute)
    : evolutionDeepLinkFromHash(initialDeepLinkHash || '')
  const evolutionDeepLinkTarget = ref(initialDeepLinkTarget)
  const versionDetailCache = ref({})
  const selectedGameDetail = ref({
    loading: false,
    error: '',
    warning: '',
    archive: null,
    decisions: [],
    events: []
  })
  const selectedSampleState = ref({
    loading: false,
    error: '',
    unsupported: false,
    errorsByBucket: {}
  })
  const selectedBatchRoles = ref([])
  const eventLog = ref([])
  const sse = ref(null)
  const runFilter = ref('')
  const sampleGameFilter = ref('')
  const runPageSize = Math.max(1, Number(options.runListLimit || DEFAULT_RUN_PAGE_SIZE))
  const sampleGamePageSize = Math.max(1, Number(options.sampleGameListLimit || DEFAULT_SAMPLE_GAME_PAGE_SIZE))
  const runPagination = ref(createPagination(runPageSize))
  const runLoadingMore = ref(false)
  const sampleGamePagination = ref(samplePaginationMap(sampleGamePageSize))
  const sampleGameLoadingMoreBucket = ref('')
  const roleRequests = createLatestOnlyTracker()
  const versionListRequests = createLatestOnlyMap()
  const leaderboardRequests = createLatestOnlyMap()
  const runListRequests = createLatestOnlyTracker()
  const refreshRequests = createLatestOnlyTracker()
  const runSelectionRequests = createLatestOnlyTracker()
  const diffRequests = createLatestOnlyTracker()
  const proposalReviewRequests = createLatestOnlyTracker()
  const sampleListRequests = createLatestOnlyTracker()
  const sampleDetailRequests = createLatestOnlyTracker()
  const versionDetailRequests = createLatestOnlyTracker()
  const trustBundleRequests = createLatestOnlyTracker()
  const actionRequests = createLatestOnlyTracker()

  const form = ref({
    training_games: 5,
    battle_games: 4,
    max_days: 5,
    auto_promote: true
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
  const visibleRunRows = computed(() => filteredRunRows.value)
  const runHasMore = computed(() => Boolean(runPagination.value.has_more))

  const selectedRoleVersions = computed(() => versionsByRole.value[selectedRole.value] || [])
  const selectedVersion = computed(() =>
    selectedRoleVersions.value.find((version) => version.version_id === selectedVersionId.value) || null
  )
  const selectedRoleLeaderboard = computed(() => leaderboardsByRole.value[selectedRole.value] || [])
  const selectedRoleLabel = computed(() => roleMeta(selectedRole.value).label)
  const hasSelection = computed(() => Boolean(selectedRun.value))
  const selectedIsBatch = computed(() => selectedRun.value?.entityType === 'batch')
  const selectedIsRun = computed(() => selectedRun.value?.entityType === 'run')
  const selectedRunSummary = computed(() => {
    const run = selectedRun.value
    if (!run) {
      return {
        id: '',
        entityLabel: '—',
        displayRole: '—',
        statusLabel: '—',
        currentStageLabel: '—',
        overallProgressPercent: 0,
        overallProgressLabel: '等待',
        stageProgressPercent: 0,
        stageProgressLabel: '等待',
        trainingProgressLabel: '等待',
        battleProgressLabel: '等待',
        recommendationLabel: '—',
        parentShort: '—',
        candidateShort: '—',
        publishedReleaseStageLabel: '—',
        trainingGameCompleted: 0,
        trainingGameRequested: 0,
        battleGameCompleted: 0,
        battleGameRequested: 0,
        winRateDeltaPct: 0,
        proposalCount: 0,
        diffCount: 0,
        diagnosticCount: 0,
        warningCount: 0,
        errorCount: 0
      }
    }
    return {
      id: run.id,
      entityLabel: run.entityLabel,
      displayRole: run.displayRole,
      statusLabel: run.statusLabel,
      currentStageLabel: run.currentStageLabel,
      overallProgressPercent: run.overallProgressPercent,
      overallProgressLabel: run.overallProgressLabel,
      stageProgressPercent: run.stageProgressPercent,
      stageProgressLabel: run.stageProgressLabel,
      trainingProgressLabel: run.trainingProgressLabel,
      battleProgressLabel: run.battleProgressLabel,
      recommendationLabel: run.recommendationLabel || recommendationText(run.recommendation),
      parentShort: run.parentShort,
      candidateShort: run.candidateShort,
      publishedReleaseStageLabel: run.publishedReleaseStageLabel,
      trainingGameCompleted: run.trainingGameCompleted,
      trainingGameRequested: run.trainingGameRequested,
      battleGameCompleted: run.battleGameCompleted,
      battleGameRequested: run.battleGameRequested,
      winRateDeltaPct: run.winRateDeltaPct,
      proposalCount: run.proposalCount,
      diffCount: run.diffCount,
      diagnosticCount: run.diagnosticCount,
      warningCount: run.warningCount,
      errorCount: run.errorCount
    }
  })
  const sampleBuckets = computed(() => [
    { key: 'training', label: SAMPLE_BUCKET_LABELS.training, count: Number(sampleGamePagination.value.training?.total ?? selectedGames.value.training.length) },
    { key: 'baseline', label: SAMPLE_BUCKET_LABELS.baseline, count: Number(sampleGamePagination.value.baseline?.total ?? selectedGames.value.baseline.length) },
    { key: 'candidate', label: SAMPLE_BUCKET_LABELS.candidate, count: Number(sampleGamePagination.value.candidate?.total ?? selectedGames.value.candidate.length) }
  ])
  const selectedGameRows = computed(() =>
    (selectedGames.value[selectedGameBucket.value] || []).map((game) =>
      normalizeSampleGame(game, selectedGameBucket.value)
    )
  )
  const selectedSampleGame = computed(() =>
    selectedGameRows.value.find((game) => game.id === selectedGameId.value) || null
  )
  const selectedSampleHistoryGameId = computed(() =>
    selectedGameDetail.value.archive?.history_game_id ||
    selectedSampleGame.value?.history_game_id ||
    ''
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
  const visibleSampleGameRows = computed(() => filteredSampleGameRows.value)
  const selectedSamplePagination = computed(() =>
    sampleGamePagination.value[selectedGameBucket.value] || createPagination(sampleGamePageSize)
  )
  const sampleGameHasMore = computed(() => Boolean(selectedSamplePagination.value.has_more))
  const sampleGameLoadingMore = computed(() => sampleGameLoadingMoreBucket.value === selectedGameBucket.value)
  const selectedSampleBucketError = computed(() =>
    selectedSampleState.value.errorsByBucket?.[selectedGameBucket.value] || ''
  )
  const selectedSampleHistoryUnavailableReason = computed(() => {
    if (selectedIsBatch.value) return '批量任务没有单局回放，请进入子运行查看样本局。'
    if (!selectedSampleGame.value) return '请先选择一局样本。'
    if (selectedGameDetail.value.loading) return '样本局详情仍在读取。'
    if (!selectedSampleHistoryGameId.value) return '缺少历史对局 ID，无法打开大厅回放或日志。'
    return ''
  })
  const selectedProposalRows = computed(() => selectedProposalReview.value.proposals || [])
  const selectedBaselinePromoteTrustDisabledReason = computed(() => {
    if (!selectedRun.value) return ''
    return baselinePromoteTrustDisabledReason(selectedRun.value, selectedProposalReview.value || {})
  })
  const selectedPromoteDisabledReason = computed(() => {
    if (!selectedRun.value) return '请选择一个运行。'
    if (selectedIsBatch.value) return '批量任务不能直接晋升，请选择子运行。'
    if (!selectedIsRun.value) return '请选择单角色运行。'
    if (selectedRun.value.status !== 'reviewing') return '只有待评审运行可以晋升。'
    const review = selectedProposalReview.value || {}
    if (review.loading) return '提案审核状态读取中。'
    if (review.unsupported) return review.error || '提案审核不可用，无法晋升。'
    if (review.error) return '提案审核读取失败，请刷新后重试。'
    const summary = review.summary || {}
    const accepted = Number(summary.accepted || summary.accepted_count || 0)
    const applied = Number(summary.applied || summary.applied_count || 0)
    if ((Number.isFinite(accepted) ? accepted : 0) + (Number.isFinite(applied) ? applied : 0) <= 0) {
      return '至少接受或应用一个提案后才能晋升。'
    }
    const trustReason = selectedBaselinePromoteTrustDisabledReason.value
    if (trustReason) return trustReason
    return ''
  })
  const selectedCanPromote = computed(() => !selectedPromoteDisabledReason.value)
  const selectedRejectDisabledReason = computed(() => {
    if (!selectedRun.value) return '请选择一个运行。'
    if (selectedIsBatch.value) return '批量任务不能直接拒绝，请选择子运行。'
    if (!selectedIsRun.value) return '请选择单角色运行。'
    if (selectedRun.value.status !== 'reviewing') return '只有待评审运行可以拒绝。'
    return ''
  })
  const selectedCanReject = computed(() => !selectedRejectDisabledReason.value)
  const selectedTerminateDisabledReason = computed(() => {
    if (!selectedRun.value) return '请选择一个运行。'
    if (selectedRun.value.isTerminal) return '运行已结束，不能终止。'
    return ''
  })
  const selectedCanTerminate = computed(() => !selectedTerminateDisabledReason.value)
  const selectedRollbackDisabledReason = computed(() => {
    if (!selectedVersion.value) return '请选择一个版本。'
    return selectedVersion.value.rollbackDisabledReason || ''
  })

  function setError(message) {
    error.value = message || ''
  }

  function setNotice(type, message) {
    notice.value = { type, message }
  }

  function clearNotice() {
    notice.value = { type: '', message: '' }
  }

  function setNoticeFromError(err, fallback, context = '') {
    const next = evolutionNoticeFromError(err, fallback, context)
    setNotice(next.type, next.message)
    return next
  }

  function clearVersionDetail() {
    selectedVersionId.value = ''
    selectedVersionDetail.value = { loading: false, error: '', data: null }
  }

  function currentTrustBundleAudit(source = 'review', payload = {}) {
    const input = typeof source === 'object' && source !== null ? source : { ...payload, source }
    const normalizedSource = shortText(input.source || source || 'review', 'review')
    return normalizeTrustBundleAudit({
      ...input,
      source: normalizedSource,
      run: input.run || selectedRun.value || {},
      review: input.review || selectedProposalReview.value || {},
      version: input.version || (normalizedSource === 'version' ? selectedVersionDetail.value.data : {}) || {}
    })
  }

  function trustBundleAuthorityRunId(audit = {}, payload = {}) {
    return firstTextValue(
      payload.run_id,
      payload.runId,
      payload.source_run_id,
      payload.sourceRunId,
      audit.source_run_id,
      selectedRun.value?.run_id,
      selectedRun.value?.id,
      selectedRunId.value
    )
  }

  async function refreshTrustBundleAudit(source = trustBundleAudit.value.source || 'review', payload = {}) {
    const baseAudit = payload.baseAudit || currentTrustBundleAudit(source, payload)
    const runId = trustBundleAuthorityRunId(baseAudit, payload)
    if (!runId) {
      trustBundleAuditError.value = '缺少来源运行，无法读取权威信任包。'
      trustBundleAudit.value = {
        ...baseAudit,
        authorityStatus: 'unavailable',
        authorityMessage: trustBundleAuditError.value
      }
      return trustBundleAudit.value
    }

    const token = trustBundleRequests.next()
    trustBundleAuditLoading.value = true
    trustBundleAuditError.value = ''
    trustBundleAudit.value = {
      ...baseAudit,
      authorityStatus: 'loading',
      authorityMessage: '正在读取权威信任包。'
    }
    try {
      const data = await apiFetch(`/evolution-runs/${encodeURIComponent(runId)}/trust-bundle`)
      if (!token.isLatest()) return trustBundleAudit.value
      const authorityAudit = normalizeTrustBundleAudit({
        ...data,
        source: 'authority',
        run: selectedRun.value || { run_id: runId },
        review: selectedProposalReview.value || {},
        version: selectedVersionDetail.value.data || {}
      })
      const consistencyChecks = trustAuditConsistencyChecks(baseAudit, authorityAudit)
      const mismatchLabels = trustAuditMismatches(baseAudit, authorityAudit)
      trustBundleAudit.value = {
        ...authorityAudit,
        cachedAudit: baseAudit,
        authorityStatus: mismatchLabels.length ? 'mismatch' : 'verified',
        authorityMessage: mismatchLabels.length
          ? '权威信任包与当前页面缓存不一致。'
          : '已读取权威信任包。',
        mismatchLabels,
        consistency_checks: consistencyChecks
      }
      return trustBundleAudit.value
    } catch (err) {
      if (!token.isLatest()) return trustBundleAudit.value
      trustBundleAuditError.value = err?.message || '权威信任包读取失败'
      trustBundleAudit.value = {
        ...baseAudit,
        authorityStatus: 'unavailable',
        authorityMessage: trustBundleAuditError.value
      }
      return trustBundleAudit.value
    } finally {
      if (token.isLatest()) trustBundleAuditLoading.value = false
    }
  }

  function openTrustBundleDrawer(source = 'review', payload = {}) {
    const baseAudit = currentTrustBundleAudit(source, payload)
    trustBundleAudit.value = baseAudit
    trustBundleDrawerOpen.value = true
    const runId = trustBundleAuthorityRunId(baseAudit, payload)
    if (!runId) return Promise.resolve(baseAudit)
    return refreshTrustBundleAudit(source, { ...payload, baseAudit, run_id: runId })
  }

  function closeTrustBundleDrawer() {
    trustBundleDrawerOpen.value = false
  }

  function setEvolutionDeepLinkTarget(target, patch = {}) {
    if (!target) {
      evolutionDeepLinkTarget.value = null
      return null
    }
    const next = {
      ...target,
      panel: target.panel || evolutionDeepLinkPanel(target),
      ...patch
    }
    evolutionDeepLinkTarget.value = next
    return next
  }

  function consumeEvolutionDeepLink(value = currentLegacyHash()) {
    const target = value && typeof value === 'object'
      ? evolutionDeepLinkFromRoute(value)
      : evolutionDeepLinkFromHash(value)
    if (!target) return null
    const current = evolutionDeepLinkTarget.value
    if (!current || current.query !== target.query || current.status === 'applied') {
      return setEvolutionDeepLinkTarget(target)
    }
    return current
  }

  function proposalDeepLinkResolved(proposalId) {
    const id = String(proposalId || '').trim()
    if (!id) return true
    if (selectedProposalRows.value.some((proposal) =>
      [proposal.apiId, proposal.proposal_id, proposal.id].some((value) => String(value || '') === id)
    )) return true
    return textItems(
      selectedProposalReview.value?.trustBundle?.proposal_ids,
      selectedProposalReview.value?.trustBundle?.proposalIds,
      selectedProposalReview.value?.trust_bundle?.proposal_ids,
      selectedRun.value?.trust_bundle?.proposal_ids,
      selectedRun.value?.trustBundle?.proposalIds
    ).includes(id)
  }

  function gateDeepLinkResolved(gateReportId) {
    const id = String(gateReportId || '').trim()
    if (!id) return true
    const review = selectedProposalReview.value || {}
    const gate = review.gate || {}
    const trustBundle = review.trustBundle || review.trust_bundle || {}
    return [
      gate.gate_report_id,
      gate.gateReportId,
      trustBundle.gate_report_id,
      trustBundle.gateReportId,
      selectedRun.value?.gate_report_id,
      selectedRun.value?.gateReportId,
      selectedRun.value?.trust_bundle?.gate_report_id,
      selectedRun.value?.trustBundle?.gateReportId
    ].some((value) => String(value || '') === id)
  }

  async function applyEvolutionDeepLink(target = evolutionDeepLinkTarget.value) {
    if (!target) return false
    const runId = firstTextValue(target.run_id)
    const explicitRole = firstTextValue(target.role)
    const versionId = firstTextValue(target.version_id)
    const proposalId = firstTextValue(target.proposal_id)
    const gateReportId = firstTextValue(target.gate_report_id)
    const pending = []
    setEvolutionDeepLinkTarget(target, {
      status: 'applying',
      pending: [],
      selected_run_id: selectedRunId.value,
      selected_version_id: selectedVersionId.value,
      message: '正在恢复自进化定位链接。'
    })
    try {
      if (runId && (selectedRunId.value !== runId || !selectedRun.value)) {
        await selectRun(runId)
      }
    } catch (err) {
      pending.push('run')
      setEvolutionDeepLinkTarget(target, {
        status: 'partial',
        pending,
        error: err?.message || '运行详情读取失败',
        selected_run_id: selectedRunId.value,
        selected_version_id: selectedVersionId.value,
        message: '运行目标未能恢复，已保留定位链接待重试。'
      })
      return true
    }

    if (runId && selectedRunId.value !== runId) pending.push('run')

    const role = explicitRole || (versionId ? firstTextValue(selectedRun.value?.role) : '')
    if (role) selectRole(role)
    if (versionId) {
      if (role) {
        await loadVersionDetail(role, versionId)
        if (selectedVersionDetail.value.error) pending.push('version_detail')
      } else {
        selectedVersionId.value = versionId
        pending.push('role')
      }
      if (selectedVersionId.value !== versionId) pending.push('version')
    }

    if (proposalId || gateReportId) {
      if (!selectedRunId.value) {
        pending.push('run')
      } else {
        if (!selectedProposalReview.value || selectedProposalReview.value.source === 'none') {
          await loadProposalReview(selectedRunId.value)
        }
        if (!proposalDeepLinkResolved(proposalId)) pending.push('proposal')
        if (!gateDeepLinkResolved(gateReportId)) pending.push('gate_report')
        trustBundleAudit.value = currentTrustBundleAudit('review')
        trustBundleDrawerOpen.value = true
      }
    }

    const status = pending.length ? 'partial' : 'applied'
    setEvolutionDeepLinkTarget(target, {
      status,
      pending,
      selected_run_id: selectedRunId.value,
      selected_version_id: selectedVersionId.value,
      trust_drawer_open: trustBundleDrawerOpen.value,
      message: status === 'applied'
        ? '自进化定位链接已恢复。'
        : '自进化定位链接已部分恢复，剩余目标保留为待恢复状态。'
    })
    return true
  }

  function handleEvolutionHashChange(event = {}) {
    const target = consumeEvolutionDeepLink(event.newURL || currentLegacyHash())
    if (target) void applyEvolutionDeepLink(target)
  }

  function clearSampleSelection({ unsupported = false, message = '' } = {}) {
    sampleGameLoadingMoreBucket.value = ''
    selectedGames.value = emptySampleGames()
    sampleGamePagination.value = samplePaginationMap(sampleGamePageSize)
    selectedGameBucket.value = 'training'
    selectedGameId.value = ''
    selectedGameDetail.value = {
      loading: false,
      error: '',
      warning: '',
      archive: null,
      decisions: [],
      events: []
    }
    selectedSampleState.value = {
      loading: false,
      error: message,
      unsupported,
      errorsByBucket: {}
    }
  }

  function clearDiffSelection() {
    selectedDiff.value = []
    selectedDiffData.value = null
  }

  function clearProposalReview({ unsupported = false, message = '' } = {}) {
    selectedProposalReview.value = normalizeProposalReview(null, selectedRun.value, {
      source: unsupported ? 'unsupported' : 'run-detail',
      unsupported,
      error: message
    })
  }

  function selectRole(role) {
    if (!role) return
    if (selectedRole.value !== role) clearVersionDetail()
    selectedRole.value = role
  }

  async function loadRoles() {
    const token = roleRequests.next()
    try {
      const overview = await apiFetch('/roles/overview')
      if (!token.isLatest()) return false
      roles.value = overview.roles || []
      if (!selectedRole.value && roles.value.length) selectedRole.value = roles.value[0]
      if (!selectedBatchRoles.value.length) selectedBatchRoles.value = roles.value.slice()
      const overviewVersions = overview.versions || {}
      const overviewLeaderboards = overview.leaderboards || {}
      versionsByRole.value = Object.fromEntries(
        roles.value.map((role) => [role, (overviewVersions[role] || []).map(normalizeVersion)])
      )
      leaderboardsByRole.value = Object.fromEntries(
        roles.value.map((role) => [role, (overviewLeaderboards[role]?.entries || []).map(normalizeLeaderboardEntry)])
      )
      return token.isLatest()
    } catch {
      // Keep compatibility with frontend mock data and older backend instances.
    }

    const data = await apiFetch('/roles')
    if (!token.isLatest()) return false
    roles.value = data.roles || []
    if (!selectedRole.value && roles.value.length) selectedRole.value = roles.value[0]
    if (!selectedBatchRoles.value.length) selectedBatchRoles.value = roles.value.slice()
    await Promise.all(roles.value.map(async (role) => {
      await Promise.all([loadVersions(role), loadLeaderboard(role)])
    }))
    return token.isLatest()
  }

  async function loadVersions(role) {
    if (!role) return
    const token = versionListRequests.next(role)
    try {
      const data = await apiFetch(`/roles/${encodeURIComponent(role)}/versions`)
      if (!token.isLatest()) return
      versionsByRole.value = {
        ...versionsByRole.value,
        [role]: (data.versions || []).map(normalizeVersion)
      }
    } catch {
      if (token.isLatest()) versionsByRole.value = { ...versionsByRole.value, [role]: [] }
    }
  }

  async function loadLeaderboard(role) {
    if (!role) return
    const token = leaderboardRequests.next(role)
    try {
      const data = await apiFetch(`/roles/${encodeURIComponent(role)}/leaderboard`)
      if (!token.isLatest()) return
      leaderboardsByRole.value = {
        ...leaderboardsByRole.value,
        [role]: (data.entries || []).map(normalizeLeaderboardEntry)
      }
    } catch {
      if (token.isLatest()) leaderboardsByRole.value = { ...leaderboardsByRole.value, [role]: [] }
    }
  }

  function runListQuery(offset = 0) {
    const params = new URLSearchParams()
    params.set('limit', String(runPageSize))
    params.set('offset', String(Math.max(0, offset || 0)))
    params.set('source', 'evolution')
    return `?${params.toString()}`
  }

  async function fetchRunPage(offset = 0) {
    const data = await apiFetch(`/evolution-runs${runListQuery(offset)}`)
    const pageRuns = data.runs || []
    const pageBatches = (data.batches || []).filter(isEvolutionBatch)
    return {
      pageRuns,
      pageBatches,
      pagination: paginationFromResponse(data, [...pageRuns, ...pageBatches], { offset, limit: runPageSize })
    }
  }

  async function fetchRunDetail(id, fallback = null) {
    try {
      return normalizeRun(await apiFetch(`/evolution-runs/${encodeURIComponent(id)}`))
    } catch (err) {
      if (fallback) return normalizeRun(fallback)
      throw err
    }
  }

  function rememberRunDetail(run) {
    if (!run?.id) return
    if (run.entityType === 'batch') {
      if (!batches.value.some((item) => (item.batch_id || item.id) === run.id)) {
        batches.value = mergeById(batches.value, [run], ['batch_id', 'id']).filter(isEvolutionBatch)
      }
      return
    }
    if (!runs.value.some((item) => (item.run_id || item.id) === run.id)) {
      runs.value = mergeById(runs.value, [run], ['run_id', 'id'])
    }
  }

  async function loadRuns({ append = false, selectFirst = true } = {}) {
    const token = runListRequests.next()
    if (!append) runLoadingMore.value = false
    const offset = append ? runPagination.value.offset + runPagination.value.returned : 0
    const { pageRuns, pageBatches, pagination } = await fetchRunPage(offset)
    if (!token.isLatest()) return false
    runs.value = append ? mergeById(runs.value, pageRuns, 'run_id') : pageRuns
    batches.value = append ? mergeById(batches.value, pageBatches, 'batch_id').filter(isEvolutionBatch) : pageBatches
    runPagination.value = pagination
    if (selectFirst && !selectedRunId.value && runRows.value.length) {
      await selectRun(runRows.value[0].id)
    } else if (selectedRunId.value) {
      const current = runRows.value.find((item) => item.id === selectedRunId.value)
      if (current && (!selectedRun.value || selectedRun.value.id !== current.id)) selectedRun.value = current
    }
    return token.isLatest()
  }

  async function loadMoreRuns() {
    if (runLoadingMore.value || !runPagination.value.has_more) return
    const token = runListRequests.next()
    runLoadingMore.value = true
    clearNotice()
    try {
      const offset = runPagination.value.offset + runPagination.value.returned
      const { pageRuns, pageBatches, pagination } = await fetchRunPage(offset)
      if (!token.isLatest()) return
      runs.value = mergeById(runs.value, pageRuns, 'run_id')
      batches.value = mergeById(batches.value, pageBatches, 'batch_id').filter(isEvolutionBatch)
      runPagination.value = pagination
      if (selectedRunId.value) {
        const current = runRows.value.find((item) => item.id === selectedRunId.value)
        if (current && (!selectedRun.value || selectedRun.value.id !== current.id)) selectedRun.value = current
      }
      setNotice('success', pageRuns.length + pageBatches.length ? '已加载更多运行记录。' : '没有更多运行记录。')
    } catch (err) {
      if (token.isLatest()) {
        const next = setNoticeFromError(err, '运行记录读取失败', 'run')
        setError(next.message)
      }
    } finally {
      if (token.isLatest()) runLoadingMore.value = false
    }
  }

  async function refreshAll({ silent = false } = {}) {
    const refreshToken = refreshRequests.next()
    const token = runListRequests.next()
    const deepLinkTarget = consumeEvolutionDeepLink() || evolutionDeepLinkTarget.value
    runLoadingMore.value = false
    if (!silent) loading.value = true
    setError('')
    try {
      await loadRoles()
      if (!token.isLatest()) return
      const { pageRuns, pageBatches, pagination } = await fetchRunPage(0)
      if (!token.isLatest()) return
      runs.value = pageRuns
      batches.value = pageBatches
      runPagination.value = pagination
      const deepLinkApplied = await applyEvolutionDeepLink(deepLinkTarget)
      if (!deepLinkApplied && !selectedRunId.value && runRows.value.length) {
        await selectRun(runRows.value[0].id)
      } else if (!deepLinkApplied && selectedRunId.value) {
        const current = runRows.value.find((item) => item.id === selectedRunId.value)
        if (current) await selectRun(selectedRunId.value)
      }
    } catch (err) {
      if (refreshToken.isLatest()) setError(err?.message || '自进化数据读取失败')
    } finally {
      if (refreshToken.isLatest()) loading.value = false
    }
  }

  async function selectRun(id) {
    if (!id) return
    const token = runSelectionRequests.next()
    selectedRunId.value = id
    const row = runRows.value.find((item) => item.id === id)
    const loaded = await fetchRunDetail(id, row)
    if (!token.isLatest() || selectedRunId.value !== id) return
    selectedRun.value = loaded
    rememberRunDetail(loaded)
    if (selectedRun.value?.role) selectRole(selectedRun.value.role)
    if (selectedRun.value?.entityType === 'batch') {
      clearDiffSelection()
      clearProposalReview({
        unsupported: true,
        message: '批量任务不直接提供逐条提案评审，请进入子运行查看。'
      })
      clearSampleSelection({
        unsupported: true,
        message: '批量任务不直接提供样本局和 diff，请在子运行中查看单角色详情。'
      })
    } else {
      await Promise.all([
        loadDiff(id, { parentToken: token }),
        loadRunGames(id, { parentToken: token }),
        loadProposalReview(id, { parentToken: token })
      ])
    }
    if (!token.isLatest() || selectedRunId.value !== id) return
    if (selectedRun.value?.isActive) {
      connect(id)
    }
  }

  async function loadDiff(id = selectedRunId.value, { parentToken = null } = {}) {
    if (!id) return
    const token = diffRequests.next()
    try {
      const data = await apiFetch(`/evolution-runs/${encodeURIComponent(id)}/diff`)
      if (!token.isLatest() || (parentToken && !parentToken.isLatest()) || selectedRunId.value !== id) return
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
      if (token.isLatest() && (!parentToken || parentToken.isLatest()) && selectedRunId.value === id) {
        selectedDiff.value = []
        selectedDiffData.value = null
      }
    }
  }

  async function loadProposalReview(id = selectedRunId.value, { parentToken = null } = {}) {
    if (!id) return
    const token = proposalReviewRequests.next()
    selectedProposalReview.value = {
      ...normalizeProposalReview(null, selectedRun.value, { source: 'run-detail' }),
      loading: true,
      error: ''
    }
    try {
      const data = await apiFetch(`/evolution-runs/${encodeURIComponent(id)}/proposals`)
      if (!token.isLatest() || (parentToken && !parentToken.isLatest()) || selectedRunId.value !== id) return
      selectedProposalReview.value = normalizeProposalReview(data, selectedRun.value, { source: 'api' })
    } catch (err) {
      if (!token.isLatest() || (parentToken && !parentToken.isLatest()) || selectedRunId.value !== id) return
      const missing = isMissingProposalEndpoint(err)
      selectedProposalReview.value = normalizeProposalReview(null, selectedRun.value, {
        source: 'run-detail',
        unsupported: missing,
        error: missing ? '' : (err?.message || '提案评审读取失败')
      })
    }
  }

  function sampleGameParams(bucket = selectedGameBucket.value) {
    const params = new URLSearchParams()
    if (bucket === 'training') {
      params.set('phase', 'training')
    } else {
      params.set('phase', 'battle')
      params.set('side', bucket)
    }
    return params
  }

  function sampleGameListQuery(bucket = selectedGameBucket.value, offset = 0) {
    const params = sampleGameParams(bucket)
    params.set('limit', String(sampleGamePageSize))
    params.set('offset', String(Math.max(0, offset || 0)))
    return `?${params.toString()}`
  }

  async function fetchSampleGamePage(id, bucket, offset = 0) {
    const data = await apiFetch(`/evolution-runs/${encodeURIComponent(id)}/games${sampleGameListQuery(bucket, offset)}`)
    const rows = data.games || []
    return {
      rows,
      pagination: paginationFromResponse(data, rows, { offset, limit: sampleGamePageSize })
    }
  }

  async function loadRunGames(id = selectedRunId.value, { parentToken = null } = {}) {
    if (!id) return
    const token = sampleListRequests.next()
    sampleGameLoadingMoreBucket.value = ''
    selectedSampleState.value = {
      loading: true,
      error: '',
      unsupported: false,
      errorsByBucket: {}
    }
    const pages = await Promise.all(SAMPLE_GAME_BUCKETS.map(async (bucket) => {
      try {
        return { bucket, ...(await fetchSampleGamePage(id, bucket, 0)), error: '' }
      } catch (err) {
        return {
          bucket,
          rows: [],
          pagination: createPagination(sampleGamePageSize),
          error: err?.message || `${SAMPLE_BUCKET_LABELS[bucket] || bucket}样本局读取失败`
        }
      }
    }))
    if (!token.isLatest() || (parentToken && !parentToken.isLatest()) || selectedRunId.value !== id) return false
    const errorsByBucket = Object.fromEntries(pages
      .filter((page) => page.error)
      .map((page) => [page.bucket, page.error]))
    selectedGames.value = Object.fromEntries(SAMPLE_GAME_BUCKETS.map((bucket) => {
      const page = pages.find((item) => item.bucket === bucket)
      return [bucket, page?.rows || []]
    }))
    sampleGamePagination.value = Object.fromEntries(SAMPLE_GAME_BUCKETS.map((bucket) => {
      const page = pages.find((item) => item.bucket === bucket)
      return [bucket, page?.pagination || createPagination(sampleGamePageSize)]
    }))
    selectedSampleState.value = {
      loading: false,
      error: Object.values(errorsByBucket)[0] || '',
      unsupported: false,
      errorsByBucket
    }
    const buckets = SAMPLE_GAME_BUCKETS
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
      selectedGameDetail.value = { loading: false, error: '', warning: '', archive: null, decisions: [], events: [] }
    }
    return token.isLatest()
  }

  function sampleGameQuery(bucket = selectedGameBucket.value) {
    return sampleGameParams(bucket).toString()
  }

  async function loadMoreSampleGames(bucket = selectedGameBucket.value) {
    const runId = selectedRunId.value
    const pagination = sampleGamePagination.value[bucket] || createPagination(sampleGamePageSize)
    if (!runId || selectedIsBatch.value || sampleGameLoadingMoreBucket.value || !pagination.has_more) return
    const token = sampleListRequests.next()
    sampleGameLoadingMoreBucket.value = bucket
    clearNotice()
    try {
      const offset = pagination.offset + pagination.returned
      const { rows, pagination: nextPagination } = await fetchSampleGamePage(runId, bucket, offset)
      if (!token.isLatest() || selectedRunId.value !== runId) return
      selectedGames.value = {
        ...selectedGames.value,
        [bucket]: mergeById(selectedGames.value[bucket] || [], rows, ['game_id', 'id'])
      }
      sampleGamePagination.value = {
        ...sampleGamePagination.value,
        [bucket]: nextPagination
      }
      selectedSampleState.value = {
        ...selectedSampleState.value,
        error: '',
        errorsByBucket: {
          ...selectedSampleState.value.errorsByBucket,
          [bucket]: ''
        }
      }
      setNotice('success', `已加载更多${SAMPLE_BUCKET_LABELS[bucket] || bucket}样本局。`)
    } catch (err) {
      if (token.isLatest()) {
        const next = setNoticeFromError(err, `${SAMPLE_BUCKET_LABELS[bucket] || bucket}样本局读取失败`, 'run')
        const message = next.message
        selectedSampleState.value = {
          ...selectedSampleState.value,
          error: message,
          errorsByBucket: {
            ...selectedSampleState.value.errorsByBucket,
            [bucket]: message
          }
        }
      }
    } finally {
      if (token.isLatest()) sampleGameLoadingMoreBucket.value = ''
    }
  }

  async function loadSampleGameDetail(bucket = selectedGameBucket.value, gameId = selectedGameId.value) {
    const runId = selectedRunId.value
    if (!runId || !gameId || selectedIsBatch.value) return
    const token = sampleDetailRequests.next()
    selectedGameDetail.value = {
      ...selectedGameDetail.value,
      loading: true,
      error: '',
      warning: ''
    }
    const base = `/evolution-runs/${encodeURIComponent(runId)}/games/${encodeURIComponent(gameId)}`
    const query = sampleGameQuery(bucket)
    try {
      const [archiveResult, decisionsResult, eventsResult] = await Promise.allSettled([
        apiFetch(`${base}/archive?${query}`),
        apiFetch(`${base}/decisions?${query}`),
        apiFetch(`${base}/events?${query}`)
      ])
      if (!token.isLatest() || selectedRunId.value !== runId || selectedGameBucket.value !== bucket || selectedGameId.value !== gameId) return
      const archive = archiveResult.status === 'fulfilled' ? archiveResult.value : null
      const decisions = decisionsResult.status === 'fulfilled' ? decisionsResult.value : { decisions: [] }
      const events = eventsResult.status === 'fulfilled' ? eventsResult.value : { events: [] }
      const failures = [
        archiveResult.status === 'rejected' ? '档案' : '',
        decisionsResult.status === 'rejected' ? '决策' : '',
        eventsResult.status === 'rejected' ? '事件' : ''
      ].filter(Boolean)
      selectedGameDetail.value = {
        loading: false,
        error: failures.length === 3 ? '样本局详情读取失败' : '',
        warning: failures.length && failures.length < 3 ? `${failures.join('、')}读取失败，当前仅展示可用详情。` : '',
        archive,
        decisions: decisions?.decisions || [],
        events: events?.events || []
      }
    } catch (err) {
      if (token.isLatest()) {
        selectedGameDetail.value = {
          loading: false,
          error: err?.message || '样本局详情读取失败',
          warning: '',
          archive: null,
          decisions: [],
          events: []
        }
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
      selectedGameDetail.value = { loading: false, error: '', warning: '', archive: null, decisions: [], events: [] }
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
    const token = versionDetailRequests.next()
    selectedVersionDetail.value = {
      loading: true,
      error: '',
      data: selectedVersionDetail.value.data?.version_id === versionId ? selectedVersionDetail.value.data : null
    }
    try {
      const data = await apiFetch(`/roles/${encodeURIComponent(role)}/versions/${encodeURIComponent(versionId)}`)
      if (!token.isLatest() || selectedRole.value !== role || selectedVersionId.value !== versionId) return
      versionDetailCache.value = {
        ...versionDetailCache.value,
        [key]: data
      }
      selectedVersionDetail.value = { loading: false, error: '', data }
    } catch (err) {
      if (token.isLatest()) {
        selectedVersionDetail.value = {
          loading: false,
          error: err?.message || '版本详情读取失败',
          data: null
        }
      }
    }
  }

  function closeEventStream() {
    evolutionStream.closeAll()
    sse.value = null
  }

  function resetLastEventId(id) {
    evolutionStream.resetEventId(id)
  }

  const evolutionStream = createResumableEventSource({
    events: ['progress', 'reviewing', 'promoted', 'rejected', 'failed', 'completed'],
    backoff: true,
    makeUrl(id, lastEventId) {
      const base = `${apiBase}/evolution-runs/${encodeURIComponent(id)}/events`
      return lastEventId ? `${base}?lastEventId=${encodeURIComponent(lastEventId)}` : base
    },
    shouldReconnect(id) {
      const current = runRows.value.find((item) => item.id === id) || selectedRun.value
      return selectedRunId.value === id && Boolean(current?.isActive)
    },
    isTerminal(event) {
      return event.type === 'reviewing' || EVOLUTION_TERMINAL_STATUSES.has(event.type)
    },
    async onEvent({ id, event, payload, source }) {
      const terminal = event.type === 'reviewing' || EVOLUTION_TERMINAL_STATUSES.has(event.type)
      if (terminal) {
        if (sse.value === source) sse.value = null
      }
      eventLog.value = [
        { id: `${Date.now()}-${event.type}`, type: event.type, payload },
        ...eventLog.value
      ].slice(0, 24)
      await loadRuns()
      if (selectedRunId.value === id) {
        if (terminal) {
          const current = runRows.value.find((item) => item.id === id)
          selectedRun.value = normalizeRun({ ...(current || selectedRun.value || {}), ...(payload || {}), run_id: id })
          if (selectedRun.value?.entityType === 'batch') {
            clearDiffSelection()
            clearProposalReview({
              unsupported: true,
              message: '批量任务不直接提供逐条提案评审，请进入子运行查看。'
            })
            clearSampleSelection({
              unsupported: true,
              message: '批量任务不直接提供样本局和 diff，请在子运行中查看单角色详情。'
            })
          } else {
            await Promise.all([loadDiff(id), loadRunGames(id), loadProposalReview(id)])
          }
          return
        }
        await selectRun(id)
      }
    },
    onError({ id, source }) {
      if (sse.value === source) sse.value = null
    }
  })

  function connect(id) {
    if (!id || typeof EventSource === 'undefined') return
    if (String(id).startsWith('mock-')) return
    const current = runRows.value.find((item) => item.id === id) || selectedRun.value
    if (current && !current.isActive) return
    if (evolutionStream.has(id)) {
      sse.value = evolutionStream.connect(id)
      return
    }
    closeEventStream()
    sse.value = evolutionStream.connect(id)
  }

  function toggleBatchRole(role) {
    const current = selectedBatchRoles.value
    selectedBatchRoles.value = current.includes(role)
      ? current.filter((item) => item !== role)
      : [...current, role]
  }

  function numberField(name, fallback, min = 1) {
    if (form.value[name] === '' || form.value[name] == null) return fallback
    const value = Number(form.value[name])
    return Number.isFinite(value) && value >= min ? Math.floor(value) : fallback
  }

  function autoPromoteField() {
    return Boolean(form.value.auto_promote)
  }

  async function startSingle() {
    if (!selectedRole.value) {
      const message = '请选择一个有基线版本的角色'
      setError(message)
      setNotice('warning', message)
      return
    }
    const token = actionRequests.next()
    actionLoading.value = 'start-single'
    setError('')
    clearNotice()
    let created = null
    try {
      created = await apiFetch('/evolution-runs', {
        method: 'POST',
        body: JSON.stringify({
          roles: [selectedRole.value],
          training_games: numberField('training_games', 5),
          battle_games: numberField('battle_games', 4),
          max_days: numberField('max_days', 5),
          auto_promote: autoPromoteField()
        })
      })
      if (!token.isLatest()) return
      resetLastEventId(created.run_id || created.batch_id)
      await loadRuns()
      if (!token.isLatest()) return
      await selectRun(created.run_id || created.batch_id)
      if (!token.isLatest()) return
      setNotice('success', '单角色进化已启动。')
    } catch (err) {
      if (token.isLatest()) {
        if (created?.run_id || created?.batch_id) {
          const message = '单角色进化已启动，但列表刷新失败，请手动刷新。'
          setError(message)
          setNotice('warning', message)
        } else {
          const next = setNoticeFromError(err, '启动单角色进化失败', 'run')
          setError(next.message)
        }
      }
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  async function startBatch() {
    if (!selectedBatchRoles.value.length) {
      const message = '请选择至少一个角色'
      setError(message)
      setNotice('warning', message)
      return
    }
    const token = actionRequests.next()
    actionLoading.value = 'start-batch'
    setError('')
    clearNotice()
    let created = null
    try {
      created = await apiFetch('/evolution-runs', {
        method: 'POST',
        body: JSON.stringify({
          roles: [...selectedBatchRoles.value],
          training_games: numberField('training_games', 5),
          battle_games: numberField('battle_games', 4),
          max_days: numberField('max_days', 5),
          auto_promote: autoPromoteField()
        })
      })
      if (!token.isLatest()) return
      resetLastEventId(created.batch_id || created.run_id)
      await loadRuns()
      if (!token.isLatest()) return
      await selectRun(created.batch_id || created.run_id)
      if (!token.isLatest()) return
      setNotice('success', '批量进化已启动。')
    } catch (err) {
      if (token.isLatest()) {
        if (created?.run_id || created?.batch_id) {
          const message = '批量进化已启动，但列表刷新失败，请手动刷新。'
          setError(message)
          setNotice('warning', message)
        } else {
          const next = setNoticeFromError(err, '启动批量进化失败', 'run')
          setError(next.message)
        }
      }
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  async function runAction(id, action) {
    if (!id || !action) return
    const token = actionRequests.next()
    actionLoading.value = `${action}:${id}`
    setError('')
    clearNotice()
    try {
      const result = await apiFetch(`/evolution-runs/${encodeURIComponent(id)}/actions`, {
        method: 'POST',
        body: JSON.stringify({ action })
      })
      if (!token.isLatest()) return
      await loadRuns()
      if (!token.isLatest()) return
      await selectRun(result.run_id || result.batch_id || id)
      if (!token.isLatest()) return
      await loadRoles()
      if (!token.isLatest()) return
      setNotice('success', runActionSuccessMessage(action))
    } catch (err) {
      if (token.isLatest()) {
        const next = setNoticeFromError(err, '操作失败', 'run')
        setError(next.message)
      }
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  async function updateProposal(id, proposalId, action, body = {}) {
    if (!id || !proposalId || !action) return
    const token = actionRequests.next()
    actionLoading.value = `proposal-${action}:${proposalId}`
    setError('')
    clearNotice()
    try {
      const result = await apiFetch(
        `/evolution-runs/${encodeURIComponent(id)}/proposals/${encodeURIComponent(proposalId)}/${encodeURIComponent(action)}`,
        {
          method: 'POST',
          body: JSON.stringify(body)
        }
      )
      if (!token.isLatest()) return
      if (result?.run || result?.run_id || result?.batch_id) {
        selectedRun.value = normalizeRun(result.run || { ...(selectedRun.value || {}), ...(result || {}), run_id: id })
      }
      await loadProposalReview(id)
      if (!token.isLatest()) return
      setNotice('success', proposalActionSuccessMessage(action))
    } catch (err) {
      if (token.isLatest()) {
        const next = setNoticeFromError(err, '提案操作失败', 'proposal')
        setError(next.message)
      }
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  async function acceptProposal(proposal, id = selectedRunId.value) {
    const proposalId = proposal?.apiId || proposal?.proposal_id || proposal?.id
    await updateProposal(id, proposalId, 'accept')
  }

  async function rejectProposal(proposal, id = selectedRunId.value, reason = '', options = {}) {
    const proposalId = proposal?.apiId || proposal?.proposal_id || proposal?.id
    const tags = textItems(options?.tags, options?.metadata?.tags)
    await updateProposal(id, proposalId, 'reject', {
      reason: reason || 'manual_reject',
      tags
    })
  }

  async function applyAcceptedProposals(id = selectedRunId.value) {
    if (!id) return
    const token = actionRequests.next()
    actionLoading.value = `proposal-apply:${id}`
    setError('')
    clearNotice()
    try {
      const result = await apiFetch(`/evolution-runs/${encodeURIComponent(id)}/proposals/apply-accepted`, {
        method: 'POST'
      })
      if (!token.isLatest()) return
      if (result?.run || result?.run_id || result?.batch_id) {
        selectedRun.value = normalizeRun(result.run || { ...(selectedRun.value || {}), ...(result || {}), run_id: id })
      }
      await Promise.all([loadProposalReview(id), loadDiff(id)])
      if (!token.isLatest()) return
      setNotice('success', '已应用接受提案。')
    } catch (err) {
      if (token.isLatest()) {
        const next = setNoticeFromError(err, '应用已接受提案失败', 'proposal')
        setError(next.message)
      }
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  async function rollback(role, versionId) {
    if (!role || !versionId) return
    const token = actionRequests.next()
    actionLoading.value = `rollback:${role}:${versionId}`
    setError('')
    clearNotice()
    try {
      await apiFetch(`/roles/${encodeURIComponent(role)}/rollback/${encodeURIComponent(versionId)}`, {
        method: 'POST'
      })
      if (!token.isLatest()) return
      await Promise.all([loadVersions(role), loadLeaderboard(role), loadRuns()])
      if (!token.isLatest()) return
      setNotice('success', '基线版本已回滚。')
    } catch (err) {
      if (token.isLatest()) {
        const next = setNoticeFromError(err, '回滚基线失败', 'version')
        setError(next.message)
      }
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  if (options.installLifecycle !== false) {
    onMounted(() => {
      consumeEvolutionDeepLink()
      if (typeof window !== 'undefined') window.addEventListener('hashchange', handleEvolutionHashChange)
    })
    onBeforeUnmount(() => {
      closeEventStream()
      noticeAutoDismiss.dispose()
      if (typeof window !== 'undefined') window.removeEventListener('hashchange', handleEvolutionHashChange)
    })
  }

  return {
    loading,
    actionLoading,
    error,
    notice,
    roles,
    roleRows,
    versionsByRole,
    leaderboardsByRole,
    runs,
    batches,
    runRows,
    filteredRunRows,
    visibleRunRows,
    runPagination,
    runLoadingMore,
    runHasMore,
    runFilter,
    selectedRole,
    selectRole,
    selectedRoleLabel,
    selectedRoleVersions,
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
    selectedRun,
    selectedIsBatch,
    selectedIsRun,
    selectedRunSummary,
    selectedDiff,
    selectedDiffData,
    selectedProposalReview,
    selectedProposalRows,
    selectedCanPromote,
    selectedPromoteDisabledReason,
    selectedCanReject,
    selectedRejectDisabledReason,
    selectedCanTerminate,
    selectedTerminateDisabledReason,
    selectedRollbackDisabledReason,
    baselinePromoteTrustDisabledReason: selectedBaselinePromoteTrustDisabledReason,
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
    hasSelection,
    refreshAll,
    selectRun,
    loadMoreRuns,
    startSingle,
    startBatch,
    runAction,
    loadProposalReview,
    consumeEvolutionDeepLink,
    applyEvolutionDeepLink,
    acceptProposal,
    rejectProposal,
    applyAcceptedProposals,
    rollback,
    selectSampleGame,
    loadMoreSampleGames,
    loadSampleGameDetail,
    loadVersionDetail,
    openTrustBundleDrawer,
    refreshTrustBundleAudit,
    closeTrustBundleDrawer,
    toggleBatchRole,
    shortId,
    sourceText,
    statusText,
    roleMeta
  }
}

export { useEvolutionWorkbench, statusText, shortId, roleMeta, sourceText }
