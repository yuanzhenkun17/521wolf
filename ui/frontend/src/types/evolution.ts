import type { Pagination, UnknownRecord } from './api'

export type EvolutionRunStatus =
  | 'queued'
  | 'running'
  | 'training'
  | 'battling'
  | 'reviewing'
  | 'promoted'
  | 'rejected'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'interrupted'
  | string

export type EvolutionEntityType = 'run' | 'batch'
export type EvolutionSampleBucket = 'training' | 'baseline' | 'candidate' | string

export interface EvolutionProgressDto extends UnknownRecord {
  percent?: string | number | null
  overall_percent?: string | number | null
  stage?: string | null
  target_games?: string | number | null
  completed_games?: string | number | null
  total?: string | number | null
  target?: string | number | null
  completed?: string | number | null
  training_total?: string | number | null
  training_completed?: string | number | null
  battle_total?: string | number | null
  battle_completed?: string | number | null
  total_roles?: string | number | null
  completed_roles?: string | number | null
}

export interface EvolutionChildRunDto extends UnknownRecord {
  id?: string | number | null
  run_id?: string | number | null
  role?: string | null
  status?: EvolutionRunStatus | null
  stage?: string | null
  progress?: EvolutionProgressDto | null
  overall_progress?: EvolutionProgressDto | null
  stage_progress?: EvolutionProgressDto | null
  training_total?: string | number | null
  training_completed?: string | number | null
  training_game_count?: string | number | null
  battle_total?: string | number | null
  battle_completed?: string | number | null
  battle_game_count?: string | number | null
}

export interface EvolutionRunDto extends UnknownRecord {
  id?: string | number | null
  run_id?: string | number | null
  batch_id?: string | number | null
  kind?: string | null
  role?: string | null
  roles?: unknown[] | null
  status?: EvolutionRunStatus | null
  stage?: string | null
  current_stage?: string | null
  recommendation?: string | null
  progress?: EvolutionProgressDto | null
  overall_progress?: EvolutionProgressDto | null
  stage_progress?: EvolutionProgressDto | null
  config?: UnknownRecord | null
  run_summaries?: Array<EvolutionChildRunDto | string> | null
  runs?: Array<EvolutionChildRunDto | string> | null
  training_games?: EvolutionSampleGameDto[] | null
  battle_games?: EvolutionSampleGameDto[] | null
  training_total?: string | number | null
  training_target?: string | number | null
  training_requested?: string | number | null
  training_completed?: string | number | null
  battle_total?: string | number | null
  battle_target?: string | number | null
  battle_requested?: string | number | null
  battle_completed?: string | number | null
  proposal_count?: string | number | null
  proposals?: EvolutionProposalDto[] | null
  diff_count?: string | number | null
  diff?: unknown[] | null
  diagnostics?: unknown[] | null
  warnings?: unknown[] | null
  error_count?: string | number | null
  errors?: unknown[] | null
}

export type EvolutionRunsDto =
  | EvolutionRunDto[]
  | {
      runs?: EvolutionRunDto[] | null
      batches?: EvolutionRunDto[] | null
      items?: EvolutionRunDto[] | null
      pagination?: Partial<Pagination> | null
      [key: string]: unknown
    }

export type EvolutionRunResponseDto =
  | EvolutionRunDto
  | {
      run?: EvolutionRunDto | null
      batch?: EvolutionRunDto | null
      data?: EvolutionRunDto | null
      [key: string]: unknown
    }

export type EvolutionRolesDto =
  | unknown[]
  | {
      roles?: unknown[] | null
      items?: unknown[] | null
      [key: string]: unknown
    }

export interface RoleVersionDto extends UnknownRecord {
  version_id?: string | number | null
  target_version_id?: string | number | null
  hash?: string | number | null
  role?: string | null
  source?: string | null
  created_at?: string | null
  is_baseline?: boolean | null
  status?: string | null
  release_stage?: string | null
  releaseStage?: string | null
  provenance?: UnknownRecord | null
}

export type RoleVersionsDto =
  | RoleVersionDto[]
  | {
      role?: string | null
      versions?: RoleVersionDto[] | null
      role_versions?: RoleVersionDto[] | null
      items?: RoleVersionDto[] | null
      [key: string]: unknown
    }

export interface EvolutionLeaderboardEntryDto extends UnknownRecord {
  key?: string | null
  rank?: string | number | null
  role?: string | null
  target_role?: string | null
  version_id?: string | null
  target_version_id?: string | null
  hash?: string | null
  score?: string | number | null
  target_role_role_weighted_score?: string | number | null
  avg_role_score?: string | number | null
  strength_score?: string | number | null
  winRate?: string | number | null
  win_rate?: string | number | null
  target_side_win_rate?: string | number | null
  games?: string | number | null
  game_count?: string | number | null
  games_played?: string | number | null
  rankable?: boolean | null
  is_baseline?: boolean | null
  release_stage?: string | null
}

export type EvolutionLeaderboardDto =
  | EvolutionLeaderboardEntryDto[]
  | {
      role?: string | null
      evaluation_set_id?: string | null
      entries?: EvolutionLeaderboardEntryDto[] | null
      rows?: EvolutionLeaderboardEntryDto[] | null
      items?: EvolutionLeaderboardEntryDto[] | null
      leaderboard?: EvolutionLeaderboardEntryDto[] | null
      [key: string]: unknown
    }

export interface EvolutionRoleOverviewDto extends UnknownRecord {
  roles?: unknown[] | null
  versions?: Record<string, RoleVersionDto[] | null> | null
  leaderboards?: Record<string, EvolutionLeaderboardDto | null> | null
  evaluation_set_id?: string | null
}

export interface EvolutionSampleGameDto extends UnknownRecord {
  id?: string | number | null
  game_id?: string | number | null
  phase?: string | null
  winner?: string | null
  in_progress?: boolean | null
  event_count?: string | number | null
  decision_count?: string | number | null
  events?: unknown[] | null
  decisions?: unknown[] | null
  day?: string | number | null
}

export interface EvolutionProposalDto extends UnknownRecord {
  id?: string | number | null
  proposal_id?: string | number | null
  title?: string | null
  name?: string | null
  summary?: string | null
  description?: string | null
  rationale?: string | null
  reason?: string | null
  hypothesis?: string | null
  strategy_hypothesis?: string | null
  claim?: string | null
  target_file?: string | null
  file?: string | null
  path?: string | null
  skill_file?: string | null
  operation?: string | null
  action?: string | null
  change_type?: string | null
  review_status?: string | null
  status?: string | null
  decision?: string | null
  evidence?: UnknownRecord | string | null
  evidence_summary?: UnknownRecord | null
  counter_evidence?: UnknownRecord | null
  counterEvidence?: UnknownRecord | null
  evidence_game_ids?: unknown[] | null
  evidenceGameIds?: unknown[] | null
  supporting_game_ids?: unknown[] | null
  counter_evidence_game_ids?: unknown[] | null
  counterEvidenceGameIds?: unknown[] | null
  counter_game_ids?: unknown[] | null
  risk_tags?: unknown[] | null
  riskTags?: unknown[] | null
  risk?: UnknownRecord | null
  diff_preview?: string | null
  patch?: string | null
  diff?: string | null
  after?: string | null
}

export interface PairedSeedDto extends UnknownRecord {
  id?: string | number | null
  pair_id?: string | number | null
  seed?: string | number | null
  battle_seed?: string | number | null
  paired_seed?: string | number | null
  baseline?: UnknownRecord | null
  baseline_result?: UnknownRecord | null
  candidate?: UnknownRecord | null
  candidate_result?: UnknownRecord | null
  baseline_score?: string | number | null
  baseline_role_score?: string | number | null
  candidate_score?: string | number | null
  candidate_role_score?: string | number | null
  score_delta?: string | number | null
  role_score_delta?: string | number | null
  winner_side?: string | null
  winner?: string | null
  side?: string | null
  status?: string | null
  result?: string | null
  rankable?: boolean | null
}

export interface ProposalReviewDto extends UnknownRecord {
  proposals?: EvolutionProposalDto[] | null
  items?: EvolutionProposalDto[] | null
  rows?: EvolutionProposalDto[] | null
  proposal_rows?: EvolutionProposalDto[] | null
  proposalReview?: UnknownRecord | null
  proposal_review?: UnknownRecord | null
  paired_seed_summary?: PairedSeedDto[] | UnknownRecord | null
  paired_seeds?: PairedSeedDto[] | null
  paired_seed_pairs?: PairedSeedDto[] | null
  paired_seed_battle_table?: PairedSeedDto[] | null
  battle_pairs?: PairedSeedDto[] | null
  gate_report?: UnknownRecord | null
  release_gate?: UnknownRecord | null
  trust_bundle?: UnknownRecord | null
  run?: EvolutionRunDto | null
}

export interface TrustBundleDto extends UnknownRecord {
  kind?: string | null
  schema_version?: number | null
  trust_bundle_id?: string | null
  trustBundleId?: string | null
  run_id?: string | null
  role?: string | null
  baseline_version?: string | null
  candidate_version?: string | null
  bundle_hash?: string | null
  gate_report_id?: string | null
  attribution_report_id?: string | null
  trust_bundle?: UnknownRecord | null
  trustBundle?: UnknownRecord | null
  bundle?: UnknownRecord | null
  data?: TrustBundleDto | UnknownRecord | null
}

export interface EvolutionDiffResponse extends UnknownRecord {
  diffs?: unknown[] | null
  diff?: unknown[] | string | null
  diff_data?: UnknownRecord | null
  skill_changes?: unknown[] | null
  patterns_added?: unknown[] | null
  patterns_removed?: unknown[] | null
  patterns_updated?: unknown[] | null
  metrics_delta?: UnknownRecord | null
}

export interface EvolutionActionRequest extends UnknownRecord {
  action: 'promote' | 'reject' | 'stop' | 'terminate' | 'resume' | string
}

export interface EvolutionStartRequest {
  roles?: string[]
  training_games?: number
  battle_games?: number
  max_days?: number
  auto_promote?: boolean
}

export interface EvolutionChildRun {
  id: string
  run_id: string
  displayRole: string
  status?: EvolutionRunStatus
  progressPercent: number
  progressLabel: string
  trainingTarget: number
  trainingCompleted: number
  battleTarget: number
  battleCompleted: number
  [key: string]: unknown
}

export interface EvolutionRun {
  id: string
  run_id?: string
  batch_id?: string
  entityType: EvolutionEntityType
  isBatch: boolean
  childRuns: EvolutionChildRun[]
  childRunCount: number
  role?: string
  roles?: string[]
  displayRole: string
  status?: EvolutionRunStatus
  currentStage: string
  recommendation: string
  recommendationLabel: string
  progressPercent: number
  progressLabel: string
  overallProgressPercent: number
  stageProgressPercent: number
  trainingProgressPercent: number
  battleProgressPercent: number
  trainingGameRequested: number
  trainingGameCompleted: number
  battleGameRequested: number
  battleGameCompleted: number
  proposalCount: number
  diffCount: number
  diagnosticCount: number
  warningCount: number
  errorCount: number
  isReviewing: boolean
  isTerminal: boolean
  isActive: boolean
  [key: string]: unknown
}

export interface RoleVersion {
  version_id: string
  role?: string
  source?: string
  created_at?: string
  is_baseline?: boolean
  status?: string
  release_stage?: string
  releaseStage: string
  rollbackDisabled: boolean
  rollbackDisabledReason: string
  short: string
  [key: string]: unknown
}

export interface EvolutionSampleGame {
  id: string
  game_id?: string
  bucket: EvolutionSampleBucket
  phase?: string
  winner?: string
  in_progress?: boolean
  eventCount: number
  decisionCount: number
  dayLabel: string
  [key: string]: unknown
}

export interface EvolutionProposal {
  id: string
  apiId: string
  title: string
  targetFile: string
  operation: string
  status: string
  summary: string
  rationale: string
  hypothesis: string
  evidenceGameIds: string[]
  counterEvidenceGameIds: string[]
  riskTags: string[]
  diffPreview: string
  [key: string]: unknown
}

export interface PairedSeed {
  id: string
  seed: string
  baselineScore: number | null
  candidateScore: number | null
  scoreDelta: number | null
  winnerSide: string
  status: string
  baselineGameId: string
  candidateGameId: string
  [key: string]: unknown
}

export interface ProposalReview {
  loading: boolean
  error: string
  unsupported: boolean
  source: string
  proposals: EvolutionProposal[]
  pairedSeeds: PairedSeed[]
  gate: UnknownRecord
  trustBundle: UnknownRecord
  summary: {
    total: number
    generated: number
    accepted: number
    rejected: number
    pending: number
    preflight: number
    applied: number
  }
  [key: string]: unknown
}

export interface TrustBundle {
  kind?: string
  schema_version?: number
  trust_bundle_id?: string
  run_id?: string
  role?: string
  baseline_version?: string
  candidate_version?: string
  bundle_hash?: string
  gate_report_id?: string
  attribution_report_id?: string
  trust_bundle: UnknownRecord
  [key: string]: unknown
}

export interface EvolutionListResponse {
  runs: EvolutionRun[]
  batches: EvolutionRun[]
  pagination?: Pagination
  raw?: unknown
}

export interface EvolutionLeaderboardEntry {
  key: string
  rank: number
  role: string
  targetRole: string
  versionId: string
  score: number
  winRate: number
  gameCount: number
  rankable: boolean
  isBaseline: boolean
  releaseStage: string
  short: string
  [key: string]: unknown
}

export interface EvolutionLeaderboardResponse {
  role: string
  evaluation_set_id?: string | null
  entries: EvolutionLeaderboardEntry[]
  raw?: unknown
  [key: string]: unknown
}

export interface EvolutionRoleOverview {
  roles: string[]
  versions: Record<string, RoleVersion[]>
  leaderboards: Record<string, EvolutionLeaderboardResponse>
  evaluation_set_id?: string | null
  raw?: unknown
  [key: string]: unknown
}
