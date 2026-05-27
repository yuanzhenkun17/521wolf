import { ScrollText } from "lucide-react";
import { Badge } from "./ui/badge";
import { DecisionDetails } from "./DecisionDetails";
import { speechLabel } from "./shared";
import { roleName } from "../presentation";
import type { Presentation, SpeechTurn } from "../presentation";
import type { Player } from "../types";

export function SpeechStage({ presentation, players, archiveMap }: { presentation: Presentation; players: Player[]; archiveMap?: Map<number, Record<string, unknown>> }) {
  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_220px]">
      <div className="max-h-[680px] overflow-y-auto rounded-lg border border-border bg-muted/30 p-5">
        {presentation.speeches.length > 0 ? (
          <div className="space-y-4">
            {presentation.speeches.map((speech) => (
              <div key={speech.index} className={speech.index === presentation.currentSpeech?.index ? "rounded-lg bg-card p-4 shadow-sm" : "rounded-lg bg-muted/40 p-4"}>
                <SpeechBubble speech={speech} role={players.find((player) => player.id === speech.speakerId)?.role} compact={speech.index !== presentation.currentSpeech?.index} archiveMap={archiveMap} />
              </div>
            ))}
          </div>
        ) : (
          <div className="flex min-h-80 items-center justify-center text-sm text-muted-foreground">等待玩家发言</div>
        )}
      </div>
      <SpeechQueue speeches={presentation.speeches} />
    </div>
  );
}

export function SpeechBubble({ speech, role, compact = false, archiveMap }: { speech: SpeechTurn; role?: string; compact?: boolean; archiveMap?: Map<number, Record<string, unknown>> }) {
  return (
    <article className={compact ? "" : "border-l-2 border-emerald-300 pl-3"}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge>{speech.speakerId} 号玩家</Badge>
        {role ? <Badge variant="outline">{roleName(role)}</Badge> : null}
        <span className="text-xs text-muted-foreground">{speechLabel(speech.actionType)}</span>
      </div>
      <p className={compact ? "mt-3 whitespace-pre-wrap text-sm leading-7" : "mt-5 whitespace-pre-wrap text-lg leading-9"}>{speech.text}</p>
      <DecisionDetails decisions={speech.decision ? [speech.decision] : []} archiveMap={archiveMap} />
    </article>
  );
}

function SpeechQueue({ speeches }: { speeches: SpeechTurn[] }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-semibold">发言顺序</div>
        <ScrollText className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="space-y-2">
        {speeches.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无发言</p>
        ) : (
          speeches.map((speech) => (
            <div key={speech.index} className="rounded-md bg-muted/40 px-3 py-2 text-sm">
              <span className="font-medium">{speech.speakerId} 号</span>
              <span className="ml-2 text-xs text-muted-foreground">{speechLabel(speech.actionType)}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
