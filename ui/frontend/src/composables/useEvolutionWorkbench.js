import { computed, onBeforeUnmount, ref } from 'vue'
import { createGameApi } from './gameApi.js'
import { createLatestOnlyMap, createLatestOnlyTracker } from './latestOnly.js'
import { createResumableEventSource } from './resumableEventSource.js'
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
} from './workbenchShared.js'

const DEFAULT_RUN_PAGE_SIZE = 80
const DEFAULT_SAMPLE_GAME_PAGE_SIZE = 80
const SAMPLE_GAME_BUCKETS = ['training', 'baseline', 'candidate']
const SAMPLE_BUCKET_LABELS = {
  training: '训练',
  baseline: '基线',
  candidate: '候选'
}

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
  return {
    ...version,
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

function shortText(value, fallback = '—') {
  const text = String(value ?? '').trim()
  return text || fallback
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

function normalizePairedSeed(row, index = 0) {
  const baseline = firstObject(row?.baseline, row?.baseline_result)
  const candidate = firstObject(row?.candidate, row?.candidate_result)
  const baselineScore = firstFinite(row?.baseline_score, row?.baseline_role_score, baseline.score, baseline.role_score)
  const candidateScore = firstFinite(row?.candidate_score, row?.candidate_role_score, candidate.score, candidate.role_score)
  const scoreDelta = firstFinite(
    row?.score_delta,
    row?.role_score_delta,
    baselineScore != null && candidateScore != null ? candidateScore - baselineScore : null
  )
  return {
    ...row,
    id: shortText(row?.id || row?.pair_id || row?.seed || row?.battle_seed || index, String(index)),
    seed: shortText(row?.seed || row?.battle_seed || row?.paired_seed || index + 1),
    baselineScore,
    candidateScore,
    scoreDelta,
    winnerSide: shortText(row?.winner_side || row?.winner || row?.side, '—'),
    status: shortText(row?.status || row?.result || (row?.rankable === false ? 'unrankable' : 'rankable'), '—'),
    failureReason: shortText(row?.failure_reason || row?.reason || row?.error, ''),
    baselineGameId: row?.baseline_game_id || baseline.game_id || '',
    candidateGameId: row?.candidate_game_id || candidate.game_id || ''
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
  const blockedReasons = uniqueText(firstArray(
    gate.blocked_reasons,
    gate.reasons,
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
      gate.status ||
      source.decision ||
      source.gate_decision ||
      run?.gate_decision ||
      run?.recommendation,
    ''
  )
  return {
    ...gate,
    decision,
    decisionLabel: gateDecisionText(decision),
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
  return uniqueText([
    ...firstArray(proposal?.risk_tags, proposal?.overfit_risk_tags),
    ...firstArray(risk.tags, risk.risk_tags, risk.overfit_risk_tags)
  ])
}

function normalizeProposal(proposal, index = 0) {
  const gate = firstObject(proposal?.gate, proposal?.gate_report, proposal?.promotion_gate)
  const risk = firstObject(proposal?.risk, proposal?.risk_summary, proposal?.overfit_risk)
  const apiId = String(proposal?.proposal_id || proposal?.id || '').trim()
  const status = shortText(proposal?.review_status || proposal?.status || proposal?.decision, 'pending')
  const targetFile = shortText(proposal?.target_file || proposal?.file || proposal?.path || proposal?.skill_file, '—')
  const title = shortText(
    proposal?.title ||
      proposal?.summary ||
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
    summary: shortText(proposal?.summary || proposal?.description || proposal?.rationale || proposal?.reason),
    rationale: shortText(proposal?.rationale || proposal?.evidence || proposal?.reason || proposal?.summary),
    riskTags: proposalRiskTags(proposal),
    riskLevel: shortText(proposal?.risk_level || risk.level || risk.risk_level || risk.severity, ''),
    riskScore: firstFinite(proposal?.risk_score, proposal?.overfit_risk_score, risk.score, risk.overfit_risk_score),
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
  const proposals = proposalSource(source, run).map(normalizeProposal)
  const pairedSeeds = pairedSeedSource(source, run).map(normalizePairedSeed)
  const gate = normalizeGateReport(source, run || {})
  const acceptedCount = proposals.filter((proposal) => ['accepted', 'accept', 'applied'].includes(String(proposal.status).toLowerCase())).length
  const rejectedCount = proposals.filter((proposal) => ['rejected', 'reject'].includes(String(proposal.status).toLowerCase())).length
  const pendingCount = Math.max(0, proposals.length - acceptedCount - rejectedCount)
  return {
    loading: false,
    error: options.error || '',
    unsupported: Boolean(options.unsupported),
    source: options.source || (data ? 'api' : 'run-detail'),
    proposals,
    gate,
    pairedSeeds,
    summary: {
      total: proposals.length,
      accepted: acceptedCount,
      rejected: rejectedCount,
      pending: pendingCount,
      riskTagCount: uniqueText(proposals.flatMap((proposal) => proposal.riskTags)).length,
      pairedSeedCount: pairedSeeds.length
    }
  }
}

function isMissingProposalEndpoint(error) {
  const message = String(error?.message || '').toLowerCase()
  return message.includes('404') || message.includes('not found') || message.includes('unexpected')
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
        battleProgressLabel: '等待'
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
      battleProgressLabel: run.battleProgressLabel
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

  function setError(message) {
    error.value = message || ''
  }

  function clearVersionDetail() {
    selectedVersionId.value = ''
    selectedVersionDetail.value = { loading: false, error: '', data: null }
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
    } catch (err) {
      if (token.isLatest()) setError(err?.message || '运行记录读取失败')
    } finally {
      if (token.isLatest()) runLoadingMore.value = false
    }
  }

  async function refreshAll({ silent = false } = {}) {
    const refreshToken = refreshRequests.next()
    const token = runListRequests.next()
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
      if (!selectedRunId.value && runRows.value.length) {
        await selectRun(runRows.value[0].id)
      } else if (selectedRunId.value) {
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
    } catch (err) {
      if (token.isLatest()) {
        const message = err?.message || `${SAMPLE_BUCKET_LABELS[bucket] || bucket}样本局读取失败`
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

  async function startSingle() {
    if (!selectedRole.value) {
      setError('请选择一个有基线版本的角色')
      return
    }
    const token = actionRequests.next()
    actionLoading.value = 'start-single'
    setError('')
    try {
      const created = await apiFetch('/evolution-runs', {
        method: 'POST',
        body: JSON.stringify({
          roles: [selectedRole.value],
          training_games: numberField('training_games', 5),
          battle_games: numberField('battle_games', 4),
          max_days: numberField('max_days', 5),
          auto_promote: true
        })
      })
      if (!token.isLatest()) return
      resetLastEventId(created.run_id || created.batch_id)
      await loadRuns()
      if (!token.isLatest()) return
      await selectRun(created.run_id || created.batch_id)
    } catch (err) {
      if (token.isLatest()) setError(err?.message || '启动单角色进化失败')
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  async function startBatch() {
    if (!selectedBatchRoles.value.length) {
      setError('请选择至少一个角色')
      return
    }
    const token = actionRequests.next()
    actionLoading.value = 'start-batch'
    setError('')
    try {
      const created = await apiFetch('/evolution-runs', {
        method: 'POST',
        body: JSON.stringify({
          roles: [...selectedBatchRoles.value],
          training_games: numberField('training_games', 5),
          battle_games: numberField('battle_games', 4),
          max_days: numberField('max_days', 5),
          auto_promote: true
        })
      })
      if (!token.isLatest()) return
      resetLastEventId(created.batch_id || created.run_id)
      await loadRuns()
      if (!token.isLatest()) return
      await selectRun(created.batch_id || created.run_id)
    } catch (err) {
      if (token.isLatest()) setError(err?.message || '启动批量进化失败')
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  async function runAction(id, action) {
    if (!id || !action) return
    const token = actionRequests.next()
    actionLoading.value = `${action}:${id}`
    setError('')
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
    } catch (err) {
      if (token.isLatest()) setError(err?.message || '操作失败')
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  async function updateProposal(id, proposalId, action, body = {}) {
    if (!id || !proposalId || !action) return
    const token = actionRequests.next()
    actionLoading.value = `proposal-${action}:${proposalId}`
    setError('')
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
    } catch (err) {
      if (token.isLatest()) setError(err?.message || '提案操作失败')
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  async function acceptProposal(proposal, id = selectedRunId.value) {
    const proposalId = proposal?.apiId || proposal?.proposal_id || proposal?.id
    await updateProposal(id, proposalId, 'accept')
  }

  async function rejectProposal(proposal, id = selectedRunId.value, reason = '') {
    const proposalId = proposal?.apiId || proposal?.proposal_id || proposal?.id
    await updateProposal(id, proposalId, 'reject', {
      reason: reason || 'manual_reject'
    })
  }

  async function applyAcceptedProposals(id = selectedRunId.value) {
    if (!id) return
    const token = actionRequests.next()
    actionLoading.value = `proposal-apply:${id}`
    setError('')
    try {
      const result = await apiFetch(`/evolution-runs/${encodeURIComponent(id)}/proposals/apply-accepted`, {
        method: 'POST'
      })
      if (!token.isLatest()) return
      if (result?.run || result?.run_id || result?.batch_id) {
        selectedRun.value = normalizeRun(result.run || { ...(selectedRun.value || {}), ...(result || {}), run_id: id })
      }
      await Promise.all([loadProposalReview(id), loadDiff(id)])
    } catch (err) {
      if (token.isLatest()) setError(err?.message || '应用已接受提案失败')
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  async function rollback(role, versionId) {
    if (!role || !versionId) return
    const token = actionRequests.next()
    actionLoading.value = `rollback:${role}:${versionId}`
    setError('')
    try {
      await apiFetch(`/roles/${encodeURIComponent(role)}/rollback/${encodeURIComponent(versionId)}`, {
        method: 'POST'
      })
      if (!token.isLatest()) return
      await Promise.all([loadVersions(role), loadLeaderboard(role), loadRuns()])
    } catch (err) {
      if (token.isLatest()) setError(err?.message || '回滚基线失败')
    } finally {
      if (token.isLatest()) actionLoading.value = ''
    }
  }

  if (options.installLifecycle !== false) {
    onBeforeUnmount(() => {
      closeEventStream()
    })
  }

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
    acceptProposal,
    rejectProposal,
    applyAcceptedProposals,
    rollback,
    selectSampleGame,
    loadMoreSampleGames,
    loadSampleGameDetail,
    loadVersionDetail,
    toggleBatchRole,
    shortId,
    sourceText,
    statusText,
    roleMeta
  }
}

export { useEvolutionWorkbench, statusText, shortId, roleMeta, sourceText }
