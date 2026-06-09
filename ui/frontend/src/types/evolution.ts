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
