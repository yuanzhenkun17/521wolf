import { Badge } from "./ui/badge";

export function LeaderboardPanel({
  data,
  onClose,
}: {
  data: Record<string, unknown> | null;
  onClose: () => void;
}) {
  const entries = (data?.entries as Array<Record<string, unknown>> | undefined) ?? [];
  return (
    <section className="overflow-y-auto rounded-lg border border-border bg-card shadow-sm">
      <div className="border-b border-border bg-muted/30 px-6 py-4">
        <h2 className="text-xl font-semibold">版本排行榜</h2>
        <p className="mt-1 text-sm text-muted-foreground">多版本 Agent 效果对比</p>
      </div>
      <div className="p-5">
        {entries.length === 0 ? (
          <div className="flex min-h-64 items-center justify-center text-sm text-muted-foreground">暂无排行榜数据，请先运行版本对战。</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th className="pb-3 pr-4 font-medium">版本</th>
                  <th className="pb-3 pr-4 font-medium">局数</th>
                  <th className="pb-3 pr-4 font-medium">狼人胜率</th>
                  <th className="pb-3 pr-4 font-medium">好人胜率</th>
                  <th className="pb-3 pr-4 font-medium">总分</th>
                  <th className="pb-3 pr-4 font-medium">发言</th>
                  <th className="pb-3 pr-4 font-medium">投票</th>
                  <th className="pb-3 pr-4 font-medium">技能</th>
                  <th className="pb-3 pr-4 font-medium">Fallback率</th>
                  <th className="pb-3 font-medium">Policy修正率</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry, idx) => (
                  <tr key={idx} className="border-b border-border/50 last:border-0 hover:bg-muted/30 transition-colors">
                    <td className="py-3 pr-4 font-medium font-mono">{entry.version as string}</td>
                    <td className="py-3 pr-4 font-mono">{entry.games as number}</td>
                    <td className="py-3 pr-4 font-mono">{((entry.werewolf_win_rate as number ?? 0) * 100).toFixed(0)}%</td>
                    <td className="py-3 pr-4 font-mono">{((entry.villager_win_rate as number ?? 0) * 100).toFixed(0)}%</td>
                    <td className="py-3 pr-4 font-semibold font-mono">{(entry.avg_score as number ?? 0).toFixed(1)}</td>
                    <td className="py-3 pr-4 font-mono">{(entry.avg_speech_score as number ?? 0).toFixed(1)}</td>
                    <td className="py-3 pr-4 font-mono">{(entry.avg_vote_score as number ?? 0).toFixed(1)}</td>
                    <td className="py-3 pr-4 font-mono">{(entry.avg_skill_score as number ?? 0).toFixed(1)}</td>
                    <td className="py-3 pr-4 font-mono">{((entry.fallback_rate as number ?? 0) * 100).toFixed(1)}%</td>
                    <td className="py-3 font-mono">{((entry.policy_adjusted_rate as number ?? 0) * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
