import { useCallback, useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  Clock,
  FolderOpen,
  Gamepad2,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  XCircle,
  Zap,
} from "lucide-react";
import {
  getSelfplayGameEvents,
  getSelfplayGameDecisions,
  getSelfplayGameArchive,
  getSelfplayRun,
  listSelfplayGames,
  listSelfplayRuns,
  startSelfplayRun,
  stopSelfplayRun,
  resumeSelfplayRun,
  terminateSelfplayRun,
  type GameArchive,
  type SelfplayConfig,
  type SelfplayGameSummary,
  type SelfplayRun,
} from "../api";
import { ArchivedGameDetail } from "../components/ArchivedGameDetail";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";

export function SelfplayPage() {
  const [runs, setRuns] = useState<SelfplayRun[]>([]);
  // versions removed — old versioning system deleted
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<SelfplayRun | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Game viewing state
  const [viewingRunId, setViewingRunId] = useState<string | null>(null);
  const [gameList, setGameList] = useState<SelfplayGameSummary[]>([]);
  const [viewingGameId, setViewingGameId] = useState<string | null>(null);
  const [gameEvents, setGameEvents] = useState<Record<string, unknown>[]>([]);
  const [gameDecisions, setGameDecisions] = useState<Record<string, unknown>[]>([]);
  const [gameArchive, setGameArchive] = useState<GameArchive | null>(null);
  const [gamesLoading, setGamesLoading] = useState(false);
  const [eventsLoading, setEventsLoading] = useState(false);

  const loadRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listSelfplayRuns();
      setRuns(data);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRuns();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [loadRuns]);

  // Request notification permission on mount
  useEffect(() => {
    if ("Notification" in window && Notification.permission === "default") {
      void Notification.requestPermission();
    }
  }, []);

  // Notify when training completes or fails
  useEffect(() => {
    if (!selectedRun) return;
    if (selectedRun.status === "completed") {
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification("自对弈训练完成", {
          body: `${selectedRun.label || selectedRun.run_id.slice(0, 8)} 已完成`,
        });
      }
    } else if (selectedRun.status === "failed") {
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification("自对弈训练失败", {
          body: `${selectedRun.label || selectedRun.run_id.slice(0, 8)}: ${selectedRun.error || "未知错误"}`,
        });
      }
    }
  }, [selectedRun?.status]);

  // Poll the selected run while it's running
  useEffect(() => {
    if (!selectedId) return;
    if (pollRef.current) clearInterval(pollRef.current);

    async function poll() {
      if (!selectedId) return;
      try {
        const run = await getSelfplayRun(selectedId);
        setSelectedRun(run);
        // Refresh the list entry too
        setRuns((prev) =>
          prev.map((r) => (r.run_id === run.run_id ? run : r))
        );
        if (run.status !== "running" && run.status !== "pending") {
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch {
        // ignore polling errors
      }
    }

    void poll();
    pollRef.current = setInterval(poll, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [selectedId]);

  // Auto-refresh game list while training is running
  const gameListPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (!viewingRunId) return;
    const run = runs.find((r) => r.run_id === viewingRunId);
    if (!run || run.status !== "running") return;

    gameListPollRef.current = setInterval(async () => {
      try {
        const games = await listSelfplayGames(viewingRunId);
        setGameList(games);
      } catch {
        // ignore polling errors
      }
    }, 5000);
    return () => {
      if (gameListPollRef.current) clearInterval(gameListPollRef.current);
    };
  }, [viewingRunId, runs]);

  async function handleSelect(runId: string) {
    setSelectedId(runId);
    setViewingRunId(null);
    setViewingGameId(null);
    try {
      const run = await getSelfplayRun(runId);
      setSelectedRun(run);
    } catch {
      setSelectedRun(null);
    }
  }

  async function handleViewGames(runId: string) {
    setGamesLoading(true);
    setViewingRunId(runId);
    setViewingGameId(null);
    setGameEvents([]);
    setGameDecisions([]);
    setGameArchive(null);
    try {
      const games = await listSelfplayGames(runId);
      setGameList(games);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载对局列表失败");
      setViewingRunId(null);
    } finally {
      setGamesLoading(false);
    }
  }

  async function handleViewGame(runId: string, gameId: string) {
    setEventsLoading(true);
    setViewingGameId(gameId);
    setGameEvents([]);
    setGameDecisions([]);
    setGameArchive(null);
    try {
      const [events, decisions, archive] = await Promise.all([
        getSelfplayGameEvents(runId, gameId),
        getSelfplayGameDecisions(runId, gameId),
        getSelfplayGameArchive(runId, gameId).catch(() => null),
      ]);
      setGameEvents(events);
      setGameDecisions(decisions);
      setGameArchive(archive);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载对局事件失败");
      setViewingGameId(null);
    } finally {
      setEventsLoading(false);
    }
  }

  function handleBackToGames() {
    setViewingGameId(null);
    setGameEvents([]);
    setGameDecisions([]);
    setGameArchive(null);
  }

  function handleBackToRunDetail() {
    setViewingRunId(null);
    setViewingGameId(null);
    setGameList([]);
    setGameEvents([]);
    setGameDecisions([]);
    setGameArchive(null);
  }

  async function handleStart(config: SelfplayConfig) {
    setStarting(true);
    setError(null);
    try {
      const run = await startSelfplayRun(config);
      setRuns((prev) => [run, ...prev]);
      setSelectedId(run.run_id);
      setSelectedRun(run);
      setShowForm(false);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "启动失败");
    } finally {
      setStarting(false);
    }
  }

  async function handleStop(runId: string) {
    try {
      const run = await stopSelfplayRun(runId);
      setSelectedRun(run);
      setRuns((prev) => prev.map((r) => (r.run_id === run.run_id ? run : r)));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "暂停失败");
    }
  }

  async function handleResume(runId: string) {
    try {
      const run = await resumeSelfplayRun(runId);
      setSelectedRun(run);
      setRuns((prev) => prev.map((r) => (r.run_id === run.run_id ? run : r)));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "恢复失败");
    }
  }

  async function handleTerminate(runId: string) {
    if (!confirm("终止会永久删除该任务的所有数据，确定要终止吗？")) return;
    try {
      const run = await terminateSelfplayRun(runId);
      setSelectedRun(run);
      setRuns((prev) => prev.map((r) => (r.run_id === run.run_id ? run : r)));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "终止失败");
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-5 px-5 py-5">
      {/* Toolbar */}
      <div className="flex items-center gap-3">
        <Button onClick={() => setShowForm(true)} disabled={showForm}>
          <Play className="h-4 w-4" />
          新建自对弈
        </Button>
        <Button variant="secondary" onClick={() => void loadRuns()} disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          刷新
        </Button>
      </div>

      {error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {/* New run form */}
      {showForm ? (
        <SelfplayForm
          onSubmit={handleStart}
          onCancel={() => setShowForm(false)}
          starting={starting}
        />
      ) : null}

      {/* Main area */}
      <div className={viewingGameId ? "grid gap-5 lg:grid-cols-[300px_1fr]" : "grid gap-5 lg:grid-cols-[1fr_380px]"}>
        <RunList
          runs={runs}
          selectedId={selectedId}
          loading={loading}
          onSelect={handleSelect}
        />
        {viewingGameId ? (
          <ArchivedGameDetail
            title="自对弈对局详情"
            gameId={viewingGameId}
            events={gameEvents}
            decisions={gameDecisions}
            archive={gameArchive}
            loading={eventsLoading}
            onBack={handleBackToGames}
          />
        ) : viewingRunId ? (
          <GameListPanel
            runId={viewingRunId}
            games={gameList}
            loading={gamesLoading}
            isRunning={runs.find((r) => r.run_id === viewingRunId)?.status === "running"}
            onViewGame={handleViewGame}
            onBack={handleBackToRunDetail}
          />
        ) : (
          <RunDetailPanel run={selectedRun} onViewGames={handleViewGames} onStop={handleStop} onResume={handleResume} onTerminate={handleTerminate} />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Selfplay creation form
// ---------------------------------------------------------------------------

function SelfplayForm({
  onSubmit,
  onCancel,
  starting,
}: {
  onSubmit: (config: SelfplayConfig) => void;
  onCancel: () => void;
  starting: boolean;
}) {
  const [numGames, setNumGames] = useState(10);
  const [maxDays, setMaxDays] = useState(20);
  const [enableSheriff, setEnableSheriff] = useState(true);
  const [enableBatchDream, setEnableBatchDream] = useState(false);
  const [skillDir, setSkillDir] = useState("");
  const [label, setLabel] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const config: SelfplayConfig = { num_games: numGames };
    if (maxDays !== 20) config.max_days = maxDays;
    if (!enableSheriff) config.enable_sheriff = false;
    if (enableBatchDream) config.enable_batch_dream = true;
    if (skillDir.trim()) config.skill_dir = skillDir.trim();
    if (label.trim()) config.label = label.trim();
    onSubmit(config);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>新建自对弈任务</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            {/* num_games */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="sp-num-games">
                对局数量
              </label>
              <input
                id="sp-num-games"
                type="number"
                min={1}
                max={1000}
                value={numGames}
                onChange={(e) => setNumGames(Number(e.target.value))}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>

            {/* max_days */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="sp-max-days">
                最大天数
              </label>
              <input
                id="sp-max-days"
                type="number"
                min={1}
                max={100}
                value={maxDays}
                onChange={(e) => setMaxDays(Number(e.target.value))}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>

            {/* skill_dir */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="sp-skill-dir">
                技能目录
                <span className="ml-1 text-xs font-normal text-muted-foreground">(可选)</span>
              </label>
              <input
                id="sp-skill-dir"
                type="text"
                value={skillDir}
                onChange={(e) => setSkillDir(e.target.value)}
                placeholder="留空使用默认 skills"
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>

            {/* label */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="sp-label">
                标签
                <span className="ml-1 text-xs font-normal text-muted-foreground">(可选)</span>
              </label>
              <input
                id="sp-label"
                type="text"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="给本次运行取个名字"
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
          </div>

          {/* Checkboxes */}
          <div className="flex flex-wrap gap-6">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={enableSheriff}
                onChange={(e) => setEnableSheriff(e.target.checked)}
                className="h-4 w-4 rounded border-border"
              />
              启用警长模式
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={enableBatchDream}
                onChange={(e) => setEnableBatchDream(e.target.checked)}
                className="h-4 w-4 rounded border-border"
              />
              启用批量梦境
            </label>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-3 border-t border-border pt-3">
            <Button type="button" variant="secondary" onClick={onCancel} disabled={starting}>
              取消
            </Button>
            <Button type="submit" disabled={starting}>
              {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
              启动
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Run list
// ---------------------------------------------------------------------------

function RunList({
  runs,
  selectedId,
  loading,
  onSelect,
}: {
  runs: SelfplayRun[];
  selectedId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
}) {
  if (loading && runs.length === 0) {
    return (
      <Card>
        <CardContent className="flex min-h-[300px] items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (runs.length === 0) {
    return (
      <Card>
        <CardContent className="flex min-h-[300px] flex-col items-center justify-center gap-3">
          <Gamepad2 className="h-10 w-10 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">暂无自对弈任务，点击上方按钮创建。</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>自对弈任务</CardTitle>
        <Badge variant="secondary">{runs.length}</Badge>
      </CardHeader>
      <CardContent className="space-y-2">
        {runs.map((run) => (
          <button
            key={run.run_id}
            className={
              run.run_id === selectedId
                ? "flex w-full items-center justify-between rounded-md border border-primary/40 bg-primary/5 px-3 py-3 text-left text-sm transition-colors"
                : "flex w-full items-center justify-between rounded-md border border-border px-3 py-3 text-left text-sm transition-colors hover:bg-muted"
            }
            onClick={() => onSelect(run.run_id)}
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <RunStatusIcon status={run.status} />
                <span className="font-medium">{run.label || run.run_id.slice(0, 8)}</span>
                <Badge variant={runStatusVariant(run.status)}>{runStatusLabel(run.status)}</Badge>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {run.completed_games}/{run.num_games} 局
                {run.created_at ? ` · ${formatTime(run.created_at)}` : null}
              </div>
            </div>
            {/* Progress bar mini */}
            <div className="ml-3 flex w-24 items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  className={progressBarClass(run.status)}
                  style={{ width: `${progressPct(run)}%` }}
                />
              </div>
              <span className="text-xs text-muted-foreground">{progressPct(run)}%</span>
            </div>
          </button>
        ))}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Run detail panel
// ---------------------------------------------------------------------------

function RunDetailPanel({
  run,
  onViewGames,
  onStop,
  onResume,
  onTerminate,
}: {
  run: SelfplayRun | null;
  onViewGames: (runId: string) => void;
  onStop: (runId: string) => void;
  onResume: (runId: string) => void;
  onTerminate: (runId: string) => void;
}) {
  if (!run) {
    return (
      <Card>
        <CardContent className="flex min-h-[300px] items-center justify-center text-sm text-muted-foreground">
          选择一个任务查看详情
        </CardContent>
      </Card>
    );
  }

  const results = run.results ?? {};
  const resultEntries = Object.entries(results);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{run.label || run.run_id.slice(0, 8)}</CardTitle>
        <Badge variant={runStatusVariant(run.status)}>{runStatusLabel(run.status)}</Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Progress */}
        <div>
          <div className="mb-2 flex items-center justify-between text-sm">
            <span className="text-muted-foreground">进度</span>
            <span className="font-semibold">
              {run.completed_games} / {run.num_games} 局
            </span>
          </div>
          <div className="h-3 overflow-hidden rounded-full bg-muted">
            <div
              className={progressBarClass(run.status)}
              style={{ width: `${progressPct(run)}%` }}
            />
          </div>
          <div className="mt-1 text-right text-xs text-muted-foreground">{progressPct(run)}%</div>
        </div>

        {/* Config info */}
        <div className="grid grid-cols-2 gap-2 text-xs">
          <InfoCell label="任务 ID" value={run.run_id} />
          <InfoCell label="状态" value={runStatusLabel(run.status)} />
          <InfoCell label="对局数量" value={String(run.num_games)} />
          <InfoCell label="最大天数" value={run.max_days != null ? String(run.max_days) : "-"} />
          <InfoCell label="Agent版本" value={run.agent_version || "-"} />
          <InfoCell label="技能目录" value={run.skill_dir || "-"} />
          <InfoCell label="警长模式" value={run.enable_sheriff ? "是" : "否"} />
          <InfoCell label="批量梦境" value={run.enable_batch_dream ? "是" : "否"} />
          <InfoCell label="创建时间" value={formatTime(run.created_at)} />
        </div>

        {/* Error */}
        {run.error ? (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            {run.error}
          </div>
        ) : null}

        {/* Retry status */}
        {run.status === "rate_limited" && (run.retry_total ?? 0) > 0 ? (
          <div className="flex items-center gap-2 text-xs text-amber-600">
            <Loader2 className="h-3 w-3 animate-spin" />
            限流重试中，第 {(run.retry_attempt ?? 0) + 1}/{run.retry_total} 次
          </div>
        ) : null}

        {/* Results */}
        {resultEntries.length > 0 ? (
          <div>
            <div className="mb-2 text-xs font-semibold text-muted-foreground">结果概览</div>
            <div className="grid grid-cols-2 gap-2">
              {resultEntries.map(([key, value]) => (
                <div key={key} className="rounded-md border border-border p-2 text-xs">
                  <div className="text-muted-foreground">{key}</div>
                  <div className="mt-0.5 font-semibold">{formatResult(value)}</div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {/* View games button — available during and after training */}
        {run.status === "completed" || run.status === "running" || run.status === "paused" ? (
          <Button variant="secondary" className="w-full" onClick={() => onViewGames(run.run_id)}>
            <FolderOpen className="h-4 w-4" />
            查看对局列表
            {run.status === "running" ? ` (${run.completed_games}/${run.num_games} 已完成)` : null}
          </Button>
        ) : null}

        {/* Stop / Resume / Terminate buttons */}
        <div className="flex gap-2">
          {run.status === "running" ? (
            <>
              <Button variant="secondary" className="flex-1" onClick={() => onStop(run.run_id)}>
                <Pause className="h-4 w-4" />
                暂停
              </Button>
              <Button variant="destructive" className="flex-1" onClick={() => onTerminate(run.run_id)}>
                <XCircle className="h-4 w-4" />
                终止
              </Button>
            </>
          ) : null}
          {run.status === "paused" ? (
            <Button variant="default" className="flex-1" onClick={() => onResume(run.run_id)}>
              <RotateCcw className="h-4 w-4" />
              继续
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Game list panel
// ---------------------------------------------------------------------------

function GameListPanel({
  runId,
  games,
  loading,
  isRunning,
  onViewGame,
  onBack,
}: {
  runId: string;
  games: SelfplayGameSummary[];
  loading: boolean;
  isRunning: boolean;
  onViewGame: (runId: string, gameId: string) => void;
  onBack: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={onBack}>
            ← 返回
          </Button>
          <CardTitle>对局列表</CardTitle>
          <Badge variant="secondary">{games.length}</Badge>
          {isRunning && (
            <Badge variant="outline" className="gap-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              训练中
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex min-h-[200px] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : games.length === 0 ? (
          <div className="flex min-h-[200px] items-center justify-center text-sm text-muted-foreground">
            暂无对局数据
          </div>
        ) : (
          <div className="max-h-[500px] space-y-2 overflow-y-auto">
            {games.map((g) => (
              <div
                key={g.game_id}
                className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm transition-colors hover:bg-muted"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-muted-foreground">
                      {g.game_id.slice(0, 8)}
                    </span>
                    {g.in_progress ? (
                      <Badge variant="outline" className="gap-1 text-xs">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        进行中
                      </Badge>
                    ) : g.winner ? (
                      <Badge variant="default" className="text-xs">
                        {g.winner}
                      </Badge>
                    ) : (
                      <Badge variant="secondary" className="text-xs">
                        无结果
                      </Badge>
                    )}
                  </div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    Day {g.day} · {g.phase} · {g.event_count} 事件
                  </div>
                </div>
                <Button variant="ghost" onClick={() => onViewGame(runId, g.game_id)}>
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function InfoCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border p-2">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className="mt-0.5 truncate text-sm font-medium">{value}</div>
    </div>
  );
}

function RunStatusIcon({ status }: { status: SelfplayRun["status"] }) {
  if (status === "completed") return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
  if (status === "failed") return <XCircle className="h-4 w-4 text-destructive" />;
  if (status === "running") return <Loader2 className="h-4 w-4 animate-spin text-primary" />;
  if (status === "paused") return <Pause className="h-4 w-4 text-amber-500" />;
  return <Clock className="h-4 w-4 text-muted-foreground" />;
}

function runStatusVariant(status: SelfplayRun["status"]): "default" | "secondary" | "destructive" | "outline" {
  if (status === "completed") return "default";
  if (status === "failed") return "destructive";
  if (status === "running") return "outline";
  return "secondary";
}

function runStatusLabel(status: SelfplayRun["status"]): string {
  if (status === "pending") return "等待中";
  if (status === "running") return "运行中";
  if (status === "paused") return "已暂停";
  if (status === "rate_limited") return "限流重试中";
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  return status;
}

function progressPct(run: SelfplayRun): number {
  if (run.num_games === 0) return 0;
  return Math.round((run.completed_games / run.num_games) * 100);
}

function progressBarClass(status: SelfplayRun["status"]): string {
  const base = "h-full rounded-full transition-all duration-500";
  if (status === "completed") return `${base} bg-emerald-500`;
  if (status === "failed") return `${base} bg-destructive`;
  if (status === "running") return `${base} bg-primary animate-pulse`;
  if (status === "paused") return `${base} bg-amber-500`;
  return `${base} bg-muted-foreground/30`;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function formatResult(value: unknown): string {
  if (typeof value === "number") return value.toFixed(2);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value ?? "-");
}
