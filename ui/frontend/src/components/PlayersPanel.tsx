import { Crown, Shield, Skull } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { roleName, teamName } from "../presentation";
import type { Player } from "../types";

function playerCardClass(player: Player) {
  const base = "min-h-24 rounded-md border p-3 text-sm transition-colors";
  if (!player.alive) return `${base} border-border bg-muted text-muted-foreground`;
  if (player.team === "werewolves") return `${base} border-rose-300 bg-rose-50 text-rose-950`;
  if (player.team === "gods") return `${base} border-emerald-300 bg-emerald-50 text-emerald-950`;
  return `${base} border-sky-300 bg-sky-50 text-sky-950`;
}

export { playerCardClass };

export function PlayersPanel({ players }: { players: Player[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>玩家席位</CardTitle>
        <Shield className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3">
        {players.map((player) => (
          <div key={player.id} className={`${playerCardClass(player)} relative`}>
            {!player.alive ? (
              <Skull className="absolute right-2 top-2 h-4 w-4 text-muted-foreground" />
            ) : null}
            <div className="flex items-center justify-between">
              <span className="font-semibold">{player.id} 号</span>
              {player.is_sheriff ? <Crown className="h-4 w-4 text-amber-500" /> : null}
            </div>
            <div className="mt-1 text-xs font-medium">{roleName(player.role)}</div>
            <div className="mt-2 text-xs opacity-75">{teamName(player.team)}</div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
