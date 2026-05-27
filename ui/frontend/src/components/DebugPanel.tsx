import { useEffect, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import { Badge } from "./ui/badge";
import { phaseName, roleName } from "../presentation";

type DebugDecision = {
  player_id: number;
  role: string;
  day: number;
  phase: string;
  action_type: string;
  source: "llm" | "tot" | "fallback" | "policy_adjusted";
  confidence: number;
  target: number | null;
  choice: string | null;
  public_text: string;
  selected_skills: string[];
  errors: string[];
  tot_enabled: boolean;
  tot_judge_reason: string;
  policy_adjustments: string[];
};

export function DebugPanel({ active }: { active: boolean }) {
  const [decisions, setDecisions] = useState<DebugDecision[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const activeRef = useRef(active);
  activeRef.current = active;

  useEffect(() => {
    if (!active) {
      wsRef.current?.close();
      wsRef.current = null;
      return;
    }
    setDecisions([]);

    let closed = false;
    let timeout: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      if (closed || !activeRef.current) return;
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${protocol}://${window.location.host}/ws/debug`);
      wsRef.current = ws;
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data as string) as DebugDecision;
        setDecisions((prev) => [...prev, data]);
      };
      ws.onerror = () => ws.close();
      ws.onclose = () => {
        wsRef.current = null;
        if (!closed && activeRef.current) {
          timeout = setTimeout(connect, 2000);
        }
      };
    }

    connect();

    return () => {
      closed = true;
      if (timeout) clearTimeout(timeout);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [active]);

  const byPlayer: Record<number, DebugDecision[]> = {};
  for (const d of decisions) {
    byPlayer[d.player_id] = [...(byPlayer[d.player_id] ?? []), d];
  }

  return (
    <section className="flex min-h-[calc(100vh-118px)] flex-col rounded-lg border border-border bg-card shadow-sm">
      <div className="border-b border-border bg-muted/30 px-6 py-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold">Agent 决策流</h2>
          <Badge variant={decisions.length > 0 ? "default" : "secondary"}>
            {decisions.length > 0 ? `${decisions.length} 次决策` : "等待中..."}
          </Badge>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">实时 WebSocket 推送 · 按玩家分组</p>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {decisions.length === 0 ? (
          <div className="flex min-h-64 items-center justify-center text-sm text-muted-foreground">
            等待 Agent 开始决策...
          </div>
        ) : (
          <div className="space-y-2">
            {Object.entries(byPlayer)
              .sort(([a], [b]) => Number(a) - Number(b))
              .map(([pid, ds]) => (
                <details key={pid} className="group rounded-md border border-border bg-muted/20">
                  <summary className="flex cursor-pointer list-none items-center gap-2 p-3 marker:hidden">
                    <Badge>{pid} 号</Badge>
                    <span className="text-sm font-medium">{roleName(ds[0]?.role ?? "")}</span>
                    <span className="text-xs text-muted-foreground">{ds.length} 次</span>
                    <ChevronRight className="ml-auto h-3.5 w-3.5 transition-transform group-open:rotate-90" />
                  </summary>
                  <div className="space-y-2 px-3 pb-3">
                    {ds.map((d, i) => (
                      <div key={i} className="rounded-sm border border-border bg-card p-2 text-xs">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="font-medium">第{d.day}天</span>
                          <Badge variant="outline">{phaseName(d.phase)}</Badge>
                          <Badge variant="outline">{actionLabel(d.action_type)}</Badge>
                          <Badge variant={sourceVariant(d.source)}>{sourceLabel(d.source)}</Badge>
                          {d.confidence > 0 ? (
                            <span className="text-muted-foreground">
                              {(d.confidence * 100).toFixed(0)}%
                            </span>
                          ) : null}
                        </div>
                        {d.target !== null ? (
                          <div className="mt-1 text-muted-foreground">
                            目标: {d.target} 号{d.choice ? ` (${d.choice})` : ""}
                          </div>
                        ) : d.choice ? (
                          <div className="mt-1 text-muted-foreground">
                            选择: {d.choice}
                          </div>
                        ) : null}
                        {d.public_text ? (
                          <div className="mt-1 max-h-16 overflow-y-auto whitespace-pre-wrap text-muted-foreground">
                            {d.public_text.slice(0, 200)}
                          </div>
                        ) : null}
                        {d.tot_enabled && d.tot_judge_reason ? (
                          <div className="mt-1 font-medium text-indigo-600 dark:text-indigo-400">
                            ToT: {d.tot_judge_reason}
                          </div>
                        ) : null}
                        {d.policy_adjustments.length > 0 ? (
                          <div className="mt-1 font-medium text-amber-600 dark:text-amber-400">
                            策略修正: {d.policy_adjustments.join("；")}
                          </div>
                        ) : null}
                        {d.errors.length > 0 ? (
                          <div className="mt-1 font-medium text-red-600 dark:text-red-400">
                            错误: {d.errors.join("；")}
                          </div>
                        ) : null}
                        {d.selected_skills.length > 0 ? (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {d.selected_skills.map((sk) => (
                              <Badge key={sk} variant="secondary" className="text-xs">{sk}</Badge>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </details>
              ))}
          </div>
        )}
      </div>
    </section>
  );
}

function actionLabel(actionType: string) {
  const map: Record<string, string> = {
    speak: "发言",
    sheriff_run: "是否上警",
    sheriff_speak: "警上发言",
    sheriff_vote: "警长投票",
    sheriff_withdraw: "退水",
    pk_speak: "PK发言",
    pk_vote: "PK投票",
    exile_vote: "放逐投票",
    last_word: "遗言",
    guard_protect: "守卫守护",
    werewolf_kill: "狼人刀人",
    seer_check: "预言家查验",
    witch_act: "女巫行动",
    hunter_shoot: "猎人开枪",
    white_wolf_explode: "白狼王自爆",
  };
  return map[actionType] ?? actionType;
}

function sourceLabel(source: string) {
  const map: Record<string, string> = {
    llm: "LLM",
    tot: "ToT",
    fallback: "回退",
    policy_adjusted: "修正",
  };
  return map[source] ?? source;
}

function sourceVariant(source: string): "default" | "secondary" | "destructive" | "outline" {
  if (source === "tot") return "default";
  if (source === "fallback") return "destructive";
  if (source === "policy_adjusted") return "outline";
  return "secondary";
}
