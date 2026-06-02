import type { AgentDecision, GameEvent, GameSnapshot } from "./types";

export type StageKind = "setup" | "sheriff" | "sheriff_result" | "night" | "day" | "vote" | "result";

export type SpeechTurn = {
  index: number;
  day: number;
  phase: string;
  speakerId: number;
  actionType: string;
  text: string;
  decision?: AgentDecision;
};

export type VoteLine = {
  voterId: number;
  targetId: number | null;
  decision?: AgentDecision;
};

export type NightAction = {
  label: string;
  actorId?: number | null;
  targetId?: number | null;
  detail: string;
  decisions: AgentDecision[];
};

export type Presentation = {
  stage: StageKind;
  day: number;
  phase: string;
  title: string;
  subtitle: string;
  alivePlayerIds: number[];
  deadPlayerIds: number[];
  currentSpeech?: SpeechTurn;
  speeches: SpeechTurn[];
  votes: VoteLine[];
  nightActions: NightAction[];
  nightDeaths: number[];
  keyEvents: GameEvent[];
  winner?: string | null;
};

export type PresentationContext = {
  stage: StageKind;
  day: number;
  phase: string;
};

const speechActions = new Set(["speak", "sheriff_speak", "pk_speak", "last_word"]);
const voteActions = new Set(["sheriff_vote", "exile_vote", "pk_vote"]);

export function buildPresentationForContext(
  snapshot: GameSnapshot | null,
  events: GameEvent[],
  context: PresentationContext,
): Presentation {
  const winner = snapshot?.winner ?? winnerFromEvents(events);
  const decisions = snapshot?.decisions ?? [];
  const decisionMap = buildEventDecisionMap(events, decisions);
  const stage = context.stage;
  const stageDay = context.day;
  const speeches = events.filter(isSpeechEvent).map((event) => toSpeechTurn(event, decisionMap.get(event.index)));
  const statements = events.filter(isStatementEvent).map((event) => toSpeechTurn(event, decisionMap.get(event.index)));
  const samePageSpeeches = speeches.filter((speech) => speech.day === stageDay && speechStageMatches(stage, speech.actionType));
  const samePageStatements = statements.filter((speech) => speech.day === stageDay && statementStageMatches(stage, speech.actionType));
  const votes = latestVoteLines(events, stageDay, stage, decisionMap);
  const nightActions = latestNightActions(events, decisions, stageDay);
  const nightDeaths = latestNightDeaths(events, stageDay);
  const currentSpeech = stage === "vote" ? lastOf(samePageStatements) : lastOf(samePageSpeeches);

  return {
    stage,
    day: stageDay,
    phase: context.phase,
    title: titleFor(stage, stageDay, winner),
    subtitle: subtitleFor(stage, currentSpeech, nightDeaths, votes),
    ...playerStatusForPage(snapshot, events, stageDay, stage),
    currentSpeech,
    speeches: samePageSpeeches,
    votes,
    nightActions,
    nightDeaths,
    keyEvents: keyEvents(events).filter((event) => keyEventMatches(stage, stageDay, event)).slice(-8).reverse(),
    winner,
  };
}

export function roleName(role: string) {
  return (
    {
      werewolf: "狼人",
      white_wolf_king: "白狼王",
      villager: "村民",
      seer: "预言家",
      witch: "女巫",
      hunter: "猎人",
      guard: "守卫",
    }[role] ?? role
  );
}

export function teamName(team: string) {
  return (
    {
      werewolves: "狼人阵营",
      villagers: "村民",
      gods: "神职",
    }[team] ?? team
  );
}

export function phaseName(phase: string) {
  return (
    {
      setup: "准备",
      sheriff_election: "警长竞选",
      night: "黑夜",
      day_speech: "白天发言",
      exile_vote: "放逐投票",
      finished: "结束",
    }[phase] ?? phase
  );
}

function titleFor(stage: StageKind, day: number, winner: string | null) {
  if (stage === "result") return winner === "werewolves" ? "狼人阵营获胜" : "好人阵营获胜";
  if (stage === "night") return `第 ${day} 夜`;
  if (stage === "day") return `第 ${day} 天白天`;
  if (stage === "vote") return `第 ${day} 天放逐投票`;
  if (stage === "sheriff_result") return "退水与警长当选";
  if (stage === "sheriff") return "警长竞选";
  return "等待开局";
}

function subtitleFor(stage: StageKind, speech: SpeechTurn | undefined, deaths: number[], votes: VoteLine[]) {
  if (stage === "night") return deaths.length > 0 ? `天亮了，昨夜 ${deaths.join("、")} 号出局` : "天黑请闭眼，各身份依次行动";
  if (stage === "day") return speech ? `${speech.speakerId} 号正在发言` : "等待玩家发言";
  if (stage === "vote") return votes.length > 0 ? `已记录 ${votes.length} 张票` : "玩家正在投票";
  if (stage === "sheriff_result") return "查看退水、警下投票和最终警长";
  if (stage === "sheriff") return speech ? `${speech.speakerId} 号竞选发言` : "玩家决定是否上警";
  if (stage === "result") return "本局游戏结束";
  return "点击开始新局";
}

function isSpeechEvent(event: GameEvent) {
  return event.event_type === "action_response" && speechActions.has(stringPayload(event, "action_type")) && Boolean(stringPayload(event, "text"));
}

function isStatementEvent(event: GameEvent) {
  const actionType = stringPayload(event, "action_type");
  return event.event_type === "action_response" && (speechActions.has(actionType) || voteActions.has(actionType)) && Boolean(stringPayload(event, "text"));
}

function toSpeechTurn(event: GameEvent, decision?: AgentDecision): SpeechTurn {
  return {
    index: event.index,
    day: event.day,
    phase: event.phase,
    speakerId: event.actor ?? 0,
    actionType: stringPayload(event, "action_type"),
    text: stringPayload(event, "text"),
    decision,
  };
}

function latestVoteLines(events: GameEvent[], day: number, stage: StageKind, decisionMap: Map<number, AgentDecision>): VoteLine[] {
  if (stage === "sheriff" || stage === "sheriff_result") {
    return voteLinesFromEndEvent(events, day, ["sheriff_election_end"], decisionMap);
  }
  if (stage !== "vote") return [];
  return voteLinesFromEndEvent(events, day, ["exile_vote_end", "pk_vote_end"], decisionMap);
}

function voteLinesFromEndEvent(
  events: GameEvent[],
  day: number,
  eventTypes: string[],
  decisionMap: Map<number, AgentDecision>,
): VoteLine[] {
  const voteEnd = findLast(events, (event) => event.day === day && eventTypes.includes(event.event_type));
  if (!voteEnd) {
    return voteLinesFromActionEvents(events, day, eventTypesForVoteFallback(eventTypes), decisionMap);
  }
  const byVoter = new Map<number, VoteLine>();
  for (const vote of voteLinesFromActionEvents(events, day, actionTypesForVoteEnd(voteEnd.event_type), decisionMap)) {
    byVoter.set(vote.voterId, vote);
  }
  const votes = voteEnd?.payload.votes;
  if (votes && typeof votes === "object" && !Array.isArray(votes)) {
    for (const [voterId, targetId] of Object.entries(votes)) {
      const vote = {
        voterId: Number(voterId),
        targetId: targetId === null ? null : Number(targetId),
        decision: byVoter.get(Number(voterId))?.decision,
      };
      if (Number.isFinite(vote.voterId) && (vote.targetId === null || Number.isFinite(vote.targetId))) {
        byVoter.set(vote.voterId, vote);
      }
    }
  }
  return Array.from(byVoter.values()).sort((left, right) => left.voterId - right.voterId);
}

function voteLinesFromActionEvents(
  events: GameEvent[],
  day: number,
  actionTypes: Set<string>,
  decisionMap: Map<number, AgentDecision>,
): VoteLine[] {
  return events
    .filter((event) => event.day === day && isVoteActionResult(event) && actionTypes.has(stringPayload(event, "action_type")))
    .map((event) => ({ voterId: event.actor ?? 0, targetId: event.target, decision: decisionMap.get(event.index) }))
    .filter((vote) => vote.voterId > 0);
}

function isVoteActionResult(event: GameEvent) {
  return event.event_type === "action_response" || event.event_type === "default_action";
}

function latestNightActions(events: GameEvent[], decisions: AgentDecision[], day: number): NightAction[] {
  return events
    .filter((event) => event.day === day && event.phase === "night")
    .flatMap((event) => {
      if (event.event_type === "guard_result") {
        return [{
          label: "守卫",
          actorId: event.actor,
          targetId: event.target,
          detail: event.target != null ? `${event.actor} 号守护 ${event.target} 号` : `${event.actor} 号未守护`,
          decisions: matchingDecisions(decisions, day, "night", "guard_protect", event.actor),
        }];
      }
      if (event.event_type === "werewolf_result") {
        return [{
          label: "狼刀",
          targetId: event.target,
          detail: `狼人选择击杀 ${event.target} 号`,
          decisions: matchingDecisions(decisions, day, "night", "werewolf_kill"),
        }];
      }
      if (event.event_type === "seer_result") {
        return [{
          label: "查验",
          actorId: event.actor,
          targetId: event.target,
          detail: `${event.actor} 号查验 ${event.target} 号：${teamName(stringPayload(event, "result"))}`,
          decisions: matchingDecisions(decisions, day, "night", "seer_check", event.actor),
        }];
      }
      if (event.event_type === "witch_result") {
        return [{
          label: "女巫",
          actorId: event.actor,
          targetId: event.target,
          detail: event.message,
          decisions: matchingDecisions(decisions, day, "night", "witch_act", event.actor),
        }];
      }
      return [];
    });
}

function latestNightDeaths(events: GameEvent[], day: number) {
  const nightEnd = findLast(events, (event) => event.day === day && ["night_death_reveal", "night_end"].includes(event.event_type));
  const deaths = nightEnd?.payload.deaths;
  return Array.isArray(deaths) ? deaths.map(Number).filter(Number.isFinite) : [];
}

function keyEvents(events: GameEvent[]) {
  return events.filter((event) =>
    [
      "night_end",
      "night_death_reveal",
      "death",
      "exile_vote_end",
      "pk_vote_end",
      "sheriff_election_end",
      "sheriff_badge_transfer",
      "sheriff_badge_destroy",
      "hunter_shot",
      "white_wolf_explode",
      "game_end",
    ].includes(event.event_type) || isSheriffWithdrawResponse(event),
  );
}

function isSheriffWithdrawResponse(event: GameEvent) {
  return event.event_type === "action_response" && stringPayload(event, "action_type") === "sheriff_withdraw";
}

function speechStageMatches(stage: StageKind, actionType: string) {
  if (stage === "sheriff") return actionType === "sheriff_speak";
  if (stage === "sheriff_result") return false;
  if (stage === "day") return actionType === "speak" || actionType === "pk_speak" || actionType === "last_word";
  if (stage === "vote") return actionType === "last_word";
  return false;
}

function statementStageMatches(stage: StageKind, actionType: string) {
  if (stage === "sheriff") return ["sheriff_speak", "sheriff_vote", "sheriff_run", "sheriff_withdraw"].includes(actionType);
  if (stage === "sheriff_result") return ["sheriff_withdraw", "sheriff_vote"].includes(actionType);
  if (stage === "day") return speechStageMatches(stage, actionType);
  if (stage === "vote") return ["exile_vote", "pk_vote", "last_word"].includes(actionType);
  return false;
}

function keyEventMatches(stage: StageKind, day: number, event: GameEvent) {
  if (stage === "result") return true;
  if (stage === "sheriff") return event.phase === "sheriff_election" && !["sheriff_election_end"].includes(event.event_type) && !isSheriffWithdrawResponse(event);
  if (stage === "sheriff_result") return event.phase === "sheriff_election" && (event.event_type === "sheriff_election_end" || isSheriffWithdrawResponse(event));
  if (stage === "night") return event.day === day && (event.phase === "night" || event.event_type === "night_death_reveal");
  if (stage === "day") return event.day === day && event.phase === "day_speech";
  if (stage === "vote") return event.day === day && event.phase === "exile_vote";
  return event.phase === "setup";
}

function playerStatusForPage(
  snapshot: GameSnapshot | null,
  events: GameEvent[],
  day: number,
  stage: StageKind,
) {
  const roles = initialPlayerIds(snapshot, events);
  const deathsBeforePage = new Set<number>();
  for (const event of events) {
    if (event.event_type !== "death" || event.target === null) continue;
    if (event.day < day || (event.day === day && deathHappenedBeforeStage(event.phase, stage))) {
      deathsBeforePage.add(event.target);
    }
  }
  return {
    alivePlayerIds: roles.filter((playerId) => !deathsBeforePage.has(playerId)),
    deadPlayerIds: roles.filter((playerId) => deathsBeforePage.has(playerId)),
  };
}

function initialPlayerIds(snapshot: GameSnapshot | null, events: GameEvent[]) {
  if (snapshot?.players.length) return snapshot.players.map((player) => player.id).sort((left, right) => left - right);
  const init = events.find((event) => event.event_type === "game_init");
  const roles = init?.payload.roles;
  if (roles && typeof roles === "object" && !Array.isArray(roles)) {
    return Object.keys(roles).map(Number).filter(Number.isFinite).sort((left, right) => left - right);
  }
  return [];
}

function deathHappenedBeforeStage(deathPhase: string, stage: StageKind) {
  const phaseOrder: Record<string, number> = {
    night: 1,
    sheriff_election: 2,
    day_speech: 3,
    exile_vote: 4,
    finished: 5,
  };
  const stageOrder: Record<StageKind, number> = {
    setup: 0,
    night: 1,
    sheriff: 2,
    sheriff_result: 2,
    day: 3,
    vote: 4,
    result: 5,
  };
  return (phaseOrder[deathPhase] ?? 0) < stageOrder[stage];
}

function eventTypesForVoteFallback(eventTypes: string[]) {
  if (eventTypes.includes("sheriff_election_end")) return new Set(["sheriff_vote"]);
  if (eventTypes.includes("pk_vote_end")) return new Set(["exile_vote", "pk_vote"]);
  return voteActions;
}

function actionTypesForVoteEnd(eventType: string) {
  if (eventType === "sheriff_election_end") return new Set(["sheriff_vote"]);
  if (eventType === "pk_vote_end") return new Set(["pk_vote"]);
  return new Set(["exile_vote"]);
}

function winnerFromEvents(events: GameEvent[]) {
  const end = findLast(events, (event) => event.event_type === "game_end");
  return end ? stringPayload(end, "winner") : null;
}

function buildEventDecisionMap(events: GameEvent[], decisions: AgentDecision[]) {
  const buckets = new Map<string, AgentDecision[]>();
  const decisionsById = new Map<string, AgentDecision>();
  for (const decision of [...decisions].sort((left, right) => left.index - right.index)) {
    if (decision.decision_id) {
      decisionsById.set(decision.decision_id, decision);
    }
    const key = decisionKey(decision.day, decision.phase, decision.action_type, decision.player_id);
    buckets.set(key, [...(buckets.get(key) ?? []), decision]);
  }

  const used = new Map<string, number>();
  const mapped = new Map<number, AgentDecision>();
  for (const event of events) {
    if (!isActionDecisionEvent(event)) continue;
    const decisionId = stringPayload(event, "decision_id");
    if (decisionId) {
      const decision = decisionsById.get(decisionId);
      if (decision) {
        mapped.set(event.index, decision);
        continue;
      }
    }
    const actionType = stringPayload(event, "action_type");
    const key = decisionKey(event.day, event.phase, actionType, event.actor);
    const offset = used.get(key) ?? 0;
    const decision = buckets.get(key)?.[offset];
    if (decision) {
      mapped.set(event.index, decision);
      used.set(key, offset + 1);
    }
  }
  return mapped;
}

function isActionDecisionEvent(event: GameEvent) {
  return event.event_type === "action_response" || event.event_type === "default_action";
}

function matchingDecisions(
  decisions: AgentDecision[],
  day: number,
  phase: string,
  actionType: string,
  playerId?: number | null,
) {
  return decisions.filter(
    (decision) =>
      decision.day === day &&
      decision.phase === phase &&
      decision.action_type === actionType &&
      (playerId === undefined || decision.player_id === playerId),
  );
}

function decisionKey(day: number, phase: string, actionType: string, playerId: number | null) {
  return `${day}:${phase}:${actionType}:${playerId ?? "none"}`;
}

function stringPayload(event: GameEvent, key: string) {
  const value = event.payload[key];
  return typeof value === "string" ? value : "";
}

function findLast<T>(items: T[], predicate: (item: T) => boolean) {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (predicate(items[index])) return items[index];
  }
  return undefined;
}

function lastOf<T>(items: T[]) {
  return items.length > 0 ? items[items.length - 1] : undefined;
}
