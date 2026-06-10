import type { Pagination, UnknownRecord } from './api'

export type BenchmarkTargetType = 'role_version' | 'model'
export type BenchmarkRunStatus = 'queued' | 'running' | 'rate_limited' | 'completed' | 'failed' | 'cancelled' | 'interrupted' | string
export type BenchmarkSuiteStatus = 'enabled' | 'active' | 'draft' | 'deprecated' | 'disabled' | 'archived' | string

export interface BenchmarkSeedSetDto extends UnknownRecord {
  id?: string | number | null
  seed_set_id?: string | number | null
  purpose?: string | null
  version?: string | number | null
  description?: string | null
  target_type?: string | null
  tier?: string | null
  seed_count?: string | number | null
  count?: string | number | null
  seed_preview?: unknown[] | string | null
  seeds?: unknown[] | string | null
  config_hash?: string | null
  enabled?: boolean | null
  overlap_warnings?: unknown[] | null
}

export interface BenchmarkSuiteDto extends UnknownRecord {
  id?: string | number | null
  benchmark_id?: string | number | null
  version?: string | number | null
  name?: string | null
  label?: string | null
  description?: string | null
  target_type?: string | null
  scope?: string | null
  roles?: unknown[] | null
  game_count?: string | number | null
  battle_games?: string | number | null
  games?: string | number | null
  max_days?: string | number | null
  seed_set_id?: string | number | null
  seed_set?: BenchmarkSeedSetDto | UnknownRecord | null
  paired_seed?: boolean | string | number | null
  metrics?: UnknownRecord | null
  gates?: UnknownRecord | null
  judge?: UnknownRecord | null
  config_hash?: string | null
  benchmark_config_hash?: string | null
  cost_tier?: string | null
  evaluation_set_id?: string | null
  status?: string | null
  lifecycle_status?: string | null
  lifecycleStatus?: string | null
  deprecated?: boolean | null
  archived?: boolean | null
  enabled?: boolean | null
  launchable?: boolean | null
  launch_disabled_reason?: string | null
}

export interface BenchmarkResultDto extends UnknownRecord {
  result_batch_id?: string | null
  batch_id?: string | null
  target_role?: string | null
  target_version_id?: string | null
  completed?: string | number | null
  errored?: string | number | null
  game_count?: string | number | null
  attempted_game_count?: string | number | null
  rankable?: boolean | null
  diagnostic_count?: string | number | null
  warning_count?: string | number | null
}

export interface BenchmarkRunDto extends UnknownRecord {
  id?: string | number | null
  run_id?: string | number | null
  batch_id?: string | number | null
  roles?: unknown[] | null
  role?: string | null
  status?: BenchmarkRunStatus | null
  benchmark?: BenchmarkSuiteDto | UnknownRecord | null
  benchmark_id?: string | null
  benchmark_version?: string | number | null
  target_type?: string | null
  evaluation_set_id?: string | null
  results?: BenchmarkResultDto[] | null
}

export interface BenchmarkLeaderboardRowDto extends UnknownRecord {
  key?: string | null
  rank?: string | number | null
  target_role?: string | null
  role?: string | null
  target_version_id?: string | null
  version_id?: string | null
  model_id?: string | null
  subject_id?: string | null
  model_config_hash?: string | null
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
}

export interface BenchmarkDiagnosticDto extends UnknownRecord {
  kind?: string | null
  level?: string | null
  origin?: string | null
  stage?: string | null
  message?: string | null
  target_role?: string | null
  result_batch_id?: string | null
  batch_id?: string | null
  game_id?: string | null
  history_game_id?: string | null
  historyGameId?: string | null
}

export interface BenchmarkSnapshotDto extends UnknownRecord {
  snapshot_id?: string | number | null
  id?: string | number | null
  title?: string | null
  release_notes?: string | null
  scope?: string | null
  benchmark_id?: string | null
  benchmark_version?: string | number | null
  evaluation_set_id?: string | null
  seed_set_id?: string | null
  benchmark_config_hash?: string | null
  target_role?: string | null
  source_filter?: UnknownRecord | null
  view_config?: UnknownRecord | null
  summary?: UnknownRecord | null
  release_gate?: UnknownRecord | null
  release_manifest?: UnknownRecord | null
  rows?: BenchmarkLeaderboardRowDto[] | null
  created_at?: string | null
}

export type BenchmarkSuiteListDto =
  | BenchmarkSuiteDto[]
  | {
      items?: BenchmarkSuiteDto[] | null
      benchmarks?: BenchmarkSuiteDto[] | null
      [key: string]: unknown
    }

export interface BenchmarkSeedRegistryDto extends UnknownRecord {
  items?: BenchmarkSeedSetDto[] | null
  seed_sets?: BenchmarkSeedSetDto[] | null
  summary?: UnknownRecord | null
}

export type BenchmarkLeaderboardDto =
  | BenchmarkLeaderboardRowDto[]
  | {
      items?: BenchmarkLeaderboardRowDto[] | null
      rows?: BenchmarkLeaderboardRowDto[] | null
      leaderboard?: BenchmarkLeaderboardRowDto[] | null
      [key: string]: unknown
    }

export type BenchmarkRunsDto =
  | BenchmarkRunDto[]
  | {
      items?: BenchmarkRunDto[] | null
      runs?: BenchmarkRunDto[] | null
      batches?: BenchmarkRunDto[] | null
      pagination?: Partial<Pagination> | null
      [key: string]: unknown
    }

export type BenchmarkRunResponseDto =
  | BenchmarkRunDto
  | {
      run?: BenchmarkRunDto | null
      batch?: BenchmarkRunDto | null
      data?: BenchmarkRunDto | null
      [key: string]: unknown
    }

export interface BenchmarkDiagnosticsDto extends UnknownRecord {
  items?: BenchmarkDiagnosticDto[] | null
  diagnostics?: BenchmarkDiagnosticDto[] | null
  summary?: UnknownRecord | null
  pagination?: Partial<Pagination> | null
}

export type BenchmarkSnapshotsDto =
  | BenchmarkSnapshotDto[]
  | {
      items?: BenchmarkSnapshotDto[] | null
      snapshots?: BenchmarkSnapshotDto[] | null
      [key: string]: unknown
    }

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

export interface BenchmarkSeedRegistryResponse {
  items: BenchmarkSeedSet[]
  summary: Record<string, unknown>
}

export interface BenchmarkDiagnosticsResponse {
  diagnostics: BenchmarkDiagnostic[]
  summary: Record<string, unknown>
  pagination?: Pagination
  raw?: unknown
}
