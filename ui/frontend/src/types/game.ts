import type { UnknownRecord } from './api'

export type RoleKey =
  | 'white_wolf_king'
  | 'werewolf'
  | 'villager'
  | 'seer'
  | 'witch'
  | 'hunter'
  | 'guard'
  | string

export type GamePhase =
  | 'setup'
  | 'night'
  | 'sheriff'
  | 'sheriff_vote'
  | 'sheriff_result'
  | 'speech'
  | 'exile_vote'
  | 'pk_vote'
  | 'vote'
  | 'ended'
  | string

export type GameStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | string
export type GameMode = 'play' | 'watch' | 'replay' | string
export type WaitingFor = 'none' | 'speech' | 'vote' | 'action' | string

export interface Player {
  id: number
  seat: number
  name: string
  role?: RoleKey
  role_hint?: string
  alive: boolean
  is_human: boolean
  is_sheriff: boolean
  role_state?: UnknownRecord
  [key: string]: unknown
}

export interface GameLog {
  sequence: number
  id?: string | number
  day?: number
  phase: GamePhase
  type: string
  event_type?: string
  actor_id?: number | string | null
  target_id?: number | string | null
  speaker: string
  visibility: 'public' | 'private' | string
  message: string
  [key: string]: unknown
}

export interface Decision {
  index: number
  id: string
  decision_id?: string
  day?: number
  phase: GamePhase
  actor_id?: number | string | null
  player_id?: number | string | null
  target_id?: number | string | null
  action: string
  action_type: string
  public_summary: string
  reason: string
  selected_skill?: string | null
  memory_refs: unknown[]
  belief_snapshot: UnknownRecord
  source: string
  confidence: number
  [key: string]: unknown
}

export interface PendingActionOption {
  value: string
  label: string
  requiresTarget?: boolean
}

export interface PendingAction {
  type: string
  prompt: string
  candidate_ids: number[]
  target_required: boolean
  allow_no_target: boolean
  options: {
    choices?: PendingActionOption[]
    poison_available?: boolean
    antidote_available?: boolean
    attacked_player?: number | string | null
    [key: string]: unknown
  }
}

export interface PendingHumanAction {
  action_type: string
  type: string
  player_id?: number
  candidate_ids: number[]
  target_required: boolean
  allow_no_target: boolean
  metadata?: UnknownRecord
  observation?: UnknownRecord
  prompt?: string
  [key: string]: unknown
}

export interface SkillState {
  witch_antidote_used?: boolean
  witch_poison_used?: boolean
  white_wolf_burst_used?: boolean
  [key: string]: unknown
}

export interface Game {
  game_id: string
  id?: string
  mode: GameMode
  status?: GameStatus
  phase: GamePhase
  day?: number
  winner?: string | null
  human_player_id?: number | null
  players: Player[]
  player_count: number
  logs: GameLog[]
  events?: GameLog[]
  decisions: Decision[]
  waiting_for: WaitingFor
  pending_action: PendingAction | null
  pending_human_action?: PendingHumanAction | null
  current_speaker_id?: number | null
  skill_state: SkillState
  role_versions?: Record<string, string>
  [key: string]: unknown
}

export interface GameStartRequest {
  seed?: number | null
  max_days?: number
  enable_sheriff?: boolean
  player_count?: number
  skill_dir?: string | null
  human_player_id?: number | null
  role_versions?: Record<string, string>
  model_profile_id?: string | null
}

export interface HumanActionRequest {
  action_type: string
  target?: number | null
  choice?: string | null
  text?: string
}

export interface ActiveGameSession {
  gameId: string | null
  mode: GameMode | ''
  running: boolean
  sseConnected: boolean
}
