import { Shield, Swords } from "lucide-react";
import { playerCardClass } from "./PlayersPanel";
import { roleName, teamName } from "../presentation";
import type { Presentation } from "../presentation";
import type { Player } from "../types";

export function ResultStage({ presentation, players }: { presentation: Presentation; players: Player[] }) {
  const isWolfWin = presentation.winner === "werewolves";
  return (
    <div className="space-y-5">
      <div className={`rounded-lg border p-5 ${isWolfWin ? "border-rose-200 bg-rose-50" : "border-emerald-200 bg-emerald-50"}`}>
        <div className="flex items-center gap-3">
          {isWolfWin ? (
            <Swords className="h-8 w-8 text-rose-600" />
          ) : (
            <Shield className="h-8 w-8 text-emerald-600" />
          )}
          <div>
            <div className={`text-2xl font-semibold ${isWolfWin ? "text-rose-900" : "text-emerald-900"}`}>
              {isWolfWin ? "狼人胜利" : "好人胜利"}
            </div>
            <p className="mt-2 text-sm text-muted-foreground">全局身份如下。</p>
          </div>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {players.map((player) => (
          <div key={player.id} className={playerCardClass(player)}>
            <div className="font-semibold">{player.id} 号</div>
            <div className="mt-1 text-sm">{roleName(player.role)}</div>
            <div className="mt-2 text-xs opacity-75">{teamName(player.team)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
