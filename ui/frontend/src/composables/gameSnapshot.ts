import type {
  Decision,
  Game,
  GameLog,
  GamePhase,
  PendingAction,
  PendingActionOption,
  PendingHumanAction,
  Player,
  SkillState
} from '../types/game'

type LooseRecord = Record<string, any>

const ROLE_LABELS = {
  white_wolf_king: '白狼王',
  werewolf: '狼人',
  villager: '平民',
  seer: '预言家',
  witch: '女巫',
  hunter: '猎人',
  guard: '守卫'
}

const PHASE_ALIASES = {
  sheriff_election: 'sheriff',
  day_speech: 'speech',
  finished: 'ended'
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

const CHOICE_ACTIONS = {
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

const ACTION_PROMPTS = {
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

function isRecord(value: unknown): value is LooseRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function objectOrEmpty(value: unknown): LooseRecord {
  return isRecord(value) ? value : {}
}

function arrayOrEmpty<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : []
}

function firstPresent(...values: unknown[]): unknown {
  for (const value of values) {
    if (value !== null && value !== undefined && value !== '') return value
  }
  return undefined
}

function textValue(value: unknown, fallback = ''): string {
  return value == null ? fallback : String(value)
}

function idValue(value: unknown): string | number | null {
  if (value == null || value === '') return null
  return typeof value === 'number' || typeof value === 'string' ? value : textValue(value)
}

function numberValue(value: unknown, fallback = 0): number {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function normalizePhase(phase: unknown): GamePhase {
  const text = typeof phase === 'string' ? phase : String(phase || '')
  return PHASE_ALIASES[text] || text || 'setup'
}

function normalizeRole(role: unknown): string {
  const text = typeof role === 'string' ? role : String(role || '')
  return ROLE_LABELS[text] || text || '未知'
}

function normalizeLogEntry(log: unknown = {}): GameLog {
  const source = objectOrEmpty(log)
  const actorId = source.actor_id ?? source.actor ?? source.player_id ?? source.playerId ?? source.speaker_id ?? source.speakerId
  const targetId = source.target_id ?? source.target
  const message = source.message ?? source._message ?? source.content ?? source.text ?? source.public_summary ?? source.public_text ?? ''
  return {
    ...source,
    sequence: source.sequence ?? source.index ?? 0,
    phase: normalizePhase(source.phase),
    type: source.type || source.event_type || source.action || source.action_type || source.kind || '',
    actor_id: actorId,
    target_id: targetId,
    speaker: source.speaker || source._speaker || source.actor_name || source.player_name || (actorId ? `${actorId}号` : '法官'),
    visibility: source.visibility || (source.public === false ? 'private' : 'public'),
    message
  }
}

function normalizeDecisionEntry(decision: unknown = {}, index = 0): Decision {
  const source = objectOrEmpty(decision)
  const metadata = objectOrEmpty(source.metadata)
  const payload = objectOrEmpty(source.payload)
  const choice = objectOrEmpty(source.choice)
  const action = textValue(firstPresent(
    source.action,
    source.action_type,
    source.type,
    source.event_type,
    metadata.action,
    payload.action,
    payload.action_type
  ))
  const actorId = firstPresent(
    source.actor_id,
    source.actor,
    source.player_id,
    source.playerId,
    source.player_seat,
    source.seat,
    metadata.actor_id,
    payload.actor_id,
    payload.player_id
  )
  const targetId = firstPresent(
    source.target_id,
    source.target,
    source.targetId,
    source.target_seat,
    source.selected_target,
    source.selectedTarget,
    metadata.target_id,
    payload.target_id,
    payload.selected_target,
    choice.target,
    choice.target_id
  )
  const publicSummary = textValue(firstPresent(
    source.public_summary,
    source.public_text,
    source.summary,
    source.message,
    source.text,
    payload.public_summary,
    payload.message
  ))
  const selectedSkills = arrayOrEmpty(source.selected_skills)
  return {
    ...source,
    index: source.index ?? index,
    id: source.id || source.decision_id || `decision_${index}`,
    actor_id: idValue(actorId),
    player_id: idValue(source.player_id ?? actorId),
    target_id: idValue(targetId),
    action,
    action_type: action,
    phase: normalizePhase(source.phase),
    public_summary: publicSummary,
    reason: textValue(firstPresent(source.reason, source.private_reasoning, metadata.reason, payload.reason, publicSummary)),
    selected_skill: source.selected_skill || selectedSkills[0] || null,
    memory_refs: source.memory_refs || source.memory_summary || [],
    belief_snapshot: source.belief_snapshot || {},
    source: source.source || 'llm',
    confidence: numberValue(firstPresent(source.confidence, metadata.confidence, payload.confidence, 0))
  }
}

function normalizePlayer(player: unknown = {}, humanPlayerId: unknown = null): Player {
  const source = objectOrEmpty(player)
  const id = Number(source.id ?? source.seat ?? 0)
  const role = source.role || source.role_hint || ''
  return {
    ...source,
    id,
    seat: source.seat || id,
    name: source.name || (id ? `${id}号` : '玩家'),
    role_hint: source.role_hint || normalizeRole(role),
    alive: source.alive !== false,
    is_human: source.is_human || (humanPlayerId != null && id === Number(humanPlayerId)),
    is_sheriff: Boolean(source.is_sheriff)
  }
}

function choiceOptionsForAction(actionType: unknown, metadata: unknown = {}): PendingActionOption[] {
  const source = objectOrEmpty(metadata)
  if (actionType === 'speech_order' && Array.isArray(source.choices) && source.choices.length) {
    return source.choices.map((value) => ({
      value: String(value),
      label: value === 'reverse' ? '逆序发言' : '顺序发言'
    }))
  }
  return CHOICE_ACTIONS[String(actionType || '')] || []
}

function targetRequiredForAction(actionType: unknown, metadata: unknown = {}): boolean {
  const source = objectOrEmpty(metadata)
  const action = canonicalActionType(actionType)
  if (typeof source.target_required === 'boolean') return source.target_required
  if (typeof source.allow_no_target === 'boolean') return !source.allow_no_target
  if (OPTIONAL_TARGET_ACTIONS.has(action)) return false
  return REQUIRED_TARGET_ACTIONS.has(action)
}

function normalizeCandidateIds(value: unknown = []): number[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => Number(isRecord(item) ? (item.id ?? item.player_id ?? item.seat) : item))
    .filter((id) => Number.isFinite(id) && id > 0)
}

function normalizeSkillState(game: Partial<Game>, pending: PendingHumanAction | null = null): SkillState {
  const human = game.players?.find((player) => player.id === Number(game.human_player_id))
  const roleState = objectOrEmpty(human?.role_state ?? pending?.observation?.role_state)
  const antidoteUsed = roleState.antidote_available === false || Boolean(roleState.antidote_history?.length)
  const poisonUsed = roleState.poison_available === false || Boolean(roleState.poison_history?.length)
  return {
    ...(game.skill_state || {}),
    witch_antidote_used: game.skill_state?.witch_antidote_used ?? antidoteUsed,
    witch_poison_used: game.skill_state?.witch_poison_used ?? poisonUsed,
    white_wolf_burst_used: game.skill_state?.white_wolf_burst_used ?? Boolean(roleState.has_exploded)
  }
}

function normalizePendingHumanAction(pending: unknown): {
  waiting_for: string
  pending_action: PendingAction | null
  pending_human_action: PendingHumanAction | null
  current_speaker_id?: number | null
} {
  if (!pending) {
    return {
      waiting_for: 'none',
      pending_action: null,
      pending_human_action: null
    }
  }

  const source = objectOrEmpty(pending)
  const actionType = canonicalActionType(source.action_type || source.type || '')
  const metadata = objectOrEmpty(source.metadata)
  const roleState = objectOrEmpty(source.observation?.role_state)
  const candidates = normalizeCandidateIds(source.candidate_ids || source.candidates || [])
  const targetRequired = targetRequiredForAction(actionType, {
    ...metadata,
    target_required: source.target_required ?? metadata.target_required,
    allow_no_target: source.allow_no_target ?? metadata.allow_no_target
  })
  const allowNoTarget = !targetRequired
  const normalizedPending = {
    ...source,
    action_type: actionType,
    type: actionType,
    candidate_ids: candidates,
    target_required: targetRequired,
    allow_no_target: allowNoTarget
  } as PendingHumanAction
  const waitingFor = SPEECH_ACTIONS.has(actionType)
    ? 'speech'
    : (VOTE_ACTIONS.has(actionType) ? 'vote' : 'action')

  return {
    waiting_for: waitingFor,
    pending_human_action: normalizedPending,
    pending_action: SPEECH_ACTIONS.has(actionType)
      ? null
      : {
          type: actionType,
          prompt: source.prompt || ACTION_PROMPTS[actionType] || '请选择本轮行动。',
          candidate_ids: candidates,
          target_required: targetRequired,
          allow_no_target: allowNoTarget,
          options: {
            ...metadata,
            target_required: targetRequired,
            allow_no_target: allowNoTarget,
            choices: choiceOptionsForAction(actionType, metadata),
            poison_available: metadata.can_poison ?? metadata.poison_available ?? roleState.poison_available ?? false,
            antidote_available: metadata.can_save ?? metadata.antidote_available ?? roleState.antidote_available ?? false,
            attacked_player: metadata.attacked_player ?? null
          }
        },
    current_speaker_id: SPEECH_ACTIONS.has(actionType) ? normalizedPending.player_id ?? null : null
  }
}

function normalizeGameSnapshot(raw: unknown, options: { mode?: string; pending?: unknown } = {}): Game | null {
  if (!raw) return raw as null

  const source = objectOrEmpty(raw)
  const pending = options.pending !== undefined ? options.pending : source.pending_human_action
  const pendingSource = objectOrEmpty(pending)
  const humanPlayerId = source.human_player_id ?? pendingSource.player_id ?? null
  const events = Array.isArray(source.logs)
    ? source.logs
    : (Array.isArray(source.events) ? source.events : [])
  const game = {
    ...source,
    mode: source.mode || options.mode || (humanPlayerId ? 'play' : 'watch'),
    human_player_id: humanPlayerId,
    phase: normalizePhase(source.phase),
    logs: events.map(normalizeLogEntry),
    decisions: (source.decisions || []).map((decision: unknown, index: number) => normalizeDecisionEntry(decision, index + 1)),
    players: (source.players || []).map((player: unknown) => normalizePlayer(player, humanPlayerId)),
    player_count: source.player_count || source.players?.length || 12,
    waiting_for: source.waiting_for || 'none',
    pending_action: source.pending_action || null
  } as Game

  if (pending !== undefined) {
    const normalizedPending = normalizePendingHumanAction(pending)
    game.waiting_for = pending ? normalizedPending.waiting_for : (source.waiting_for || 'none')
    game.pending_action = pending ? normalizedPending.pending_action : (source.pending_action || null)
    game.pending_human_action = pending ? normalizedPending.pending_human_action : null
    if (normalizedPending.current_speaker_id !== undefined) {
      game.current_speaker_id = normalizedPending.current_speaker_id
    }
  }

  game.skill_state = normalizeSkillState(game, game.pending_human_action || null)
  return game
}

function isSpeechAction(actionType: unknown): boolean {
  return SPEECH_ACTIONS.has(canonicalActionType(actionType))
}

function canonicalActionType(actionType: unknown): string {
  if (actionType === 'white_wolf_burst') return 'white_wolf_explode'
  if (actionType === 'white_wolf_explosion') return 'white_wolf_explode'
  if (actionType === 'vote') return 'exile_vote'
  return actionType ? String(actionType) : ''
}

function canonicalChoice(actionType: unknown, choice: unknown): string | null {
  if (choice === '') return null
  const action = canonicalActionType(actionType)
  if (action === 'witch_act') {
    if (choice === 'antidote') return 'save'
    if (choice === 'skip') return 'none'
  }
  if (action === 'white_wolf_explode' && choice === 'burst') return 'explode'
  return choice == null ? null : String(choice)
}


export {
  canonicalActionType,
  canonicalChoice,
  choiceOptionsForAction,
  isSpeechAction,
  normalizeCandidateIds,
  normalizeGameSnapshot,
  normalizeDecisionEntry,
  normalizeLogEntry,
  normalizePendingHumanAction,
  normalizePhase,
  normalizePlayer,
  targetRequiredForAction
}
