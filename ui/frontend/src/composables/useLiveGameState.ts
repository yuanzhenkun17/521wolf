import { computed } from 'vue'
import { displayActionLabel, displayPhaseLabel, displayWinnerLabel } from '../components/history/historyDisplay.ts'
import { decisionActionText, phaseLabel, phaseText, roleIconSpecs, roleMatches, seatHash } from './gameStateShared.ts'
import { choiceOptionsForAction, targetRequiredForAction } from './gameSnapshot.ts'
import { buildSceneEffects } from './sceneEffects.ts'

type LooseRecord = Record<string, any>

const chatSpeechTypes = new Set([
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
const chatVoteTypes = new Set(['vote', 'exile_vote', 'pk_vote', 'sheriff_vote'])
const sceneVotePhases = new Set(['vote', 'exile_vote', 'pk_vote', 'sheriff_vote'])
const votePhaseByType = {
  vote: 'exile_vote',
  exile_vote: 'exile_vote',
  exile_vote_start: 'exile_vote',
  exile_vote_end: 'exile_vote',
  exile_vote_tie: 'exile_vote',
  pk_vote: 'pk_vote',
  pk_vote_start: 'pk_vote',
  pk_vote_end: 'pk_vote',
  sheriff_vote: 'sheriff_vote'
}
const chatActionTypes = new Set([
  'guard_protect',
  'werewolf_kill',
  'seer_check',
  'witch_act',
  'hunter_shoot',
  'hunter_shot',
  'white_wolf_explode',
  'white_wolf_explosion',
  'sheriff_run',
  'sheriff_pass',
  'sheriff_withdraw',
  'sheriff_stay',
  'sheriff_badge',
  'speech_order'
])
const judgeAnnouncementTypes = new Set([
  'setup',
  'night_start',
  'night_end',
  'night_result',
  'night_death_reveal',
  'day_speech_start',
  'day_speech_end',
  'vote_prompt',
  'exile',
  'death',
  'exile_vote_start',
  'exile_vote_end',
  'exile_vote_tie',
  'pk_vote_end',
  'sheriff_start',
  'sheriff_result',
  'sheriff_election_start',
  'sheriff_election_end',
  'sheriff_badge_transfer',
  'sheriff_badge_destroy',
  'game_over',
  'game_end'
])
const judgeSpeakers = new Set(['法官', '系统'])
const JUDGE_AVATAR_URL = '/livehall-assets/props/optimized/judge-avatar-160.webp'
const typedRecordLabels = new Set([
  'action_request',
  'action_response',
  'invalid_response',
  'default_action',
  'agent_error'
])

function primaryLogTypes(log: LooseRecord | null | undefined) {
  return [
    log?.type,
    log?.event_type,
    log?.action,
    log?.action_type,
    log?.kind,
    log?._chatKind,
    log?.category
  ].map((value) => String(value || '').trim()).filter(Boolean)
}

function phaseLogTypes(log: LooseRecord | null | undefined) {
  return [log?.phase, log?.event_phase, log?.stage]
    .map((value) => String(value || '').trim())
    .filter(Boolean)
}

function normalizedLogType(log: LooseRecord | null | undefined) {
  return primaryLogTypes(log)[0] || ''
}

function hasAnyType(types: string[], set: Set<string>) {
  return types.some((type) => set.has(type))
}

function numericId(value: unknown): number | null {
  const id = Number(value)
  return Number.isFinite(id) && id > 0 ? id : null
}

function rowTargetId(row: LooseRecord = {}) {
  return numericId(
    row?.target_id
    ?? row?.selected_target
    ?? row?.target
    ?? row?.payload?.target_id
    ?? row?.payload?.target
  )
}

function voteActionPhase(action: unknown = '') {
  const value = String(action || '').trim()
  return votePhaseByType[value] || ''
}

function voteAction(row: LooseRecord = {}) {
  return String(row?.action || row?.action_type || row?.type || row?.event_type || '').trim()
}

function canonicalVoteAction(action: unknown = '') {
  const value = String(action || '').trim()
  return value === 'vote' ? 'exile_vote' : value
}

function voteRowMatchesPhase(row: LooseRecord = {}, activePhase = '') {
  const actionPhase = voteActionPhase(voteAction(row))
  if (!actionPhase) return false
  const rowPhase = String(row?.phase || activePhase).trim()
  if (activePhase === 'vote') {
    return actionPhase !== 'sheriff_vote' && (!sceneVotePhases.has(rowPhase) || rowPhase === 'vote')
  }
  if (actionPhase !== activePhase) return false
  return !sceneVotePhases.has(rowPhase) || rowPhase === activePhase || rowPhase === 'vote'
}

function latestVoteActionForScope(rows: LooseRecord[] = [], activePhase = '', currentDay: number | null = null) {
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    const row = rows[index]
    const action = voteAction(row)
    if (!action || !voteRowMatchesPhase(row, activePhase)) continue
    const rowDay = numericId(row?.day)
    if (currentDay && rowDay !== currentDay) continue
    return canonicalVoteAction(action)
  }
  return ''
}

function logActorId(log: LooseRecord | null | undefined) {
  return numericId(
    log?.actor_id
    ?? log?.actor
    ?? log?.player_id
    ?? log?.playerId
    ?? log?.speaker_id
    ?? log?.speakerId
    ?? log?.agent_id
    ?? log?.seat
    ?? log?._seat
  )
}

function logText(log: LooseRecord | null | undefined) {
  return String(
    log?._message
    ?? log?.message
    ?? log?.content
    ?? log?.text
    ?? log?.public_summary
    ?? log?.public_text
    ?? log?.payload?.message
    ?? log?.payload?.text
    ?? ''
  )
}

function chatKindForLog(log: LooseRecord | null | undefined) {
  const hasActor = logActorId(log) !== null
  const hasPlayerSpeaker = Boolean(log?.speaker) && !judgeSpeakers.has(log.speaker)
  if (!hasActor && !hasPlayerSpeaker) return null
  const primaryTypes = primaryLogTypes(log)
  if (hasAnyType(primaryTypes, chatVoteTypes)) return { key: 'vote', label: '投票' }
  if (hasAnyType(primaryTypes, chatActionTypes)) return { key: 'action', label: '行动' }
  if (hasAnyType(primaryTypes, chatSpeechTypes)) {
    return { key: 'speech', label: primaryTypes.includes('last_word') ? '遗言' : '发言' }
  }
  if (logText(log).trim() && hasAnyType(phaseLogTypes(log), chatSpeechTypes)) {
    return { key: 'speech', label: '发言' }
  }
  return null
}

function isJudgeAnnouncementLog(log: LooseRecord | null | undefined) {
  const type = normalizedLogType(log)
  if (judgeAnnouncementTypes.has(type)) return true
  if (log?.visibility === 'system') return true
  return judgeSpeakers.has(log?.speaker) && !chatKindForLog(log)
}

function winnerPromptText(winner: unknown) {
  if (!winner) return ''
  const label = displayWinnerLabel(winner)
  if (!label || label === '未记录') return '游戏结束'
  if (/获胜|胜利|平局|结束|取消|异常/.test(label)) return `游戏结束，${label}`
  return `游戏结束，胜利方：${label}`
}

export function createLiveGameState(refs: LooseRecord, helpers: LooseRecord) {
  const {
    game,
    currentView,
    backendMode,
    visualSeatSalt,
    judgeBoardStarted,
    roleAssignmentComplete,
    roleAssignmentCompleteNotice,
    speechRemaining,
    witchChoice,
    actionChoice,
    burstArmed
  } = refs
  const {
    canSeeLog,
    playerLabel,
    playerNumberById,
    normalizePlayerText,
    cardImage,
    roleIconImage,
    logSpeaker,
    logMessage
  } = helpers

  const computedState: LooseRecord = {}

  function isWolfRole(role: unknown = '') {
    const value = String(role || '')
    return value.includes('狼人') || value.includes('白狼王')
  }

  function canSeePlayerRole(player: LooseRecord | null | undefined) {
    if (!player) return false
    if (computedState.isWatch?.value || refs.isReplayMode.value || game.value?.winner) return true
    const human = computedState.humanPlayer?.value
    if (!human) return false
    if (Number(player.id) === Number(human.id) || player.is_human) return true
    return isWolfRole(human.role_hint) && isWolfRole(player.role_hint)
  }

  function visibleRoleIcon(player: LooseRecord | null | undefined) {
    return canSeePlayerRole(player) ? roleIconImage(player) : '/role-icons/optimized/未知.webp'
  }

  function visibleCardImage(player: LooseRecord | null | undefined) {
    if (!player) return JUDGE_AVATAR_URL
    return canSeePlayerRole(player) ? cardImage({ ...player, role_visible: true }) : '/cards/card-back.png'
  }

  function visiblePlayer(player: LooseRecord) {
    const roleVisible = canSeePlayerRole(player)
    return {
      ...player,
      role_visible: roleVisible,
      role_hint_actual: player?.role_hint || '',
      role_hint: roleVisible ? (player?.role_hint || '') : '未知',
      roleIcon: roleVisible ? roleIconImage(player) : '/role-icons/optimized/未知.webp'
    }
  }

  function playerForLog(log: LooseRecord | null | undefined) {
    const players = game.value?.players ?? []
    const actorId = logActorId(log)
    const speakerName = String(log?._speaker || log?.speaker || log?.actor_name || log?.player_name || '').trim()
    return players.find((player) =>
      Number(player.id) === actorId
      || String(player.name || '').trim() === speakerName
      || `${player.seat}号` === speakerName
      || `${player.id}号` === speakerName
    ) || null
  }

  function effectiveCurrentSpeakerId() {
    const direct = numericId(
      game.value?.current_speaker_id
      ?? game.value?.currentSpeakerId
      ?? game.value?.speaker_id
      ?? game.value?.speakerId
    )
    if (direct) return direct
    const pending = game.value?.pending_human_action
    const pendingType = String(pending?.action_type || pending?.type || '').trim()
    const pendingId = numericId(pending?.player_id ?? pending?.actor_id ?? pending?.speaker_id ?? pending?.seat)
    if (pendingId && chatSpeechTypes.has(pendingType)) return pendingId
    if (pending || ['action', 'vote'].includes(game.value?.waiting_for)) return null
    const logs = game.value?.logs ?? []
    for (let index = logs.length - 1; index >= 0; index -= 1) {
      const log = logs[index]
      if (log?.visibility === 'private' || chatKindForLog(log)?.key !== 'speech') continue
      const actorId = logActorId(log)
      if (actorId) return actorId
      const player = playerForLog(log)
      if (player?.id) return player.id
    }
    return null
  }

  function chatLogEntry(log: LooseRecord) {
    const player = playerForLog(log)
    const kind = chatKindForLog(log)
    const seat = player ? playerNumberById(player.id) : (log?.actor_id ? playerNumberById(log.actor_id) : '')
    return {
      ...log,
      _chatKind: kind?.key || 'action',
      _kindLabel: kind?.label || '行动',
      _seat: seat,
      _speaker: logSpeaker(log),
      _message: logMessage(log) || logText(log),
      _roleIcon: player ? visibleRoleIcon(player) : '/role-icons/optimized/未知.webp',
      _speaking: Boolean(player?.id && player.id === effectiveCurrentSpeakerId())
    }
  }

  function recordKindForLog(log: LooseRecord | null | undefined) {
    const kind = chatKindForLog(log)
    if (kind) return kind
    const type = normalizedLogType(log)
    if (typedRecordLabels.has(type)) {
      return { key: 'event', label: decisionActionText[type] || displayActionLabel(type) }
    }
    if (isJudgeAnnouncementLog(log)) return { key: 'judge', label: log?.speaker === '系统' ? '系统' : '法官' }
    return {
      key: 'event',
      label: decisionActionText[type] || phaseLabel[type] || displayActionLabel(type) || '记录'
    }
  }

  function matchRecordEntry(log: LooseRecord) {
    const player = playerForLog(log)
    const kind = recordKindForLog(log)
    const actor = logActorId(log)
    const seat = player
      ? playerNumberById(player.id)
      : (actor ? playerNumberById(actor) : (isJudgeAnnouncementLog(log) ? '法' : ''))
    return {
      ...log,
      _chatKind: kind.key,
      _kindLabel: kind.label,
      _seat: seat,
      _speaker: logSpeaker(log),
      _message: logMessage(log) || logText(log),
      _roleIcon: player ? visibleRoleIcon(player) : JUDGE_AVATAR_URL,
      _speaking: Boolean(player?.id && player.id === effectiveCurrentSpeakerId())
    }
  }

  computedState.isNight = computed(() => game.value?.phase === 'night')
  computedState.inLogs = computed(() => currentView.value === 'logs')
  computedState.inBenchmark = computed(() => currentView.value === 'benchmark')
  computedState.inEvolution = computed(() => currentView.value === 'evolution')
  computedState.inTasks = computed(() => currentView.value === 'tasks')
  computedState.inSettings = computed(() => currentView.value === 'settings')
  computedState.inLobby = computed(() =>
    currentView.value === 'lobby'
    || (!game.value && currentView.value !== 'match' && !computedState.inLogs.value && !computedState.inBenchmark.value && !computedState.inEvolution.value && !computedState.inTasks.value && !computedState.inSettings.value)
  )
  computedState.inMatch = computed(() => currentView.value === 'match')
  computedState.isWatch = computed(() => game.value?.mode === 'watch')
  computedState.sceneEffects = computed(() =>
    buildSceneEffects(game.value, {
      canSeeLog,
      isWatch: computedState.isWatch.value,
      isReplayMode: refs.isReplayMode.value
    })
  )
  computedState.humanPlayer = computed(() => game.value?.players?.find((p) => p.id === game.value.human_player_id))
  computedState.livingPlayers = computed(() => game.value?.players?.filter((p) => p.alive) ?? [])
  computedState.canVotePlayers = computed(() => computedState.livingPlayers.value.filter((p) => p.id !== game.value?.human_player_id))
  computedState.publicLogs = computed(() => (game.value?.logs ?? []).filter(canSeeLog).slice(-10))
  computedState.chatLogs = computed(() =>
    (game.value?.logs ?? [])
      .filter((log) => canSeeLog(log) && chatKindForLog(log))
      .map(chatLogEntry)
      .slice(-80)
  )
  computedState.matchRecordLogs = computed(() => {
    const logs = game.value?.logs ?? []
    if (computedState.isWatch.value || refs.isReplayMode.value) {
      return logs.filter(canSeeLog).map(matchRecordEntry)
    }
    return computedState.chatLogs.value
  })
  computedState.judgeLogs = computed(() =>
    (game.value?.logs ?? [])
      .filter((log) => canSeeLog(log) && isJudgeAnnouncementLog(log))
      .slice(-80)
  )
  computedState.groupedJudgeLogs = computed(() => {
    const groups = []
    let currentGroup = null
    computedState.judgeLogs.value.forEach((log) => {
      const day = log.day || 0
      const phase = log.phase || 'unknown'
      const groupKey = `${day}-${phase}`
      if (!currentGroup || currentGroup.key !== groupKey) {
        currentGroup = {
          key: groupKey,
          day,
          phase,
          phaseLabel: (phaseText[phase] || displayPhaseLabel(phase)).replace('{day}', day),
          logs: []
        }
        groups.push(currentGroup)
      }
      currentGroup.logs.push(log)
    })
    return groups.slice(-10)
  })
  computedState.speakingPlayer = computed(() => {
    const speakerId = effectiveCurrentSpeakerId()
    if (!speakerId) return null
    return game.value?.players?.find((p) => Number(p.id) === speakerId) || null
  })
  computedState.displayPhase = computed(() => {
    if (!game.value) return '选择模式'
    return (phaseText[game.value.phase] || '').replace('{day}', game.value.day)
  })
  computedState.promptText = computed(() => {
    if (!game.value) return '选择模式开始游戏'
    if (game.value.winner) return winnerPromptText(game.value.winner)
    if (game.value.waiting_for === 'speech') return '轮到你发言，所有智能体正在等待'
    if (game.value.waiting_for === 'vote') return '轮到你投票，提交后智能体继续行动'
    if (game.value.waiting_for === 'action') {
      return game.value.pending_action?.prompt || game.value.pending_human_action?.prompt || '轮到你行动，提交后智能体继续行动'
    }
    if (computedState.speakingPlayer.value) return `${playerLabel(computedState.speakingPlayer.value)} 正在发言`
    return phaseLabel[game.value.phase]
  })
  computedState.speakerMessage = computed(() => {
    const speaker = computedState.speakingPlayer.value
    if (!speaker) return game.value?.winner ? winnerPromptText(game.value.winner) : computedState.promptText.value
    const logs = (game.value?.logs ?? [])
      .filter((log) => log.visibility !== 'private' && (logActorId(log) === Number(speaker.id) || log.speaker === speaker.name))
    return normalizePlayerText(logText(logs.at(-1)) || computedState.promptText.value)
  })
  computedState.speakerCarousel = computed(() => {
    const players = game.value?.players ?? []
    const current = computedState.speakingPlayer.value
    if (!players.length || !current) {
      return [{ key: 'speaker-judge', label: '法官', image: JUDGE_AVATAR_URL, tone: 'current' }]
    }
    const order = players.filter((p) => p.alive)
    const index = order.findIndex((p) => p.id === current.id)
    const prev = order[(index - 1 + order.length) % order.length]
    const next = order[(index + 1) % order.length]
    return [
      { key: `speaker-${prev.id}`, label: playerLabel(prev), image: visibleCardImage(prev), tone: 'prev' },
      { key: `speaker-${current.id}`, label: playerLabel(current), image: visibleCardImage(current), tone: 'current' },
      { key: `speaker-${next.id}`, label: playerLabel(next), image: visibleCardImage(next), tone: 'next' }
    ]
  })
  computedState.inferredSheriffId = computed(() => {
    if (game.value?.sheriff_id) return game.value.sheriff_id
    const rows = game.value?.decisions ?? []
    for (let i = rows.length - 1; i >= 0; i--) {
      const decision = rows[i]
      if (decision.action === 'sheriff_destroy') return null
      if (decision.action === 'sheriff_transfer') return decision.target_id
      if (decision.action === 'sheriff_elect') return decision.target_id || decision.actor_id
    }
    return null
  })
  computedState.sheriffElection = computed(() => {
    const rows = game.value?.decisions ?? []
    const electIndex = rows.findLastIndex?.((row) => row.action === 'sheriff_elect') ?? -1
    const fallbackIndex = electIndex >= 0 ? electIndex : rows.length
    const runs = rows
      .slice(Math.max(0, fallbackIndex - 8), electIndex >= 0 ? electIndex : rows.length)
      .filter((row) => row.action === 'sheriff_run')
      .map((row) => `${playerNumberById(row.actor_id)}号`)
    const winner = computedState.inferredSheriffId.value ? `${playerNumberById(computedState.inferredSheriffId.value)}号` : ''
    if (!runs.length && !winner) return null
    return { candidates: [...new Set(runs)], winner }
  })
  computedState.roleName = computed(() => computedState.humanPlayer.value?.role_hint || (computedState.isWatch.value ? '观战者' : '未知身份'))
  computedState.pendingAction = computed(() => game.value?.pending_action || { type: '', prompt: '', candidate_ids: [], options: {} })
  computedState.pendingActionType = computed(() => computedState.pendingAction.value?.type || '')
  computedState.pendingChoiceOptions = computed(() =>
    computedState.pendingAction.value?.options?.choices
    || choiceOptionsForAction(computedState.pendingActionType.value, computedState.pendingAction.value?.options || {})
  )
  computedState.skillState = computed(() => game.value?.skill_state || {})
  computedState.isHumanWitch = computed(() => computedState.roleName.value.includes('女巫'))
  computedState.isHumanWhiteWolf = computed(() => computedState.roleName.value.includes('白狼王'))
  computedState.canUseWitchAntidote = computed(() =>
    computedState.pendingActionType.value === 'witch_act'
    && !computedState.skillState.value.witch_antidote_used
    && computedState.pendingAction.value.options?.antidote_available !== false
  )
  computedState.canUseWitchPoison = computed(() => computedState.pendingActionType.value === 'witch_act' && !computedState.skillState.value.witch_poison_used && computedState.pendingAction.value.options?.poison_available)
  computedState.actionCandidates = computed(() => {
    const ids = new Set(computedState.pendingAction.value?.candidate_ids || [])
    return computedState.livingPlayers.value.filter((player) => ids.has(player.id))
  })
  computedState.whiteWolfTargets = computed(() => {
    if (
      computedState.pendingActionType.value !== 'white_wolf_explode'
      || !computedState.humanPlayer.value?.alive
      || !computedState.isHumanWhiteWolf.value
      || computedState.skillState.value.white_wolf_burst_used
    ) return []
    const ids = new Set(computedState.pendingAction.value?.candidate_ids || [])
    const candidates = ids.size
      ? computedState.livingPlayers.value.filter((player) => ids.has(player.id))
      : computedState.livingPlayers.value
    return candidates.filter((player) => player.id !== game.value?.human_player_id)
  })
  computedState.canWhiteWolfBurst = computed(() => computedState.whiteWolfTargets.value.length > 0 && !refs.isReplayMode.value && !computedState.isWatch.value)
  computedState.needsTarget = computed(() => {
    if (computedState.pendingActionType.value === 'witch_act') return witchChoice.value === 'poison'
    const selectedChoice = actionChoice.value
    const selectedChoiceOption = computedState.pendingChoiceOptions.value.find((option) => option.value === selectedChoice)
    if (selectedChoiceOption?.requiresTarget) return true
    if (computedState.pendingChoiceOptions.value.length) return false
    const pending = computedState.pendingAction.value || {}
    return targetRequiredForAction(computedState.pendingActionType.value, {
      ...(pending.options || {}),
      target_required: pending.target_required ?? pending.options?.target_required,
      allow_no_target: pending.allow_no_target ?? pending.options?.allow_no_target
    })
  })
  computedState.actionInstruction = computed(() => {
    if (computedState.pendingActionType.value === 'witch_act' && witchChoice.value === 'poison') return '法官提醒：点击一名玩家模型使用毒药。'
    if (computedState.pendingActionType.value === 'witch_act' && witchChoice.value === 'antidote') {
      const attacked = computedState.pendingAction.value.options?.attacked_player
      return attacked ? `法官提醒：确认使用解药救 ${attacked} 号。` : '法官提醒：确认使用解药。'
    }
    if (computedState.pendingActionType.value === 'witch_act') return computedState.pendingAction.value.prompt || '女巫请选择是否发动技能。'
    if (computedState.pendingActionType.value === 'white_wolf_explode' && burstArmed.value) return '白狼王自爆已准备，点击要带走的玩家模型。'
    if (computedState.pendingChoiceOptions.value.length) return computedState.pendingAction.value.prompt || '请选择本轮行动。'
    if (computedState.pendingActionType.value) return computedState.pendingAction.value.prompt || '法官提醒：点击一名玩家模型选择目标。'
    if (game.value?.waiting_for === 'vote') return '投票环节，点击你要投票的玩家模型。'
    return ''
  })
  computedState.speechCountdownText = computed(() => {
    const value = Math.max(0, speechRemaining.value)
    const minutes = String(Math.floor(value / 60)).padStart(1, '0')
    const seconds = String(value % 60).padStart(2, '0')
    return `${minutes}:${seconds}`
  })
  computedState.pageVoteTally = computed(() => {
    const currentGame = game.value
    if (!currentGame) return []
    const phase = String(currentGame.phase || '').trim()
    const pendingAction = String(currentGame.pending_action?.type || currentGame.pending_human_action?.action_type || '').trim()
    const pendingPhase = voteActionPhase(pendingAction)
    const activePhase = pendingPhase || (sceneVotePhases.has(phase)
      ? phase
      : (currentGame.waiting_for === 'vote' ? 'exile_vote' : ''))
    if (!activePhase) return []
    const currentDay = numericId(currentGame.day)
    const canonicalPendingAction = canonicalVoteAction(pendingAction)
    const exactAction = ['exile_vote', 'pk_vote', 'sheriff_vote'].includes(canonicalPendingAction)
      ? canonicalPendingAction
      : (['exile_vote', 'pk_vote', 'sheriff_vote'].includes(activePhase) ? activePhase : '')

    const rows = new Map<number, LooseRecord>()
    const ensureVoteRow = (targetId: number | null, patch: LooseRecord = {}) => {
      if (!targetId) return
      const row = rows.get(targetId) || { target_id: targetId, targetName: `${targetId}号`, voter_ids: [], voter_labels: [] }
      if (patch.targetName) row.targetName = patch.targetName
      if (patch.count != null) row.count = Math.max(Number(row.count) || 0, Number(patch.count) || 0)
      ;(patch.voterLabels || []).forEach((label) => {
        if (label && !row.voter_labels.includes(label)) row.voter_labels.push(label)
      })
      rows.set(targetId, row)
      return row
    }
    const upsertVote = (targetId: number | null, voterId: number | null, patch: LooseRecord = {}) => {
      const row = ensureVoteRow(targetId, patch)
      if (!row) return
      if (voterId && !row.voter_ids.includes(voterId)) row.voter_ids.push(voterId)
      rows.set(targetId, row)
    }

    ;(currentGame.vote_tally || []).forEach((row) => {
      const targetId = rowTargetId(row)
      if (!targetId) return
      const voterIds = [
        ...(Array.isArray(row.voter_ids) ? row.voter_ids : []),
        ...(Array.isArray(row.voters) ? row.voters : []),
        ...(Array.isArray(row.votes) ? row.votes.map((vote) => vote?.actor_id ?? vote?.player_id ?? vote?.actor) : [])
      ].map(numericId).filter(Boolean)
      const voterLabels = [
        ...(Array.isArray(row.voters) ? row.voters : []),
        ...(Array.isArray(row.votes) ? row.votes.map((vote) => vote?.actorName || vote?.actor_name || vote?.player_name) : [])
      ].filter((value) => value && !numericId(value)).map(String)
      const targetName = row.targetName || row.target || `${targetId}号`
      const count = Number(row.count) || 0
      if (!voterIds.length) {
        ensureVoteRow(targetId, { targetName, count, voterLabels })
      } else if (voterLabels.length) {
        ensureVoteRow(targetId, { targetName, count, voterLabels })
      }
      voterIds.forEach((id) => upsertVote(targetId, id, { targetName, count }))
    })

    const collectRows = [...(currentGame.decisions || []), ...(currentGame.logs || [])]
    const activeAction = exactAction || latestVoteActionForScope(collectRows, activePhase, currentDay)
    collectRows.forEach((row) => {
      const action = voteAction(row)
      if (!voteRowMatchesPhase(row, activePhase)) return
      if (activeAction && canonicalVoteAction(action) !== activeAction) return
      const rowDay = numericId(row?.day)
      if (currentDay && rowDay !== currentDay) return
      upsertVote(rowTargetId(row), logActorId(row))
    })

    return [...rows.values()]
      .map((row) => {
        const next: LooseRecord = { ...row, count: Math.max(row.voter_ids.length + row.voter_labels.length, Number(row.count) || 0) }
        if (!next.voter_labels.length) delete next.voter_labels
        return next
      })
      .filter((row) => row.count > 0)
      .sort((a, b) => b.count - a.count || a.target_id - b.target_id)
  })
  computedState.sceneVoteTally = computed(() => computedState.pageVoteTally.value.map((row) => ({
    ...row,
    voters: [
      ...(row.voter_ids || []).map((id) => `${playerNumberById(id)}号`),
      ...(row.voter_labels || [])
    ]
  })))
  computedState.roleStats = computed(() => {
    const players = game.value?.players ?? []
    const counts = game.value?.role_counts ?? {}
    return roleIconSpecs
      .map((spec) => {
        const rolePlayers = players.filter((player) => roleMatches(player.role_hint ?? '', spec.tokens))
        const configured = Object.entries(counts).find(([role]) => roleMatches(role, spec.tokens))?.[1] ?? 0
        const total = rolePlayers.length || Number(configured) || 0
        const alive = rolePlayers.length ? rolePlayers.filter((player) => player.alive).length : total
        return { ...spec, alive, total }
      })
      .filter((item) => item.total > 0)
  })
  computedState.visualSeatPlayers = computed(() => {
    const players = (game.value?.players ?? []).slice(0, 12)
    if (backendMode.value === 'api' || computedState.isWatch.value) {
      return players
        .map((player, index) => ({ player, index }))
        .sort((a, b) => (Number(a.player?.seat || a.player?.id || a.index) - Number(b.player?.seat || b.player?.id || b.index)) || a.index - b.index)
        .map((item) => item.player)
    }
    const signature = players.map((player, index) => `${player?.id ?? index}:${player?.role_hint ?? ''}`).join('|')
    const makeShuffled = () => players
      .map((player, index) => ({ player, index, order: seatHash(`${visualSeatSalt.value}:${signature}:${player?.id ?? index}`) }))
      .sort((a, b) => a.order - b.order || a.index - b.index)
      .map((item) => item.player)

    if (!computedState.isWatch.value) {
      const human = players.find((p) => p.is_human)
      if (human) {
        const shuffled = makeShuffled()
        const shuffledIndexMap = new Map(shuffled.map((p, i) => [p.id, i]))
        const humanIdx = shuffledIndexMap.get(human.id) ?? shuffled.indexOf(human)
        const sorted = shuffled
          .filter((p) => p.id !== human.id)
          .map((p) => ({ player: p, idx: shuffledIndexMap.get(p.id) ?? 0 }))
          .sort((a, b) => ((a.idx - humanIdx + 12) % 12) - ((b.idx - humanIdx + 12) % 12))
          .map((item) => item.player)
        return [human, ...sorted]
      }
    }
    return makeShuffled()
  })
  computedState.playerIdentityList = computed(() =>
    computedState.visualSeatPlayers.value.map((player, idx) => {
      const display = visiblePlayer(player)
      return {
        ...display,
        displaySeat: idx + 1,
        isSheriff: player.is_sheriff || player.id === computedState.inferredSheriffId.value,
        speaking: player.id === effectiveCurrentSpeakerId()
      }
    })
  )
  computedState.judgeBoardMessage = computed(() => {
    if (!judgeBoardStarted.value) return '你好，我是本局的法官，点击下方的开始按钮开启对局。'
    if (!roleAssignmentComplete.value) return '正在分配角色...'
    if (roleAssignmentCompleteNotice.value) return '角色分配完成，开始使用技能。'
    return ''
  })
  computedState.decisionRows = computed(() =>
    (game.value?.decisions ?? []).map((decision, index) => ({
      ...decision,
      index: index + 1,
      actorName: `${playerNumberById(decision.actor_id)}号`,
      targetName: decision.target_id ? `${playerNumberById(decision.target_id)}号` : '无目标',
      reason: normalizePlayerText(decision.reason),
      public_summary: normalizePlayerText(decision.public_summary),
      actionName: decisionActionText[decision.action] || displayActionLabel(decision.action)
    }))
  )

  return computedState
}
