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
// Version Management APIs
// ---------------------------------------------------------------------------

export type VersionManifest = {
  version_id: string;
  label: string;
  skill_dir: string;
  created_at: string;
  status: string;
  description?: string;
  tags?: string[];
};

export type VersionDetail = VersionManifest & {
  config: Record<string, unknown>;
  metrics?: Record<string, unknown>;
};

export type VersionLeaderboardEntry = {
  version_id?: string;
  version?: string;
  label?: string;
  games: number;
  werewolf_win_rate: number;
  villager_win_rate: number;
  avg_score: number;
  avg_score_ci95?: [number, number];
  role_weighted_score?: number;
  role_weighted_score_ci95?: [number, number];
  score_delta_vs_base?: number;
  significant_vs_base?: boolean;
  avg_speech_score: number;
  avg_vote_score: number;
  avg_skill_score: number;
  avg_confidence?: number;
  confidence_calibration_error?: number;
  confidence_calibration_count?: number;
  confidence_buckets?: Record<string, {
    count: number;
    correct: number;
    confidence_sum?: number;
    avg_confidence: number;
    accuracy: number;
    error: number;
  }>;
  fallback_rate: number;
  policy_adjusted_rate: number;
  werewolf_win_rate_ci95?: [number, number];
  villager_win_rate_ci95?: [number, number];
};

export type PromoteResult = {
  version_id: string;
  passed: boolean;
  score: number;
  details: Record<string, unknown>;
};

export async function listVersions(): Promise<VersionManifest[]> {
  const response = await fetch("/api/versions");
  if (!response.ok) throw new Error("无法读取版本列表");
  const data = await response.json();
  return data.versions ?? data;
}

export async function getVersionDetail(versionId: string): Promise<VersionDetail> {
  const response = await fetch(`/api/versions/${versionId}`);
  if (!response.ok) throw new Error("无法读取版本详情");
  return response.json();
}

export async function promoteVersion(versionId: string): Promise<PromoteResult> {
  const response = await fetch(`/api/versions/${versionId}/promote`, { method: "POST" });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? "晋升评估失败");
  }
  return response.json();
}

export async function createVersion(config: {
  name: string;
  base?: string;
  notes?: string;
  provider?: string;
  model?: string;
  temperature?: number;
  max_tokens?: number;
  base_url?: string;
  tot_enabled?: boolean;
  got_enabled?: boolean;
  got_trigger_threshold?: number;
  batch_dream_enabled?: boolean;
}): Promise<VersionManifest> {
  const response = await fetch("/api/versions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? "创建版本失败");
  }
  return response.json();
}

export async function getVersionLeaderboard(): Promise<VersionLeaderboardEntry[]> {
  const response = await fetch("/api/versions/leaderboard");
  if (!response.ok) throw new Error("排行榜数据不可用");
  const data = await response.json();
  return data.entries ?? data;
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

// ---------------------------------------------------------------------------
// Evolution APIs
// ---------------------------------------------------------------------------

export type EvolutionConfig = {
  base_version: string;
  candidate_version: string;
  training_games?: number;
  battle_games?: number;
  training_seed_start?: number;
  battle_seed_start?: number;
  max_days?: number;
  enable_dream?: boolean;
  enable_skill_proposals?: boolean;
  auto_apply_skill_proposals?: boolean;
  min_score_improvement?: number;
  max_win_rate_drop?: number;
  notes?: string;
};

export type EvolutionRun = {
  run_id: string;
  status: "running" | "completed" | "failed";
  stage: string;
  started_at: string;
  artifact_run_id?: string;
  config: EvolutionConfig & Record<string, unknown>;
  result?: Record<string, unknown>;
  candidate_version?: string;
  promoted?: boolean;
  reasons?: string[];
  metrics?: Record<string, number>;
  error?: string;
};

export async function startEvolutionRun(config: EvolutionConfig): Promise<EvolutionRun> {
  const response = await fetch("/api/evolution", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? "无法启动自进化");
  }
  return response.json();
}

export async function listEvolutionRuns(): Promise<EvolutionRun[]> {
  const response = await fetch("/api/evolution");
  if (!response.ok) throw new Error("无法读取自进化任务");
  const data = await response.json();
  return data.runs ?? data;
}

export async function getEvolutionRun(runId: string): Promise<EvolutionRun> {
  const response = await fetch(`/api/evolution/${runId}`);
  if (!response.ok) throw new Error("无法读取自进化任务状态");
  return response.json();
}

// ---------------------------------------------------------------------------
// Mixed Version Battle APIs
// ---------------------------------------------------------------------------

export type MixedBattleConfig = {
  wolves_version: string;
  villagers_version: string;
  games_per_side?: number;
  seed_start?: number;
  max_days?: number;
  enable_review?: boolean;
};

export type MixedBattleRun = {
  run_id: string;
  status: "running" | "completed" | "failed";
  started_at: string;
  config: Record<string, unknown>;
  leaderboard?: VersionLeaderboardEntry[];
  result?: Record<string, unknown>;
  error?: string;
};

export async function startMixedBattle(config: MixedBattleConfig): Promise<MixedBattleRun> {
  const response = await fetch("/api/mixed-battles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? "无法启动混编对战");
  }
  return response.json();
}

export async function listMixedBattles(): Promise<MixedBattleRun[]> {
  const response = await fetch("/api/mixed-battles");
  if (!response.ok) throw new Error("无法读取混编对战任务");
  const data = await response.json();
  return data.runs ?? data;
}

// ---------------------------------------------------------------------------
// Proposals & Memory APIs
// ---------------------------------------------------------------------------

export type Proposal = {
  proposal_id: string;
  role: string;
  proposal_type: string;
  content: string;
  status: string;
  score?: number;
  created_at: string;
  metadata?: Record<string, unknown>;
};

export type MemoryCandidate = {
  id: string;
  role: string;
  content: string;
  source: string;
  score?: number;
  created_at: string;
};

export type DreamReport = {
  id: string;
  role: string;
  summary: string;
  insights: string[];
  created_at: string;
  metadata?: Record<string, unknown>;
};

export async function listProposals(role?: string): Promise<Proposal[]> {
  const params = role ? `?role=${encodeURIComponent(role)}` : "";
  const response = await fetch(`/api/proposals${params}`);
  if (!response.ok) throw new Error("无法读取提案列表");
  const data = await response.json();
  return data.proposals ?? data;
}

export async function getProposalDetail(proposalId: string): Promise<Proposal> {
  const response = await fetch(`/api/proposals/${proposalId}`);
  if (!response.ok) throw new Error("无法读取提案详情");
  return response.json();
}

export async function listPatches(): Promise<Proposal[]> {
  const response = await fetch("/api/proposals/patches");
  if (!response.ok) throw new Error("无法读取补丁列表");
  const data = await response.json();
  return data.patches ?? data;
}

export async function listMemoryCandidates(role?: string): Promise<MemoryCandidate[]> {
  const params = role ? `?role=${encodeURIComponent(role)}` : "";
  const response = await fetch(`/api/memory-candidates${params}`);
  if (!response.ok) throw new Error("无法读取记忆候选");
  const data = await response.json();
  return data.candidates ?? data;
}

export async function listDreams(role?: string): Promise<DreamReport[]> {
  const params = role ? `?role=${encodeURIComponent(role)}` : "";
  const response = await fetch(`/api/dreams${params}`);
  if (!response.ok) throw new Error("无法读取梦境报告");
  const data = await response.json();
  return data.dreams ?? data;
}

