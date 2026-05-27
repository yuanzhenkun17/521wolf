import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Clock,
  FolderOpen,
  Gamepad2,
  Loader2,
  Play,
  RefreshCw,
  XCircle,
  Zap,
} from "lucide-react";
import {
  getSelfplayRun,
  listSelfplayRuns,
  startSelfplayRun,
  type SelfplayConfig,
  type SelfplayRun,
} from "../api";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";

export function SelfplayPage() {
  const [runs, setRuns] = useState<SelfplayRun[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<SelfplayRun | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

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

  async function handleSelect(runId: string) {
    setSelectedId(runId);
    try {
      const run = await getSelfplayRun(runId);
      setSelectedRun(run);
    } catch {
      setSelectedRun(null);
    }
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
        <SelfplayForm onSubmit={handleStart} onCancel={() => setShowForm(false)} starting={starting} />
      ) : null}

      {/* Main area */}
      <div className="grid gap-5 lg:grid-cols-[1fr_380px]">
        <RunList
          runs={runs}
          selectedId={selectedId}
          loading={loading}
          onSelect={handleSelect}
        />
        <RunDetailPanel run={selectedRun} />
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
                placeholder="留空使用默认"
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

function RunDetailPanel({ run }: { run: SelfplayRun | null }) {
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
