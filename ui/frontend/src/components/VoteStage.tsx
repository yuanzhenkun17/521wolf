import { Badge } from "./ui/badge";
import { DecisionDetails } from "./DecisionDetails";
import { SpeechBubble } from "./SpeechStage";
import { roleName } from "../presentation";
import type { Presentation } from "../presentation";
import type { AgentDecision, Player } from "../types";

export function VoteStage({ presentation, players, archiveMap }: { presentation: Presentation; players: Player[]; archiveMap?: Map<number, Record<string, unknown>> }) {
  const grouped = presentation.votes.reduce<Record<string, number[]>>((acc, vote) => {
    const key = vote.targetId === null ? "abstain" : String(vote.targetId);
    acc[key] = [...(acc[key] ?? []), vote.voterId];
    return acc;
  }, {});
  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-2">
        {Object.entries(grouped).map(([targetId, voterIds]) => {
          const isAbstain = targetId === "abstain";
          const target = isAbstain ? undefined : players.find((player) => player.id === Number(targetId));
          return (
            <div key={targetId} className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center justify-between">
                <div className="text-lg font-semibold">{isAbstain ? "弃票" : `${targetId} 号`}</div>
                {target ? <Badge variant="outline">{roleName(target.role)}</Badge> : null}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {voterIds.map((voterId) => (
                  <VoteDecisionLine
                    key={`${voterId}-${targetId}`}
                    voterId={voterId}
                    isAbstain={isAbstain}
                    decision={presentation.votes.find((vote) => vote.voterId === voterId)?.decision}
                    archiveMap={archiveMap}
                  />
                ))}
              </div>
              <div className="mt-2 text-xs text-muted-foreground">{voterIds.length} 票</div>
            </div>
          );
        })}
      </div>
      {presentation.currentSpeech ? (
        <div className="rounded-lg border border-border bg-card p-5">
          <SpeechBubble speech={presentation.currentSpeech} role={players.find((player) => player.id === presentation.currentSpeech?.speakerId)?.role} archiveMap={archiveMap} />
        </div>
      ) : null}
    </div>
  );
}

function VoteDecisionLine({
  voterId,
  isAbstain,
  decision,
  archiveMap,
}: {
  voterId: number;
  isAbstain: boolean;
  decision?: AgentDecision;
  archiveMap?: Map<number, Record<string, unknown>>;
}) {
  return (
    <div className="min-w-0 rounded-md bg-muted/40 px-2 py-1.5">
      <Badge variant="secondary">
        {voterId} 号{isAbstain ? "弃票" : "投票"}
      </Badge>
      <DecisionDetails decisions={decision ? [decision] : []} compact archiveMap={archiveMap} />
    </div>
  );
}
