import { Star } from "lucide-react";
import { roleName } from "../presentation";
import type { Player } from "../types";

export function AliveStrip({
  alivePlayerIds,
  deadPlayerIds,
  players,
}: {
  alivePlayerIds: number[];
  deadPlayerIds: number[];
  players: Player[];
}) {
  const allPlayerIds = [...alivePlayerIds, ...deadPlayerIds].sort((left, right) => left - right);
  if (allPlayerIds.length === 0) return null;
  return (
    <div className="mb-5 rounded-lg border border-border bg-card/60 p-4">
      <div className="mb-3 text-sm font-semibold">当前玩家状态</div>
      <div className="flex flex-wrap gap-2">
        {allPlayerIds.map((playerId) => {
          const player = players.find((item) => item.id === playerId);
          const dead = deadPlayerIds.includes(playerId);
          const isSheriff = Boolean(player?.is_sheriff);
          return (
            <span
              key={playerId}
              className={dead
                ? "inline-flex items-center gap-1 rounded-md border border-border bg-muted py-0.5 pl-2 pr-2 text-xs font-semibold text-muted-foreground line-through"
                : "inline-flex items-center gap-1 rounded-md border border-secondary/30 bg-secondary/10 py-0.5 pl-2 pr-2 text-xs font-semibold text-secondary-foreground"
              }
            >
              {isSheriff && !dead ? (
                <Star className="absolute -right-1 -top-1 h-3.5 w-3.5 fill-amber-400 text-amber-400" />
              ) : null}
              {playerId}号{player ? ` · ${roleName(player.role)}` : ""}{dead ? " · 出局" : ""}
            </span>
          );
        })}
      </div>
    </div>
  );
}
