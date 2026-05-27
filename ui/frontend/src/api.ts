import type { GameArchive, GameSnapshot } from "./types";

export async function listGames(): Promise<GameSnapshot[]> {
  const response = await fetch("/api/games");
  if (!response.ok) throw new Error("无法读取游戏列表");
  const data = await response.json();
  return data.games;
}

export async function startGame(): Promise<GameSnapshot> {
  const response = await fetch("/api/games", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
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

