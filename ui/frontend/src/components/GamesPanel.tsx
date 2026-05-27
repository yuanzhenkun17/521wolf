import { Skull } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import type { GameSnapshot } from "../types";

export function GamesPanel({ games, onLoad }: { games: GameSnapshot[]; onLoad: (gameId: string) => void }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>历史对局</CardTitle>
        <Skull className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent className="space-y-2">
        {games.slice(0, 8).map((game) => (
          <button
            key={game.game_id}
            className="flex w-full items-center justify-between rounded-md px-2 py-2 text-left text-sm hover:bg-muted"
            onClick={() => onLoad(game.game_id)}
          >
            <span>{game.log_name}</span>
            <span className="text-xs text-muted-foreground">{game.winner ?? game.status}</span>
          </button>
        ))}
      </CardContent>
    </Card>
  );
}
