import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, BadgeCheck, Bug, ChevronRight, Crown, Loader2, Moon, Play, ScrollText, Shield, Skull, Star, Sun, Vote, Trophy } from "lucide-react";
import { getGame, getGameArchive, getGameReview, getLeaderboard, listGames, startGame } from "./api";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import { DebugPanel } from "./components/DebugPanel";
import { buildGamePages, latestPageId, type GamePage } from "./gamePages";
import { phaseName, roleName, teamName, type Presentation, type SpeechTurn } from "./presentation";
import type { AgentDecision, GameArchive, GameEvent, GameSnapshot, Player } from "./types";

export function App() {
  const [snapshot, setSnapshot] = useState<GameSnapshot | null>(null);
  const [events, setEvents] = useState<GameEvent[]>([]);
  const [games, setGames] = useState<GameSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [selectedPageId, setSelectedPageId] = useState("setup");
  const [followLatest, setFollowLatest] = useState(true);
  const [reviewData, setReviewData] = useState<Record<string, unknown> | null>(null);
  const [showReview, setShowReview] = useState(false);
  const [leaderboardData, setLeaderboardData] = useState<Record<string, unknown> | null>(null);
  const [showLeaderboard, setShowLeaderboard] = useState(false);
  const [showDebug, setShowDebug] = useState(false);
  const [archiveData, setArchiveData] = useState<GameArchive | null>(null);
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
  const archiveMap = useMemo(() => {
    if (!archiveData?.decisions) return undefined;
    const map = new Map<number, Record<string, unknown>>();
    for (const entry of archiveData.decisions) {
      const idx = entry.index as number | undefined;
      if (idx !== undefined) map.set(idx, entry);
    }
    return map;
  }, [archiveData]);
  const aliveCount = useMemo(() => snapshot?.players.filter((player) => player.alive).length ?? 0, [snapshot]);
  const deadCount = useMemo(() => snapshot?.players.filter((player) => !player.alive).length ?? 0, [snapshot]);

  async function loadGame(gameId: string) {
    eventSourceRef.current?.close();
    const loaded = await getGame(gameId);
    setSnapshot(loaded);
    setEvents(loaded.events ?? []);
    setFollowLatest(true);
    setArchiveData(null);
    // Load archive for completed games to enable rich decision details
    if (loaded.status === "completed" || loaded.winner) {
      void getGameArchive(gameId).then(setArchiveData).catch(() => setArchiveData(null));
    }
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
      void getGameArchive(gameId).then(setArchiveData).catch(() => setArchiveData(null));
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
            {snapshot?.winner && snapshot?.status !== "running" ? (
              <Button
                variant={showReview ? "default" : "secondary"}
                onClick={() => {
                  if (showReview) {
                    setShowReview(false);
                  } else {
                    setShowReview(true);
                    setReviewData(null);
                    void getGameReview(snapshot.game_id).then(setReviewData).catch(() => setReviewData(null));
                  }
                }}
              >
                <ScrollText className="h-4 w-4" />
                {showReview ? "返回对局" : "复盘"}
              </Button>
            ) : null}
            <Button
              variant={showLeaderboard ? "default" : "secondary"}
              onClick={() => {
                if (showLeaderboard) {
                  setShowLeaderboard(false);
                } else {
                  setShowReview(false);
                  setShowDebug(false);
                  setShowLeaderboard(true);
                  setLeaderboardData(null);
                  void getLeaderboard().then(setLeaderboardData).catch(() => setLeaderboardData(null));
                }
              }}
            >
              <Trophy className="h-4 w-4" />
              {showLeaderboard ? "返回对局" : "排行榜"}
            </Button>
            {snapshot?.status === "running" ? (
              <Button
                variant={showDebug ? "default" : "secondary"}
                onClick={() => {
                  setShowReview(false);
                  setShowLeaderboard(false);
                  setShowDebug((v) => !v);
                }}
              >
                <Bug className="h-4 w-4" />
                {showDebug ? "返回对局" : "决策流"}
              </Button>
            ) : null}
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

        {showLeaderboard ? (
          <LeaderboardPanel data={leaderboardData} onClose={() => setShowLeaderboard(false)} />
        ) : showReview ? (
          <ReviewPanel
            reviewData={reviewData}
            players={snapshot?.players ?? []}
            onClose={() => setShowReview(false)}
          />
        ) : showDebug ? (
          <DebugPanel active={showDebug} />
        ) : (
          <GameStage
            page={selectedPage}
            pages={pages}
            presentation={presentation}
            players={snapshot?.players ?? []}
            archiveMap={archiveMap}
            followLatest={followLatest}
            onSelectPage={(pageId) => {
              setSelectedPageId(pageId);
              setFollowLatest(false);
            }}
            onFollowLatest={() => setFollowLatest(true)}
          />
        )}

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
  archiveMap,
  followLatest,
  onSelectPage,
  onFollowLatest,
}: {
  page: GamePage;
  pages: GamePage[];
  presentation: Presentation;
  players: Player[];
  archiveMap?: Map<number, Record<string, unknown>>;
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

function NightStage({ presentation, archiveMap }: { presentation: Presentation; archiveMap?: Map<number, Record<string, unknown>> }) {
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
    <div className="rounded-md border border-border bg-muted/50 p-4">
      <div className="text-sm font-semibold">天亮结果</div>
      <div className="mt-2 text-sm text-muted-foreground">{deaths.length > 0 ? `${deaths.join("、")} 号玩家出局` : "昨夜平安夜"}</div>
    </div>
  );
}

function SpeechStage({ presentation, players, archiveMap }: { presentation: Presentation; players: Player[]; archiveMap?: Map<number, Record<string, unknown>> }) {
  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_220px]">
      <div className="max-h-[680px] overflow-y-auto rounded-lg border border-border bg-muted/30 p-5">
        {presentation.speeches.length > 0 ? (
          <div className="space-y-4">
            {presentation.speeches.map((speech) => (
              <div key={speech.index} className={speech.index === presentation.currentSpeech?.index ? "rounded-lg bg-card p-4 shadow-sm" : "rounded-lg bg-card/70 p-4"}>
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

function SpeechBubble({ speech, role, compact = false, archiveMap }: { speech: SpeechTurn; role?: string; compact?: boolean; archiveMap?: Map<number, Record<string, unknown>> }) {
  return (
    <article>
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

function VoteStage({ presentation, players, archiveMap }: { presentation: Presentation; players: Player[]; archiveMap?: Map<number, Record<string, unknown>> }) {
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
                    archiveMap={archiveMap}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
      {presentation.currentSpeech ? (
        <div className="rounded-lg border border-border bg-muted/30 p-5">
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
    <div className="min-w-0 rounded-md bg-secondary px-2 py-1.5">
      <Badge variant="secondary">
        {voterId} 号{isAbstain ? "弃票" : "投票"}
      </Badge>
      <DecisionDetails decisions={decision ? [decision] : []} compact archiveMap={archiveMap} />
    </div>
  );
}

function DecisionDetails({
  decisions,
  compact = false,
  archiveMap,
}: {
  decisions: AgentDecision[];
  compact?: boolean;
  archiveMap?: Map<number, Record<string, unknown>>;
}) {
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
          <DecisionBody key={decision.index} decision={decision} archiveEntry={archiveMap?.get(decision.index)} />
        ))}
      </div>
    </details>
  );
}

function DecisionBody({
  decision,
  archiveEntry,
}: {
  decision: AgentDecision;
  archiveEntry?: Record<string, unknown>;
}) {
  const ac = archiveEntry;
  const totCandidates = (ac?.tot_candidates as Array<Record<string, unknown>> | undefined) ?? [];
  const totJudgeReason = (ac?.tot_judge_reason as string | undefined) ?? "";
  const promptMessages = (ac?.prompt_messages as Array<Record<string, unknown>> | undefined) ?? [];
  const selectedSkills = (ac?.selected_skills as string[] | undefined) ?? [];
  const memoryContext = ac?.memory_context as Record<string, unknown> | undefined;
  const beliefContext = ac?.belief_context as Record<string, unknown> | undefined;
  return (
    <details className="group rounded-md border border-border bg-card p-3">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 marker:hidden">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{decision.player_id ?? "-"} 号</Badge>
          <Badge variant="secondary">{roleName(decision.role)}</Badge>
          <span className="text-xs text-muted-foreground">{speechLabel(decision.action_type)}</span>
          <span className="text-xs text-muted-foreground">{decisionSourceName(decision.source)}</span>
          {decision.confidence > 0 ? (
            <span className="text-xs text-muted-foreground">置信度: {(decision.confidence * 100).toFixed(0)}%</span>
          ) : null}
          {decision.selected_skill ? (
            <Badge variant="secondary" className="text-xs">{decision.selected_skill}</Badge>
          ) : null}
        </div>
        <ChevronRight className="h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-90" />
      </summary>
      <div className="mt-3 space-y-3">
        <p className="whitespace-pre-wrap text-sm leading-6">{decision.private_reasoning}</p>
        <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
          <DecisionMeta label="选择" value={decisionChoiceText(decision)} />
          <DecisionMeta label="候选" value={decision.candidates.length > 0 ? decision.candidates.join("、") : "-"} />
          <DecisionMeta label="备选" value={decision.alternatives.length > 0 ? decision.alternatives.join("、") : "-"} />
          <DecisionMeta label="置信度" value={decision.confidence > 0 ? `${(decision.confidence * 100).toFixed(0)}%` : "-"} />
          <DecisionMeta label="记忆事件" value={decision.memory_summary.length > 0 ? decision.memory_summary.slice(-2).join("；") : "-"} />
          <DecisionMeta label="记忆引用" value={decision.memory_refs.length > 0 ? decision.memory_refs.join("、") : "-"} />
        </div>
        {decision.rejected_reasons.length > 0 ? (
          <div className="text-xs text-muted-foreground">排除理由：{decision.rejected_reasons.join("；")}</div>
        ) : null}
        {decision.policy_adjustments.length > 0 ? (
          <div className="rounded-sm border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
            <span className="font-medium">策略修正：</span>
            {decision.policy_adjustments.join("；")}
          </div>
        ) : null}
        {decision.errors.length > 0 ? (
          <div className="rounded-sm border border-red-200 bg-red-50 p-2 text-xs text-red-800">
            <span className="font-medium">错误：</span>
            {decision.errors.join("；")}
          </div>
        ) : null}
        <DecisionExpandedSections
          decision={decision}
          totCandidates={totCandidates}
          totJudgeReason={totJudgeReason}
          promptMessages={promptMessages}
          selectedSkills={selectedSkills}
          memoryContext={memoryContext}
          beliefContext={beliefContext}
        />
      </div>
    </details>
  );
}

function DecisionExpandedSections({
  decision,
  totCandidates,
  totJudgeReason,
  promptMessages,
  selectedSkills,
  memoryContext,
  beliefContext,
}: {
  decision: AgentDecision;
  totCandidates: Array<Record<string, unknown>>;
  totJudgeReason: string;
  promptMessages: Array<Record<string, unknown>>;
  selectedSkills: string[];
  memoryContext?: Record<string, unknown>;
  beliefContext?: Record<string, unknown>;
}) {
  const hasBelief = beliefContext && Object.keys(beliefContext).length > 0;
  const hasRaw = decision.raw_output.length > 0;
  const hasToT = totCandidates.length > 0;
  const hasPrompt = promptMessages.length > 0;
  const hasMemory = memoryContext && Object.keys(memoryContext).length > 0;
  const hasSkill = selectedSkills.length > 0 && !decision.selected_skill;
  const hasAny = hasBelief || hasRaw || hasToT || hasPrompt || hasMemory || hasSkill;
  if (!hasAny) return null;
  return (
    <div className="space-y-2">
      {/* ToT Candidates — highlight feature */}
      {hasToT ? (
        <details className="group rounded-sm border border-indigo-200 bg-indigo-50 p-2">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-indigo-800 marker:hidden">
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
            ToT 候选方案 ({totCandidates.length})
          </summary>
          <div className="mt-2 space-y-2">
            {totCandidates.map((cand, idx) => (
              <div key={idx} className="rounded-sm border border-indigo-100 bg-white p-2 text-xs">
                <div className="font-medium text-indigo-900">方案 {idx + 1}</div>
                {cand.action ? <div className="mt-1 text-muted-foreground">行动: {String(cand.action)}</div> : null}
                {cand.public_text ? <div className="mt-1 text-muted-foreground">发言: {String(cand.public_text)}</div> : null}
                {cand.private_reasoning ? <div className="mt-1 text-muted-foreground">推理: {String(cand.private_reasoning)}</div> : null}
                {cand.expected_gain ? <div className="mt-1 text-muted-foreground">预期收益: {String(cand.expected_gain)}</div> : null}
                {cand.risk ? <div className="mt-1 text-muted-foreground">风险: {String(cand.risk)}</div> : null}
                {cand.judge_reason ? <div className="mt-1 text-amber-700">裁决: {String(cand.judge_reason)}</div> : null}
              </div>
            ))}
            {totJudgeReason ? (
              <div className="rounded-sm border border-amber-100 bg-amber-50 p-2 text-xs text-amber-800">
                <span className="font-medium">Judge 裁决：</span>{totJudgeReason}
              </div>
            ) : null}
          </div>
        </details>
      ) : null}

      {/* Skill injection */}
      {hasSkill ? (
        <details className="group rounded-sm border border-border p-2">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground marker:hidden">
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
            注入 Skills
          </summary>
          <div className="mt-2 flex flex-wrap gap-1">
            {selectedSkills.map((sk) => (
              <Badge key={sk} variant="secondary" className="text-xs">{sk}</Badge>
            ))}
          </div>
        </details>
      ) : null}

      {/* Memory context */}
      {hasMemory ? (
        <details className="group rounded-sm border border-border p-2">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground marker:hidden">
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
            记忆上下文
          </summary>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">
            {JSON.stringify(memoryContext, null, 2)}
          </pre>
        </details>
      ) : null}

      {/* Belief context */}
      {hasBelief ? (
        <details className="group rounded-sm border border-border p-2">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground marker:hidden">
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
            Belief 快照
          </summary>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">
            {JSON.stringify(beliefContext, null, 2)}
          </pre>
        </details>
      ) : null}

      {/* Prompt messages */}
      {hasPrompt ? (
        <details className="group rounded-sm border border-border p-2">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground marker:hidden">
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
            Prompt ({promptMessages.length} 条)
          </summary>
          <div className="mt-2 space-y-2">
            {promptMessages.map((msg, idx) => (
              <div key={idx} className="rounded-sm border border-border bg-card p-2 text-xs">
                <Badge variant="outline" className="mb-1">{(msg.role as string) ?? "unknown"}</Badge>
                <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-muted-foreground">
                  {typeof msg.content === "string" ? msg.content.slice(0, 500) : JSON.stringify(msg.content, null, 2).slice(0, 500)}
                  {(typeof msg.content === "string" ? msg.content.length > 500 : false) ? "..." : ""}
                </pre>
              </div>
            ))}
          </div>
        </details>
      ) : null}

      {/* Raw output */}
      {hasRaw ? (
        <details className="group rounded-sm border border-border p-2">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-muted-foreground marker:hidden">
            <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90" />
            Raw Output
          </summary>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">
            {decision.raw_output}
          </pre>
        </details>
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
  if (source === "tot") return "ToT 决策";
  if (source === "fallback") return "回退决策";
  if (source === "policy_adjusted") return "策略修正";
  return "LLM 决策";
}

function SheriffResultStage({ presentation, players, archiveMap }: { presentation: Presentation; players: Player[]; archiveMap?: Map<number, Record<string, unknown>> }) {
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
        <VoteStage presentation={presentation} players={players} archiveMap={archiveMap} />
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

function ReviewPanel({
  reviewData,
  players,
  onClose,
}: {
  reviewData: Record<string, unknown> | null;
  players: Player[];
  onClose: () => void;
}) {
  if (reviewData === null) {
    return (
      <section className="flex min-h-[calc(100vh-118px)] items-center justify-center rounded-lg border border-border bg-card text-sm text-muted-foreground">
        加载中...
      </section>
    );
  }

  const winner = String(reviewData.winner ?? "");
  const summary = String(reviewData.summary ?? "");
  const teamScores = reviewData.team_scores as Record<string, number> | undefined;
  const playerScores = reviewData.player_scores as Record<string, Record<string, unknown>> | undefined;
  const turningPoints = reviewData.key_turning_points as Array<Record<string, unknown>> | undefined;
  const mistakes = reviewData.mistakes as Array<Record<string, unknown>> | undefined;
  const skillSummary = reviewData.skill_summary as Record<string, Record<string, unknown>> | undefined;
  const suggestions = reviewData.suggestions as string[] | undefined;

  const sortedPlayers = playerScores
    ? Object.entries(playerScores).sort(([, a], [, b]) => (b.total_score as number ?? 0) - (a.total_score as number ?? 0))
    : [];

  return (
    <section className="overflow-y-auto rounded-lg border border-border bg-card shadow-sm">
      <div className="border-b border-border bg-muted/30 px-6 py-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold">复盘报告</h2>
          <Badge>{winner === "werewolves" ? "狼人胜利" : "好人胜利"}</Badge>
        </div>
        {summary ? <p className="mt-2 text-sm text-muted-foreground">{summary}</p> : null}
      </div>

      <div className="space-y-6 p-5">
        {/* Team scores */}
        {teamScores ? (
          <div>
            <h3 className="mb-3 text-sm font-semibold">阵营平均分</h3>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-md border border-sky-200 bg-sky-50 p-3 text-sky-900">
                <div className="text-xs">好人阵营</div>
                <div className="mt-1 text-2xl font-bold">{(teamScores.villagers ?? 0).toFixed(1)}</div>
              </div>
              <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-rose-900">
                <div className="text-xs">狼人阵营</div>
                <div className="mt-1 text-2xl font-bold">{(teamScores.werewolves ?? 0).toFixed(1)}</div>
              </div>
            </div>
          </div>
        ) : null}

        {/* Player scores table */}
        {sortedPlayers.length > 0 ? (
          <div>
            <h3 className="mb-3 text-sm font-semibold">玩家评分</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-border text-muted-foreground">
                    <th className="pb-2 pr-3 font-medium">玩家</th>
                    <th className="pb-2 pr-3 font-medium">角色</th>
                    <th className="pb-2 pr-3 font-medium">总分</th>
                    <th className="pb-2 pr-3 font-medium">发言</th>
                    <th className="pb-2 pr-3 font-medium">投票</th>
                    <th className="pb-2 pr-3 font-medium">技能</th>
                    <th className="pb-2 pr-3 font-medium">信息</th>
                    <th className="pb-2 pr-3 font-medium">协作</th>
                    <th className="pb-2 font-medium">胜负</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedPlayers.map(([pid, pr]) => {
                    const scores = (pr.scores as Record<string, number>) ?? {};
                    const player = players.find((p) => p.id === Number(pid));
                    return (
                      <tr key={pid} className="border-b border-border/50 last:border-0">
                        <td className="py-2 pr-3 font-medium">{pid} 号</td>
                        <td className="py-2 pr-3">{player ? roleName(player.role) : String(pr.role ?? "")}</td>
                        <td className="py-2 pr-3 font-semibold">{(pr.total_score as number ?? 0).toFixed(1)}</td>
                        <td className="py-2 pr-3">{(scores.speech ?? 0).toFixed(1)}</td>
                        <td className="py-2 pr-3">{(scores.vote ?? 0).toFixed(1)}</td>
                        <td className="py-2 pr-3">{(scores.skill ?? 0).toFixed(1)}</td>
                        <td className="py-2 pr-3">{(scores.information ?? 0).toFixed(1)}</td>
                        <td className="py-2 pr-3">{(scores.cooperation ?? 0).toFixed(1)}</td>
                        <td className="py-2">
                          <Badge variant={pr.outcome === "win" ? "default" : "secondary"}>
                            {pr.outcome === "win" ? "胜" : "负"}
                          </Badge>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}

        {/* Highlights & Mistakes per player */}
        {sortedPlayers.length > 0 ? (
          <div>
            <h3 className="mb-3 text-sm font-semibold">高光与失误</h3>
            <div className="grid gap-3 md:grid-cols-2">
              {sortedPlayers.map(([pid, pr]) => {
                const highlights = (pr.highlights as string[]) ?? [];
                const mistakes = (pr.mistakes as string[]) ?? [];
                if (highlights.length === 0 && mistakes.length === 0) return null;
                return (
                  <div key={pid} className="rounded-md border border-border p-3">
                    <div className="mb-2 text-sm font-medium">{pid} 号 · {roleName(players.find((p) => p.id === Number(pid))?.role ?? "")}</div>
                    {highlights.length > 0 ? (
                      <div className="mb-2 text-xs text-emerald-700">
                        <span className="font-medium">高光：</span>
                        {highlights.join("；")}
                      </div>
                    ) : null}
                    {mistakes.length > 0 ? (
                      <div className="text-xs text-red-700">
                        <span className="font-medium">失误：</span>
                        {mistakes.join("；")}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        {/* Key turning points */}
        {turningPoints && turningPoints.length > 0 ? (
          <div>
            <h3 className="mb-3 text-sm font-semibold">关键转折点</h3>
            <div className="space-y-2">
              {turningPoints.map((tp, idx) => (
                <div key={idx} className="rounded-md border border-border p-3 text-sm">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">第 {tp.day as number} 天</span>
                    <Badge variant="outline">{(tp.phase as string) ?? ""}</Badge>
                    <Badge variant={tp.impact === "positive" ? "default" : "destructive"}>
                      {tp.impact === "positive" ? "正面" : tp.impact === "negative" ? "负面" : "混合"}
                    </Badge>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{tp.description as string}</p>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {/* Mistakes list */}
        {mistakes && mistakes.length > 0 ? (
          <div>
            <h3 className="mb-3 text-sm font-semibold">关键错误</h3>
            <div className="space-y-2">
              {mistakes.map((m, idx) => (
                <div key={idx} className="rounded-md border border-border p-3 text-sm">
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary">{m.player_id as number} 号</Badge>
                    <Badge variant="outline">{m.mistake_type as string}</Badge>
                    <Badge variant={m.severity === "high" ? "destructive" : "secondary"}>
                      {m.severity as string}
                    </Badge>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{m.description as string}</p>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {/* Skill summary */}
        {skillSummary && Object.keys(skillSummary).length > 0 ? (
          <div>
            <h3 className="mb-3 text-sm font-semibold">Skill 表现</h3>
            <div className="grid gap-3 md:grid-cols-2">
              {Object.entries(skillSummary).map(([name, sk]) => (
                <div key={name} className="rounded-md border border-border p-3 text-sm">
                  <div className="font-medium">{name}</div>
                  <div className="mt-2 text-xs text-muted-foreground">
                    使用 {sk.use_count as number} 次，平均置信度 {((sk.avg_confidence as number ?? 0) * 100).toFixed(0)}%
                  </div>
                  {sk.suggestion ? (
                    <div className="mt-1 text-xs text-amber-700">{sk.suggestion as string}</div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {/* Suggestions */}
        {suggestions && suggestions.length > 0 ? (
          <div>
            <h3 className="mb-3 text-sm font-semibold">改进建议</h3>
            <div className="space-y-2">
              {suggestions.map((s, idx) => (
                <div key={idx} className="rounded-md bg-muted p-3 text-xs">
                  {s}
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function LeaderboardPanel({
  data,
  onClose,
}: {
  data: Record<string, unknown> | null;
  onClose: () => void;
}) {
  const entries = (data?.entries as Array<Record<string, unknown>> | undefined) ?? [];
  return (
    <section className="overflow-y-auto rounded-lg border border-border bg-card shadow-sm">
      <div className="border-b border-border bg-muted/30 px-6 py-4">
        <h2 className="text-xl font-semibold">版本排行榜</h2>
        <p className="mt-1 text-sm text-muted-foreground">多版本 Agent 效果对比</p>
      </div>
      <div className="p-5">
        {entries.length === 0 ? (
          <div className="flex min-h-64 items-center justify-center text-sm text-muted-foreground">暂无排行榜数据，请先运行版本对战。</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th className="pb-3 pr-4 font-medium">版本</th>
                  <th className="pb-3 pr-4 font-medium">局数</th>
                  <th className="pb-3 pr-4 font-medium">狼人胜率</th>
                  <th className="pb-3 pr-4 font-medium">好人胜率</th>
                  <th className="pb-3 pr-4 font-medium">总分</th>
                  <th className="pb-3 pr-4 font-medium">发言</th>
                  <th className="pb-3 pr-4 font-medium">投票</th>
                  <th className="pb-3 pr-4 font-medium">技能</th>
                  <th className="pb-3 pr-4 font-medium">Fallback率</th>
                  <th className="pb-3 font-medium">Policy修正率</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry, idx) => (
                  <tr key={idx} className="border-b border-border/50 last:border-0 hover:bg-muted/30">
                    <td className="py-3 pr-4 font-medium">{entry.version as string}</td>
                    <td className="py-3 pr-4">{entry.games as number}</td>
                    <td className="py-3 pr-4">{((entry.werewolf_win_rate as number ?? 0) * 100).toFixed(0)}%</td>
                    <td className="py-3 pr-4">{((entry.villager_win_rate as number ?? 0) * 100).toFixed(0)}%</td>
                    <td className="py-3 pr-4 font-semibold">{(entry.avg_score as number ?? 0).toFixed(1)}</td>
                    <td className="py-3 pr-4">{(entry.avg_speech_score as number ?? 0).toFixed(1)}</td>
                    <td className="py-3 pr-4">{(entry.avg_vote_score as number ?? 0).toFixed(1)}</td>
                    <td className="py-3 pr-4">{(entry.avg_skill_score as number ?? 0).toFixed(1)}</td>
                    <td className="py-3 pr-4">{((entry.fallback_rate as number ?? 0) * 100).toFixed(1)}%</td>
                    <td className="py-3">{((entry.policy_adjusted_rate as number ?? 0) * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
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
