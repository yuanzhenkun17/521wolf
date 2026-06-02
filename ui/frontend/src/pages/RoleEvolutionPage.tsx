import { useCallback, useEffect, useRef, useState } from "react";
import { FolderOpen, Loader2, Pause, Play, RotateCcw, Rocket, Trophy, CheckCircle, XCircle, GitBranch, Layers3 } from "lucide-react";
import {
  listRoles,
  listRoleVersions,
  getRoleLeaderboard,
  listRoleEvolutionRuns,
  listRoleBatchEvolutionRuns,
  listRoleEvolutionTrainingGames,
  getRoleEvolutionTrainingGameArchive,
  getRoleEvolutionTrainingGameDecisions,
  getRoleEvolutionTrainingGameEvents,
  startRoleEvolution,
  startRoleBatchEvolution,
  getRoleEvolutionStatus,
  getRoleBatchEvolutionStatus,
  getRoleEvolutionDiff,
  promoteRoleEvolution,
  promoteRoleBatchEvolution,
  rejectRoleEvolution,
  rejectRoleBatchEvolution,
  rollbackRole,
  stopRoleEvolution,
  resumeRoleEvolution,
  terminateRoleEvolution,
  rerunConsolidation,
  stopBatchEvolution,
  terminateBatchEvolution,
  listBattleGames,
  getBattleGameEvents,
  getBattleGameDecisions,
  getBattleGameArchive,
  type RoleVersion,
  type RoleLeaderboardEntry,
  type EvolutionRunStatus,
  type BatchEvolutionRunStatus,
  type GameArchive,
  type SelfplayGameSummary,
} from "../api";
import { ArchivedGameDetail } from "../components/ArchivedGameDetail";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ROLE_LABELS: Record<string, string> = {
  werewolf: "狼人",
  seer: "预言家",
  witch: "女巫",
  guard: "守卫",
  hunter: "猎人",
  villager: "村民",
  white_wolf_king: "白狼王",
};

const PROMOTED_STATUSES = new Set(["promoted", "rejected"]);

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function RoleEvolutionPage() {
  const [roles, setRoles] = useState<string[]>([]);
  const [selectedRole, setSelectedRole] = useState<string>("");
  const [versions, setVersions] = useState<RoleVersion[]>([]);
  const [leaderboard, setLeaderboard] = useState<RoleLeaderboardEntry[]>([]);
  const [activeRun, setActiveRun] = useState<EvolutionRunStatus | null>(null);
  const [diff, setDiff] = useState<
    { filename: string; action: string; before: string | null; after: string | null }[] | null
  >(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trainingGames, setTrainingGames] = useState(20);
  const [battleGames, setBattleGames] = useState(10);
  const [gameConcurrency, setGameConcurrency] = useState(1);
  const [llmConcurrency, setLlmConcurrency] = useState(5);
  const [llmRpm, setLlmRpm] = useState(60);
  const [roleConcurrency, setRoleConcurrency] = useState(2);
  const [selectedBatchRoles, setSelectedBatchRoles] = useState<string[]>([]);
  const [activeBatch, setActiveBatch] = useState<BatchEvolutionRunStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [batchStarting, setBatchStarting] = useState(false);
  const [promoting, setPromoting] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [batchPromoting, setBatchPromoting] = useState(false);
  const [batchRejecting, setBatchRejecting] = useState(false);
  const [pollExhausted, setPollExhausted] = useState(false);
  const [trainingGameRunId, setTrainingGameRunId] = useState<string | null>(null);
  const [trainingGameList, setTrainingGameList] = useState<SelfplayGameSummary[]>([]);
  const [viewingTrainingGameId, setViewingTrainingGameId] = useState<string | null>(null);
  const [trainingEvents, setTrainingEvents] = useState<Record<string, unknown>[]>([]);
  const [trainingDecisions, setTrainingDecisions] = useState<Record<string, unknown>[]>([]);
  const [trainingArchive, setTrainingArchive] = useState<GameArchive | null>(null);
  const [trainingGamesLoading, setTrainingGamesLoading] = useState(false);
  const [trainingDetailLoading, setTrainingDetailLoading] = useState(false);
  // Battle game viewing state
  const [battleRunId, setBattleRunId] = useState<string | null>(null);
  const [battleSide, setBattleSide] = useState<"baseline" | "candidate">("baseline");
  const [battleGameList, setBattleGameList] = useState<SelfplayGameSummary[]>([]);
  const [viewingBattleGameId, setViewingBattleGameId] = useState<string | null>(null);
  const [battleEvents, setBattleEvents] = useState<Record<string, unknown>[]>([]);
  const [battleDecisions, setBattleDecisions] = useState<Record<string, unknown>[]>([]);
  const [battleArchive, setBattleArchive] = useState<GameArchive | null>(null);
  const [battleGamesLoading, setBattleGamesLoading] = useState(false);
  const [battleDetailLoading, setBattleDetailLoading] = useState(false);
  const sseRef = useRef<EventSource | null>(null);
  const batchSseRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const batchPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollRetriesRef = useRef(0);
  const batchPollRetriesRef = useRef(0);

  const restoreActiveRun = useCallback(async (role: string) => {
    if (!role) return;
    try {
      const runs = await listRoleEvolutionRuns();
      const run = runs
        .filter((item) => item.role === role && !PROMOTED_STATUSES.has(item.status))
        .sort((a, b) => b.run_id.localeCompare(a.run_id))[0];
      setActiveRun(run ?? null);
    } catch (exc) {
      console.error("Failed to restore active run:", exc);
    }
  }, []);

  const restoreActiveBatch = useCallback(async () => {
    try {
      const batches = await listRoleBatchEvolutionRuns();
      const batch = batches
        .filter((item) => !PROMOTED_STATUSES.has(item.status))
        .sort((a, b) => b.batch_id.localeCompare(a.batch_id))[0];
      setActiveBatch(batch ?? null);
    } catch (exc) {
      console.error("Failed to restore active batch:", exc);
    }
  }, []);

  // Load roles on mount
  useEffect(() => {
    (async () => {
      try {
        const data = await listRoles();
        setRoles(data);
        if (data.length > 0) setSelectedRole(data[0]);
        setSelectedBatchRoles(data.slice(0, Math.min(3, data.length)));
        void restoreActiveBatch();
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "加载角色列表失败");
      }
    })();
  }, [restoreActiveBatch]);

  // Load versions + leaderboard when selected role changes
  const loadRoleData = useCallback(async (role: string) => {
    if (!role) return;
    setLoading(true);
    setError(null);
    try {
      const [v, lb] = await Promise.all([listRoleVersions(role), getRoleLeaderboard(role)]);
      setVersions(v);
      setLeaderboard(lb);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载角色数据失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRoleData(selectedRole);
    void restoreActiveRun(selectedRole);
  }, [selectedRole, loadRoleData, restoreActiveRun]);

  // Request notification permission on mount
  useEffect(() => {
    if ("Notification" in window && Notification.permission === "default") {
      void Notification.requestPermission();
    }
  }, []);

  // Notify when evolution completes or fails
  useEffect(() => {
    if (!activeRun) return;
    if (activeRun.status === "reviewing") {
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification("角色演化完成", {
          body: `${activeRun.role} 演化完成，等待审查`,
        });
      }
    } else if (activeRun.status === "failed") {
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification("角色演化失败", {
          body: `${activeRun.role}: ${activeRun.errors?.[0] || "未知错误"}`,
        });
      }
    }
  }, [activeRun?.status]);

  // Notify when batch evolution completes or fails
  useEffect(() => {
    if (!activeBatch) return;
    if (activeBatch.status === "reviewing") {
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification("批量演化完成", {
          body: `批量演化完成，等待审查`,
        });
      }
    } else if (activeBatch.status === "failed") {
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification("批量演化失败", {
          body: `${activeBatch.errors?.[0] || "未知错误"}`,
        });
      }
    }
  }, [activeBatch?.status]);

  // SSE connection for active run
  useEffect(() => {
    if (!activeRun || PROMOTED_STATUSES.has(activeRun.status)) return;

    const es = new EventSource(`/api/role-evolution/${activeRun.run_id}/events`);
    sseRef.current = es;

    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as EvolutionRunStatus;
        setActiveRun(data);
      } catch {
        // ignore malformed events
      }
    };

    es.onerror = () => {
      // Fall back to polling on SSE error
      es.close();
      sseRef.current = null;
      startPolling(activeRun.run_id);
    };

    return () => {
      es.close();
      sseRef.current = null;
    };
  }, [activeRun?.run_id, activeRun?.status]);

  useEffect(() => {
    if (!activeBatch || PROMOTED_STATUSES.has(activeBatch.status)) return;

    const es = new EventSource(`/api/role-evolution/batch/${activeBatch.batch_id}/events`);
    batchSseRef.current = es;

    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as BatchEvolutionRunStatus;
        setActiveBatch(data);
      } catch {
        // ignore malformed events
      }
    };

    es.onerror = () => {
      es.close();
      batchSseRef.current = null;
      startBatchPolling(activeBatch.batch_id);
    };

    return () => {
      es.close();
      batchSseRef.current = null;
    };
  }, [activeBatch?.batch_id, activeBatch?.status]);

  const MAX_POLL_RETRIES = 20;

  function startPolling(runId: string) {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRetriesRef.current = 0;
    setPollExhausted(false);
    pollRef.current = setInterval(async () => {
      try {
        const data = await getRoleEvolutionStatus(runId);
        setActiveRun(data);
        pollRetriesRef.current = 0;
        if (PROMOTED_STATUSES.has(data.status)) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch {
        pollRetriesRef.current += 1;
        if (pollRetriesRef.current >= MAX_POLL_RETRIES) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setPollExhausted(true);
        }
      }
    }, 3000);
  }

  function startBatchPolling(batchId: string) {
    if (batchPollRef.current) clearInterval(batchPollRef.current);
    batchPollRetriesRef.current = 0;
    batchPollRef.current = setInterval(async () => {
      try {
        const data = await getRoleBatchEvolutionStatus(batchId);
        setActiveBatch(data);
        batchPollRetriesRef.current = 0;
        if (PROMOTED_STATUSES.has(data.status)) {
          if (batchPollRef.current) clearInterval(batchPollRef.current);
          batchPollRef.current = null;
        }
      } catch {
        batchPollRetriesRef.current += 1;
        if (batchPollRetriesRef.current >= MAX_POLL_RETRIES) {
          if (batchPollRef.current) clearInterval(batchPollRef.current);
          batchPollRef.current = null;
        }
      }
    }, 3000);
  }

  // Clean up on unmount
  useEffect(() => {
    return () => {
      if (sseRef.current) sseRef.current.close();
      if (batchSseRef.current) batchSseRef.current.close();
      if (pollRef.current) clearInterval(pollRef.current);
      if (batchPollRef.current) clearInterval(batchPollRef.current);
    };
  }, []);

  // Load diff when run enters reviewing status
  useEffect(() => {
    if (!activeRun || activeRun.status !== "reviewing") {
      setDiff(null);
      return;
    }
    (async () => {
      try {
        const data = await getRoleEvolutionDiff(activeRun.run_id);
        setDiff(data.diffs);
      } catch {
        setDiff(null);
      }
    })();
  }, [activeRun?.run_id, activeRun?.status]);

  // Auto-refresh training game list while training is in progress
  const trainingGamePollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (!trainingGameRunId || !activeRun || activeRun.status !== "training") return;

    trainingGamePollRef.current = setInterval(async () => {
      try {
        const games = await listRoleEvolutionTrainingGames(trainingGameRunId);
        setTrainingGameList(games);
      } catch {
        // ignore polling errors
      }
    }, 5000);
    return () => {
      if (trainingGamePollRef.current) clearInterval(trainingGamePollRef.current);
    };
  }, [trainingGameRunId, activeRun?.status]);

  // Auto-refresh battle game list while battling is in progress
  const battleGamePollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (!battleRunId || !activeRun || activeRun.status !== "battling") return;

    battleGamePollRef.current = setInterval(async () => {
      try {
        const games = await listBattleGames(battleRunId, battleSide);
        setBattleGameList(games);
      } catch {
        // ignore polling errors
      }
    }, 5000);
    return () => {
      if (battleGamePollRef.current) clearInterval(battleGamePollRef.current);
    };
  }, [battleRunId, battleSide, activeRun?.status]);

  async function handleStart() {
    if (!selectedRole) return;
    setStarting(true);
    setError(null);
    try {
      const res = await startRoleEvolution(
        selectedRole,
        trainingGames,
        battleGames,
        gameConcurrency,
        llmConcurrency,
        llmRpm,
      );
      const status = await getRoleEvolutionStatus(res.run_id);
      setActiveRun(status);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "启动失败");
    } finally {
      setStarting(false);
    }
  }

  async function handleStartBatch() {
    if (selectedBatchRoles.length === 0) return;
    setBatchStarting(true);
    setError(null);
    try {
      const res = await startRoleBatchEvolution({
        roles: selectedBatchRoles,
        trainingGames,
        battleGames,
        roleConcurrency,
        gameConcurrency,
        llmConcurrency,
        llmRpm,
      });
      setActiveBatch(res);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "启动批量演化失败");
    } finally {
      setBatchStarting(false);
    }
  }

  async function handlePromoteBatch() {
    if (!activeBatch) return;
    setBatchPromoting(true);
    setError(null);
    try {
      const next = await promoteRoleBatchEvolution(activeBatch.batch_id);
      setActiveBatch(next);
      await loadRoleData(selectedRole);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "批量推广失败");
    } finally {
      setBatchPromoting(false);
    }
  }

  async function handleRejectBatch() {
    if (!activeBatch) return;
    setBatchRejecting(true);
    setError(null);
    try {
      const next = await rejectRoleBatchEvolution(activeBatch.batch_id);
      setActiveBatch(next);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "批量拒绝失败");
    } finally {
      setBatchRejecting(false);
    }
  }

  async function handleStopBatch() {
    if (!activeBatch) return;
    setError(null);
    try {
      const next = await stopBatchEvolution(activeBatch.batch_id);
      setActiveBatch(next);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "批量暂停失败");
    }
  }

  async function handleTerminateBatch() {
    if (!activeBatch) return;
    if (!confirm("终止会永久删除该批量演化任务的所有数据，确定要终止吗？")) return;
    setError(null);
    try {
      const next = await terminateBatchEvolution(activeBatch.batch_id);
      setActiveBatch(next);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "批量终止失败");
    }
  }

  function toggleBatchRole(role: string) {
    setSelectedBatchRoles((current) =>
      current.includes(role) ? current.filter((item) => item !== role) : [...current, role],
    );
  }

  async function handlePromote() {
    if (!activeRun) return;
    setPromoting(true);
    setError(null);
    try {
      await promoteRoleEvolution(activeRun.run_id);
      setActiveRun(null);
      setDiff(null);
      await loadRoleData(selectedRole);
      // Show success notification
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification("推广成功", {
          body: `${activeRun.role} 的候选版本已推广为 baseline`,
        });
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "推广失败");
    } finally {
      setPromoting(false);
    }
  }

  async function handleReject() {
    if (!activeRun) return;
    setRejecting(true);
    setError(null);
    try {
      await rejectRoleEvolution(activeRun.run_id);
      setActiveRun(null);
      setDiff(null);
      await loadRoleData(selectedRole);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "拒绝失败");
    } finally {
      setRejecting(false);
    }
  }

  async function handleStopEvolution() {
    if (!activeRun) return;
    setError(null);
    try {
      const updated = await stopRoleEvolution(activeRun.run_id);
      setActiveRun(updated);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "停止失败");
    }
  }

  async function handleResumeEvolution() {
    if (!activeRun) return;
    setError(null);
    try {
      const updated = await resumeRoleEvolution(activeRun.run_id);
      setActiveRun(updated);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "恢复失败");
    }
  }

  async function handleTerminateEvolution() {
    if (!activeRun) return;
    if (!confirm("终止会永久删除该演化任务的所有数据，确定要终止吗？")) return;
    setError(null);
    try {
      const updated = await terminateRoleEvolution(activeRun.run_id);
      setActiveRun(updated);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "终止失败");
    }
  }

  async function handleRerunConsolidation() {
    if (!activeRun) return;
    setError(null);
    try {
      const updated = await rerunConsolidation(activeRun.run_id);
      setActiveRun(updated);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "重新整合失败");
    }
  }

  async function handleRollback(hash: string) {
    if (!selectedRole) return;
    setError(null);
    try {
      await rollbackRole(selectedRole, hash);
      await loadRoleData(selectedRole);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "回滚失败");
    }
  }

  async function handleViewTrainingGames(runId: string) {
    setTrainingGamesLoading(true);
    setError(null);
    setTrainingGameRunId(runId);
    setViewingTrainingGameId(null);
    setTrainingEvents([]);
    setTrainingDecisions([]);
    setTrainingArchive(null);
    try {
      const games = await listRoleEvolutionTrainingGames(runId);
      setTrainingGameList(games);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载训练对局失败");
      setTrainingGameRunId(null);
      setTrainingGameList([]);
    } finally {
      setTrainingGamesLoading(false);
    }
  }

  async function handleViewTrainingGame(runId: string, gameId: string) {
    setTrainingDetailLoading(true);
    setViewingTrainingGameId(gameId);
    setTrainingEvents([]);
    setTrainingDecisions([]);
    setTrainingArchive(null);
    try {
      const [events, decisions, archive] = await Promise.all([
        getRoleEvolutionTrainingGameEvents(runId, gameId),
        getRoleEvolutionTrainingGameDecisions(runId, gameId),
        getRoleEvolutionTrainingGameArchive(runId, gameId).catch(() => null),
      ]);
      setTrainingEvents(events);
      setTrainingDecisions(decisions);
      setTrainingArchive(archive);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载训练对局详情失败");
      setViewingTrainingGameId(null);
    } finally {
      setTrainingDetailLoading(false);
    }
  }

  function handleBackToTrainingGames() {
    setViewingTrainingGameId(null);
    setTrainingEvents([]);
    setTrainingDecisions([]);
    setTrainingArchive(null);
  }

  function handleCloseTrainingGames() {
    setTrainingGameRunId(null);
    setTrainingGameList([]);
    handleBackToTrainingGames();
  }

  async function handleViewBattleGames(runId: string, side: "baseline" | "candidate") {
    setBattleGamesLoading(true);
    setBattleRunId(runId);
    setBattleSide(side);
    setViewingBattleGameId(null);
    setBattleEvents([]);
    setBattleDecisions([]);
    setBattleArchive(null);
    try {
      const games = await listBattleGames(runId, side);
      setBattleGameList(games);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载对战对局失败");
      setBattleRunId(null);
    } finally {
      setBattleGamesLoading(false);
    }
  }

  async function handleViewBattleGame(runId: string, side: string, gameId: string) {
    setBattleDetailLoading(true);
    setViewingBattleGameId(gameId);
    setBattleEvents([]);
    setBattleDecisions([]);
    setBattleArchive(null);
    try {
      const [events, decisions, archive] = await Promise.all([
        getBattleGameEvents(runId, side, gameId),
        getBattleGameDecisions(runId, side, gameId),
        getBattleGameArchive(runId, side, gameId).catch(() => null),
      ]);
      setBattleEvents(events);
      setBattleDecisions(decisions);
      setBattleArchive(archive);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载对战对局详情失败");
      setViewingBattleGameId(null);
    } finally {
      setBattleDetailLoading(false);
    }
  }

  function handleBackToBattleGames() {
    setViewingBattleGameId(null);
    setBattleEvents([]);
    setBattleDecisions([]);
    setBattleArchive(null);
  }

  function handleCloseBattleGames() {
    setBattleRunId(null);
    setBattleGameList([]);
    handleBackToBattleGames();
  }

  // Derive baseline info
  const baseline = versions.find((v) => v.is_baseline) ?? versions[0] ?? null;

  return (
    <div className="mx-auto max-w-7xl space-y-5 px-5 py-5">
      <h1 className="text-xl font-bold">角色演化</h1>

      {/* Role tabs */}
      <div className="flex flex-wrap items-center gap-2">
        {roles.map((role) => (
          <button
            key={role}
            className={
              role === selectedRole
                ? "rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
                : "rounded-md border border-border bg-card px-4 py-2 text-sm hover:bg-muted"
            }
            onClick={() => setSelectedRole(role)}
          >
            {ROLE_LABELS[role] ?? role}
          </button>
        ))}
        <Button
          variant="secondary"
          size="default"
          onClick={() => void loadRoleData(selectedRole)}
          disabled={loading || !selectedRole}
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          刷新
        </Button>
      </div>

      {error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {/* Current baseline info */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">当前 baseline</CardTitle>
        </CardHeader>
        <CardContent>
          {baseline ? (
            <div className="flex flex-wrap items-center gap-4 text-sm">
              <span>
                baseline:{" "}
                <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{baseline.hash.slice(0, 8)}</code>
              </span>
              <span className="text-muted-foreground">({formatTime(baseline.created_at)})</span>
              <span className="text-muted-foreground">历史版本: {versions.length} 个</span>
            </div>
          ) : (
            <span className="text-sm text-muted-foreground">暂无版本数据</span>
          )}
        </CardContent>
      </Card>

      {/* Start evolution form */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            <Rocket className="mr-1.5 inline-block h-4 w-4" />
            单角色演化
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="re-train">
                训练局数
              </label>
              <input
                id="re-train"
                type="number"
                min={1}
                value={trainingGames}
                onChange={(e) => setTrainingGames(Math.max(1, Number(e.target.value)))}
                className="w-28 rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="re-battle">
                对战局数
              </label>
              <input
                id="re-battle"
                type="number"
                min={1}
                value={battleGames}
                onChange={(e) => setBattleGames(Math.max(1, Number(e.target.value)))}
                className="w-28 rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <NumberField
              id="re-game-concurrency"
              label="局并发"
              min={1}
              value={gameConcurrency}
              onChange={setGameConcurrency}
            />
            <NumberField
              id="re-llm-concurrency"
              label="LLM并发"
              min={1}
              value={llmConcurrency}
              onChange={setLlmConcurrency}
            />
            <NumberField
              id="re-llm-rpm"
              label="LLM RPM"
              min={1}
              value={llmRpm}
              onChange={setLlmRpm}
            />
            <Button onClick={() => void handleStart()} disabled={starting || !selectedRole}>
              {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              开始自进化
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            <Layers3 className="mr-1.5 inline-block h-4 w-4" />
            批量演化
          </CardTitle>
          <Badge variant="secondary">{selectedBatchRoles.length} 个角色</Badge>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {roles.map((role) => {
              const selected = selectedBatchRoles.includes(role);
              return (
                <button
                  key={role}
                  type="button"
                  className={
                    selected
                      ? "rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
                      : "rounded-md border border-border bg-background px-3 py-2 text-sm hover:bg-muted"
                  }
                  onClick={() => toggleBatchRole(role)}
                >
                  {ROLE_LABELS[role] ?? role}
                </button>
              );
            })}
          </div>
          <div className="flex flex-wrap items-end gap-4">
            <NumberField
              id="re-role-concurrency"
              label="角色并发"
              min={1}
              value={roleConcurrency}
              onChange={setRoleConcurrency}
            />
            <NumberField
              id="re-batch-game-concurrency"
              label="局并发"
              min={1}
              value={gameConcurrency}
              onChange={setGameConcurrency}
            />
            <NumberField
              id="re-batch-llm-concurrency"
              label="LLM并发"
              min={1}
              value={llmConcurrency}
              onChange={setLlmConcurrency}
            />
            <NumberField
              id="re-batch-llm-rpm"
              label="LLM RPM"
              min={1}
              value={llmRpm}
              onChange={setLlmRpm}
            />
            <Button
              onClick={() => void handleStartBatch()}
              disabled={batchStarting || selectedBatchRoles.length === 0}
            >
              {batchStarting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              启动批量演化
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Active run progress */}
      {activeRun ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">进行中的演化</CardTitle>
            <Badge variant={runStatusVariant(activeRun.status)}>{runStatusLabel(activeRun.status)}</Badge>
          </CardHeader>
          <CardContent className="space-y-3">
            <StageProgress label="训练" current={activeRun.training_completed} total={activeRun.training_games} />
            <StageProgress label="对战" current={activeRun.battle_completed} total={activeRun.battle_games} />
            <div className="text-xs text-muted-foreground">
              当前阶段: {activeRun.current_stage}
              {activeRun.candidate_hash ? (
                <span>
                  {" "}
                  | 候选: <code className="rounded bg-muted px-1 text-xs">{activeRun.candidate_hash.slice(0, 8)}</code>
                </span>
              ) : null}
              {activeRun.training_run_id ? (
                <span>
                  {" "}
                  | 训练目录: <code className="rounded bg-muted px-1 text-xs">{activeRun.training_run_id}</code>
                </span>
              ) : null}
            </div>
            {activeRun.errors.length > 0 ? (
              <div className="text-xs text-destructive">{activeRun.errors.join("; ")}</div>
            ) : null}
            {activeRun.status === "rate_limited" && (activeRun.retry_total ?? 0) > 0 ? (
              <div className="flex items-center gap-2 text-xs text-amber-600">
                <Loader2 className="h-3 w-3 animate-spin" />
                限流重试中，第 {(activeRun.retry_attempt ?? 0) + 1}/{activeRun.retry_total} 次
              </div>
            ) : null}
            {pollExhausted ? (
              <div className="text-xs text-muted-foreground">实时更新已断开，请手动刷新页面</div>
            ) : null}
            <div className="flex gap-2 border-t border-border pt-3">
              <Button
                variant="secondary"
                onClick={() => void handleViewTrainingGames(activeRun.run_id)}
              >
                <FolderOpen className="h-4 w-4" />
                查看训练过程
                {activeRun.training_completed > 0 ? ` (${activeRun.training_completed}/${activeRun.training_games} 已完成)` : null}
              </Button>
              {activeRun.battle_completed > 0 ? (
                <>
                  <Button
                    variant="secondary"
                    onClick={() => void handleViewBattleGames(activeRun.run_id, "baseline")}
                  >
                    <FolderOpen className="h-4 w-4" />
                    基线对战
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => void handleViewBattleGames(activeRun.run_id, "candidate")}
                  >
                    <FolderOpen className="h-4 w-4" />
                    候选对战
                  </Button>
                </>
              ) : null}
              {activeRun.status !== "paused" && activeRun.status !== "failed" && !PROMOTED_STATUSES.has(activeRun.status) ? (
                <>
                  <Button variant="secondary" onClick={() => void handleStopEvolution()}>
                    <Pause className="h-4 w-4" />
                    暂停
                  </Button>
                  <Button variant="destructive" onClick={() => void handleTerminateEvolution()}>
                    <XCircle className="h-4 w-4" />
                    终止
                  </Button>
                </>
              ) : null}
              {activeRun.status === "paused" ? (
                <Button variant="default" onClick={() => void handleResumeEvolution()}>
                  <RotateCcw className="h-4 w-4" />
                  继续
                </Button>
              ) : null}
              {activeRun.status === "reviewing" && !activeRun.battle_result ? (
                <Button variant="default" onClick={() => void handleRerunConsolidation()}>
                  <RotateCcw className="h-4 w-4" />
                  重新整合
                </Button>
              ) : null}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {activeBatch ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">批量演化状态</CardTitle>
            <Badge variant={runStatusVariant(activeBatch.status)}>{runStatusLabel(activeBatch.status)}</Badge>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {activeBatch.roles.map((role) => {
                const roleRunId = activeBatch.role_run_ids[role];
                return (
                  <div key={role} className="rounded-md border border-border p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium">{ROLE_LABELS[role] ?? role}</span>
                      <Badge variant="secondary">
                        {runStatusLabel(activeBatch.role_statuses[role] ?? "queued")}
                      </Badge>
                    </div>
                    {activeBatch.role_candidates[role] ? (
                      <code className="mt-2 block text-xs text-muted-foreground">
                        {activeBatch.role_candidates[role]?.slice(0, 8)}
                      </code>
                    ) : null}
                    {roleRunId ? (
                      <Button
                        variant="ghost"
                        className="mt-2 h-8 px-2 text-xs"
                        onClick={() => void handleViewTrainingGames(roleRunId)}
                      >
                        <FolderOpen className="h-3.5 w-3.5" />
                        训练过程
                      </Button>
                    ) : null}
                  </div>
                );
              })}
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <MetricTile label="单角色通过" value={activeBatch.accepted_roles.length} />
              <MetricTile label="单角色拒绝" value={activeBatch.rejected_roles.length} />
              <MetricTile label="组合评估" value={activeBatch.combined_passed ? "通过" : "未通过"} />
            </div>

            {activeBatch.status === "reviewing" ? (
              <div className="flex flex-wrap gap-3 border-t border-border pt-3">
                <Button
                  onClick={() => void handlePromoteBatch()}
                  disabled={batchPromoting || !activeBatch.combined_passed}
                >
                  {batchPromoting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <CheckCircle className="h-4 w-4" />
                  )}
                  批量推广
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => void handleRejectBatch()}
                  disabled={batchRejecting}
                >
                  {batchRejecting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <XCircle className="h-4 w-4" />
                  )}
                  拒绝批量结果
                </Button>
              </div>
            ) : null}

            {activeBatch.status !== "reviewing" && activeBatch.status !== "promoted" && activeBatch.status !== "rejected" && activeBatch.status !== "failed" && activeBatch.status !== "paused" ? (
              <div className="flex flex-wrap gap-3 border-t border-border pt-3">
                <Button variant="secondary" onClick={() => void handleStopBatch()}>
                  <Pause className="h-4 w-4" />
                  暂停
                </Button>
                <Button variant="destructive" onClick={() => void handleTerminateBatch()}>
                  <XCircle className="h-4 w-4" />
                  终止
                </Button>
              </div>
            ) : null}

            {activeBatch.errors.length > 0 ? (
              <div className="text-xs text-destructive">{activeBatch.errors.join("; ")}</div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {trainingGameRunId ? (
        viewingTrainingGameId ? (
          <ArchivedGameDetail
            title="训练对局详情"
            gameId={viewingTrainingGameId}
            events={trainingEvents}
            decisions={trainingDecisions}
            archive={trainingArchive}
            loading={trainingDetailLoading}
            onBack={handleBackToTrainingGames}
          />
        ) : (
          <TrainingGameListPanel
            runId={trainingGameRunId}
            games={trainingGameList}
            loading={trainingGamesLoading}
            isRunning={activeRun?.status === "training"}
            onViewGame={handleViewTrainingGame}
            onClose={handleCloseTrainingGames}
          />
        )
      ) : null}

      {battleRunId ? (
        viewingBattleGameId ? (
          <ArchivedGameDetail
            title={`${battleSide === "baseline" ? "基线" : "候选"}对战详情`}
            gameId={viewingBattleGameId}
            events={battleEvents}
            decisions={battleDecisions}
            archive={battleArchive}
            loading={battleDetailLoading}
            onBack={handleBackToBattleGames}
          />
        ) : (
          <TrainingGameListPanel
            runId={battleRunId}
            games={battleGameList}
            loading={battleGamesLoading}
            isRunning={false}
            onViewGame={(runId, gameId) => handleViewBattleGame(runId, battleSide, gameId)}
            onClose={handleCloseBattleGames}
          />
        )
      ) : null}

      {/* Leaderboard */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            <Trophy className="mr-1.5 inline-block h-4 w-4" />
            排行榜
          </CardTitle>
          <Badge variant="secondary">{leaderboard.length} 个版本</Badge>
        </CardHeader>
        <CardContent>
          {loading && leaderboard.length === 0 ? (
            <div className="flex min-h-[200px] items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : leaderboard.length === 0 ? (
            <div className="flex min-h-[200px] items-center justify-center text-sm text-muted-foreground">
              暂无排行榜数据
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-border text-muted-foreground">
                    <th className="pb-3 pr-4 font-medium">哈希</th>
                    <th className="pb-3 pr-4 font-medium">基线</th>
                    <th className="pb-3 pr-4 font-medium">胜率</th>
                    <th className="pb-3 pr-4 font-medium">角色分</th>
                    <th className="pb-3 pr-4 font-medium">对战记录</th>
                    <th className="pb-3 pr-4 font-medium">推荐</th>
                    <th className="pb-3 font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {leaderboard.map((entry) => (
                    <tr
                      key={entry.hash}
                      className="border-b border-border/50 last:border-0 hover:bg-muted/30"
                    >
                      <td className="py-3 pr-4">
                        <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                          {entry.hash.slice(0, 8)}
                        </code>
                      </td>
                      <td className="py-3 pr-4">
                        {entry.is_baseline ? (
                          <Badge className="bg-amber-500 text-white">★</Badge>
                        ) : null}
                      </td>
                      <td className="py-3 pr-4">{pct(entry.target_side_win_rate)}</td>
                      <td className="py-3 pr-4 font-semibold">
                        {num(entry.target_role_role_weighted_score)}
                      </td>
                      <td className="py-3 pr-4">{entry.battle_record}</td>
                      <td className="py-3 pr-4">{recommendationBadge(entry.recommendation)}</td>
                      <td className="py-3">
                        {!entry.is_baseline ? (
                          <Button
                            variant="ghost"
                            size="default"
                            onClick={() => void handleRollback(entry.hash)}
                          >
                            回滚
                          </Button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Review panel — shown when run reaches "reviewing" status */}
      {activeRun && activeRun.status === "reviewing" ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              <GitBranch className="mr-1.5 inline-block h-4 w-4" />
              审查结果
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Diff summary */}
            {diff && diff.length > 0 ? (
              <div>
                <div className="mb-2 text-xs font-semibold text-muted-foreground">
                  变更清单: {diff.length} 个文件修改
                </div>
                <div className="space-y-2">
                  {diff.map((d, i) => (
                    <div key={i} className="rounded-md border border-border p-3 text-xs">
                      <div className="flex items-center gap-2 mb-2">
                        <Badge variant={diffActionVariant(d.action)}>{d.action}</Badge>
                        <code className="text-xs">{d.filename}</code>
                      </div>
                      {d.before && d.after ? (
                        <div className="space-y-2">
                          <div>
                            <div className="text-[10px] text-muted-foreground mb-1">修改前:</div>
                            <pre className="p-2 rounded bg-muted text-[10px] overflow-auto max-h-40">{d.before}</pre>
                          </div>
                          <div>
                            <div className="text-[10px] text-muted-foreground mb-1">修改后:</div>
                            <pre className="p-2 rounded bg-muted text-[10px] overflow-auto max-h-40">{d.after}</pre>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">暂无变更数据</div>
            )}

            {/* Battle result */}
            {activeRun.battle_result ? (
              <div className="text-sm">
                对战: {activeRun.battle_result.wins}W{activeRun.battle_result.losses}L (
                {pct(activeRun.battle_result.win_rate)})
              </div>
            ) : null}

            {/* Promote / Reject buttons */}
            <div className="flex gap-3 border-t border-border pt-3">
              <Button onClick={() => void handlePromote()} disabled={promoting}>
                {promoting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <CheckCircle className="h-4 w-4" />
                )}
                推广
              </Button>
              <Button variant="destructive" onClick={() => void handleReject()} disabled={rejecting}>
                {rejecting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <XCircle className="h-4 w-4" />
                )}
                拒绝
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StageProgress({ label, current, total }: { label: string; current: number; total: number }) {
  const pctVal = total > 0 ? Math.round((current / total) * 100) : 0;
  const done = current >= total;
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-semibold">
          {current}/{total}
        </span>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-muted">
        <div
          className={done ? "h-full rounded-full bg-emerald-500 transition-all" : "h-full rounded-full bg-primary animate-pulse transition-all"}
          style={{ width: `${pctVal}%` }}
        />
      </div>
    </div>
  );
}

function NumberField({
  id,
  label,
  min,
  value,
  onChange,
}: {
  id: string;
  label: string;
  min: number;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        type="number"
        min={min}
        value={value}
        onChange={(e) => onChange(Math.max(min, Number(e.target.value)))}
        className="w-28 rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
    </div>
  );
}

function MetricTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-border bg-background p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

function TrainingGameListPanel({
  runId,
  games,
  loading,
  isRunning,
  onViewGame,
  onClose,
}: {
  runId: string;
  games: SelfplayGameSummary[];
  loading: boolean;
  isRunning: boolean;
  onViewGame: (runId: string, gameId: string) => void;
  onClose: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={onClose}>
            关闭
          </Button>
          <CardTitle className="text-base">训练对局</CardTitle>
          <Badge variant="secondary">{games.length}</Badge>
          {isRunning && (
            <Badge variant="outline" className="gap-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              训练中
            </Badge>
          )}
        </div>
        <code className="text-xs text-muted-foreground">{runId}</code>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex min-h-[180px] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : games.length === 0 ? (
          <div className="flex min-h-[180px] items-center justify-center text-sm text-muted-foreground">
            暂无已完成训练局
          </div>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {games.map((game) => (
              <div key={game.game_id} className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <code className="text-xs text-muted-foreground">{game.game_id}</code>
                    {game.in_progress ? (
                      <Badge variant="outline" className="gap-1 text-xs">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        进行中
                      </Badge>
                    ) : game.winner ? (
                      <Badge>{game.winner}</Badge>
                    ) : (
                      <Badge variant="secondary">无结果</Badge>
                    )}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    Day {game.day ?? 0} · {game.phase || "-"} · {game.event_count ?? 0} 事件
                  </div>
                </div>
                <Button variant="ghost" onClick={() => onViewGame(runId, game.game_id)}>
                  <FolderOpen className="h-4 w-4" />
                  查看
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function recommendationBadge(rec: string) {
  if (rec === "promote") return <Badge className="bg-emerald-500 text-white">建议推广</Badge>;
  if (rec === "caution") return <Badge variant="secondary">谨慎推广</Badge>;
  return <Badge variant="destructive">建议拒绝</Badge>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function runStatusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "promoted") return "default";
  if (status === "failed") return "destructive";
  if (status === "rejected") return "destructive";
  if (status === "reviewing") return "outline";
  return "secondary";
}

function runStatusLabel(status: string): string {
  if (status === "pending") return "等待中";
  if (status === "training") return "训练中";
  if (status === "consolidating") return "整合中";
  if (status === "applying") return "应用中";
  if (status === "merging") return "合并中";
  if (status === "battling") return "对战中";
  if (status === "combined_battling") return "组合对战";
  if (status === "reviewing") return "审查中";
  if (status === "promoted") return "已推广";
  if (status === "rejected") return "已拒绝";
  if (status === "failed") return "失败";
  if (status === "paused") return "已暂停";
  if (status === "rate_limited") return "限流重试中";
  return status;
}

function diffActionVariant(action: string): "default" | "secondary" | "destructive" | "outline" {
  if (action === "add") return "default";
  if (action === "delete") return "destructive";
  if (action === "modify") return "outline";
  return "secondary";
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
  } catch {
    return iso;
  }
}

function pct(value: number): string {
  return `${(Number.isFinite(value) ? value * 100 : 0).toFixed(0)}%`;
}

function num(value: unknown, digits = 1): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : (0).toFixed(digits);
}
