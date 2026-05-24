export type Player = {
  id: number;
  role: string;
  team: string;
  alive: boolean;
  is_sheriff: boolean;
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
  alternatives: number[];
  rejected_reasons: string[];
  belief_snapshot: Record<string, unknown>;
  memory_summary: string[];
  source: "llm" | "fallback" | "policy_adjusted";
};

export type GameSnapshot = {
  game_id: string;
  log_name: string;
  status: "starting" | "running" | "completed" | "failed";
  winner: string | null;
  seed: number | null;
  day: number;
  phase: string;
  sheriff_id: number | null;
  players: Player[];
  event_count: number;
  events: GameEvent[];
  decisions: AgentDecision[];
  error: string | null;
};
