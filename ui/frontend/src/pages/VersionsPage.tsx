import { useCallback, useEffect, useState } from "react";
import {
  Award,
  BarChart3,
  ChevronRight,
  GitBranch,
  Loader2,
  Rocket,
  Trophy,
} from "lucide-react";
import {
  createVersion,
  listMixedBattles,
  listEvolutionRuns,
  getVersionDetail,
  getVersionLeaderboard,
  listVersions,
  promoteVersion,
  startMixedBattle,
  startEvolutionRun,
  type EvolutionConfig,
  type EvolutionRun,
  type MixedBattleConfig,
  type MixedBattleRun,
  type PromoteResult,
  type VersionDetail,
  type VersionLeaderboardEntry,
  type VersionManifest,
} from "../api";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";

const ROLE_OPTIONS = [
  { value: "", label: "全部" },
  { value: "seer", label: "预言家" },
  { value: "witch", label: "女巫" },
  { value: "guard", label: "守卫" },
  { value: "hunter", label: "猎人" },
  { value: "werewolf", label: "狼人" },
  { value: "villager", label: "村民" },
  { value: "white_wolf_king", label: "白狼王" },
];

export function VersionsPage() {
  const [versions, setVersions] = useState<VersionManifest[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<VersionDetail | null>(null);
  const [leaderboard, setLeaderboard] = useState<VersionLeaderboardEntry[]>([]);
  const [evolutionRuns, setEvolutionRuns] = useState<EvolutionRun[]>([]);
  const [mixedRuns, setMixedRuns] = useState<MixedBattleRun[]>([]);
  const [tab, setTab] = useState<"list" | "leaderboard" | "evolution" | "mixed">("list");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [promoting, setPromoting] = useState<string | null>(null);
  const [promoteResult, setPromoteResult] = useState<PromoteResult | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [creating, setCreating] = useState(false);
  const [evolving, setEvolving] = useState(false);
  const [mixing, setMixing] = useState(false);

  const loadVersions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listVersions();
      setVersions(data);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadLeaderboard = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getVersionLeaderboard();
      setLeaderboard(data);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadEvolutionRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listEvolutionRuns();
      setEvolutionRuns(data);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadMixedRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listMixedBattles();
      setMixedRuns(data);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadVersions();
  }, [loadVersions]);

  async function handleSelect(versionId: string) {
    setSelectedId(versionId);
    setPromoteResult(null);
    try {
      const data = await getVersionDetail(versionId);
      setDetail(data);
    } catch {
      setDetail(null);
    }
  }

  async function handlePromote(versionId: string) {
    setPromoting(versionId);
    setPromoteResult(null);
    try {
      const result = await promoteVersion(versionId);
      setPromoteResult(result);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "晋升失败");
    } finally {
      setPromoting(null);
    }
  }

  async function handleCreate(config: {
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
  }) {
    setCreating(true);
    setError(null);
    try {
      await createVersion(config);
      setShowCreateForm(false);
      void loadVersions();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "创建失败");
    } finally {
      setCreating(false);
    }
  }

  async function handleStartEvolution(config: EvolutionConfig) {
    setEvolving(true);
    setError(null);
    try {
      await startEvolutionRun(config);
      await loadEvolutionRuns();
      void loadVersions();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "自进化启动失败");
    } finally {
      setEvolving(false);
    }
  }

  async function handleStartMixedBattle(config: MixedBattleConfig) {
    setMixing(true);
    setError(null);
    try {
      await startMixedBattle(config);
      await loadMixedRuns();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "混编对战启动失败");
    } finally {
      setMixing(false);
    }
  }

  function handleTabChange(t: "list" | "leaderboard" | "evolution" | "mixed") {
    setTab(t);
    if (t === "leaderboard" && leaderboard.length === 0) {
      void loadLeaderboard();
    }
    if (t === "evolution" && evolutionRuns.length === 0) {
      void loadEvolutionRuns();
    }
    if (t === "mixed" && mixedRuns.length === 0) {
      void loadMixedRuns();
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-5 px-5 py-5">
      {/* Tab bar */}
      <div className="flex items-center gap-2">
        <button
          className={
            tab === "list"
              ? "rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
              : "rounded-md border border-border bg-card px-4 py-2 text-sm hover:bg-muted"
          }
          onClick={() => handleTabChange("list")}
        >
          <GitBranch className="mr-1.5 inline-block h-4 w-4" />
          版本列表
        </button>
        <button
          className={
            tab === "leaderboard"
              ? "rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
              : "rounded-md border border-border bg-card px-4 py-2 text-sm hover:bg-muted"
          }
          onClick={() => handleTabChange("leaderboard")}
        >
          <Trophy className="mr-1.5 inline-block h-4 w-4" />
          排行榜
        </button>
        <button
          className={
            tab === "evolution"
              ? "rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
              : "rounded-md border border-border bg-card px-4 py-2 text-sm hover:bg-muted"
          }
          onClick={() => handleTabChange("evolution")}
        >
          <Rocket className="mr-1.5 inline-block h-4 w-4" />
          自进化
        </button>
        <button
          className={
            tab === "mixed"
              ? "rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
              : "rounded-md border border-border bg-card px-4 py-2 text-sm hover:bg-muted"
          }
          onClick={() => handleTabChange("mixed")}
        >
          <GitBranch className="mr-1.5 inline-block h-4 w-4" />
          混编对战
        </button>
        {tab === "list" ? (
          <>
            <Button onClick={() => setShowCreateForm(true)} disabled={showCreateForm}>
              <GitBranch className="h-4 w-4" />
              新建版本
            </Button>
            <Button variant="secondary" size="default" onClick={() => void loadVersions()} disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              刷新
            </Button>
          </>
        ) : tab === "leaderboard" ? (
          <Button variant="secondary" size="default" onClick={() => void loadLeaderboard()} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            刷新
          </Button>
        ) : tab === "evolution" ? (
          <Button variant="secondary" size="default" onClick={() => void loadEvolutionRuns()} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            刷新
          </Button>
        ) : (
          <Button variant="secondary" size="default" onClick={() => void loadMixedRuns()} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            刷新
          </Button>
        )}
      </div>

      {error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {showCreateForm ? (
        <CreateVersionForm
          versions={versions}
          creating={creating}
          onSubmit={handleCreate}
          onCancel={() => setShowCreateForm(false)}
        />
      ) : null}

      {tab === "leaderboard" ? (
        <LeaderboardTable entries={leaderboard} loading={loading} />
      ) : tab === "evolution" ? (
        <EvolutionPanel
          versions={versions}
          runs={evolutionRuns}
          loading={loading}
          evolving={evolving}
          onSubmit={handleStartEvolution}
        />
      ) : tab === "mixed" ? (
        <MixedBattlePanel
          versions={versions}
          runs={mixedRuns}
          loading={loading}
          mixing={mixing}
          onSubmit={handleStartMixedBattle}
        />
      ) : (
        <div className="grid gap-5 lg:grid-cols-[1fr_380px]">
          <VersionList
            versions={versions}
            selectedId={selectedId}
            loading={loading}
            onSelect={handleSelect}
          />
          <VersionDetailPanel
            detail={detail}
            promoting={promoting}
            promoteResult={promoteResult}
            onPromote={handlePromote}
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function VersionList({
  versions,
  selectedId,
  loading,
  onSelect,
}: {
  versions: VersionManifest[];
  selectedId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
}) {
  if (loading && versions.length === 0) {
    return (
      <Card>
        <CardContent className="flex min-h-[300px] items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (versions.length === 0) {
    return (
      <Card>
        <CardContent className="flex min-h-[300px] items-center justify-center text-sm text-muted-foreground">
          暂无版本数据
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>版本清单</CardTitle>
        <Badge variant="secondary">{versions.length}</Badge>
      </CardHeader>
      <CardContent className="space-y-2">
        {versions.map((v) => (
          <button
            key={v.version_id}
            className={
              v.version_id === selectedId
                ? "flex w-full items-center justify-between rounded-md border border-primary/40 bg-primary/5 px-3 py-3 text-left text-sm transition-colors"
                : "flex w-full items-center justify-between rounded-md border border-border px-3 py-3 text-left text-sm transition-colors hover:bg-muted"
            }
            onClick={() => onSelect(v.version_id)}
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium">{v.label}</span>
                <Badge variant={statusVariant(v.status)}>{statusLabel(v.status)}</Badge>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {v.skill_dir ? `技能: ${v.skill_dir}` : null}
                {v.created_at ? ` · ${formatTime(v.created_at)}` : null}
              </div>
              {v.description ? (
                <p className="mt-1 truncate text-xs text-muted-foreground">{v.description}</p>
              ) : null}
            </div>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          </button>
        ))}
      </CardContent>
    </Card>
  );
}

function VersionDetailPanel({
  detail,
  promoting,
  promoteResult,
  onPromote,
}: {
  detail: VersionDetail | null;
  promoting: string | null;
  promoteResult: PromoteResult | null;
  onPromote: (id: string) => void;
}) {
  if (!detail) {
    return (
      <Card>
        <CardContent className="flex min-h-[300px] items-center justify-center text-sm text-muted-foreground">
          选择一个版本查看详情
        </CardContent>
      </Card>
    );
  }

  const metrics = detail.metrics ?? {};
  const config = detail.config ?? {};

  return (
    <Card>
      <CardHeader>
        <CardTitle>{detail.label}</CardTitle>
        <Badge variant={statusVariant(detail.status)}>{statusLabel(detail.status)}</Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Basic info */}
        <div className="grid grid-cols-2 gap-2 text-xs">
          <InfoCell label="版本 ID" value={detail.version_id} />
          <InfoCell label="技能目录" value={detail.skill_dir || "-"} />
          <InfoCell label="创建时间" value={formatTime(detail.created_at)} />
          <InfoCell label="状态" value={statusLabel(detail.status)} />
        </div>

        {/* Config */}
        {Object.keys(config).length > 0 ? (
          <div>
            <div className="mb-2 text-xs font-semibold text-muted-foreground">配置参数</div>
            <div className="rounded-md border border-border bg-muted/30 p-3">
              <pre className="overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">
                {JSON.stringify(config, null, 2)}
              </pre>
            </div>
          </div>
        ) : null}

        {/* Metrics summary */}
        {Object.keys(metrics).length > 0 ? (
          <div>
            <div className="mb-2 text-xs font-semibold text-muted-foreground">指标概览</div>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(metrics).map(([key, value]) => (
                <div key={key} className="rounded-md border border-border p-2 text-xs">
                  <div className="text-muted-foreground">{key}</div>
                  <div className="mt-0.5 font-semibold">{formatMetric(value)}</div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {/* Promote button */}
        <div className="flex items-center gap-3 border-t border-border pt-3">
          <Button
            onClick={() => onPromote(detail.version_id)}
            disabled={promoting === detail.version_id}
          >
            {promoting === detail.version_id ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Rocket className="h-4 w-4" />
            )}
            晋升评估
          </Button>
          <span className="text-xs text-muted-foreground">运行基准测试评估此版本</span>
        </div>

        {/* Promote result */}
        {promoteResult ? (
          <div
            className={
              promoteResult.passed
                ? "rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-900"
                : "rounded-md border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900"
            }
          >
            <div className="flex items-center gap-2 font-semibold">
              <Award className="h-4 w-4" />
              {promoteResult.passed ? "晋升通过" : "晋升未通过"}
              <Badge variant={promoteResult.passed ? "default" : "destructive"}>
                得分 {promoteResult.score.toFixed(1)}
              </Badge>
            </div>
            {Object.keys(promoteResult.details).length > 0 ? (
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs opacity-80">
                {JSON.stringify(promoteResult.details, null, 2)}
              </pre>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function CreateVersionForm({
  versions,
  creating,
  onSubmit,
  onCancel,
}: {
  versions: VersionManifest[];
  creating: boolean;
  onSubmit: (config: {
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
  }) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [base, setBase] = useState("");
  const [notes, setNotes] = useState("");
  const [provider, setProvider] = useState("volcengine");
  const [model, setModel] = useState("doubao-seed-2.0-pro");
  const [baseUrl, setBaseUrl] = useState("");
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(2048);
  const [totEnabled, setTotEnabled] = useState(true);
  const [gotEnabled, setGotEnabled] = useState(true);
  const [gotThreshold, setGotThreshold] = useState(0.3);
  const [batchDream, setBatchDream] = useState(true);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    onSubmit({
      name: name.trim(),
      base: base || undefined,
      notes: notes.trim() || undefined,
      provider,
      model,
      temperature,
      max_tokens: maxTokens,
      base_url: baseUrl || undefined,
      tot_enabled: totEnabled,
      got_enabled: gotEnabled,
      got_trigger_threshold: gotThreshold,
      batch_dream_enabled: batchDream,
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>新建版本</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="cv-name">版本名称</label>
              <input id="cv-name" type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="例如: v2.1-experiment" className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring" />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="cv-base">基础版本<span className="ml-1 text-xs font-normal text-muted-foreground">(可选)</span></label>
              <select id="cv-base" value={base} onChange={(e) => setBase(e.target.value)} className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring">
                <option value="">从默认技能创建</option>
                {versions.map((v) => (<option key={v.version_id} value={v.version_id}>{v.version_id}</option>))}
              </select>
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="cv-notes">备注<span className="ml-1 text-xs font-normal text-muted-foreground">(可选)</span></label>
            <input id="cv-notes" type="text" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="版本说明" className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring" />
          </div>
          {/* Model config */}
          <div>
            <div className="mb-2 text-xs font-semibold text-muted-foreground">模型配置</div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label className="text-sm font-medium" htmlFor="cv-provider">Provider</label>
                <input id="cv-provider" type="text" value={provider} onChange={(e) => setProvider(e.target.value)} className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring" />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium" htmlFor="cv-model">Model</label>
                <input id="cv-model" type="text" value={model} onChange={(e) => setModel(e.target.value)} className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring" />
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label className="text-sm font-medium" htmlFor="cv-baseurl">Base URL<span className="ml-1 text-xs font-normal text-muted-foreground">(可选)</span></label>
                <input id="cv-baseurl" type="text" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring" />
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label className="text-sm font-medium" htmlFor="cv-temp">Temperature</label>
                <input id="cv-temp" type="number" min={0} max={2} step={0.1} value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring" />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium" htmlFor="cv-tokens">Max Tokens</label>
                <input id="cv-tokens" type="number" min={256} max={32768} step={256} value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))} className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring" />
              </div>
            </div>
          </div>
          {/* Runtime config */}
          <div>
            <div className="mb-2 text-xs font-semibold text-muted-foreground">推理配置</div>
            <div className="grid gap-4 sm:grid-cols-3">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={totEnabled} onChange={(e) => setTotEnabled(e.target.checked)} className="h-4 w-4 rounded border-border" />
                启用 ToT (思维树)
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={gotEnabled} onChange={(e) => setGotEnabled(e.target.checked)} className="h-4 w-4 rounded border-border" />
                启用 GoT (推理图)
              </label>
              <div className="space-y-1.5">
                <label className="text-sm font-medium" htmlFor="cv-got-threshold">GoT 触发阈值</label>
                <input id="cv-got-threshold" type="number" min={0} max={1} step={0.05} value={gotThreshold} onChange={(e) => setGotThreshold(Number(e.target.value))} className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring" />
              </div>
            </div>
          </div>
          {/* Evolution config */}
          <div>
            <div className="mb-2 text-xs font-semibold text-muted-foreground">进化配置</div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={batchDream} onChange={(e) => setBatchDream(e.target.checked)} className="h-4 w-4 rounded border-border" />
              启用批量梦境 (Batch Dream)
            </label>
          </div>
          <div className="flex justify-end gap-3 border-t border-border pt-3">
            <Button type="button" variant="secondary" onClick={onCancel} disabled={creating}>取消</Button>
            <Button type="submit" disabled={creating || !name.trim()}>
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitBranch className="h-4 w-4" />}
              创建
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function EvolutionPanel({
  versions,
  runs,
  loading,
  evolving,
  onSubmit,
}: {
  versions: VersionManifest[];
  runs: EvolutionRun[];
  loading: boolean;
  evolving: boolean;
  onSubmit: (config: EvolutionConfig) => void;
}) {
  const defaultBase = versions[0]?.version_id ?? "";
  const [baseVersion, setBaseVersion] = useState(defaultBase);
  const [candidateVersion, setCandidateVersion] = useState("");
  const [candidateEdited, setCandidateEdited] = useState(false);
  const [trainingGames, setTrainingGames] = useState(5);
  const [battleGames, setBattleGames] = useState(20);
  const [maxDays, setMaxDays] = useState(20);
  const [enableDream, setEnableDream] = useState(true);
  const [enableSkillProposals, setEnableSkillProposals] = useState(true);
  const [autoApplySkillProposals, setAutoApplySkillProposals] = useState(false);
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (!baseVersion && defaultBase) {
      setBaseVersion(defaultBase);
    }
  }, [baseVersion, defaultBase]);

  useEffect(() => {
    if (!candidateEdited) {
      setCandidateVersion(suggestEvolutionVersionName(versions, baseVersion || defaultBase));
    }
  }, [baseVersion, candidateEdited, defaultBase, versions]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!baseVersion || !candidateVersion.trim()) return;
    onSubmit({
      base_version: baseVersion,
      candidate_version: candidateVersion.trim(),
      training_games: trainingGames,
      battle_games: battleGames,
      max_days: maxDays,
      enable_dream: enableDream,
      enable_skill_proposals: enableSkillProposals,
      auto_apply_skill_proposals: autoApplySkillProposals,
      notes: notes.trim(),
    });
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[420px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle>启动自进化</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="ev-base">基础版本</label>
              <select
                id="ev-base"
                value={baseVersion}
                onChange={(e) => setBaseVersion(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="">选择版本</option>
                {versions.map((v) => (
                  <option key={v.version_id} value={v.version_id}>
                    {v.version_id}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="ev-candidate">候选版本</label>
              <input
                id="ev-candidate"
                type="text"
                value={candidateVersion}
                onChange={(e) => {
                  setCandidateEdited(true);
                  setCandidateVersion(e.target.value);
                }}
                placeholder="例如: v1.2-evo-werewolf-fake-seer"
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <button
                type="button"
                className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                onClick={() => {
                  setCandidateEdited(false);
                  setCandidateVersion(suggestEvolutionVersionName(versions, baseVersion || defaultBase));
                }}
              >
                使用建议命名
              </button>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <NumberField id="ev-train" label="训练局数" value={trainingGames} min={1} onChange={setTrainingGames} />
              <NumberField id="ev-battle" label="对战局数" value={battleGames} min={1} onChange={setBattleGames} />
              <NumberField id="ev-days" label="最大天数" value={maxDays} min={1} onChange={setMaxDays} />
            </div>
            <div className="space-y-2 rounded-md border border-border p-3">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={enableDream} onChange={(e) => setEnableDream(e.target.checked)} className="h-4 w-4 rounded border-border" />
                生成批量梦境复盘
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={enableSkillProposals} onChange={(e) => setEnableSkillProposals(e.target.checked)} className="h-4 w-4 rounded border-border" />
                生成 skill proposal
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={autoApplySkillProposals} onChange={(e) => setAutoApplySkillProposals(e.target.checked)} className="h-4 w-4 rounded border-border" />
                自动应用可进化 proposal
              </label>
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium" htmlFor="ev-notes">备注</label>
              <input
                id="ev-notes"
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="本轮实验目标"
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <Button type="submit" disabled={evolving || !baseVersion || !candidateVersion.trim()} className="w-full">
              {evolving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
              启动
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>自进化任务</CardTitle>
          <Badge variant="secondary">{runs.length}</Badge>
        </CardHeader>
        <CardContent className="space-y-2">
          {loading && runs.length === 0 ? (
            <div className="flex min-h-[260px] items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : runs.length === 0 ? (
            <div className="flex min-h-[260px] items-center justify-center text-sm text-muted-foreground">
              暂无自进化任务
            </div>
          ) : (
            runs.map((run) => (
              <div key={run.run_id} className="rounded-md border border-border p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{run.run_id}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {String(run.config.base_version)} → {String(run.config.candidate_version)}
                    </div>
                  </div>
                  <Badge variant={statusVariant(run.status)}>{statusLabel(run.status)}</Badge>
                </div>
                <div className="mt-3 grid gap-2 text-xs sm:grid-cols-4">
                  <InfoCell label="阶段" value={run.stage} />
                  <InfoCell label="训练局" value={String(run.config.training_games ?? "-")} />
                  <InfoCell label="对战局" value={String(run.config.battle_games ?? "-")} />
                  <InfoCell label="结果" value={run.promoted === undefined ? "-" : run.promoted ? "通过" : "拒绝"} />
                </div>
                {run.reasons && run.reasons.length > 0 ? (
                  <div className="mt-2 text-xs text-muted-foreground">{run.reasons.join("；")}</div>
                ) : null}
                {run.error ? (
                  <div className="mt-2 text-xs text-destructive">{run.error}</div>
                ) : null}
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function MixedBattlePanel({
  versions,
  runs,
  loading,
  mixing,
  onSubmit,
}: {
  versions: VersionManifest[];
  runs: MixedBattleRun[];
  loading: boolean;
  mixing: boolean;
  onSubmit: (config: MixedBattleConfig) => void;
}) {
  const first = versions[0]?.version_id ?? "";
  const second = versions[1]?.version_id ?? first;
  const [wolvesVersion, setWolvesVersion] = useState(first);
  const [villagersVersion, setVillagersVersion] = useState(second);
  const [gamesPerSide, setGamesPerSide] = useState(5);
  const [seedStart, setSeedStart] = useState(1);
  const [maxDays, setMaxDays] = useState(20);
  const [enableReview, setEnableReview] = useState(true);

  useEffect(() => {
    if (!wolvesVersion && first) setWolvesVersion(first);
    if (!villagersVersion && second) setVillagersVersion(second);
  }, [first, second, villagersVersion, wolvesVersion]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!wolvesVersion || !villagersVersion) return;
    onSubmit({
      wolves_version: wolvesVersion,
      villagers_version: villagersVersion,
      games_per_side: gamesPerSide,
      seed_start: seedStart,
      max_days: maxDays,
      enable_review: enableReview,
    });
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[420px_1fr]">
      <Card>
        <CardHeader>
          <CardTitle>启动混编对战</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <VersionSelect
              id="mixed-wolves"
              label="狼人阵营版本"
              value={wolvesVersion}
              versions={versions}
              onChange={setWolvesVersion}
            />
            <VersionSelect
              id="mixed-villagers"
              label="好人阵营版本"
              value={villagersVersion}
              versions={versions}
              onChange={setVillagersVersion}
            />
            <div className="grid grid-cols-3 gap-3">
              <NumberField id="mixed-games" label="每边局数" value={gamesPerSide} min={1} onChange={setGamesPerSide} />
              <NumberField id="mixed-seed" label="起始种子" value={seedStart} min={1} onChange={setSeedStart} />
              <NumberField id="mixed-days" label="最大天数" value={maxDays} min={1} onChange={setMaxDays} />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={enableReview} onChange={(e) => setEnableReview(e.target.checked)} className="h-4 w-4 rounded border-border" />
              生成复盘评分
            </label>
            <Button type="submit" disabled={mixing || !wolvesVersion || !villagersVersion} className="w-full">
              {mixing ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitBranch className="h-4 w-4" />}
              启动
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>混编对战任务</CardTitle>
          <Badge variant="secondary">{runs.length}</Badge>
        </CardHeader>
        <CardContent className="space-y-2">
          {loading && runs.length === 0 ? (
            <div className="flex min-h-[260px] items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : runs.length === 0 ? (
            <div className="flex min-h-[260px] items-center justify-center text-sm text-muted-foreground">
              暂无混编对战任务
            </div>
          ) : (
            runs.map((run) => (
              <div key={run.run_id} className="rounded-md border border-border p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{run.run_id}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      每个 seed 会镜像两局，交换狼人/好人阵营版本
                    </div>
                  </div>
                  <Badge variant={statusVariant(run.status)}>{statusLabel(run.status)}</Badge>
                </div>
                {run.leaderboard && run.leaderboard.length > 0 ? (
                  <div className="mt-3 overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="text-muted-foreground">
                        <tr>
                          <th className="pb-2 pr-3 font-medium">版本</th>
                          <th className="pb-2 pr-3 font-medium">局数</th>
                          <th className="pb-2 pr-3 font-medium">狼胜率</th>
                          <th className="pb-2 pr-3 font-medium">好胜率</th>
                          <th className="pb-2 font-medium">总分</th>
                          <th className="pb-2 font-medium">校准误差</th>
                        </tr>
                      </thead>
                      <tbody>
                        {run.leaderboard.map((entry) => (
                          <tr key={leaderboardName(entry)} className="border-t border-border/60">
                            <td className="py-2 pr-3">{leaderboardName(entry)}</td>
                            <td className="py-2 pr-3">{entry.games}</td>
                            <td className="py-2 pr-3">{pct(entry.werewolf_win_rate)}</td>
                            <td className="py-2 pr-3">{pct(entry.villager_win_rate)}</td>
                            <td className="py-2">{num(entry.avg_score, 1)}</td>
                            <td className="py-2">{pct(entry.confidence_calibration_error ?? 0)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
                {run.error ? <div className="mt-2 text-xs text-destructive">{run.error}</div> : null}
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function VersionSelect({
  id,
  label,
  value,
  versions,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  versions: VersionManifest[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium" htmlFor={id}>{label}</label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
      >
        <option value="">选择版本</option>
        {versions.map((version) => (
          <option key={version.version_id} value={version.version_id}>
            {version.version_id}
          </option>
        ))}
      </select>
    </div>
  );
}

function NumberField({
  id,
  label,
  value,
  min,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  min: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium" htmlFor={id}>{label}</label>
      <input
        id={id}
        type="number"
        min={min}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
    </div>
  );
}

function LeaderboardTable({
  entries,
  loading,
}: {
  entries: VersionLeaderboardEntry[];
  loading: boolean;
}) {
  if (loading && entries.length === 0) {
    return (
      <Card>
        <CardContent className="flex min-h-[300px] items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (entries.length === 0) {
    return (
      <Card>
        <CardContent className="flex min-h-[300px] flex-col items-center justify-center gap-3">
          <BarChart3 className="h-10 w-10 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">暂无排行榜数据，请先运行版本对战。</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>版本排行榜</CardTitle>
        <Badge variant="secondary">{entries.length} 个版本</Badge>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="pb-3 pr-4 font-medium">#</th>
              <th className="pb-3 pr-4 font-medium">版本</th>
              <th className="pb-3 pr-4 font-medium">局数</th>
              <th className="pb-3 pr-4 font-medium">狼人胜率</th>
              <th className="pb-3 pr-4 font-medium">好人胜率</th>
              <th className="pb-3 pr-4 font-medium">总分</th>
              <th className="pb-3 pr-4 font-medium">发言</th>
              <th className="pb-3 pr-4 font-medium">投票</th>
              <th className="pb-3 pr-4 font-medium">技能</th>
              <th className="pb-3 pr-4 font-medium">校准误差</th>
              <th className="pb-3 pr-4 font-medium">Fallback率</th>
              <th className="pb-3 font-medium">Policy修正率</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, idx) => (
              <tr
                key={leaderboardName(entry)}
                className="border-b border-border/50 last:border-0 hover:bg-muted/30"
              >
                <td className="py-3 pr-4 font-semibold text-muted-foreground">{idx + 1}</td>
                <td className="py-3 pr-4 font-medium">{leaderboardName(entry)}</td>
                <td className="py-3 pr-4">{entry.games}</td>
                <td className="py-3 pr-4">{pct(entry.werewolf_win_rate)}</td>
                <td className="py-3 pr-4">{pct(entry.villager_win_rate)}</td>
                <td className="py-3 pr-4 font-semibold">{num(entry.avg_score, 1)}</td>
                <td className="py-3 pr-4">{num(entry.avg_speech_score, 1)}</td>
                <td className="py-3 pr-4">{num(entry.avg_vote_score, 1)}</td>
                <td className="py-3 pr-4">{num(entry.avg_skill_score, 1)}</td>
                <td className="py-3 pr-4">{pct(entry.confidence_calibration_error ?? 0)}</td>
                <td className="py-3 pr-4">{pct(entry.fallback_rate)}</td>
                <td className="py-3">{pct(entry.policy_adjusted_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
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

function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "active") return "default";
  if (status === "promoted") return "default";
  if (status === "validated") return "default";
  if (status === "completed") return "default";
  if (status === "running") return "outline";
  if (status === "failed") return "destructive";
  if (status === "rejected") return "destructive";
  return "secondary";
}

function statusLabel(status: string): string {
  if (status === "active") return "活跃";
  if (status === "promoted") return "已晋升";
  if (status === "validated") return "已验证";
  if (status === "candidate") return "候选";
  if (status === "running") return "运行中";
  if (status === "completed") return "完成";
  if (status === "rejected") return "已拒绝";
  if (status === "archived") return "已归档";
  if (status === "failed") return "失败";
  return status;
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

function formatMetric(value: unknown): string {
  if (typeof value === "number") return value.toFixed(2);
  return String(value ?? "-");
}

function pct(value: number): string {
  return `${(Number.isFinite(value) ? value * 100 : 0).toFixed(0)}%`;
}

function num(value: unknown, digits = 1): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : (0).toFixed(digits);
}

function leaderboardName(entry: VersionLeaderboardEntry): string {
  return entry.label ?? entry.version_id ?? entry.version ?? "unknown";
}

function suggestEvolutionVersionName(versions: VersionManifest[], baseVersion: string): string {
  const parsed = versions
    .map((version) => /^v(\d+)\.(\d+)/.exec(version.version_id))
    .filter((match): match is RegExpExecArray => match !== null)
    .map((match) => ({
      major: Number(match[1]),
      minor: Number(match[2]),
    }));
  const latest = parsed.reduce(
    (best, item) => {
      if (item.major > best.major) return item;
      if (item.major === best.major && item.minor > best.minor) return item;
      return best;
    },
    { major: 1, minor: 0 },
  );
  const baseSlug = slugVersionName(baseVersion || "baseline");
  return `v${latest.major}.${latest.minor + 1}-evo-${baseSlug}`;
}

function slugVersionName(value: string): string {
  const withoutPrefix = value.replace(/^v\d+\.\d+-?/, "");
  const slug = withoutPrefix
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || "baseline";
}
