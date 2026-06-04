export type RoleState = {
  // Witch
  antidote_available?: boolean;
  poison_available?: boolean;
  antidote_history?: Array<{ day: number; target: number }>;
  poison_history?: Array<{ day: number; target: number }>;
  // Guard
  last_target?: number | null;
  protect_history?: Array<{ day: number; target: number | null }>;
  // Seer
  checks?: Record<string, { day: number; target: number; result: string }>;
  // Hunter
  has_shot?: boolean;
  shot_target?: number | null;
  // White wolf king
  has_exploded?: boolean;
};

export type Player = {
  id: number;
  role: string;
  team: string;
  alive: boolean;
  is_sheriff: boolean;
  is_human?: boolean;
  role_state?: RoleState;
};

export type GameEvent = {
  index: number;
  day: number;
  phase: string;
  event_type: string;
  message: string;
  level: string;
  visibility: string;
  actor: number | null;
  target: number | null;
  payload: Record<string, unknown>;
};

export type AgentDecision = {
  decision_id?: string;
  index: number;
  day: number;
  phase: string;
  player_id: number | null;
  role: string;
  action_type: string;
  candidates: number[];
  selected_target: number | null;
  selected_choice: string | null;
  public_text: string;
  private_reasoning: string;
  confidence: number;
  alternatives: number[];
  rejected_reasons: string[];
  selected_skill: string;
  memory_refs: string[];
  belief_snapshot: Record<string, unknown>;
  memory_summary: string[];
  raw_output: string;
  errors: string[];
  policy_adjustments: string[];
  source: "llm" | "fallback" | "policy_adjusted" | "tot" | "got";
};

export type GameSnapshot = {
  game_id: string;
  log_name: string;
  status: "starting" | "running" | "completed" | "failed";
  winner: string | null;
  seed: number | null;
  human_player_id?: number | null;
  day: number;
  phase: string;
  sheriff_id: number | null;
  players: Player[];
  event_count: number;
  events: GameEvent[];
  decisions: AgentDecision[];
  error: string | null;
};

export type GameArchive = {
  decisions: Array<Record<string, unknown>>;
  [key: string]: unknown;
};

export type ArchiveMap = Map<string | number, Record<string, unknown>>;
