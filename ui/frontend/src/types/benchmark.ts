import type { Pagination, UnknownRecord } from './api'

export type BenchmarkTargetType = 'role_version' | 'model'
export type BenchmarkRunStatus = 'queued' | 'running' | 'rate_limited' | 'completed' | 'failed' | 'cancelled' | 'interrupted' | string
export type BenchmarkSuiteStatus = 'enabled' | 'active' | 'draft' | 'deprecated' | 'disabled' | 'archived' | string

export interface BenchmarkSeedSet {
  id: string
  seed_set_id: string
  purpose: string
  version: number | null
  description: string
  target_type: BenchmarkTargetType | ''
  tier: string
  seed_count: number | null
  seed_preview: string[]
  config_hash: string
  enabled: boolean
  overlap_warnings: UnknownRecord[]
  [key: string]: unknown
}

export interface BenchmarkSuite {
  id: string
  version: number | null
  name: string
  label: string
  description: string
  target_type: BenchmarkTargetType
  roles: string[]
  game_count: number | null
  max_days: number | null
  seed_set_id: string
  seed_count: number | null
  seed_preview: string[]
  seed_set: UnknownRecord
  paired_seed: boolean
  metrics: UnknownRecord
  gates: UnknownRecord
  judge: UnknownRecord
  config_hash: string
  benchmark_config_hash: string
  cost_tier: string
  evaluation_set_id: string
  status: BenchmarkSuiteStatus
  launchable: boolean
  launch_disabled_reason: string
  [key: string]: unknown
}

export interface BenchmarkRequest {
  benchmark_id?: string | null
  target_type?: BenchmarkTargetType
  roles?: string[]
  battle_games?: number | null
  max_days?: number | null
  target_versions?: Record<string, string>
  model_id?: string | null
  model_config_hash?: string | null
  budget_limit_units?: number | null
  budget_limit_cost?: number | null
  stop_after_budget_units?: number | null
  langfuse_dataset_name?: string | null
  langfuse_experiment_name?: string | null
  langfuse_run_name?: string | null
}

export interface BenchmarkResult {
  result_batch_id: string
  target_role: string
  target_version_id: string
  completed: number
  errored: number
  game_count: number
  attempted_game_count: number
  rankable: boolean
  diagnostic_count: number
  warning_count: number
  [key: string]: unknown
}

export interface BenchmarkRun {
  id: string
  run_id?: string
  batch_id?: string
  status?: BenchmarkRunStatus
  roles?: string[]
  roleKeys: string[]
  displayRole: string
  benchmarkId: string
  benchmarkVersion: string | number | null
  benchmarkTargetType: BenchmarkTargetType
  evaluationSetId: string
  resultRows?: BenchmarkResult[]
  isActive: boolean
  isTerminal: boolean
  [key: string]: unknown
}

export interface BenchmarkGame {
  id: string
  game_id: string
  history_game_id: string
  result_batch_id: string
  target_role: string
  status: string
  event_count: number
  decision_count: number
  diagnostic_count: number
  replay_available: boolean
  replayHash: string
  [key: string]: unknown
}

export interface BenchmarkDiagnostic {
  id: string
  kind: string
  level: string
  origin: string
  stage: string
  message: string
  target_role: string
  result_batch_id: string
  game_id: string
  history_game_id: string
  replayHash: string
  [key: string]: unknown
}

export interface BenchmarkLeaderboardRow {
  key: string
  rank: number
  primary: string
  secondary: string
  score: number
  winRate: number
  games: number
  rankable: boolean
  target_role?: string
  target_version_id?: string
  model_id?: string
  model_config_hash?: string
  [key: string]: unknown
}

export interface BenchmarkSnapshot {
  snapshot_id: string
  title: string
  release_notes: string
  scope: BenchmarkTargetType
  benchmark_id: string
  benchmark_version: string | number | null
  evaluation_set_id: string
  seed_set_id: string
  benchmark_config_hash: string
  target_role: string
  source_filter: UnknownRecord
  view_config: UnknownRecord
  summary: UnknownRecord
  release_gate: UnknownRecord
  release_manifest: UnknownRecord
  rows: BenchmarkLeaderboardRow[]
  created_at: string
  [key: string]: unknown
}

export interface BenchmarkView {
  kind: 'benchmark_saved_view'
  schema_version: number
  view_key: string
  name: string
  scope: BenchmarkTargetType
  benchmark_id: string | null
  evaluation_set_id: string | null
  target_role: string | null
  view_config: {
    mode: BenchmarkTargetType
    rank_filter: 'all' | 'rankable' | 'unrankable'
    columns: string[]
    sort: string
    search: string
    density: string
  }
  created_at?: string | null
  updated_at?: string | null
  [key: string]: unknown
}

export interface BenchmarkListResponse<T> {
  items: T[]
  pagination?: Pagination
  raw?: unknown
}
