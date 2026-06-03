import type { GameArchive, GameSnapshot } from "./types";

export type { GameArchive } from "./types";

export interface GameConfig {
  seed?: number;
  max_days?: number;
  enable_sheriff?: boolean;
  skill_dir?: string;
  player_count?: number;
  role_versions?: Record<string, string>;  // {role: hash} per-role version selection
  human_player_id?: number;  // 1-12, which player slot is human-controlled
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

export async function getGameArchive(gameId: string): Promise<GameArchive> {
  const response = await fetch(`/api/games/${gameId}/archive`);
  if (!response.ok) throw new Error("存档数据不可用");
  return response.json();
}

// ---------------------------------------------------------------------------
// Human player action APIs
// ---------------------------------------------------------------------------

export type HumanActionPending = {
  player_id: number;
  action_type: string;
  phase: string | null;
  day: number;
  role: string | null;
  alive_players: number[];
  candidates: number[];
  metadata: Record<string, unknown>;
  observation: {
    role: string | null;
    day: number;
    alive_players: number[];
  };
};

export type HumanActionSubmit = {
  action_type: string;
  target?: number | null;
  choice?: string | null;
  text?: string;
};

export async function getHumanAction(gameId: string): Promise<HumanActionPending | null> {
  const response = await fetch(`/api/games/${gameId}/human-action`);
  if (response.status === 204) return null;
  if (!response.ok) throw new Error("无法读取人类玩家操作");
  return response.json();
}

export async function submitHumanAction(gameId: string, action: HumanActionSubmit): Promise<void> {
  const response = await fetch(`/api/games/${gameId}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(action),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? "提交操作失败");
  }
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
  const response = await fetch("/api/evolution-runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      roles: [role],
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
  const response = await fetch("/api/evolution-runs");
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
  const response = await fetch("/api/evolution-runs", {
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
  const response = await fetch(`/api/evolution-runs/${batchId}`);
  if (!response.ok) throw new Error("无法读取批量演化状态");
  return response.json();
}

export async function promoteRoleBatchEvolution(batchId: string): Promise<BatchEvolutionRunStatus> {
  return evolutionRunAction(batchId, "promote", "批量推广失败");
}

export async function rejectRoleBatchEvolution(batchId: string): Promise<BatchEvolutionRunStatus> {
  return evolutionRunAction(batchId, "reject", "批量拒绝失败");
}

export async function stopBatchEvolution(batchId: string): Promise<BatchEvolutionRunStatus> {
  return evolutionRunAction(batchId, "stop", "无法暂停批量演化");
}

export async function terminateBatchEvolution(batchId: string): Promise<BatchEvolutionRunStatus> {
  return evolutionRunAction(batchId, "terminate", "无法终止批量演化");
}

export async function listRoleEvolutionRuns(): Promise<EvolutionRunStatus[]> {
  const response = await fetch("/api/evolution-runs");
  if (!response.ok) throw new Error("无法读取演化任务列表");
  const data = await response.json();
  return data.runs ?? [];
}

export async function getRoleEvolutionStatus(runId: string): Promise<EvolutionRunStatus> {
  const response = await fetch(`/api/evolution-runs/${runId}`);
  if (!response.ok) throw new Error("无法读取演化状态");
  return response.json();
}

export async function stopRoleEvolution(runId: string): Promise<EvolutionRunStatus> {
  return evolutionRunAction(runId, "stop", "无法停止演化任务");
}

export async function resumeRoleEvolution(runId: string): Promise<EvolutionRunStatus> {
  return evolutionRunAction(runId, "resume", "无法恢复演化任务");
}

export async function rerunConsolidation(runId: string): Promise<EvolutionRunStatus> {
  return evolutionRunAction(runId, "rerun_consolidation", "无法重新整合");
}

export async function terminateRoleEvolution(runId: string): Promise<EvolutionRunStatus> {
  return evolutionRunAction(runId, "terminate", "无法终止演化任务");
}

export async function getRoleEvolutionDiff(runId: string): Promise<{ diffs: Array<{ filename: string; action: string; before: string | null; after: string | null }> }> {
  const response = await fetch(`/api/evolution-runs/${runId}/diff`);
  if (!response.ok) throw new Error("无法读取变更清单");
  return response.json();
}

export async function promoteRoleEvolution(runId: string): Promise<EvolutionRunStatus> {
  return evolutionRunAction(runId, "promote", "推广失败");
}

export async function rejectRoleEvolution(runId: string): Promise<EvolutionRunStatus> {
  return evolutionRunAction(runId, "reject", "拒绝失败");
}

async function evolutionRunAction<T>(runId: string, action: string, fallback: string): Promise<T> {
  const response = await fetch(`/api/evolution-runs/${runId}/actions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? fallback);
  }
  return response.json();
}

export type EvolutionGameSummary = {
  game_id: string;
  winner: string | null;
  day: number;
  phase: string;
  event_count: number;
  in_progress?: boolean;
};

export async function listRoleEvolutionTrainingGames(runId: string): Promise<EvolutionGameSummary[]> {
  const response = await fetch(`/api/evolution-runs/${runId}/games?phase=training`);
  if (!response.ok) throw new Error("无法读取训练对局列表");
  const data = await response.json();
  return data.games ?? [];
}

export async function getRoleEvolutionTrainingGameEvents(runId: string, gameId: string): Promise<Record<string, unknown>[]> {
  const response = await fetch(`/api/evolution-runs/${runId}/games/${gameId}/events?phase=training`);
  if (!response.ok) throw new Error("无法读取训练对局事件");
  const data = await response.json();
  return data.events ?? [];
}

export async function getRoleEvolutionTrainingGameDecisions(runId: string, gameId: string): Promise<Record<string, unknown>[]> {
  const response = await fetch(`/api/evolution-runs/${runId}/games/${gameId}/decisions?phase=training`);
  if (!response.ok) throw new Error("无法读取训练决策记录");
  const data = await response.json();
  return data.decisions ?? [];
}

export async function getRoleEvolutionTrainingGameArchive(runId: string, gameId: string): Promise<GameArchive> {
  const response = await fetch(`/api/evolution-runs/${runId}/games/${gameId}/archive?phase=training`);
  if (!response.ok) throw new Error("无法读取训练对局存档");
  return response.json();
}

export async function listBattleGames(runId: string, side: "baseline" | "candidate"): Promise<EvolutionGameSummary[]> {
  const response = await fetch(`/api/evolution-runs/${runId}/games?phase=battle&side=${side}`);
  if (!response.ok) throw new Error("无法读取对战对局列表");
  const data = await response.json();
  return data.games ?? [];
}

export async function getBattleGameEvents(runId: string, side: string, gameId: string): Promise<Record<string, unknown>[]> {
  const response = await fetch(`/api/evolution-runs/${runId}/games/${gameId}/events?phase=battle&side=${side}`);
  if (!response.ok) throw new Error("无法读取对战对局事件");
  const data = await response.json();
  return data.events ?? [];
}

export async function getBattleGameDecisions(runId: string, side: string, gameId: string): Promise<Record<string, unknown>[]> {
  const response = await fetch(`/api/evolution-runs/${runId}/games/${gameId}/decisions?phase=battle&side=${side}`);
  if (!response.ok) throw new Error("无法读取对战决策记录");
  const data = await response.json();
  return data.decisions ?? [];
}

export async function getBattleGameArchive(runId: string, side: string, gameId: string): Promise<GameArchive> {
  const response = await fetch(`/api/evolution-runs/${runId}/games/${gameId}/archive?phase=battle&side=${side}`);
  if (!response.ok) throw new Error("无法读取对战对局存档");
  return response.json();
}



