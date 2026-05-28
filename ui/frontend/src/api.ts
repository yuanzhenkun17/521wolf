import type { GameArchive, GameSnapshot } from "./types";

export interface GameConfig {
  seed?: number;
  max_days?: number;
  enable_sheriff?: boolean;
  skill_dir?: string;
  player_count?: number;
}

export async function listGames(): Promise<GameSnapshot[]> {
  const response = await fetch("/api/games");
  if (!response.ok) throw new Error("无法读取游戏列表");
  const data = await response.json();
  return data.games;
}

export async function startGame(config: GameConfig = {}): Promise<GameSnapshot> {
  const response = await fetch("/api/games", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? "无法启动游戏");
  }
  return response.json();
}

export async function getGame(gameId: string): Promise<GameSnapshot> {
  const response = await fetch(`/api/games/${gameId}`);
  if (!response.ok) throw new Error("无法读取游戏快照");
  return response.json();
}

export async function getGameReview(gameId: string): Promise<Record<string, unknown>> {
  const response = await fetch(`/api/games/${gameId}/review`);
  if (!response.ok) throw new Error("复盘数据不可用");
  return response.json();
}

export async function getLeaderboard(): Promise<Record<string, unknown>> {
  const response = await fetch("/api/leaderboards");
  if (!response.ok) throw new Error("排行榜数据不可用");
  return response.json();
}

export async function getGameArchive(gameId: string): Promise<GameArchive> {
  const response = await fetch(`/api/games/${gameId}/archive`);
  if (!response.ok) throw new Error("存档数据不可用");
  return response.json();
}

// ---------------------------------------------------------------------------
// Role Evolution APIs
// ---------------------------------------------------------------------------

export type RoleVersion = {
  hash: string;
  role: string;
  created_at: string;
  parent_hash: string | null;
  source: string;
  notes: string[];
  is_baseline: boolean;
};

export type RoleHistory = {
  role: string;
  baseline: string;
  versions: string[];
};

export type RoleLeaderboardEntry = {
  hash: string;
  role: string;
  is_baseline: boolean;
  total_games: number;
  target_role_role_weighted_score: number;
  target_role_speech_score: number;
  target_role_vote_score: number;
  target_role_skill_score: number;
  target_role_fallback_rate: number;
  target_role_bad_case_rate: number;
  target_side_win_rate: number;
  target_side_win_rate_ci: [number, number];
  delta_vs_baseline: Record<string, number>;
  battle_record: string;
  recommendation: string;
  data_sufficient: boolean;
};

export type EvolutionRunStatus = {
  run_id: string;
  role: string;
  parent_hash: string;
  status: string;
  training_games: number;
  battle_games: number;
  training_completed: number;
  battle_completed: number;
  current_stage: string;
  candidate_hash: string | null;
  battle_result: { wins: number; losses: number; win_rate: number } | null;
  diff: Array<{
    filename: string;
    action: string;
    before: string | null;
    after: string | null;
    proposal_ref: string;
  }> | null;
  errors: string[];
  kind: string;
  schema_version: number;
};

export async function listRoles(): Promise<string[]> {
  const response = await fetch("/api/roles");
  if (!response.ok) throw new Error("无法读取角色列表");
  const data = await response.json();
  return data.roles;
}

export async function listRoleVersions(role: string): Promise<RoleVersion[]> {
  const response = await fetch(`/api/roles/${encodeURIComponent(role)}/versions`);
  if (!response.ok) throw new Error("无法读取角色版本");
  const data = await response.json();
  return data.versions;
}

export async function getRoleVersion(role: string, hash: string): Promise<RoleVersion & { skills: Record<string, string> }> {
  const response = await fetch(`/api/roles/${encodeURIComponent(role)}/versions/${hash}`);
  if (!response.ok) throw new Error("无法读取版本详情");
  return response.json();
}

export async function getRoleLeaderboard(role: string): Promise<RoleLeaderboardEntry[]> {
  const response = await fetch(`/api/roles/${encodeURIComponent(role)}/leaderboard`);
  if (!response.ok) throw new Error("无法读取排行榜");
  const data = await response.json();
  return data.entries;
}

export async function rollbackRole(role: string, hash: string): Promise<void> {
  const response = await fetch(`/api/roles/${encodeURIComponent(role)}/rollback/${hash}`, { method: "POST" });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? "回滚失败");
  }
}

export async function startRoleEvolution(role: string, trainingGames: number, battleGames: number): Promise<{ run_id: string }> {
  const response = await fetch("/api/role-evolution/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role, training_games: trainingGames, battle_games: battleGames }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? "无法启动自进化");
  }
  return response.json();
}

export async function getRoleEvolutionStatus(runId: string): Promise<EvolutionRunStatus> {
  const response = await fetch(`/api/role-evolution/${runId}/status`);
  if (!response.ok) throw new Error("无法读取演化状态");
  return response.json();
}

export async function getRoleEvolutionDiff(runId: string): Promise<{ diffs: Array<{ filename: string; action: string; before: string | null; after: string | null }> }> {
  const response = await fetch(`/api/role-evolution/${runId}/diff`);
  if (!response.ok) throw new Error("无法读取变更清单");
  return response.json();
}

export async function promoteRoleEvolution(runId: string): Promise<EvolutionRunStatus> {
  const response = await fetch(`/api/role-evolution/${runId}/promote`, { method: "POST" });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? "推广失败");
  }
  return response.json();
}

export async function rejectRoleEvolution(runId: string): Promise<EvolutionRunStatus> {
  const response = await fetch(`/api/role-evolution/${runId}/reject`, { method: "POST" });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? "拒绝失败");
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Selfplay APIs
// ---------------------------------------------------------------------------

export type SelfplayRun = {
  run_id: string;
  label: string;
  status: "pending" | "running" | "completed" | "failed";
  num_games: number;
  completed_games: number;
  agent_version?: string;
  artifact_run_id?: string;
  skill_dir?: string;
  max_days?: number;
  enable_sheriff?: boolean;
  enable_batch_dream?: boolean;
  created_at: string;
  results?: Record<string, unknown>;
  error?: string;
};

export type SelfplayConfig = {
  num_games: number;
  agent_version?: string;
  skill_dir?: string;
  max_days?: number;
  enable_sheriff?: boolean;
  enable_batch_dream?: boolean;
  label?: string;
};

export async function listSelfplayRuns(): Promise<SelfplayRun[]> {
  const response = await fetch("/api/selfplay");
  if (!response.ok) throw new Error("无法读取自对弈列表");
  const data = await response.json();
  return data.runs ?? data;
}

export async function getSelfplayRun(runId: string): Promise<SelfplayRun> {
  const response = await fetch(`/api/selfplay/${runId}`);
  if (!response.ok) throw new Error("无法读取自对弈状态");
  return response.json();
}

export async function startSelfplayRun(config: SelfplayConfig): Promise<SelfplayRun> {
  const response = await fetch("/api/selfplay", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? "无法启动自对弈");
  }
  return response.json();
}



