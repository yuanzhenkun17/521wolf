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
  exile_vote: 'vote',
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

function normalizePhase(phase) {
  return PHASE_ALIASES[phase] || phase || 'setup'
}

function normalizeRole(role) {
  return ROLE_LABELS[role] || role || '未知'
}

function normalizeLogEntry(log = {}) {
  const actorId = log.actor_id ?? log.actor ?? log.player_id ?? log.playerId ?? log.speaker_id ?? log.speakerId
  const targetId = log.target_id ?? log.target
  const message = log.message ?? log._message ?? log.content ?? log.text ?? log.public_summary ?? log.public_text ?? ''
  return {
    ...log,
    sequence: log.sequence ?? log.index ?? 0,
    phase: normalizePhase(log.phase),
    type: log.type || log.event_type || log.action || log.action_type || log.kind || '',
    actor_id: actorId,
    target_id: targetId,
    speaker: log.speaker || log._speaker || log.actor_name || log.player_name || (actorId ? `${actorId}号` : '法官'),
    visibility: log.visibility || (log.public === false ? 'private' : 'public'),
    message
  }
}

function normalizeDecisionEntry(decision = {}, index = 0) {
  const action = decision.action || decision.action_type || ''
  const actorId = decision.actor_id ?? decision.player_id
  const targetId = decision.target_id ?? decision.selected_target
  const publicSummary = decision.public_summary || decision.public_text || decision.text || ''
  const selectedSkills = decision.selected_skills || []
  return {
    ...decision,
    index: decision.index ?? index,
    id: decision.id || decision.decision_id || `decision_${index}`,
    actor_id: actorId,
    player_id: decision.player_id ?? actorId,
    target_id: targetId,
    action,
    action_type: action,
    phase: normalizePhase(decision.phase),
    public_summary: publicSummary,
    reason: decision.reason || decision.private_reasoning || publicSummary,
    selected_skill: decision.selected_skill || selectedSkills[0] || null,
    memory_refs: decision.memory_refs || decision.memory_summary || [],
    belief_snapshot: decision.belief_snapshot || {},
    source: decision.source || 'llm',
    confidence: decision.confidence ?? 0
  }
}

function normalizePlayer(player = {}, humanPlayerId = null) {
  const id = Number(player.id ?? player.seat ?? 0)
  const role = player.role || player.role_hint || ''
  return {
    ...player,
    id,
    seat: player.seat || id,
    name: player.name || (id ? `${id}号` : '玩家'),
    role_hint: player.role_hint || normalizeRole(role),
    alive: player.alive !== false,
    is_human: player.is_human || (humanPlayerId != null && id === Number(humanPlayerId)),
    is_sheriff: Boolean(player.is_sheriff)
  }
}

function choiceOptionsForAction(actionType, metadata = {}) {
  if (actionType === 'speech_order' && Array.isArray(metadata.choices) && metadata.choices.length) {
    return metadata.choices.map((value) => ({
      value,
      label: value === 'reverse' ? '逆序发言' : '顺序发言'
    }))
  }
  return CHOICE_ACTIONS[actionType] || []
}

function normalizeCandidateIds(value = []) {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => Number(typeof item === 'object' && item !== null ? (item.id ?? item.player_id ?? item.seat) : item))
    .filter((id) => Number.isFinite(id) && id > 0)
}

function normalizeSkillState(game, pending = null) {
  const human = game.players?.find((player) => player.id === Number(game.human_player_id))
  const roleState = human?.role_state || pending?.observation?.role_state || {}
  const antidoteUsed = roleState.antidote_available === false || Boolean(roleState.antidote_history?.length)
  const poisonUsed = roleState.poison_available === false || Boolean(roleState.poison_history?.length)
  return {
    ...(game.skill_state || {}),
    witch_antidote_used: game.skill_state?.witch_antidote_used ?? antidoteUsed,
    witch_poison_used: game.skill_state?.witch_poison_used ?? poisonUsed,
    white_wolf_burst_used: game.skill_state?.white_wolf_burst_used ?? Boolean(roleState.has_exploded)
  }
}

function normalizePendingHumanAction(pending) {
  if (!pending) {
    return {
      waiting_for: 'none',
      pending_action: null,
      pending_human_action: null
    }
  }

  const actionType = canonicalActionType(pending.action_type || pending.type || '')
  const metadata = pending.metadata || {}
  const roleState = pending.observation?.role_state || {}
  const candidates = normalizeCandidateIds(pending.candidate_ids || pending.candidates || [])
  const normalizedPending = {
    ...pending,
    action_type: actionType,
    type: actionType,
    candidate_ids: candidates
  }
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
          prompt: pending.prompt || ACTION_PROMPTS[actionType] || '请选择本轮行动。',
          candidate_ids: candidates,
          options: {
            ...metadata,
            choices: choiceOptionsForAction(actionType, metadata),
            poison_available: metadata.can_poison ?? metadata.poison_available ?? roleState.poison_available ?? false,
            antidote_available: metadata.can_save ?? metadata.antidote_available ?? roleState.antidote_available ?? false,
            attacked_player: metadata.attacked_player ?? null
          }
        },
    current_speaker_id: SPEECH_ACTIONS.has(actionType) ? normalizedPending.player_id : null
  }
}

function normalizeGameSnapshot(raw, options = {}) {
  if (!raw) return raw

  const pending = options.pending !== undefined ? options.pending : raw.pending_human_action
  const humanPlayerId = raw.human_player_id ?? pending?.player_id ?? null
  const events = Array.isArray(raw.logs)
    ? raw.logs
    : (Array.isArray(raw.events) ? raw.events : [])
  const game = {
    ...raw,
    mode: raw.mode || options.mode || (humanPlayerId ? 'play' : 'watch'),
    human_player_id: humanPlayerId,
    phase: normalizePhase(raw.phase),
    logs: events.map(normalizeLogEntry),
    decisions: (raw.decisions || []).map((decision, index) => normalizeDecisionEntry(decision, index + 1)),
    players: (raw.players || []).map((player) => normalizePlayer(player, humanPlayerId)),
    player_count: raw.player_count || raw.players?.length || 12,
    waiting_for: raw.waiting_for || 'none',
    pending_action: raw.pending_action || null
  }

  if (pending !== undefined) {
    const normalizedPending = normalizePendingHumanAction(pending)
    game.waiting_for = pending ? normalizedPending.waiting_for : (raw.waiting_for || 'none')
    game.pending_action = pending ? normalizedPending.pending_action : (raw.pending_action || null)
    game.pending_human_action = pending ? normalizedPending.pending_human_action : null
    if (normalizedPending.current_speaker_id !== undefined) {
      game.current_speaker_id = normalizedPending.current_speaker_id
    }
  }

  game.skill_state = normalizeSkillState(game, game.pending_human_action || null)
  return game
}

function isSpeechAction(actionType) {
  return SPEECH_ACTIONS.has(actionType)
}

function canonicalActionType(actionType) {
  if (actionType === 'white_wolf_burst') return 'white_wolf_explode'
  if (actionType === 'white_wolf_explosion') return 'white_wolf_explode'
  if (actionType === 'vote') return 'exile_vote'
  return actionType || ''
}

function canonicalChoice(actionType, choice) {
  if (choice === '') return null
  const action = canonicalActionType(actionType)
  if (action === 'witch_act') {
    if (choice === 'antidote') return 'save'
    if (choice === 'skip') return 'none'
  }
  if (action === 'white_wolf_explode' && choice === 'burst') return 'explode'
  return choice ?? null
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
  normalizePlayer
}
