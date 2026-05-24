import type { GameEvent, GameSnapshot } from "./types";
import {
  buildPresentationForContext,
  phaseName,
  type Presentation,
  type StageKind,
} from "./presentation";

export type GamePage = {
  id: string;
  label: string;
  stage: StageKind;
  day: number;
  sort: number;
  events: GameEvent[];
  presentation: Presentation;
};

const pageOrder: Record<StageKind, number> = {
  setup: 0,
  night: 1,
  sheriff: 2,
  sheriff_result: 3,
  day: 4,
  vote: 5,
  result: 6,
};

export function buildGamePages(snapshot: GameSnapshot | null, events: GameEvent[]): GamePage[] {
  const groups = new Map<string, { stage: StageKind; day: number; events: GameEvent[] }>();

  for (const event of events) {
    const stage = pageStage(event);
    if (stage === "sheriff_result") {
      ensureSheriffSpeechPage(groups, event.day);
    }
    const day = event.day;
    const id = pageId(stage, day);
    const group = groups.get(id) ?? { stage, day, events: [] };
    group.events.push(event);
    groups.set(id, group);
  }

  if (events.length === 0) {
    const presentation = buildPresentationForContext(snapshot, [], { stage: "setup", day: 0, phase: "setup" });
    return [{ id: "setup", label: "准备", stage: "setup", day: 0, sort: 0, events: [], presentation }];
  }

  const pages = Array.from(groups.entries()).map(([id, group]) => {
    const phase = phaseForStage(group.stage);
    return {
      id,
      label: pageLabel(group.stage, group.day),
      stage: group.stage,
      day: group.day,
      sort: group.day * 10 + pageOrder[group.stage],
      events: group.events,
      presentation: buildPresentationForContext(snapshot, events, {
        stage: group.stage,
        day: group.day,
        phase,
      }),
    };
  });

  if (snapshot?.winner && !pages.some((page) => page.stage === "result")) {
    const latest = events.length > 0 ? events[events.length - 1] : undefined;
    const day = snapshot.day || latest?.day || 0;
    pages.push({
      id: "result",
      label: "结果",
      stage: "result",
      day,
      sort: day * 10 + pageOrder.result,
      events: events.filter((event) => event.event_type === "game_end"),
      presentation: buildPresentationForContext(snapshot, events, { stage: "result", day, phase: "finished" }),
    });
  }

  return pages.sort((left, right) => left.sort - right.sort);
}

export function latestPageId(pages: GamePage[]) {
  return pages.length > 0 ? pages[pages.length - 1].id : "setup";
}

function pageId(stage: StageKind, day: number) {
  if (stage === "setup") return "setup";
  if (stage === "result") return "result";
  if (stage === "sheriff") return `day${day}-sheriff`;
  if (stage === "sheriff_result") return `day${day}-sheriff-result`;
  return `day${day}-${stage}`;
}

function pageLabel(stage: StageKind, day: number) {
  if (stage === "setup") return "准备";
  if (stage === "result") return "结果";
  if (stage === "night") return `第${day}夜`;
  if (stage === "sheriff") return "警长竞选";
  if (stage === "sheriff_result") return "退水/警长";
  if (stage === "day") return `第${day}天`;
  if (stage === "vote") return `第${day}天投票`;
  return phaseName(stage);
}

function phaseForStage(stage: StageKind) {
  if (stage === "sheriff") return "sheriff_election";
  if (stage === "sheriff_result") return "sheriff_election";
  if (stage === "night") return "night";
  if (stage === "day") return "day_speech";
  if (stage === "vote") return "exile_vote";
  if (stage === "result") return "finished";
  return "setup";
}

function pageStage(event: GameEvent): StageKind {
  if (event.event_type === "game_end" || event.phase === "finished") return "result";
  if (event.phase === "sheriff_election") {
    const actionType = typeof event.payload.action_type === "string" ? event.payload.action_type : "";
    if (
      event.event_type === "sheriff_election_end" ||
      actionType === "sheriff_withdraw" ||
      actionType === "sheriff_vote"
    ) {
      return "sheriff_result";
    }
    return "sheriff";
  }
  if (event.phase === "night") return "night";
  if (event.phase === "day_speech") return "day";
  if (event.phase === "exile_vote") return "vote";
  return "setup";
}

function ensureSheriffSpeechPage(
  groups: Map<string, { stage: StageKind; day: number; events: GameEvent[] }>,
  day: number,
) {
  const id = pageId("sheriff", day);
  if (!groups.has(id)) {
    groups.set(id, { stage: "sheriff", day, events: [] });
  }
}
