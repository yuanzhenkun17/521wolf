import { Badge } from "./ui/badge";
import { roleName } from "../presentation";
import type { Player } from "../types";

export function ReviewPanel({
  reviewData,
  players,
  onClose,
}: {
  reviewData: Record<string, unknown> | null;
  players: Player[];
  onClose: () => void;
}) {
  if (reviewData === null) {
    return (
      <section className="flex min-h-[calc(100vh-118px)] items-center justify-center rounded-lg border border-border bg-card text-sm text-muted-foreground">
        加载中...
      </section>
    );
  }

  const winner = String(reviewData.winner ?? "");
  const summary = String(reviewData.summary ?? "");
  const teamScores = reviewData.team_scores as Record<string, number> | undefined;
  const playerScores = reviewData.player_scores as Record<string, Record<string, unknown>> | undefined;
  const turningPoints = reviewData.key_turning_points as Array<Record<string, unknown>> | undefined;
  const mistakes = reviewData.mistakes as Array<Record<string, unknown>> | undefined;
  const skillSummary = reviewData.skill_summary as Record<string, Record<string, unknown>> | undefined;
  const suggestions = reviewData.suggestions as string[] | undefined;

  const sortedPlayers = playerScores
    ? Object.entries(playerScores).sort(([, a], [, b]) => (b.total_score as number ?? 0) - (a.total_score as number ?? 0))
    : [];

  return (
    <section className="overflow-y-auto rounded-lg border border-border bg-card shadow-sm">
      <div className="border-b border-border bg-muted/30 px-6 py-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold">复盘报告</h2>
          <Badge className={winner === "werewolves" ? "bg-rose-600 text-white" : "bg-emerald-600 text-white"}>{winner === "werewolves" ? "狼人胜利" : "好人胜利"}</Badge>
        </div>
        {summary ? <p className="mt-2 text-sm text-muted-foreground">{summary}</p> : null}
      </div>

      <div className="space-y-6 p-5">
        {teamScores ? (
          <div>
            <h3 className="mb-3 text-sm font-semibold">阵营平均分</h3>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-emerald-900">
                <div className="text-xs text-emerald-700">好人阵营</div>
                <div className="mt-1 text-2xl font-bold">{(teamScores.villagers ?? 0).toFixed(1)}</div>
              </div>
              <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-rose-900">
                <div className="text-xs text-rose-700">狼人阵营</div>
                <div className="mt-1 text-2xl font-bold">{(teamScores.werewolves ?? 0).toFixed(1)}</div>
              </div>
            </div>
          </div>
        ) : null}

        {sortedPlayers.length > 0 ? (
          <div>
            <h3 className="mb-3 text-sm font-semibold">玩家评分</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-border text-muted-foreground">
                    <th className="pb-2 pr-3 font-medium">玩家</th>
                    <th className="pb-2 pr-3 font-medium">角色</th>
                    <th className="pb-2 pr-3 font-medium">总分</th>
                    <th className="pb-2 pr-3 font-medium">发言</th>
                    <th className="pb-2 pr-3 font-medium">投票</th>
                    <th className="pb-2 pr-3 font-medium">技能</th>
                    <th className="pb-2 pr-3 font-medium">信息</th>
                    <th className="pb-2 pr-3 font-medium">协作</th>
                    <th className="pb-2 font-medium">胜负</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedPlayers.map(([pid, pr], idx) => {
                    const scores = (pr.scores as Record<string, number>) ?? {};
                    const player = players.find((p) => p.id === Number(pid));
                    return (
                      <tr key={pid} className={`border-b border-border/50 last:border-0 ${idx % 2 === 0 ? "bg-muted/20" : ""}`}>
                        <td className="py-2 pr-3 font-medium font-mono">{pid} 号</td>
                        <td className="py-2 pr-3">{player ? roleName(player.role) : String(pr.role ?? "")}</td>
                        <td className="py-2 pr-3 font-semibold">{(pr.total_score as number ?? 0).toFixed(1)}</td>
                        <td className="py-2 pr-3 text-muted-foreground">{(scores.speech ?? 0).toFixed(1)}</td>
                        <td className="py-2 pr-3 text-muted-foreground">{(scores.vote ?? 0).toFixed(1)}</td>
                        <td className="py-2 pr-3 text-muted-foreground">{(scores.skill ?? 0).toFixed(1)}</td>
                        <td className="py-2 pr-3 text-muted-foreground">{(scores.information ?? 0).toFixed(1)}</td>
                        <td className="py-2 pr-3 text-muted-foreground">{(scores.cooperation ?? 0).toFixed(1)}</td>
                        <td className="py-2">
                          <Badge className={pr.outcome === "win" ? "bg-emerald-600 text-white" : "bg-muted text-muted-foreground"}>
                            {pr.outcome === "win" ? "胜" : "负"}
                          </Badge>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}

        {sortedPlayers.length > 0 ? (
          <div>
            <h3 className="mb-3 text-sm font-semibold">高光与失误</h3>
            <div className="grid gap-3 md:grid-cols-2">
              {sortedPlayers.map(([pid, pr]) => {
                const highlights = (pr.highlights as string[]) ?? [];
                const mistakesList = (pr.mistakes as string[]) ?? [];
                if (highlights.length === 0 && mistakesList.length === 0) return null;
                return (
                  <div key={pid} className="rounded-md border border-border bg-card p-3">
                    <div className="mb-2 text-sm font-medium">{pid} 号 · {roleName(players.find((p) => p.id === Number(pid))?.role ?? "")}</div>
                    {highlights.length > 0 ? (
                      <div className="mb-2 text-xs text-emerald-700">
                        <span className="font-medium">高光：</span>
                        {highlights.join("；")}
                      </div>
                    ) : null}
                    {mistakesList.length > 0 ? (
                      <div className="text-xs text-red-700">
                        <span className="font-medium">失误：</span>
                        {mistakesList.join("；")}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        {turningPoints && turningPoints.length > 0 ? (
          <div>
            <h3 className="mb-3 text-sm font-semibold">关键转折点</h3>
            <div className="space-y-3">
              {turningPoints.map((tp, idx) => (
                <div key={idx} className="rounded-md border border-border bg-card p-3 text-sm">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">第 {tp.day as number} 天</span>
                    <Badge variant="outline">{(tp.phase as string) ?? ""}</Badge>
                    <Badge className={tp.impact === "positive" ? "bg-emerald-100 text-emerald-800" : tp.impact === "negative" ? "bg-red-100 text-red-800" : "bg-amber-100 text-amber-800"}>
                      {tp.impact === "positive" ? "正面" : tp.impact === "negative" ? "负面" : "混合"}
                    </Badge>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{tp.description as string}</p>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {mistakes && mistakes.length > 0 ? (
          <div>
            <h3 className="mb-3 text-sm font-semibold">关键错误</h3>
            <div className="space-y-2">
              {mistakes.map((m, idx) => (
                <div key={idx} className="rounded-md border-l-2 border-red-300 border border-border bg-red-50/50 p-3 text-sm">
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary">{m.player_id as number} 号</Badge>
                    <Badge variant="outline">{m.mistake_type as string}</Badge>
                    <Badge className={m.severity === "high" ? "bg-red-100 text-red-800" : "bg-muted text-muted-foreground"}>
                      {m.severity as string}
                    </Badge>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{m.description as string}</p>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {skillSummary && Object.keys(skillSummary).length > 0 ? (
          <div>
            <h3 className="mb-3 text-sm font-semibold">Skill 表现</h3>
            <div className="grid gap-3 md:grid-cols-2">
              {Object.entries(skillSummary).map(([name, sk]) => (
                <div key={name} className="rounded-md border border-border bg-card p-3 text-sm">
                  <div className="font-medium">{name}</div>
                  <div className="mt-2 text-xs text-muted-foreground">
                    使用 {sk.use_count as number} 次，平均置信度 {((sk.avg_confidence as number ?? 0) * 100).toFixed(0)}%
                  </div>
                  {sk.suggestion ? (
                    <div className="mt-1 text-xs text-amber-700">{sk.suggestion as string}</div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {suggestions && suggestions.length > 0 ? (
          <div>
            <h3 className="mb-3 text-sm font-semibold">改进建议</h3>
            <div className="space-y-2">
              {suggestions.map((s, idx) => (
                <div key={idx} className="rounded-md bg-muted/40 border border-border p-3 text-xs">
                  {s}
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
