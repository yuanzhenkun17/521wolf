import type {
  EvolutionChildRun,
  EvolutionListResponse,
  EvolutionProposal,
  EvolutionRun,
  EvolutionSampleGame,
  PairedSeed,
  ProposalReview,
  RoleVersion,
  TrustBundle
} from '../../types/evolution'
import { arrayOrEmpty, firstNumber, firstString, integerValue, mergeByStableId, normalizePagination, nullableNumber, objectOrEmpty, shortId, stringValue, uniqueStrings } from '../common'

export const EVOLUTION_ACTIVE_STATUSES = new Set(['queued', 'running', 'training', 'battling', 'combined_battling', 'applying'])
export const EVOLUTION_TERMINAL_STATUSES = new Set(['reviewing', 'promoted', 'rejected', 'failed', 'completed', 'cancelled', 'interrupted'])

const ROLLBACK_BLOCKED_RELEASE_STAGES = new Set(['shadow', 'canary'])

function percentValue(value: unknown): number | null {
  const number = nullableNumber(value)
  if (number == null) return null
  const pct = number <= 1 ? number * 100 : number
  return Math.max(0, Math.min(100, Math.round(pct)))
}

function progressFromCount(completed: unknown, target: unknown, fallbackLabel = '等待'): { percent: number; label: string } {
  const done = nullableNumber(completed)
  const total = nullableNumber(target)
  if (total != null && total > 0) {
    const normalizedDone = Math.max(0, Math.min(total, done ?? 0))
    return {
      percent: Math.max(0, Math.min(100, Math.round((normalizedDone / total) * 100))),
      label: `${normalizedDone} / ${total}`
    }
  }
  return { percent: 0, label: fallbackLabel }
}

export function normalizeReleaseStage(value: unknown): string {
  return stringValue(value).toLowerCase()
}

export function normalizeChildRun(raw: unknown): EvolutionChildRun {
  if (typeof raw === 'string') {
    return {
      id: raw,
      run_id: raw,
      displayRole: '—',
      progressPercent: 0,
      progressLabel: '等待',
      trainingTarget: 0,
      trainingCompleted: 0,
      battleTarget: 0,
      battleCompleted: 0
    }
  }
  const source = objectOrEmpty(raw)
  const progress = objectOrEmpty(source.progress)
  const overall = objectOrEmpty(source.overall_progress)
  const stage = objectOrEmpty(source.stage_progress ?? progress)
  const explicit = percentValue(overall.percent ?? progress.overall_percent ?? source.overall_percent ?? stage.percent)
  const trainingTarget = firstNumber(overall.training_total, source.training_total, source.training_game_count) ?? 0
  const trainingCompleted = firstNumber(overall.training_completed, source.training_completed) ?? 0
  const battleTarget = firstNumber(overall.battle_total, source.battle_total, source.battle_game_count) ?? 0
  const battleCompleted = firstNumber(overall.battle_completed, source.battle_completed) ?? 0
  return {
    ...source,
    id: firstString(source.run_id, source.id),
    run_id: firstString(source.run_id, source.id),
    displayRole: stringValue(source.role, '—'),
    status: stringValue(source.status || source.stage),
    progressPercent: explicit ?? 0,
    progressLabel: explicit == null ? '等待' : `${explicit}%`,
    trainingTarget,
    trainingCompleted,
    battleTarget,
    battleCompleted
  }
}

export function normalizeRun(raw: unknown): EvolutionRun {
  const source = objectOrEmpty(raw)
  const id = firstString(source.run_id, source.batch_id, source.id)
  const isBatch = Boolean(source.batch_id)
  const childRuns = isBatch
    ? (arrayOrEmpty(source.run_summaries).length ? arrayOrEmpty(source.run_summaries) : arrayOrEmpty(source.runs)).map(normalizeChildRun)
    : []
  const progress = objectOrEmpty(source.progress)
  const overall = objectOrEmpty(source.overall_progress)
  const stageProgress = objectOrEmpty(source.stage_progress ?? progress)
  const trainingGames = arrayOrEmpty(source.training_games)
  const battleGames = arrayOrEmpty(source.battle_games)
  const currentStage = firstString(source.current_stage, progress.stage, source.stage, source.status)
  const explicit = percentValue(overall.percent ?? progress.overall_percent ?? source.overall_percent ?? stageProgress.percent)
  const roleKeys = arrayOrEmpty(source.roles).map((role) => stringValue(role)).filter(Boolean)
  const trainingTarget = firstNumber(overall.training_total, progress.training_total, source.training_total, source.training_target, source.training_requested, objectOrEmpty(source.config).training_games, trainingGames.length) ?? 0
  const trainingCompleted = firstNumber(overall.training_completed, progress.training_completed, source.training_completed, trainingGames.length) ?? 0
  const battleTarget = firstNumber(overall.battle_total, progress.battle_total, source.battle_total, source.battle_target, source.battle_requested, objectOrEmpty(source.config).battle_games, battleGames.length) ?? 0
  const battleCompleted = firstNumber(overall.battle_completed, progress.battle_completed, source.battle_completed, battleGames.length) ?? 0
  const overallProgress = explicit == null
    ? progressFromCount(trainingCompleted + battleCompleted, trainingTarget + battleTarget)
    : { percent: explicit, label: `${explicit}%` }
  const stageProgressValue = percentValue(stageProgress.percent ?? progress.percent)
  const status = stringValue(source.status)
  return {
    ...source,
    id,
    entityType: isBatch ? 'batch' : 'run',
    isBatch,
    childRuns,
    childRunCount: childRuns.length,
    displayRole: roleKeys.length ? roleKeys.join(', ') : stringValue(source.role, 'unknown'),
    currentStage,
    recommendation: stringValue(source.recommendation),
    recommendationLabel: stringValue(source.recommendation),
    progressPercent: overallProgress.percent,
    progressLabel: overallProgress.label,
    overallProgressPercent: overallProgress.percent,
    stageProgressPercent: stageProgressValue ?? 0,
    trainingProgressPercent: progressFromCount(trainingCompleted, trainingTarget).percent,
    battleProgressPercent: progressFromCount(battleCompleted, battleTarget).percent,
    trainingGameRequested: trainingTarget,
    trainingGameCompleted: trainingCompleted,
    battleGameRequested: battleTarget,
    battleGameCompleted: battleCompleted,
    proposalCount: integerValue(source.proposal_count, arrayOrEmpty(source.proposals).length),
    diffCount: integerValue(source.diff_count, arrayOrEmpty(source.diff).length),
    diagnosticCount: arrayOrEmpty(source.diagnostics).length,
    warningCount: arrayOrEmpty(source.warnings).length,
    errorCount: integerValue(source.error_count, arrayOrEmpty(source.errors).length),
    isReviewing: status === 'reviewing',
    isTerminal: EVOLUTION_TERMINAL_STATUSES.has(status),
    isActive: EVOLUTION_ACTIVE_STATUSES.has(status)
  }
}

export function normalizeVersion(raw: unknown): RoleVersion {
  const source = objectOrEmpty(raw)
  const versionId = firstString(source.version_id, source.target_version_id, source.hash)
  const provenance = objectOrEmpty(source.provenance)
  const releaseStage = normalizeReleaseStage(source.release_stage ?? source.releaseStage ?? provenance.release_stage ?? provenance.releaseStage)
  const rollbackDisabledReason = source.is_baseline
    ? '当前基线'
    : (ROLLBACK_BLOCKED_RELEASE_STAGES.has(releaseStage) ? `${releaseStage}不可回滚` : '')
  return {
    ...source,
    version_id: versionId,
    releaseStage,
    rollbackDisabled: Boolean(rollbackDisabledReason),
    rollbackDisabledReason,
    short: shortId(versionId)
  }
}

export function normalizeSampleGame(raw: unknown, bucket = 'training'): EvolutionSampleGame {
  const source = objectOrEmpty(raw)
  const id = firstString(source.game_id, source.id)
  return {
    ...source,
    id,
    game_id: firstString(source.game_id, id),
    bucket,
    eventCount: integerValue(source.event_count, arrayOrEmpty(source.events).length),
    decisionCount: integerValue(source.decision_count, arrayOrEmpty(source.decisions).length),
    dayLabel: source.day ? `第${source.day}天` : '—'
  }
}

export function normalizePairedSeed(raw: unknown, index = 0): PairedSeed {
  const source = objectOrEmpty(raw)
  const primitiveSeed = raw != null && typeof raw !== 'object' ? raw : ''
  const baseline = objectOrEmpty(source.baseline ?? source.baseline_result)
  const candidate = objectOrEmpty(source.candidate ?? source.candidate_result)
  const baselineScore = firstNumber(source.baseline_score, source.baseline_role_score, baseline.score, baseline.role_score)
  const candidateScore = firstNumber(source.candidate_score, source.candidate_role_score, candidate.score, candidate.role_score)
  const scoreDelta = firstNumber(
    source.score_delta,
    source.role_score_delta,
    baselineScore != null && candidateScore != null ? candidateScore - baselineScore : null
  )
  return {
    ...source,
    id: firstString(source.id, source.pair_id, source.seed, source.battle_seed, primitiveSeed, index),
    seed: firstString(source.seed, source.battle_seed, source.paired_seed, primitiveSeed, index + 1),
    baselineScore,
    candidateScore,
    scoreDelta,
    winnerSide: firstString(source.winner_side, source.winner, source.side, '—'),
    status: firstString(source.status, source.result, source.rankable === false ? 'unrankable' : 'rankable'),
    baselineGameId: firstString(source.baseline_game_id, baseline.game_id),
    candidateGameId: firstString(source.candidate_game_id, candidate.game_id)
  }
}

export function normalizeProposal(raw: unknown, index = 0): EvolutionProposal {
  const source = objectOrEmpty(raw)
  const apiId = firstString(source.proposal_id, source.id)
  const evidence = objectOrEmpty(source.evidence ?? source.evidence_summary)
  const counterEvidence = objectOrEmpty(source.counter_evidence ?? source.counterEvidence)
  const hypothesis = firstString(source.hypothesis, source.strategy_hypothesis, source.claim)
  const targetFile = firstString(source.target_file, source.file, source.path, source.skill_file, '—')
  return {
    ...source,
    apiId,
    id: apiId || `proposal-${index + 1}`,
    title: firstString(source.title, source.summary, hypothesis, source.name, targetFile !== '—' ? targetFile : '', `提案 ${index + 1}`),
    targetFile,
    operation: firstString(source.operation, source.action, source.change_type, '变更'),
    status: firstString(source.review_status, source.status, source.decision, 'pending'),
    summary: firstString(source.summary, source.description, source.rationale, source.reason, hypothesis),
    rationale: firstString(source.rationale, source.problem_observation, source.evidence, source.reason, source.summary),
    hypothesis,
    evidenceGameIds: uniqueStrings([source.evidence_game_ids, source.evidenceGameIds, source.supporting_game_ids, evidence.game_ids]),
    counterEvidenceGameIds: uniqueStrings([source.counter_evidence_game_ids, source.counterEvidenceGameIds, source.counter_game_ids, counterEvidence.game_ids]),
    riskTags: uniqueStrings([source.risk_tags, source.riskTags, objectOrEmpty(source.risk).tags]),
    diffPreview: firstString(source.diff_preview, source.patch, source.diff, source.after)
  }
}

export function normalizeProposalReview(data: unknown = null, run: unknown = null, options: { source?: string; error?: string; unsupported?: boolean } = {}): ProposalReview {
  const source = Array.isArray(data) ? { proposals: data } : objectOrEmpty(data)
  const runSource = objectOrEmpty(run)
  const reviewSummary = objectOrEmpty(source.proposal_review ?? source.proposalReview ?? runSource.proposal_review ?? runSource.proposalReview)
  const proposals = (arrayOrEmpty(source.proposals).length ? arrayOrEmpty(source.proposals) : arrayOrEmpty(runSource.proposals)).map(normalizeProposal)
  const pairedSeeds = arrayOrEmpty(source.paired_seed_summary ?? source.paired_seeds ?? source.battle_pairs ?? runSource.paired_seed_summary).map(normalizePairedSeed)
  const acceptedCount = proposals.filter((proposal) => ['accepted', 'accept', 'applied'].includes(proposal.status.toLowerCase())).length
  const rejectedCount = proposals.filter((proposal) => ['rejected', 'reject'].includes(proposal.status.toLowerCase())).length
  const total = integerValue(reviewSummary.total ?? reviewSummary.generated_count, proposals.length)
  const accepted = integerValue(reviewSummary.accepted_count, acceptedCount)
  const rejected = integerValue(reviewSummary.rejected_count, rejectedCount)
  return {
    loading: false,
    error: options.error || '',
    unsupported: Boolean(options.unsupported),
    source: options.source || (data ? 'api' : 'run-detail'),
    proposals,
    pairedSeeds,
    gate: objectOrEmpty(source.gate_report ?? source.release_gate ?? runSource.gate_report),
    trustBundle: objectOrEmpty(source.trust_bundle ?? runSource.trust_bundle),
    summary: {
      total,
      generated: integerValue(reviewSummary.generated_count, total),
      accepted,
      rejected,
      pending: Math.max(0, total - accepted - rejected),
      preflight: integerValue(reviewSummary.preflight_passed_count, 0),
      applied: integerValue(reviewSummary.applied_count, arrayOrEmpty(reviewSummary.applied_proposal_ids).length)
    }
  }
}

export function normalizeTrustBundle(raw: unknown): TrustBundle | null {
  const source = objectOrEmpty(raw)
  const bundle = objectOrEmpty(source.trust_bundle)
  const id = firstString(source.trust_bundle_id, bundle.trust_bundle_id)
  if (!id && !Object.keys(bundle).length) return null
  return {
    ...source,
    trust_bundle_id: id,
    run_id: firstString(source.run_id, bundle.run_id),
    role: firstString(source.role, bundle.role),
    baseline_version: firstString(source.baseline_version, bundle.baseline_version),
    candidate_version: firstString(source.candidate_version, bundle.candidate_version),
    bundle_hash: firstString(source.bundle_hash, bundle.bundle_hash),
    trust_bundle: bundle
  }
}

export function normalizeEvolutionListResponse(raw: unknown): EvolutionListResponse {
  const source = objectOrEmpty(raw)
  const runs = arrayOrEmpty(source.runs).map(normalizeRun)
  const batches = arrayOrEmpty(source.batches).map(normalizeRun)
  return {
    runs,
    batches,
    pagination: source.pagination ? normalizePagination(source.pagination, [...runs, ...batches]) : undefined,
    raw
  }
}

export function mergeEvolutionRuns(existing: EvolutionRun[], incoming: EvolutionRun[]): EvolutionRun[] {
  return mergeByStableId(existing, incoming, ['run_id', 'batch_id', 'id'])
}
