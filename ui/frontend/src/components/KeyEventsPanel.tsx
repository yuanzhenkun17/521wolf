import { Activity } from "lucide-react";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { phaseName } from "../presentation";
import type { Presentation } from "../presentation";

export function KeyEventsPanel({ presentation }: { presentation: Presentation }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>关键事件</CardTitle>
        <Activity className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent className="space-y-3">
        {presentation.keyEvents.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无</p>
        ) : (
          presentation.keyEvents.map((event) => (
            <div key={event.index} className="rounded-md border border-border p-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-medium text-muted-foreground">第 {event.day} 天</span>
                <Badge variant="outline">{phaseName(event.phase)}</Badge>
              </div>
              <div className="mt-2 text-sm">{event.message}</div>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
