import { Moon } from "lucide-react";
import { Badge } from "./ui/badge";
import { DecisionDetails } from "./DecisionDetails";
import type { Presentation } from "../presentation";

export function NightStage({ presentation, archiveMap }: { presentation: Presentation; archiveMap?: Map<number, Record<string, unknown>> }) {
  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-slate-200 bg-slate-950 p-6 text-white">
        <div className="flex items-center gap-3">
          <Moon className="h-8 w-8" />
          <div>
            <div className="text-lg font-semibold">天黑请闭眼</div>
            <div className="text-sm opacity-70">守卫、狼人、预言家、女巫正在行动</div>
          </div>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {presentation.nightActions.length === 0 ? (
          <div className="rounded-md border border-border bg-muted/40 p-4 text-sm text-muted-foreground">暂无夜间行动记录</div>
        ) : (
          presentation.nightActions.map((action) => (
            <div key={`${action.label}-${action.detail}`} className="rounded-md border border-border bg-card p-4">
              <Badge variant="outline">{action.label}</Badge>
              <p className="mt-3 text-sm leading-6">{action.detail}</p>
              <DecisionDetails decisions={action.decisions} archiveMap={archiveMap} />
            </div>
          ))
        )}
      </div>
      <DawnResult deaths={presentation.nightDeaths} />
    </div>
  );
}

function DawnResult({ deaths }: { deaths: number[] }) {
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 p-4">
      <div className="text-sm font-semibold text-amber-900">天亮结果</div>
      <div className="mt-2 text-sm text-amber-800">{deaths.length > 0 ? `${deaths.join("、")} 号玩家出局` : "昨夜平安夜"}</div>
    </div>
  );
}
