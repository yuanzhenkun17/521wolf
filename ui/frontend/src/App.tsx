import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, BadgeCheck, ChevronRight, Crown, Loader2, Moon, Play, ScrollText, Shield, Skull, Star, Sun, Vote } from "lucide-react";
import { getGame, listGames, startGame } from "./api";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import { buildGamePages, latestPageId, type GamePage } from "./gamePages";
import { phaseName, roleName, teamName, type Presentation, type SpeechTurn } from "./presentation";
import type { AgentDecision, GameEvent, GameSnapshot, Player } from "./types";

export function App() {
  const [snapshot, setSnapshot] = useState<GameSnapshot | null>(null);
  const [events, setEvents] = useState<GameEvent[]>([]);
  const [games, setGames] = useState<GameSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [selectedPageId, setSelectedPageId] = useState("setup");
  const [followLatest, setFollowLatest] = useState(true);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    listGames()
      .then((items) => {
        setGames(items);
        if (items.length > 0) void loadGame(items[0].game_id);
      })
      .catch((exc: Error) => setError(exc.message));
  }, []);

  useEffect(() => () => eventSourceRef.current?.close(), []);

  const pages = useMemo(() => buildGamePages(snapshot, events), [snapshot, events]);
  const newestPageId = useMemo(() => latestPageId(pages), [pages]);
  useEffect(() => {
    if (followLatest || !pages.some((page) => page.id === selectedPageId)) {
      setSelectedPageId(newestPageId);
    }
  }, [followLatest, newestPageId, pages, selectedPageId]);
  const selectedPage = useMemo(
    () => pages.find((page) => page.id === selectedPageId) ?? pages[pages.length - 1],
    [pages, selectedPageId],
  );
  const presentation = selectedPage.presentation;
  const aliveCount = useMemo(() => snapshot?.players.filter((player) => player.alive).length ?? 0, [snapshot]);
  const deadCount = useMemo(() => snapshot?.players.filter((player) => !player.alive).length ?? 0, [snapshot]);

  async function loadGame(gameId: string) {
    eventSourceRef.current?.close();
    const loaded = await getGame(gameId);
    setSnapshot(loaded);
    setEvents(loaded.events ?? []);
    setFollowLatest(true);
    if (loaded.status === "running" || loaded.status === "starting") connectEvents(loaded.game_id);
  }

  async function handleStart() {
    setStarting(true);
    setError(null);
    try {
      const created = await startGame();
      setSnapshot(created);
      setEvents([]);
      setFollowLatest(true);
      setGames((items) => [created, ...items.filter((item) => item.game_id !== created.game_id)]);
      connectEvents(created.game_id);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "启动失败");
    } finally {
      setStarting(false);
    }
  }

  function connectEvents(gameId: string) {
    eventSourceRef.current?.close();
    const source = new EventSource(`/api/games/${gameId}/events`);
    eventSourceRef.current = source;

    source.addEventListener("log", (message) => {
      const event = JSON.parse(message.data) as GameEvent;
      setEvents((items) => (items.some((item) => item.index === event.index) ? items : [...items, event]));
      void getGame(gameId).then(setSnapshot).catch(() => undefined);
    });

    source.addEventListener("done", (message) => {
      const doneSnapshot = JSON.parse(message.data) as GameSnapshot;
      setSnapshot(doneSnapshot);
      source.close();
      void listGames().then(setGames).catch(() => undefined);
    });

    source.addEventListener("error", () => {
      setError("实时连接中断");
      source.close();
    });
  }

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-10 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold">521wolf 上帝视角</h1>
              <Badge variant="outline">全身份可见</Badge>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              {snapshot ? `${snapshot.log_name} · 第 ${presentation.day} 天 · ${phaseName(snapshot.phase)}` : "等待开局"}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {snapshot?.winner ? <Badge>{snapshot.winner === "werewolves" ? "狼人胜利" : "好人胜利"}</Badge> : null}
            <Button onClick={handleStart} disabled={starting || snapshot?.status === "running"}>
              {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              开始新局
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-5 px-5 py-5 lg:grid-cols-[320px_1fr_300px]">
        <section className="space-y-5">
          <StatusPanel snapshot={snapshot} aliveCount={aliveCount} deadCount={deadCount} />
          <PlayersPanel players={snapshot?.players ?? []} />
        </section>

        <GameStage
          page={selectedPage}
          pages={pages}
          presentation={presentation}
          players={snapshot?.players ?? []}
          followLatest={followLatest}
          onSelectPage={(pageId) => {
            setSelectedPageId(pageId);
            setFollowLatest(false);
          }}
          onFollowLatest={() => setFollowLatest(true)}
        />

        <aside className="space-y-5">
          <KeyEventsPanel presentation={presentation} />
          <GamesPanel games={games} onLoad={(gameId) => void loadGame(gameId)} />
          {error ? <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{error}</div> : null}
        </aside>
      </div>
    </main>
  );
}

function StatusPanel({ snapshot, aliveCount, deadCount }: { snapshot: GameSnapshot | null; aliveCount: number; deadCount: number }) {
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

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

function PlayersPanel({ players }: { players: Player[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>玩家席位</CardTitle>
        <Shield className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-2">
        {players.map((player) => (
          <div key={player.id} className={playerCardClass(player)}>
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

function playerCardClass(player: Player) {
  const base = "min-h-24 rounded-md border p-3 text-sm transition-colors";
  if (!player.alive) return `${base} border-border bg-muted text-muted-foreground`;
  if (player.team === "werewolves") return `${base} border-rose-300 bg-rose-50 text-rose-950`;
  if (player.team === "gods") return `${base} border-emerald-300 bg-emerald-50 text-emerald-950`;
  return `${base} border-sky-300 bg-sky-50 text-sky-950`;
}

function GameStage({
  page,
  pages,
  presentation,
  players,
  followLatest,
  onSelectPage,
  onFollowLatest,
}: {
  page: GamePage;
  pages: GamePage[];
  presentation: Presentation;
  players: Player[];
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
        {presentation.stage === "night" ? <NightStage presentation={presentation} /> : null}
        {presentation.stage === "day" || presentation.stage === "sheriff" ? <SpeechStage presentation={presentation} players={players} /> : null}
        {presentation.stage === "sheriff_result" ? <SheriffResultStage presentation={presentation} players={players} /> : null}
        {presentation.stage === "vote" ? <VoteStage presentation={presentation} players={players} /> : null}
        {presentation.stage === "result" ? <ResultStage presentation={presentation} players={players} /> : null}
        {presentation.stage === "setup" ? <SetupStage /> : null}
      </div>
    </section>
  );
}

function AliveStrip({
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
    <div className="mb-5 rounded-lg border border-border bg-muted/30 p-4">
      <div className="mb-3 text-sm font-semibold">当前玩家状态</div>
      <div className="flex flex-wrap gap-2">
        {allPlayerIds.map((playerId) => {
          const player = players.find((item) => item.id === playerId);
          const dead = deadPlayerIds.includes(playerId);
          const isSheriff = Boolean(player?.is_sheriff);
          return (
            <span
              key={playerId}
              className={
                dead
                  ? "relative inline-flex items-center rounded-md border border-border bg-muted py-0.5 pl-2 pr-2 text-xs font-semibold text-muted-foreground line-through"
                  : "relative inline-flex items-center rounded-md border border-transparent bg-secondary py-0.5 pl-2 pr-2 text-xs font-semibold text-secondary-foreground"
              }
            >
              {isSheriff ? (
                <Star className="absolute -right-1 -top-1 h-3.5 w-3.5 fill-amber-400 text-amber-500 drop-shadow-sm" />
              ) : null}
              {playerId}号{player ? ` · ${roleName(player.role)}` : ""}{dead ? " · 出局" : ""}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function PageNav({
  pages,
  selectedPageId,
  onSelectPage,
}: {
  pages: GamePage[];
  selectedPageId: string;
  onSelectPage: (pageId: string) => void;
}) {
  return (
    <div className="border-b border-border bg-muted/30 px-4 py-3">
      <div className="flex gap-2 overflow-x-auto pb-1">
        {pages.map((page) => (
          <button
            key={page.id}
            className={
              page.id === selectedPageId
                ? "shrink-0 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
                : "shrink-0 rounded-md border border-border bg-card px-3 py-2 text-sm hover:bg-muted"
            }
            onClick={() => onSelectPage(page.id)}
          >
            {page.label}
          </button>
        ))}
      </div>
    </div>
  );
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

function NightStage({ presentation }: { presentation: Presentation }) {
  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-slate-200 bg-slate-950 p-6 text-white">
        <div className="flex items-center gap-3">
          <Moon className="h-8 w-8 text-sky-200" />
          <div>
            <div className="text-lg font-semibold">天黑请闭眼</div>
            <div className="text-sm text-slate-300">守卫、狼人、预言家、女巫正在行动</div>
          </div>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {presentation.nightActions.length === 0 ? (
          <div className="rounded-md border border-border p-4 text-sm text-muted-foreground">暂无夜间行动记录</div>
        ) : (
          presentation.nightActions.map((action) => (
            <div key={`${action.label}-${action.detail}`} className="rounded-md border border-border p-4">
              <Badge variant="outline">{action.label}</Badge>
              <p className="mt-3 text-sm leading-6">{action.detail}</p>
              <DecisionDetails decisions={action.decisions} />
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
    <div className="rounded-md border border-border bg-muted/50 p-4">
      <div className="text-sm font-semibold">天亮结果</div>
      <div className="mt-2 text-sm text-muted-foreground">{deaths.length > 0 ? `${deaths.join("、")} 号玩家出局` : "昨夜平安夜"}</div>
    </div>
  );
}

function SpeechStage({ presentation, players }: { presentation: Presentation; players: Player[] }) {
  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_220px]">
      <div className="max-h-[680px] overflow-y-auto rounded-lg border border-border bg-muted/30 p-5">
        {presentation.speeches.length > 0 ? (
          <div className="space-y-4">
            {presentation.speeches.map((speech) => (
              <div key={speech.index} className={speech.index === presentation.currentSpeech?.index ? "rounded-lg bg-card p-4 shadow-sm" : "rounded-lg bg-card/70 p-4"}>
                <SpeechBubble speech={speech} role={players.find((player) => player.id === speech.speakerId)?.role} compact={speech.index !== presentation.currentSpeech?.index} />
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

function SpeechBubble({ speech, role, compact = false }: { speech: SpeechTurn; role?: string; compact?: boolean }) {
  return (
    <article>
      <div className="flex flex-wrap items-center gap-2">
        <Badge>{speech.speakerId} 号玩家</Badge>
        {role ? <Badge variant="outline">{roleName(role)}</Badge> : null}
        <span className="text-xs text-muted-foreground">{speechLabel(speech.actionType)}</span>
      </div>
      <p className={compact ? "mt-3 whitespace-pre-wrap text-sm leading-7" : "mt-5 whitespace-pre-wrap text-lg leading-9"}>{speech.text}</p>
      <DecisionDetails decisions={speech.decision ? [speech.decision] : []} />
    </article>
  );
}

function SpeechQueue({ speeches }: { speeches: SpeechTurn[] }) {
  return (
    <div className="rounded-lg border border-border p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-semibold">发言顺序</div>
        <ScrollText className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="space-y-2">
        {speeches.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无发言</p>
        ) : (
          speeches.map((speech) => (
            <div key={speech.index} className="rounded-md bg-muted px-3 py-2 text-sm">
              <span className="font-medium">{speech.speakerId} 号</span>
              <span className="ml-2 text-xs text-muted-foreground">{speechLabel(speech.actionType)}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function speechLabel(actionType: string) {
  if (actionType === "sheriff_run") return "是否上警";
  if (actionType === "sheriff_withdraw") return "退水选择";
  if (actionType === "sheriff_speak") return "警上发言";
  if (actionType === "pk_speak") return "PK 发言";
  if (actionType === "last_word") return "遗言";
  if (actionType === "sheriff_vote") return "警长投票";
  if (actionType === "pk_vote") return "PK 投票";
  if (actionType === "exile_vote") return "放逐投票";
  if (actionType === "guard_protect") return "守卫守护";
  if (actionType === "werewolf_kill") return "狼人刀人";
  if (actionType === "seer_check") return "预言家查验";
  if (actionType === "witch_act") return "女巫行动";
  if (actionType === "hunter_shoot") return "猎人开枪";
  if (actionType === "white_wolf_explode") return "白狼王自爆";
  if (actionType === "sheriff_badge") return "警徽处理";
  if (actionType === "speech_order") return "发言顺序";
  return "白天发言";
}

function VoteStage({ presentation, players }: { presentation: Presentation; players: Player[] }) {
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
            <div key={targetId} className="rounded-lg border border-border p-4">
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
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
      {presentation.currentSpeech ? (
        <div className="rounded-lg border border-border bg-muted/30 p-5">
          <SpeechBubble speech={presentation.currentSpeech} role={players.find((player) => player.id === presentation.currentSpeech?.speakerId)?.role} />
        </div>
      ) : null}
    </div>
  );
}

function VoteDecisionLine({
  voterId,
  isAbstain,
  decision,
}: {
  voterId: number;
  isAbstain: boolean;
  decision?: AgentDecision;
}) {
  return (
    <div className="min-w-0 rounded-md bg-secondary px-2 py-1.5">
      <Badge variant="secondary">
        {voterId} 号{isAbstain ? "弃票" : "投票"}
      </Badge>
      <DecisionDetails decisions={decision ? [decision] : []} compact />
    </div>
  );
}

function DecisionDetails({ decisions, compact = false }: { decisions: AgentDecision[]; compact?: boolean }) {
  if (decisions.length === 0) return null;
  return (
    <details className={compact ? "group mt-2 text-xs" : "group mt-4 rounded-md border border-border bg-muted/30 p-3 text-sm"}>
      <summary className="flex cursor-pointer list-none items-center gap-1.5 font-medium text-muted-foreground marker:hidden">
        <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
        决策过程
        {decisions.length > 1 ? <span className="text-xs font-normal">({decisions.length})</span> : null}
      </summary>
      <div className={compact ? "mt-2 space-y-2 text-muted-foreground" : "mt-3 space-y-3"}>
        {decisions.map((decision) => (
          <DecisionBody key={decision.index} decision={decision} />
        ))}
      </div>
    </details>
  );
}

function DecisionBody({ decision }: { decision: AgentDecision }) {
  return (
    <div className="rounded-md border border-border bg-card p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{decision.player_id ?? "-"} 号</Badge>
        <Badge variant="secondary">{roleName(decision.role)}</Badge>
        <span className="text-xs text-muted-foreground">{speechLabel(decision.action_type)}</span>
        <span className="text-xs text-muted-foreground">{decisionSourceName(decision.source)}</span>
      </div>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-6">{decision.private_reasoning}</p>
      <div className="mt-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
        <DecisionMeta label="选择" value={decisionChoiceText(decision)} />
        <DecisionMeta label="候选" value={decision.candidates.length > 0 ? decision.candidates.join("、") : "-"} />
        <DecisionMeta label="备选" value={decision.alternatives.length > 0 ? decision.alternatives.join("、") : "-"} />
        <DecisionMeta label="记忆" value={decision.memory_summary.length > 0 ? decision.memory_summary.slice(-2).join("；") : "-"} />
      </div>
      {decision.rejected_reasons.length > 0 ? (
        <div className="mt-3 text-xs text-muted-foreground">排除理由：{decision.rejected_reasons.join("；")}</div>
      ) : null}
    </div>
  );
}

function DecisionMeta({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-sm bg-muted px-2 py-1">
      <span className="font-medium text-foreground">{label}：</span>
      <span className="break-words">{value}</span>
    </div>
  );
}

function decisionChoiceText(decision: AgentDecision) {
  if (decision.selected_target !== null) return `${decision.selected_target} 号`;
  if (decision.selected_choice) return decision.selected_choice;
  return "-";
}

function decisionSourceName(source: AgentDecision["source"]) {
  if (source === "fallback") return "回退决策";
  if (source === "policy_adjusted") return "策略修正";
  return "LLM 决策";
}

function SheriffResultStage({ presentation, players }: { presentation: Presentation; players: Player[] }) {
  const withdraws = presentation.keyEvents.filter((event) => {
    const actionType = typeof event.payload.action_type === "string" ? event.payload.action_type : "";
    return event.event_type === "action_response" && actionType === "sheriff_withdraw";
  });
  const electionEnd = presentation.keyEvents.find((event) => event.event_type === "sheriff_election_end");
  const winner = electionEnd?.payload.winner;
  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-border bg-muted/30 p-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm text-muted-foreground">最终警长</div>
            <div className="mt-1 text-2xl font-semibold">{typeof winner === "number" ? `${winner} 号` : "无人当选"}</div>
          </div>
          {typeof winner === "number" ? <Badge>{roleName(players.find((player) => player.id === winner)?.role ?? "")}</Badge> : null}
        </div>
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <div className="rounded-lg border border-border p-4">
          <div className="mb-3 text-sm font-semibold">退水情况</div>
          {withdraws.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无退水记录</p>
          ) : (
            <div className="space-y-2">
              {withdraws.map((event) => (
                <div key={event.index} className="flex items-center justify-between rounded-md bg-muted px-3 py-2 text-sm">
                  <span>{event.actor} 号</span>
                  <Badge variant={event.payload.choice === "withdraw" ? "secondary" : "outline"}>
                    {event.payload.choice === "withdraw" ? "退水" : "留在警上"}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </div>
        <VoteStage presentation={presentation} players={players} />
      </div>
    </div>
  );
}

function ResultStage({ presentation, players }: { presentation: Presentation; players: Player[] }) {
  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-border bg-muted/40 p-5">
        <div className="text-2xl font-semibold">{presentation.winner === "werewolves" ? "狼人胜利" : "好人胜利"}</div>
        <p className="mt-2 text-sm text-muted-foreground">全局身份如下。</p>
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

function SetupStage() {
  return <div className="flex min-h-96 items-center justify-center text-sm text-muted-foreground">点击右上角开始一局新的狼人杀。</div>;
}

function KeyEventsPanel({ presentation }: { presentation: Presentation }) {
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
            <div key={event.index} className="rounded-md border border-border p-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium">第 {event.day} 天</span>
                <Badge variant="outline">{phaseName(event.phase)}</Badge>
              </div>
              <div className="mt-2 text-muted-foreground">{event.message}</div>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

function GamesPanel({ games, onLoad }: { games: GameSnapshot[]; onLoad: (gameId: string) => void }) {
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
