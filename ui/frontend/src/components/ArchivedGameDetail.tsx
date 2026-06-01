import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Loader2 } from "lucide-react";
import { buildGamePages, latestPageId } from "../gamePages";
import { GameStage } from "./GameStage";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import type { AgentDecision, ArchiveMap, GameArchive, GameEvent, GameSnapshot, Player } from "../types";

export function ArchivedGameDetail({
  title,
  gameId,
  events,
  decisions,
  archive,
  loading,
  onBack,
}: {
  title: string;
  gameId: string;
  events: Record<string, unknown>[];
  decisions: Record<string, unknown>[];
  archive: GameArchive | null;
  loading: boolean;
  onBack: () => void;
}) {
  const normalizedEvents = useMemo(() => events.map(normalizeEvent), [events]);
  const normalizedDecisions = useMemo(() => decisions.map(normalizeDecision), [decisions]);
  const players = useMemo(() => buildPlayers(archive, normalizedEvents), [archive, normalizedEvents]);
  const snapshot = useMemo(
    () => buildSnapshot(gameId, normalizedEvents, normalizedDecisions, players, archive),
    [archive, gameId, normalizedDecisions, normalizedEvents, players],
  );
  const pages = useMemo(() => buildGamePages(snapshot, normalizedEvents), [snapshot, normalizedEvents]);
  const newestPageId = useMemo(() => latestPageId(pages), [pages]);
  const [selectedPageId, setSelectedPageId] = useState(newestPageId);
  const [followLatest, setFollowLatest] = useState(true);

  useEffect(() => {
    setSelectedPageId(newestPageId);
    setFollowLatest(true);
  }, [gameId, newestPageId]);

  const selectedPage = useMemo(
    () => pages.find((page) => page.id === selectedPageId) ?? pages[pages.length - 1],
    [pages, selectedPageId],
  );
  const archiveMap = useMemo(() => {
    if (!archive?.decisions) return undefined;
    const map: ArchiveMap = new Map();
    for (const entry of archive.decisions) {
      const decisionId = typeof entry.decision_id === "string" ? entry.decision_id : "";
      const idx = typeof entry.index === "number" ? entry.index : Number(entry.index);
      if (decisionId) map.set(decisionId, entry);
      if (Number.isFinite(idx)) map.set(idx, entry);
    }
    return map;
  }, [archive]);

  if (loading) {
    return (
      <section className="rounded-lg border border-border bg-card p-6">
        <div className="mb-4 flex items-center gap-3">
          <Button variant="ghost" onClick={onBack}>
            <ArrowLeft className="h-4 w-4" />
            返回
          </Button>
          <h2 className="text-sm font-semibold">{title}</h2>
        </div>
        <div className="flex min-h-[320px] items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      </section>
    );
  }

  if (events.length === 0) {
    return (
      <section className="rounded-lg border border-border bg-card p-6">
        <div className="mb-4 flex items-center gap-3">
          <Button variant="ghost" onClick={onBack}>
            <ArrowLeft className="h-4 w-4" />
            返回
          </Button>
          <h2 className="text-sm font-semibold">{title}</h2>
        </div>
        <div className="flex min-h-[320px] items-center justify-center text-sm text-muted-foreground">
          暂无事件数据
        </div>
      </section>
    );
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <Button variant="ghost" onClick={onBack}>
            <ArrowLeft className="h-4 w-4" />
            返回
          </Button>
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold">{title}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <code className="rounded bg-muted px-1.5 py-0.5">{gameId}</code>
              <Badge variant="secondary">{normalizedEvents.length} 事件</Badge>
              <Badge variant="secondary">{normalizedDecisions.length} 决策</Badge>
            </div>
          </div>
        </div>
      </div>
      <GameStage
        page={selectedPage}
        pages={pages}
        presentation={selectedPage.presentation}
        players={players}
        archiveMap={archiveMap}
        followLatest={followLatest}
        onSelectPage={(pageId) => {
          setSelectedPageId(pageId);
          setFollowLatest(false);
        }}
        onFollowLatest={() => {
          setSelectedPageId(newestPageId);
          setFollowLatest(true);
        }}
      />
    </section>
  );
}

function buildSnapshot(
  gameId: string,
  events: GameEvent[],
  decisions: AgentDecision[],
  players: Player[],
  archive: GameArchive | null,
): GameSnapshot {
  const latest = events[events.length - 1];
  const winner = stringValue(archive?.winner) || winnerFromEvents(events);
  return {
    game_id: gameId,
    log_name: gameId,
    status: "completed",
    winner,
    seed: numberOrNull(archive?.seed),
    day: latest?.day ?? 0,
    phase: latest?.phase ?? "setup",
    sheriff_id: sheriffFromEvents(events),
    players,
    event_count: events.length,
    events,
    decisions,
    error: null,
  };
}

function buildPlayers(archive: GameArchive | null, events: GameEvent[]): Player[] {
  const roles = roleMapFromArchive(archive) ?? roleMapFromEvents(events);
  const dead = new Set(
    events
      .filter((event) => event.event_type === "death" && event.target !== null)
      .map((event) => Number(event.target)),
  );
  const sheriffId = sheriffFromEvents(events);
  return Object.entries(roles)
    .map(([rawId, role]) => {
      const id = Number(rawId);
      return {
        id,
        role,
        team: teamForRole(role),
        alive: !dead.has(id),
        is_sheriff: sheriffId === id,
      };
    })
    .filter((player) => Number.isFinite(player.id))
    .sort((left, right) => left.id - right.id);
}

function roleMapFromArchive(archive: GameArchive | null): Record<string, string> | null {
  const direct = archive?.player_roles;
  if (isRecord(direct)) return stringRecord(direct);
  const finalState = archive?.final_state;
  if (isRecord(finalState) && isRecord(finalState.player_roles)) {
    return stringRecord(finalState.player_roles);
  }
  return null;
}

function roleMapFromEvents(events: GameEvent[]): Record<string, string> {
  const init = events.find((event) => event.event_type === "game_init");
  const roles = init?.payload.roles;
  return isRecord(roles) ? stringRecord(roles) : {};
}

function normalizeEvent(raw: Record<string, unknown>, idx: number): GameEvent {
  const payload = isRecord(raw.payload) ? raw.payload : {};
  return {
    index: numberValue(raw.index, idx + 1),
    day: numberValue(raw.day, 0),
    phase: stringValue(raw.phase) || "setup",
    event_type: stringValue(raw.event_type) || stringValue(raw.type),
    message: stringValue(raw.message) || stringValue(raw.content),
    level: stringValue(raw.level) || "info",
    visibility: stringValue(raw.visibility) || "god",
    actor: numberOrNull(raw.actor),
    target: numberOrNull(raw.target),
    payload,
  };
}

function normalizeDecision(raw: Record<string, unknown>, idx: number): AgentDecision {
  const source = stringValue(raw.source);
  const selectedSkills = stringArray(raw.selected_skills);
  return {
    decision_id: stringValue(raw.decision_id) || undefined,
    index: numberValue(raw.index, idx + 1),
    day: numberValue(raw.day, 0),
    phase: stringValue(raw.phase) || "setup",
    player_id: numberOrNull(raw.player_id),
    role: stringValue(raw.role),
    action_type: stringValue(raw.action_type),
    candidates: numberArray(raw.candidates),
    selected_target: numberOrNull(raw.selected_target),
    selected_choice: stringValue(raw.selected_choice) || null,
    public_text: stringValue(raw.public_text),
    private_reasoning: stringValue(raw.private_reasoning),
    confidence: numberValue(raw.confidence, 0),
    alternatives: numberArray(raw.alternatives),
    rejected_reasons: stringArray(raw.rejected_reasons),
    selected_skill: selectedSkills[0] ?? "",
    memory_refs: stringArray(raw.memory_refs),
    belief_snapshot: isRecord(raw.belief_snapshot) ? raw.belief_snapshot : {},
    memory_summary: stringArray(raw.memory_summary),
    raw_output: stringValue(raw.raw_output),
    errors: stringArray(raw.errors),
    policy_adjustments: stringArray(raw.policy_adjustments),
    source: isDecisionSource(source) ? source : "llm",
  };
}

function winnerFromEvents(events: GameEvent[]): string | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const winner = stringValue(events[index].payload.winner);
    if (winner) return winner;
  }
  return null;
}

function sheriffFromEvents(events: GameEvent[]): number | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const winner = numberOrNull(events[index].payload.winner);
    if (winner !== null) return winner;
  }
  return null;
}

function teamForRole(role: string): string {
  if (role === "werewolf" || role === "white_wolf_king") return "werewolves";
  if (role === "villager") return "villagers";
  return "gods";
}

function isDecisionSource(value: string): value is AgentDecision["source"] {
  return ["llm", "fallback", "policy_adjusted", "tot", "got"].includes(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringRecord(value: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(Object.entries(value).map(([key, val]) => [key, String(val)]));
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function numberValue(value: unknown, fallback: number): number {
  const num = typeof value === "number" ? value : Number(value);
  return Number.isFinite(num) ? num : fallback;
}

function numberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const num = typeof value === "number" ? value : Number(value);
  return Number.isFinite(num) ? num : null;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function numberArray(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => Number(item)).filter(Number.isFinite);
}
