import { useCallback, useEffect, useState } from "react";
import {
  Brain,
  ChevronRight,
  FileCode,
  FileText,
  FlaskConical,
  Lightbulb,
  Loader2,
  MemoryStick,
  Moon,
  RefreshCw,
  Star,
} from "lucide-react";
import {
  getProposalDetail,
  listDreams,
  listMemoryCandidates,
  listPatches,
  listProposals,
  type DreamReport,
  type MemoryCandidate,
  type Proposal,
} from "../api";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";

type Tab = "proposals" | "patches" | "memory" | "dreams";

const ROLE_OPTIONS = [
  { value: "", label: "全部角色" },
  { value: "seer", label: "预言家" },
  { value: "witch", label: "女巫" },
  { value: "guard", label: "守卫" },
  { value: "hunter", label: "猎人" },
  { value: "werewolf", label: "狼人" },
  { value: "villager", label: "村民" },
  { value: "white_wolf_king", label: "白狼王" },
];

export function ProposalsPage() {
  const [tab, setTab] = useState<Tab>("proposals");
  const [role, setRole] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Data per tab
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [patches, setPatches] = useState<Proposal[]>([]);
  const [memories, setMemories] = useState<MemoryCandidate[]>([]);
  const [dreams, setDreams] = useState<DreamReport[]>([]);

  // Detail selection
  const [selectedProposal, setSelectedProposal] = useState<Proposal | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadData = useCallback(async (t: Tab, r: string) => {
    setLoading(true);
    setError(null);
    try {
      switch (t) {
        case "proposals": {
          const data = await listProposals(r || undefined);
          setProposals(data);
          break;
        }
        case "patches": {
          const data = await listPatches();
          setPatches(data);
          break;
        }
        case "memory": {
          const data = await listMemoryCandidates(r || undefined);
          setMemories(data);
          break;
        }
        case "dreams": {
          const data = await listDreams(r || undefined);
          setDreams(data);
          break;
        }
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData(tab, role);
  }, [tab, role, loadData]);

  function handleTabChange(t: Tab) {
    setTab(t);
    setSelectedProposal(null);
  }

  function handleRoleChange(r: string) {
    setRole(r);
    setSelectedProposal(null);
  }

  async function handleProposalSelect(proposalId: string) {
    setDetailLoading(true);
    try {
      const detail = await getProposalDetail(proposalId);
      setSelectedProposal(detail);
    } catch {
      setSelectedProposal(null);
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-5 px-5 py-5">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <TabButton active={tab === "proposals"} onClick={() => handleTabChange("proposals")}>
          <FileText className="h-4 w-4" />
          提案
        </TabButton>
        <TabButton active={tab === "patches"} onClick={() => handleTabChange("patches")}>
          <FileCode className="h-4 w-4" />
          补丁
        </TabButton>
        <TabButton active={tab === "memory"} onClick={() => handleTabChange("memory")}>
          <MemoryStick className="h-4 w-4" />
          记忆候选
        </TabButton>
        <TabButton active={tab === "dreams"} onClick={() => handleTabChange("dreams")}>
          <Moon className="h-4 w-4" />
          梦境报告
        </TabButton>

        <div className="mx-2 h-6 w-px bg-border" />

        {/* Role filter */}
        <select
          value={role}
          onChange={(e) => handleRoleChange(e.target.value)}
          className="rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        >
          {ROLE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        <Button variant="secondary" onClick={() => void loadData(tab, role)} disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          刷新
        </Button>
      </div>

      {error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {/* Content */}
      {tab === "proposals" ? (
        <ProposalsList
          proposals={proposals}
          loading={loading}
          selectedId={selectedProposal?.proposal_id ?? null}
          onSelect={handleProposalSelect}
          detail={selectedProposal}
          detailLoading={detailLoading}
        />
      ) : tab === "patches" ? (
        <PatchesList patches={patches} loading={loading} />
      ) : tab === "memory" ? (
        <MemoryList memories={memories} loading={loading} />
      ) : (
        <DreamsList dreams={dreams} loading={loading} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab button helper
// ---------------------------------------------------------------------------

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      className={
        active
          ? "inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
          : "inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm hover:bg-muted"
      }
      onClick={onClick}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Proposals (with detail panel)
// ---------------------------------------------------------------------------

function ProposalsList({
  proposals,
  loading,
  selectedId,
  onSelect,
  detail,
  detailLoading,
}: {
  proposals: Proposal[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  detail: Proposal | null;
  detailLoading: boolean;
}) {
  const items = proposals;

  if (loading && items.length === 0) {
    return (
      <Card>
        <CardContent className="flex min-h-[300px] items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (items.length === 0) {
    return (
      <Card>
        <CardContent className="flex min-h-[300px] flex-col items-center justify-center gap-3">
          <Lightbulb className="h-10 w-10 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">暂无提案数据</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_380px]">
      <Card>
        <CardHeader>
          <CardTitle>提案列表</CardTitle>
          <Badge variant="secondary">{items.length}</Badge>
        </CardHeader>
        <CardContent className="space-y-2">
          {items.map((p) => (
            <button
              key={p.proposal_id}
              className={
                p.proposal_id === selectedId
                  ? "flex w-full items-center justify-between rounded-md border border-primary/40 bg-primary/5 px-3 py-3 text-left text-sm transition-colors"
                  : "flex w-full items-center justify-between rounded-md border border-border px-3 py-3 text-left text-sm transition-colors hover:bg-muted"
              }
              onClick={() => onSelect(p.proposal_id)}
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{roleLabel(p.role)}</Badge>
                  <span className="font-medium">{proposalTypeLabel(p.proposal_type)}</span>
                  <Badge variant={proposalStatusVariant(p.status)}>{proposalStatusLabel(p.status)}</Badge>
                </div>
                <p className="mt-1 truncate text-xs text-muted-foreground">{p.content}</p>
                <div className="mt-1 text-xs text-muted-foreground">
                  {p.score != null ? `评分: ${p.score.toFixed(1)}` : null}
                  {p.created_at ? ` · ${formatTime(p.created_at)}` : null}
                </div>
              </div>
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
            </button>
          ))}
        </CardContent>
      </Card>

      {/* Detail panel */}
      <ProposalDetailPanel detail={detail} loading={detailLoading} />
    </div>
  );
}

function ProposalDetailPanel({
  detail,
  loading,
}: {
  detail: Proposal | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <Card>
        <CardContent className="flex min-h-[200px] items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (!detail) {
    return (
      <Card>
        <CardContent className="flex min-h-[200px] items-center justify-center text-sm text-muted-foreground">
          选择一个提案查看详情
        </CardContent>
      </Card>
    );
  }

  const meta = detail.metadata ?? {};

  return (
    <Card>
      <CardHeader>
        <CardTitle>{proposalTypeLabel(detail.proposal_type)}</CardTitle>
        <Badge variant={proposalStatusVariant(detail.status)}>{proposalStatusLabel(detail.status)}</Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-2 text-xs">
          <InfoCell label="提案 ID" value={detail.proposal_id} />
          <InfoCell label="角色" value={roleLabel(detail.role)} />
          <InfoCell label="类型" value={proposalTypeLabel(detail.proposal_type)} />
          <InfoCell label="评分" value={detail.score != null ? detail.score.toFixed(1) : "-"} />
          <InfoCell label="状态" value={proposalStatusLabel(detail.status)} />
          <InfoCell label="创建时间" value={formatTime(detail.created_at)} />
        </div>

        {/* Content */}
        <div>
          <div className="mb-1.5 text-xs font-semibold text-muted-foreground">内容</div>
          <div className="max-h-[300px] overflow-y-auto rounded-md border border-border bg-muted/30 p-3">
            <p className="whitespace-pre-wrap text-sm leading-6">{detail.content}</p>
          </div>
        </div>

        {/* Metadata */}
        {Object.keys(meta).length > 0 ? (
          <div>
            <div className="mb-1.5 text-xs font-semibold text-muted-foreground">元数据</div>
            <div className="rounded-md border border-border bg-muted/30 p-3">
              <pre className="overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">
                {JSON.stringify(meta, null, 2)}
              </pre>
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Patches
// ---------------------------------------------------------------------------

function PatchesList({ patches, loading }: { patches: Proposal[]; loading: boolean }) {
  if (loading && patches.length === 0) {
    return (
      <Card>
        <CardContent className="flex min-h-[300px] items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (patches.length === 0) {
    return (
      <Card>
        <CardContent className="flex min-h-[300px] flex-col items-center justify-center gap-3">
          <FlaskConical className="h-10 w-10 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">暂无补丁数据</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>技能补丁</CardTitle>
        <Badge variant="secondary">{patches.length}</Badge>
      </CardHeader>
      <CardContent className="space-y-3">
        {patches.map((p) => (
          <div key={p.proposal_id} className="rounded-md border border-border p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{roleLabel(p.role)}</Badge>
              <span className="text-sm font-medium">{proposalTypeLabel(p.proposal_type)}</span>
              <Badge variant={proposalStatusVariant(p.status)}>{proposalStatusLabel(p.status)}</Badge>
              {p.score != null ? (
                <span className="text-xs text-muted-foreground">评分: {p.score.toFixed(1)}</span>
              ) : null}
            </div>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-muted-foreground">{p.content}</p>
            <div className="mt-2 text-xs text-muted-foreground">{formatTime(p.created_at)}</div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Memory Candidates
// ---------------------------------------------------------------------------

function MemoryList({ memories, loading }: { memories: MemoryCandidate[]; loading: boolean }) {
  if (loading && memories.length === 0) {
    return (
      <Card>
        <CardContent className="flex min-h-[300px] items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (memories.length === 0) {
    return (
      <Card>
        <CardContent className="flex min-h-[300px] flex-col items-center justify-center gap-3">
          <Brain className="h-10 w-10 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">暂无记忆候选</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>记忆候选</CardTitle>
        <Badge variant="secondary">{memories.length}</Badge>
      </CardHeader>
      <CardContent className="space-y-3">
        {memories.map((m) => (
          <div key={m.id} className="rounded-md border border-border p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{roleLabel(m.role)}</Badge>
              <span className="text-xs text-muted-foreground">来源: {m.source}</span>
              {m.score != null ? (
                <span className="text-xs text-muted-foreground">评分: {m.score.toFixed(1)}</span>
              ) : null}
            </div>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-muted-foreground">{m.content}</p>
            <div className="mt-2 text-xs text-muted-foreground">{formatTime(m.created_at)}</div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Dreams
// ---------------------------------------------------------------------------

function DreamsList({ dreams, loading }: { dreams: DreamReport[]; loading: boolean }) {
  if (loading && dreams.length === 0) {
    return (
      <Card>
        <CardContent className="flex min-h-[300px] items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (dreams.length === 0) {
    return (
      <Card>
        <CardContent className="flex min-h-[300px] flex-col items-center justify-center gap-3">
          <Moon className="h-10 w-10 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">暂无梦境报告</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>梦境报告</CardTitle>
        <Badge variant="secondary">{dreams.length}</Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        {dreams.map((d) => (
          <div key={d.id} className="rounded-md border border-border p-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{roleLabel(d.role)}</Badge>
              <span className="text-xs text-muted-foreground">{formatTime(d.created_at)}</span>
            </div>
            <p className="mt-2 text-sm font-medium">{d.summary}</p>
            {d.insights.length > 0 ? (
              <div className="mt-3 space-y-1.5">
                {d.insights.map((insight, idx) => (
                  <div key={idx} className="flex items-start gap-2 text-sm text-muted-foreground">
                    <Star className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
                    <span>{insight}</span>
                  </div>
                ))}
              </div>
            ) : null}
            {d.metadata && Object.keys(d.metadata).length > 0 ? (
              <details className="group mt-3">
                <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground marker:hidden">
                  <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
                  元数据
                </summary>
                <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">
                  {JSON.stringify(d.metadata, null, 2)}
                </pre>
              </details>
            ) : null}
          </div>
        ))}
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

function roleLabel(role: string): string {
  const map: Record<string, string> = {
    seer: "预言家",
    witch: "女巫",
    guard: "守卫",
    hunter: "猎人",
    werewolf: "狼人",
    villager: "村民",
    white_wolf_king: "白狼王",
  };
  return map[role] ?? role;
}

function proposalTypeLabel(t: string): string {
  const map: Record<string, string> = {
    skill_update: "技能更新",
    strategy_patch: "策略补丁",
    memory_injection: "记忆注入",
    behavior_adjust: "行为调整",
  };
  return map[t] ?? t;
}

function proposalStatusVariant(s: string): "default" | "secondary" | "destructive" | "outline" {
  if (s === "approved" || s === "active") return "default";
  if (s === "rejected" || s === "failed") return "destructive";
  if (s === "pending" || s === "review") return "outline";
  return "secondary";
}

function proposalStatusLabel(s: string): string {
  const map: Record<string, string> = {
    pending: "待审核",
    approved: "已通过",
    rejected: "已拒绝",
    active: "生效中",
    review: "审核中",
    applied: "已应用",
  };
  return map[s] ?? s;
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
