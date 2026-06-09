import type {
  ActiveGameSession,
  Decision,
  Game,
  GameLog,
  GamePhase,
  PendingHumanAction,
  PendingAction,
  PendingActionOption,
  Player,
  RoleKey,
  SkillState
} from '../../types/game'
import { arrayOrEmpty, booleanValue, firstString, integerValue, isRecord, numberValue, objectOrEmpty, stringValue } from '../common'

const ROLE_LABELS: Record<string, string> = {
  white_wolf_king: '白狼王',
  werewolf: '狼人',
  villager: '平民',
  seer: '预言家',
  witch: '女巫',
  hunter: '猎人',
  guard: '守卫'
}

const PHASE_ALIASES: Record<string, GamePhase> = {
  sheriff_election: 'sheriff',
  day_speech: 'speech',
  finished: 'ended',
  result: 'night'
}

const SPEECH_ACTIONS = new Set([
  'speech',
  'speak',
  'talk',
  'message',
  'chat',
  'statement',
  'discussion',
  'day_speech',
  'player_speech',
  'sheriff_speak',
  'sheriff_speech',
  'pk_speak',
  'pk_speech',
  'last_word'
])

const VOTE_ACTIONS = new Set(['vote', 'exile_vote', 'pk_vote', 'sheriff_vote'])
const REQUIRED_TARGET_ACTIONS = new Set(['guard_protect', 'werewolf_kill', 'seer_check'])
const OPTIONAL_TARGET_ACTIONS = new Set(['exile_vote', 'pk_vote', 'sheriff_vote', 'hunter_shoot'])

const CHOICE_ACTIONS: Record<string, PendingActionOption[]> = {
  sheriff_run: [
    { value: 'run', label: '竞选' },
    { value: 'pass', label: '不上警' }
  ],
  sheriff_withdraw: [
    { value: 'stay', label: '留警上' },
    { value: 'withdraw', label: '退水' }
  ],
  speech_order: [
    { value: 'forward', label: '顺序发言' },
    { value: 'reverse', label: '逆序发言' }
  ],
  sheriff_badge: [
    { value: 'transfer', label: '移交警徽', requiresTarget: true },
    { value: 'destroy', label: '撕毁警徽' }
  ],
  white_wolf_explode: [
    { value: 'explode', label: '自爆带人', requiresTarget: true },
    { value: 'pass', label: '暂不自爆' }
  ]
}

const ACTION_PROMPTS: Record<string, string> = {
  sheriff_run: '请选择是否竞选警长。',
  sheriff_withdraw: '请选择是否退水。',
  sheriff_vote: '请选择警长票目标。',
  sheriff_badge: '请选择警徽处理方式。',
  speech_order: '请选择发言顺序。',
  guard_protect: '请选择守护目标。',
  werewolf_kill: '请选择夜刀目标。',
  seer_check: '请选择查验目标。',
  witch_act: '女巫请选择是否发动技能。',
  white_wolf_explode: '请选择是否发动白狼王自爆。',
  exile_vote: '请选择放逐票目标。',
  pk_vote: '请选择对决票目标。',
  hunter_shoot: '请选择开枪目标。'
}

const TERMINAL_GAME_STATUSES = new Set(['completed', 'failed', 'cancelled'])

export function normalizePhase(phase: unknown): GamePhase {
  const text = stringValue(phase, 'setup')
  return PHASE_ALIASES[text] || text
}

export function normalizeRoleLabel(role: unknown): string {
  const key = stringValue(role)
  return ROLE_LABELS[key] || key || '未知'
}

export function canonicalActionType(actionType: unknown): string {
  const action = stringValue(actionType)
  if (action === 'white_wolf_burst' || action === 'white_wolf_explosion') return 'white_wolf_explode'
  if (action === 'vote') return 'exile_vote'
  return action
}

export function canonicalChoice(actionType: unknown, choice: unknown): string | null {
  if (choice === '') return null
  const action = canonicalActionType(actionType)
  const text = choice == null ? null : String(choice)
  if (action === 'witch_act') {
    if (text === 'antidote') return 'save'
    if (text === 'skip') return 'none'
  }
  if (action === 'white_wolf_explode' && text === 'burst') return 'explode'
  return text
}

export function isSpeechAction(actionType: unknown): boolean {
  return SPEECH_ACTIONS.has(canonicalActionType(actionType))
}

export function normalizeCandidateIds(value: unknown): number[] {
  return arrayOrEmpty(value)
    .map((item) => {
      if (isRecord(item)) return Number(item.id ?? item.player_id ?? item.seat)
      return Number(item)
    })
    .filter((id) => Number.isFinite(id) && id > 0)
}

export function choiceOptionsForAction(actionType: unknown, metadata: unknown = {}): PendingActionOption[] {
  const action = canonicalActionType(actionType)
  const source = objectOrEmpty(metadata)
  const choices = arrayOrEmpty(source.choices)
  if (action === 'speech_order' && choices.length) {
    return choices.map((value) => ({
      value: stringValue(value),
      label: value === 'reverse' ? '逆序发言' : '顺序发言'
    }))
  }
  return CHOICE_ACTIONS[action] || []
}

export function targetRequiredForAction(actionType: unknown, metadata: unknown = {}): boolean {
  const action = canonicalActionType(actionType)
  const source = objectOrEmpty(metadata)
  if (typeof source.target_required === 'boolean') return source.target_required
  if (typeof source.allow_no_target === 'boolean') return !source.allow_no_target
  if (OPTIONAL_TARGET_ACTIONS.has(action)) return false
  return REQUIRED_TARGET_ACTIONS.has(action)
}

export function normalizeLogEntry(raw: unknown = {}): GameLog {
  const log = objectOrEmpty(raw)
  const actorId = log.actor_id ?? log.actor ?? log.player_id ?? log.playerId ?? log.speaker_id ?? log.speakerId
  const targetId = log.target_id ?? log.target
  const message = firstString(log.message, log._message, log.content, log.text, log.public_summary, log.public_text)
  return {
    ...log,
    sequence: integerValue(log.sequence ?? log.index, 0),
    phase: normalizePhase(log.phase),
    type: firstString(log.type, log.event_type, log.action, log.action_type, log.kind),
    actor_id: actorId as GameLog['actor_id'],
    target_id: targetId as GameLog['target_id'],
    speaker: firstString(log.speaker, log._speaker, log.actor_name, log.player_name, actorId ? `${actorId}号` : '法官'),
    visibility: firstString(log.visibility, log.public === false ? 'private' : 'public'),
    message
  }
}

export function normalizeDecisionEntry(raw: unknown = {}, index = 0): Decision {
  const decision = objectOrEmpty(raw)
  const action = firstString(decision.action, decision.action_type)
  const actorId = decision.actor_id ?? decision.player_id
  const targetId = decision.target_id ?? decision.selected_target
  const publicSummary = firstString(decision.public_summary, decision.public_text, decision.text)
  const selectedSkills = arrayOrEmpty<string>(decision.selected_skills)
  return {
    ...decision,
    index: integerValue(decision.index, index),
    id: firstString(decision.id, decision.decision_id, `decision_${index}`),
    actor_id: actorId as Decision['actor_id'],
    player_id: (decision.player_id ?? actorId) as Decision['player_id'],
    target_id: targetId as Decision['target_id'],
    action,
    action_type: action,
    phase: normalizePhase(decision.phase),
    public_summary: publicSummary,
    reason: firstString(decision.reason, decision.private_reasoning, publicSummary),
    selected_skill: firstString(decision.selected_skill, selectedSkills[0]) || null,
    memory_refs: arrayOrEmpty(decision.memory_refs ?? decision.memory_summary),
    belief_snapshot: objectOrEmpty(decision.belief_snapshot),
    source: firstString(decision.source, 'llm'),
    confidence: numberValue(decision.confidence, 0)
  }
}

export function normalizePlayer(raw: unknown = {}, humanPlayerId: unknown = null): Player {
  const player = objectOrEmpty(raw)
  const id = integerValue(player.id ?? player.seat, 0)
  const role = firstString(player.role, player.role_hint)
  const humanId = humanPlayerId == null ? null : Number(humanPlayerId)
  return {
    ...player,
    id,
    seat: integerValue(player.seat, id),
    name: firstString(player.name, id ? `${id}号` : '玩家'),
    role: role as RoleKey,
    role_hint: firstString(player.role_hint, normalizeRoleLabel(role)),
    alive: player.alive !== false,
    is_human: booleanValue(player.is_human, humanId != null && id === humanId),
    is_sheriff: booleanValue(player.is_sheriff, false)
  }
}

export function normalizePendingHumanAction(raw: unknown): {
  waiting_for: string
  pending_action: PendingAction | null
  pending_human_action: PendingHumanAction | null
  current_speaker_id?: number | null
} {
  if (!raw) {
    return {
      waiting_for: 'none',
      pending_action: null,
      pending_human_action: null
    }
  }

  const pending = objectOrEmpty(raw)
  const actionType = canonicalActionType(pending.action_type ?? pending.type)
  const metadata = objectOrEmpty(pending.metadata)
  const observation = objectOrEmpty(pending.observation)
  const roleState = objectOrEmpty(observation.role_state)
  const candidates = normalizeCandidateIds(pending.candidate_ids ?? pending.candidates)
  const targetRequired = targetRequiredForAction(actionType, {
    ...metadata,
    target_required: pending.target_required ?? metadata.target_required,
    allow_no_target: pending.allow_no_target ?? metadata.allow_no_target
  })
  const normalizedPending: PendingHumanAction = {
    ...pending,
    action_type: actionType,
    type: actionType,
    player_id: pending.player_id == null ? undefined : integerValue(pending.player_id),
    candidate_ids: candidates,
    target_required: targetRequired,
    allow_no_target: !targetRequired
  }
  const waitingFor = SPEECH_ACTIONS.has(actionType) ? 'speech' : VOTE_ACTIONS.has(actionType) ? 'vote' : 'action'

  return {
    waiting_for: waitingFor,
    pending_human_action: normalizedPending,
    pending_action: SPEECH_ACTIONS.has(actionType)
      ? null
      : {
          type: actionType,
          prompt: firstString(pending.prompt, ACTION_PROMPTS[actionType], '请选择本轮行动。'),
          candidate_ids: candidates,
          target_required: targetRequired,
          allow_no_target: !targetRequired,
          options: {
            ...metadata,
            target_required: targetRequired,
            allow_no_target: !targetRequired,
            choices: choiceOptionsForAction(actionType, metadata),
            poison_available: booleanValue(metadata.can_poison ?? metadata.poison_available ?? roleState.poison_available, false),
            antidote_available: booleanValue(metadata.can_save ?? metadata.antidote_available ?? roleState.antidote_available, false),
            attacked_player: (metadata.attacked_player ?? null) as number | string | null
          }
        },
    current_speaker_id: SPEECH_ACTIONS.has(actionType) ? integerValue(pending.player_id, 0) || null : null
  }
}

export function normalizeSkillState(game: Partial<Game>, pending: PendingHumanAction | null = null): SkillState {
  const players = Array.isArray(game.players) ? game.players : []
  const human = players.find((player) => player.id === Number(game.human_player_id))
  const roleState = objectOrEmpty(human?.role_state ?? objectOrEmpty(pending?.observation).role_state)
  const existing = objectOrEmpty(game.skill_state)
  const antidoteHistory = arrayOrEmpty(roleState.antidote_history)
  const poisonHistory = arrayOrEmpty(roleState.poison_history)
  const antidoteUsed = roleState.antidote_available === false || antidoteHistory.length > 0
  const poisonUsed = roleState.poison_available === false || poisonHistory.length > 0
  return {
    ...existing,
    witch_antidote_used: booleanValue(existing.witch_antidote_used, antidoteUsed),
    witch_poison_used: booleanValue(existing.witch_poison_used, poisonUsed),
    white_wolf_burst_used: booleanValue(existing.white_wolf_burst_used, booleanValue(roleState.has_exploded, false))
  }
}

export function normalizeGameSnapshot(raw: unknown, options: { mode?: string; pending?: unknown } = {}): Game | null {
  if (!raw) return null
  const source = objectOrEmpty(raw)
  const pendingSource = Object.prototype.hasOwnProperty.call(options, 'pending') ? options.pending : source.pending_human_action
  const humanPlayerId = source.human_player_id ?? objectOrEmpty(pendingSource).player_id ?? null
  const events = Array.isArray(source.logs) ? source.logs : arrayOrEmpty(source.events)
  const players = arrayOrEmpty(source.players).map((player) => normalizePlayer(player, humanPlayerId))
  const decisions = arrayOrEmpty(source.decisions).map((decision, index) => normalizeDecisionEntry(decision, index + 1))
  const game: Game = {
    ...source,
    game_id: firstString(source.game_id, source.id),
    id: firstString(source.id, source.game_id) || undefined,
    mode: firstString(source.mode, options.mode, humanPlayerId ? 'play' : 'watch'),
    human_player_id: humanPlayerId == null ? null : integerValue(humanPlayerId),
    phase: normalizePhase(source.phase),
    logs: events.map(normalizeLogEntry),
    decisions,
    players,
    player_count: integerValue(source.player_count, players.length || 12),
    waiting_for: firstString(source.waiting_for, 'none'),
    pending_action: (source.pending_action as PendingAction | null) || null,
    skill_state: objectOrEmpty(source.skill_state)
  }

  if (pendingSource !== undefined) {
    const normalizedPending = normalizePendingHumanAction(pendingSource)
    game.waiting_for = pendingSource ? normalizedPending.waiting_for : firstString(source.waiting_for, 'none')
    game.pending_action = pendingSource ? normalizedPending.pending_action : ((source.pending_action as PendingAction | null) || null)
    game.pending_human_action = pendingSource ? normalizedPending.pending_human_action : null
    if (normalizedPending.current_speaker_id !== undefined) {
      game.current_speaker_id = normalizedPending.current_speaker_id
    }
  }

  game.skill_state = normalizeSkillState(game, game.pending_human_action || null)
  return game
}

export function isTerminalGame(game: Pick<Game, 'winner' | 'status'> | null | undefined): boolean {
  return Boolean(game?.winner) || TERMINAL_GAME_STATUSES.has(stringValue(game?.status))
}

export function isReturnableGame(game: Pick<Game, 'game_id' | 'winner' | 'status'> | null | undefined): boolean {
  return Boolean(game?.game_id) && !isTerminalGame(game)
}

export function activeSessionFromGame(game: Partial<Game> | null | undefined, options: { mode?: string; sseConnected?: boolean } = {}): ActiveGameSession {
  const running = isReturnableGame(game as Game)
  return {
    gameId: firstString(game?.game_id) || null,
    mode: firstString(game?.mode, options.mode),
    running,
    sseConnected: running && Boolean(options.sseConnected)
  }
}

export function emptyActiveSession(): ActiveGameSession {
  return { gameId: null, mode: '', running: false, sseConnected: false }
}
