import { BadgeCheck, ChevronRight, Crown, Moon, Star, Sun, Vote } from "lucide-react";
import { Button } from "./ui/button";
import { AliveStrip } from "./AliveStrip";
import { PageNav } from "./PageNav";
import { NightStage } from "./NightStage";
import { SpeechStage } from "./SpeechStage";
import { VoteStage } from "./VoteStage";
import { SheriffResultStage } from "./SheriffResultStage";
import { ResultStage } from "./ResultStage";
import { phaseName, type Presentation } from "../presentation";
import type { GamePage } from "../gamePages";
import type { ArchiveMap, Player } from "../types";

export function GameStage({
  page,
  pages,
  presentation,
  players,
  archiveMap,
  followLatest,
  onSelectPage,
  onFollowLatest,
}: {
  page: GamePage;
  pages: GamePage[];
  presentation: Presentation;
  players: Player[];
  archiveMap?: ArchiveMap;
  followLatest: boolean;
  onSelectPage: (pageId: string) => void;
  onFollowLatest: () => void;
}) {
  return (
    <section className="min-h-[calc(100vh-118px)] overflow-hidden rounded-lg border border-border bg-card shadow-sm">
      <div className={stageHeaderClass(presentation.stage)}>
        <div>
          <div className="flex items-center gap-2 text-sm opacity-80">
            {stageIcon(presentation.stage)}
            <span>{phaseName(presentation.phase)}</span>
          </div>
          <h2 className="mt-2 text-3xl font-semibold">{presentation.title}</h2>
          <p className="mt-2 text-sm opacity-80">{presentation.subtitle}</p>
        </div>
        {!followLatest ? (
          <Button variant="secondary" onClick={onFollowLatest}>
            回到当前
          </Button>
        ) : null}
      </div>
      <PageNav pages={pages} selectedPageId={page.id} onSelectPage={onSelectPage} />
      <div className="p-5">
        <AliveStrip alivePlayerIds={presentation.alivePlayerIds} deadPlayerIds={presentation.deadPlayerIds} players={players} />
        {presentation.stage === "night" ? <NightStage presentation={presentation} archiveMap={archiveMap} /> : null}
        {presentation.stage === "day" || presentation.stage === "sheriff" ? <SpeechStage presentation={presentation} players={players} archiveMap={archiveMap} /> : null}
        {presentation.stage === "sheriff_result" ? <SheriffResultStage presentation={presentation} players={players} archiveMap={archiveMap} /> : null}
        {presentation.stage === "vote" ? <VoteStage presentation={presentation} players={players} archiveMap={archiveMap} /> : null}
        {presentation.stage === "result" ? <ResultStage presentation={presentation} players={players} /> : null}
        {presentation.stage === "setup" ? <SetupStage /> : null}
      </div>
    </section>
  );
}

function SetupStage() {
  return <div className="flex min-h-96 items-center justify-center text-sm text-muted-foreground">点击右上角开始一局新的狼人杀。</div>;
}

function stageHeaderClass(stage: Presentation["stage"]) {
  const base = "flex min-h-44 items-end justify-between px-6 py-6 text-white";
  if (stage === "night") return `${base} bg-slate-950`;
  if (stage === "vote") return `${base} bg-amber-700`;
  if (stage === "result") return `${base} bg-emerald-800`;
  if (stage === "sheriff") return `${base} bg-indigo-800`;
  return `${base} bg-sky-800`;
}

function stageIcon(stage: Presentation["stage"]) {
  if (stage === "night") return <Moon className="h-4 w-4" />;
  if (stage === "vote") return <Vote className="h-4 w-4" />;
  if (stage === "result") return <BadgeCheck className="h-4 w-4" />;
  if (stage === "sheriff") return <Crown className="h-4 w-4" />;
  return <Sun className="h-4 w-4" />;
}
