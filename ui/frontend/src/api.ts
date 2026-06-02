import type { GameArchive, GameSnapshot } from "./types";

export type { GameArchive } from "./types";

export interface GameConfig {
  seed?: number;
  max_days?: number;
  enable_sheriff?: boolean;
  skill_dir?: string;
  player_count?: number;
  role_versions?: Record<string, string>;  // {role: hash} per-role version selection
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
  artifact_run_id?: string | null;
  training_run_id?: string | null;
  training_output_dir?: string | null;
  role: string;
  parent_hash: string;
  status: string;
  training_games: number;
  battle_games: number;
  training_completed: number;
  battle_completed: number;
  current_stage: string;
  candidate_hash: string | null;
  battle_result: { wins: number; losses: number; win_rate: number; skipped?: boolean; reason?: string } | null;
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
  retry_attempt?: number;
  retry_total?: number;
};

export type BatchEvolutionRunStatus = {
  kind: string;
  schema_version: number;
  batch_id: string;
  roles: string[];
  status: string;
  stage: string;
  current_stage: string;
  started_at: string;
  training_games: number;
  battle_games: number;
  role_concurrency: number;
  game_concurrency: number;
  llm_concurrency: number;
  llm_rpm: number;
  role_statuses: Record<string, string>;
  role_run_ids: Record<string, string>;
  role_candidates: Record<string, string | null>;
  accepted_roles: string[];
  rejected_roles: string[];
  combined_passed: boolean;
  promoted_roles: string[];
  errors: string[];
  combined_battle_result: Record<string, unknown> | null;
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
  const response = await fetch(`/api/roles/${encodeURIComponent(role)}/versions/${encodeURIComponent(hash)}`);
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
  const response = await fetch(`/api/roles/${encodeURIComponent(role)}/rollback/${encodeURIComponent(hash)}`, { method: "POST" });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? "回滚失败");
  }
}

export async function startRoleEvolution(
  role: string,
  trainingGames: number,
  battleGames: number,
  gameConcurrency = 1,
  llmConcurrency = 5,
  llmRpm = 60,
): Promise<{ run_id: string }> {
  const response = await fetch("/api/role-evolution/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      role,
      training_games: trainingGames,
      battle_games: battleGames,
      game_concurrency: gameConcurrency,
      llm_concurrency: llmConcurrency,
      llm_rpm: llmRpm,
    }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? "无法启动自进化");
  }
  return response.json();
}

export async function listRoleBatchEvolutionRuns(): Promise<BatchEvolutionRunStatus[]> {
  const response = await fetch("/api/role-evolution/batches");
  if (!response.ok) throw new Error("无法读取批量演化任务列表");
  const data = await response.json();
  return data.batches ?? [];
}

export async function startRoleBatchEvolution(config: {
  roles: string[];
  trainingGames: number;
  battleGames: number;
  roleConcurrency: number;
  gameConcurrency: number;
  llmConcurrency: number;
  llmRpm: number;
}): Promise<BatchEvolutionRunStatus> {
  const response = await fetch("/api/role-evolution/batch/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      roles: config.roles,
      training_games: config.trainingGames,
      battle_games: config.battleGames,
      role_concurrency: config.roleConcurrency,
      game_concurrency: config.gameConcurrency,
      llm_concurrency: config.llmConcurrency,
      llm_rpm: config.llmRpm,
    }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? "无法启动批量演化");
  }
  return response.json();
}

export async function getRoleBatchEvolutionStatus(batchId: string): Promise<BatchEvolutionRunStatus> {
  const response = await fetch(`/api/role-evolution/batch/${batchId}/status`);
  if (!response.ok) throw new Error("无法读取批量演化状态");
  return response.json();
}

export async function promoteRoleBatchEvolution(batchId: string): Promise<BatchEvolutionRunStatus> {
  const response = await fetch(`/api/role-evolution/batch/${batchId}/promote`, { method: "POST" });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? "批量推广失败");
  }
  return response.json();
}

export async function rejectRoleBatchEvolution(batchId: string): Promise<BatchEvolutionRunStatus> {
  const response = await fetch(`/api/role-evolution/batch/${batchId}/reject`, { method: "POST" });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? "批量拒绝失败");
  }
  return response.json();
}

export async function stopBatchEvolution(batchId: string): Promise<BatchEvolutionRunStatus> {
  const response = await fetch(`/api/role-evolution/batch/${batchId}/stop`, { method: "POST" });
  if (!response.ok) throw new Error("无法暂停批量演化");
  return response.json();
}

export async function terminateBatchEvolution(batchId: string): Promise<BatchEvolutionRunStatus> {
  const response = await fetch(`/api/role-evolution/batch/${batchId}/terminate`, { method: "POST" });
  if (!response.ok) throw new Error("无法终止批量演化");
  return response.json();
}

export async function listRoleEvolutionRuns(): Promise<EvolutionRunStatus[]> {
  const response = await fetch("/api/role-evolution");
  if (!response.ok) throw new Error("无法读取演化任务列表");
  const data = await response.json();
  return data.runs ?? [];
}

export async function getRoleEvolutionStatus(runId: string): Promise<EvolutionRunStatus> {
  const response = await fetch(`/api/role-evolution/${runId}/status`);
  if (!response.ok) throw new Error("无法读取演化状态");
  return response.json();
}

export async function stopRoleEvolution(runId: string): Promise<EvolutionRunStatus> {
  const response = await fetch(`/api/role-evolution/${runId}/stop`, { method: "POST" });
  if (!response.ok) throw new Error("无法停止演化任务");
  return response.json();
}

export async function resumeRoleEvolution(runId: string): Promise<EvolutionRunStatus> {
  const response = await fetch(`/api/role-evolution/${runId}/resume`, { method: "POST" });
  if (!response.ok) throw new Error("无法恢复演化任务");
  return response.json();
}

export async function rerunConsolidation(runId: string): Promise<EvolutionRunStatus> {
  const response = await fetch(`/api/role-evolution/${runId}/rerun-consolidation`, { method: "POST" });
  if (!response.ok) throw new Error("无法重新整合");
  return response.json();
}

export async function terminateRoleEvolution(runId: string): Promise<EvolutionRunStatus> {
  const response = await fetch(`/api/role-evolution/${runId}/terminate`, { method: "POST" });
  if (!response.ok) throw new Error("无法终止演化任务");
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
  status: "pending" | "running" | "paused" | "rate_limited" | "completed" | "failed";
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
  retry_attempt?: number;
  retry_total?: number;
};

export type SelfplayConfig = {
  num_games: number;
  agent_version?: string;
  skill_dir?: string;
  max_days?: number;
  enable_sheriff?: boolean;
  enable_batch_dream?: boolean;
  label?: string;
  game_concurrency?: number;
  llm_concurrency?: number;
  llm_rpm?: number;
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

export async function stopSelfplayRun(runId: string): Promise<SelfplayRun> {
  const response = await fetch(`/api/selfplay/${runId}/stop`, { method: "POST" });
  if (!response.ok) throw new Error("无法停止自对弈");
  return response.json();
}

export async function resumeSelfplayRun(runId: string): Promise<SelfplayRun> {
  const response = await fetch(`/api/selfplay/${runId}/resume`, { method: "POST" });
  if (!response.ok) throw new Error("无法恢复自对弈");
  return response.json();
}

export async function terminateSelfplayRun(runId: string): Promise<SelfplayRun> {
  const response = await fetch(`/api/selfplay/${runId}/terminate`, { method: "POST" });
  if (!response.ok) throw new Error("无法终止自对弈");
  return response.json();
}

export type SelfplayGameSummary = {
  game_id: string;
  winner: string | null;
  day: number;
  phase: string;
  event_count: number;
  in_progress?: boolean;
};

export async function listSelfplayGames(runId: string): Promise<SelfplayGameSummary[]> {
  const response = await fetch(`/api/selfplay/${runId}/games`);
  if (!response.ok) throw new Error("无法读取对局列表");
  const data = await response.json();
  return data.games ?? [];
}

export async function getSelfplayGameEvents(runId: string, gameId: string): Promise<Record<string, unknown>[]> {
  const response = await fetch(`/api/selfplay/${runId}/games/${gameId}/events`);
  if (!response.ok) throw new Error("无法读取对局事件");
  const data = await response.json();
  return data.events ?? [];
}

export async function getSelfplayGameDecisions(runId: string, gameId: string): Promise<Record<string, unknown>[]> {
  const response = await fetch(`/api/selfplay/${runId}/games/${gameId}/decisions`);
  if (!response.ok) throw new Error("无法读取决策记录");
  const data = await response.json();
  return data.decisions ?? [];
}

export async function getSelfplayGameArchive(runId: string, gameId: string): Promise<GameArchive> {
  const response = await fetch(`/api/selfplay/${runId}/games/${gameId}/archive`);
  if (!response.ok) throw new Error("无法读取对局存档");
  return response.json();
}

export async function listRoleEvolutionTrainingGames(runId: string): Promise<SelfplayGameSummary[]> {
  const response = await fetch(`/api/role-evolution/${runId}/games`);
  if (!response.ok) throw new Error("无法读取训练对局列表");
  const data = await response.json();
  return data.games ?? [];
}

export async function getRoleEvolutionTrainingGameEvents(runId: string, gameId: string): Promise<Record<string, unknown>[]> {
  const response = await fetch(`/api/role-evolution/${runId}/games/${gameId}/events`);
  if (!response.ok) throw new Error("无法读取训练对局事件");
  const data = await response.json();
  return data.events ?? [];
}

export async function getRoleEvolutionTrainingGameDecisions(runId: string, gameId: string): Promise<Record<string, unknown>[]> {
  const response = await fetch(`/api/role-evolution/${runId}/games/${gameId}/decisions`);
  if (!response.ok) throw new Error("无法读取训练决策记录");
  const data = await response.json();
  return data.decisions ?? [];
}

export async function getRoleEvolutionTrainingGameArchive(runId: string, gameId: string): Promise<GameArchive> {
  const response = await fetch(`/api/role-evolution/${runId}/games/${gameId}/archive`);
  if (!response.ok) throw new Error("无法读取训练对局存档");
  return response.json();
}

export async function listBattleGames(runId: string, side: "baseline" | "candidate"): Promise<SelfplayGameSummary[]> {
  const response = await fetch(`/api/role-evolution/${runId}/battle/${side}/games`);
  if (!response.ok) throw new Error("无法读取对战对局列表");
  const data = await response.json();
  return data.games ?? [];
}

export async function getBattleGameEvents(runId: string, side: string, gameId: string): Promise<Record<string, unknown>[]> {
  const response = await fetch(`/api/role-evolution/${runId}/battle/${side}/games/${gameId}/events`);
  if (!response.ok) throw new Error("无法读取对战对局事件");
  const data = await response.json();
  return data.events ?? [];
}

export async function getBattleGameDecisions(runId: string, side: string, gameId: string): Promise<Record<string, unknown>[]> {
  const response = await fetch(`/api/role-evolution/${runId}/battle/${side}/games/${gameId}/decisions`);
  if (!response.ok) throw new Error("无法读取对战决策记录");
  const data = await response.json();
  return data.decisions ?? [];
}

export async function getBattleGameArchive(runId: string, side: string, gameId: string): Promise<GameArchive> {
  const response = await fetch(`/api/role-evolution/${runId}/battle/${side}/games/${gameId}/archive`);
  if (!response.ok) throw new Error("无法读取对战对局存档");
  return response.json();
}



