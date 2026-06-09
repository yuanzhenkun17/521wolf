import type { Pagination, UnknownRecord } from './api'
import type { Decision, Game, GameLog, GamePhase, Player } from './game'

export type HistorySource = 'all' | 'normal' | 'benchmark' | 'evolution' | string
export type HistoryWorkspaceTab = 'phase' | 'review' | 'archive'

export interface EvidenceSource {
  log_source?: HistorySource
  log_source_label?: string
  source_run_id?: string | null
  source_phase?: string | null
  source_phase_label?: string | null
  seed?: string | number | null
  role_versions?: Record<string, string>
  [key: string]: unknown
}

export interface HistoryPage {
  key: string
  day: number
  phase: GamePhase
  title: string
  log_count: number
  decision_count: number
  index: number
  loaded?: boolean
  logs?: GameLog[]
  decisions?: Decision[]
  summary?: UnknownRecord
  pagination?: HistoryPhasePagination | null
  [key: string]: unknown
}

export interface HistoryPhasePagination {
  logs: Pagination
  decisions: Pagination
}

export interface HistoryPhaseDetail {
  key: string
  day: number
  phase: GamePhase
  logs: GameLog[]
  decisions: Decision[]
  summary: UnknownRecord
  pagination: HistoryPhasePagination
  loaded_at: number
  [key: string]: unknown
}

export interface HistoryGame extends Game {
  event_count: number
  decision_count: number
  evidence_source?: EvidenceSource
  phases: HistoryPage[]
  history_pages: HistoryPage[]
  __historyPages?: HistoryPage[]
  __phaseDetails?: Record<string, HistoryPhaseDetail>
  __activePhaseKey?: string
  __detailView?: string
}

export interface HistoryListResponse {
  games: HistoryGame[]
  pagination: Pagination
  counts: Record<string, number>
  facets: Record<string, unknown>
  raw?: unknown
}

export interface ReplaySnapshot extends Game {
  cursor: number
  limit: number
  next_cursor: number | null
  has_more: boolean
  players: Player[]
  logs: GameLog[]
  decisions: Decision[]
}

export interface HistoryQuery {
  limit?: number | null
  offset?: number
  source?: HistorySource
  status?: string
}

export interface PhaseDetailQuery {
  day: number
  phase: GamePhase
  log_offset?: number
  log_limit?: number
  decision_offset?: number
  decision_limit?: number
}
