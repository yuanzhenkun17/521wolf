import { Badge } from "./ui/badge";
import { VoteStage } from "./VoteStage";
import { roleName } from "../presentation";
import type { Presentation } from "../presentation";
import type { ArchiveMap, Player } from "../types";

export function SheriffResultStage({ presentation, players, archiveMap }: { presentation: Presentation; players: Player[]; archiveMap?: ArchiveMap }) {
  const withdraws = presentation.keyEvents.filter((event) => {
    const actionType = typeof event.payload.action_type === "string" ? event.payload.action_type : "";
    return event.event_type === "action_response" && actionType === "sheriff_withdraw";
  });
  const electionEnd = presentation.keyEvents.find((event) => event.event_type === "sheriff_election_end");
  const winner = electionEnd?.payload.winner;
  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm text-amber-700">最终警长</div>
            <div className="mt-1 text-2xl font-semibold text-amber-900">{typeof winner === "number" ? `${winner} 号` : "无人当选"}</div>
          </div>
          {typeof winner === "number" ? <Badge className="bg-amber-600 text-white">{roleName(players.find((player) => player.id === winner)?.role ?? "")}</Badge> : null}
        </div>
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 text-sm font-semibold">退水情况</div>
          {withdraws.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无退水记录</p>
          ) : (
            <div className="space-y-2">
              {withdraws.map((event) => (
                <div key={event.index} className="flex items-center justify-between rounded-md bg-muted/40 px-3 py-2 text-sm">
                  <span>{event.actor} 号</span>
                  <Badge variant={event.payload.choice === "withdraw" ? "secondary" : "outline"}>
                    {event.payload.choice === "withdraw" ? "退水" : "留在警上"}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </div>
        <VoteStage presentation={presentation} players={players} archiveMap={archiveMap} />
      </div>
    </div>
  );
}
