import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { phaseName } from "../presentation";
import type { GameSnapshot } from "../types";

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-border bg-muted/40 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

export function StatusPanel({ snapshot, aliveCount, deadCount }: { snapshot: GameSnapshot | null; aliveCount: number; deadCount: number }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>对局状态</CardTitle>
        <Badge variant={snapshot?.status === "running" ? "default" : "secondary"}>{snapshot?.status ?? "idle"}</Badge>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 text-sm">
        <Metric label="存活" value={aliveCount} />
        <Metric label="出局" value={deadCount} />
        <Metric label="警长" value={snapshot?.sheriff_id ?? "-"} />
        <Metric label="环节" value={phaseName(snapshot?.phase ?? "setup")} />
      </CardContent>
    </Card>
  );
}
