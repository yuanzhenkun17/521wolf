import { useEffect, useMemo, useRef, useState } from "react";
import { Routes, Route, Navigate, useParams, useNavigate } from "react-router-dom";
import { Loader2, Play, ScrollText } from "lucide-react";
import { getGame, getGameArchive, getGameReview, listGames, startGame, type GameConfig } from "./api";
import { GameConfigDialog } from "./components/GameConfigDialog";
import { HumanActionPanel } from "./components/HumanActionPanel";
import { Navigation } from "./components/Navigation";
import { StatusPanel } from "./components/StatusPanel";
import { PlayersPanel } from "./components/PlayersPanel";
import { EngineStatePanel } from "./components/EngineStatePanel";
import { KeyEventsPanel } from "./components/KeyEventsPanel";
import { GamesPanel } from "./components/GamesPanel";
import { GameStage } from "./components/GameStage";
import { ReviewPanel } from "./components/ReviewPanel";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { buildGamePages, latestPageId } from "./gamePages";
import { phaseName } from "./presentation";
import type { ArchiveMap, GameArchive, GameEvent, GameSnapshot } from "./types";
import { RoleEvolutionPage } from "./pages/RoleEvolutionPage";


// ---------------------------------------------------------------------------
// GameView: main game observation page (used for both / and /games/:gameId)
// ---------------------------------------------------------------------------

function GameView() {
  const { gameId: routeGameId } = useParams<{ gameId: string }>();
  const navigate = useNavigate();

  const [snapshot, setSnapshot] = useState<GameSnapshot | null>(null);
  const [events, setEvents] = useState<GameEvent[]>([]);
  const [games, setGames] = useState<GameSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [selectedPageId, setSelectedPageId] = useState("setup");
  const [followLatest, setFollowLatest] = useState(true);
  const [reviewData, setReviewData] = useState<Record<string, unknown> | null>(null);
  const [showReview, setShowReview] = useState(false);
  const [archiveData, setArchiveData] = useState<GameArchive | null>(null);
  const [showConfigDialog, setShowConfigDialog] = useState(false);
  const [humanActionSignal, setHumanActionSignal] = useState(0);
  const eventSourceRef = useRef<EventSource | null>(null);
  const loadedRef = useRef(false);

  // Load game list on mount; optionally load a specific game from route
  useEffect(() => {
    listGames()
      .then((items) => {
        setGames(items);
        if (routeGameId) {
          void loadGame(routeGameId);
        } else if (items.length > 0) {
          void loadGame(items[0].game_id);
        }
        loadedRef.current = true;
      })
      .catch((exc: Error) => setError(exc.message));
  }, []);

  // Cleanup SSE on unmount
  useEffect(() => () => eventSourceRef.current?.close(), []);

  // Sync route gameId changes (after initial load)
  useEffect(() => {
    if (loadedRef.current && routeGameId && routeGameId !== snapshot?.game_id) {
      void loadGame(routeGameId);
    }
  }, [routeGameId]);

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
    const map: ArchiveMap = new Map();
    for (const entry of archiveData.decisions) {
      const idx = entry.index as number | undefined;
      const decisionId = entry.decision_id as string | undefined;
      if (decisionId) map.set(decisionId, entry);
      if (idx !== undefined) map.set(idx, entry);
    }
    return map;
  }, [archiveData]);
  const aliveCount = useMemo(() => snapshot?.players.filter((p) => p.alive).length ?? 0, [snapshot]);
  const deadCount = useMemo(() => snapshot?.players.filter((p) => !p.alive).length ?? 0, [snapshot]);

  async function loadGame(gameId: string) {
    eventSourceRef.current?.close();
    const loaded = await getGame(gameId);
    setSnapshot(loaded);
    setEvents(loaded.events ?? []);
    setFollowLatest(true);
    setArchiveData(null);
    setShowReview(false);
    if (loaded.status === "completed" || loaded.winner) {
      void getGameArchive(gameId).then(setArchiveData).catch(() => setArchiveData(null));
    }
    if (loaded.status === "running" || loaded.status === "starting") connectEvents(loaded.game_id);
    if (!routeGameId || routeGameId !== gameId) {
      navigate(`/games/${gameId}`, { replace: true });
    }
  }

  async function handleStart(config: GameConfig = {}) {
    setStarting(true);
    setError(null);
    setShowConfigDialog(false);
    try {
      const created = await startGame(config);
      setSnapshot(created);
      setEvents([]);
      setFollowLatest(true);
      setGames((items) => [created, ...items.filter((i) => i.game_id !== created.game_id)]);
      connectEvents(created.game_id);
      navigate(`/games/${created.game_id}`, { replace: true });
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
      setEvents((items) => (items.some((i) => i.index === event.index) ? items : [...items, event]));
      void getGame(gameId).then(setSnapshot).catch(() => undefined);
    });

    source.addEventListener("decision_needed", () => {
      setHumanActionSignal((value) => value + 1);
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
    <>
      {/* Game-specific header bar */}
      <header className="border-b border-border bg-background/95">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-3">
          <div className="min-w-0">
            <p className="text-sm text-muted-foreground truncate">
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
            <Button onClick={() => setShowConfigDialog(true)} disabled={starting || snapshot?.status === "running"}>
              {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              开始新局
            </Button>
          </div>
        </div>
      </header>

      {/* 3-column layout */}
      <div className="mx-auto grid max-w-7xl gap-5 px-5 py-5 lg:grid-cols-[320px_1fr_300px]">
        <section className="space-y-5">
          <StatusPanel snapshot={snapshot} aliveCount={aliveCount} deadCount={deadCount} />
          <PlayersPanel players={snapshot?.players ?? []} />
          <EngineStatePanel players={snapshot?.players ?? []} />
        </section>

        {showReview ? (
          <ReviewPanel reviewData={reviewData} players={snapshot?.players ?? []} onClose={() => setShowReview(false)} />
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

      <GameConfigDialog open={showConfigDialog} onClose={() => setShowConfigDialog(false)} onSubmit={handleStart} starting={starting} />
      {snapshot && (
        <HumanActionPanel
          gameId={snapshot.game_id}
          gameStatus={snapshot.status}
          refreshSignal={humanActionSignal}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// App shell: Navigation + Routes
// ---------------------------------------------------------------------------

export function App() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <Navigation />
      <Routes>
        <Route path="/" element={<GameView />} />
        <Route path="/games/:gameId" element={<GameView />} />
        <Route path="/roles" element={<RoleEvolutionPage />} />
        <Route path="/selfplay" element={<Navigate to="/roles" replace />} />
      </Routes>
    </main>
  );
}
