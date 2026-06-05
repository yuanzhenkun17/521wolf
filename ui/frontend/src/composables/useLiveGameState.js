import { computed } from 'vue'
import { decisionActionText, judgeVisibleTypes, phaseLabel, phaseText, roleIconSpecs, roleMatches, seatHash } from './gameStateShared.js'
import { choiceOptionsForAction } from './gameSnapshot.js'

export function createLiveGameState(refs, helpers) {
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

  const computedState = {}

  computedState.isNight = computed(() => game.value?.phase === 'night')
  computedState.inLogs = computed(() => currentView.value === 'logs')
  computedState.inEvolution = computed(() => currentView.value === 'evolution')
  computedState.inLobby = computed(() =>
    currentView.value === 'lobby'
    || (!game.value && !computedState.inLogs.value && !computedState.inEvolution.value)
  )
  computedState.inMatch = computed(() => currentView.value === 'match' && Boolean(game.value))
  computedState.isWatch = computed(() => game.value?.mode === 'watch')
  computedState.humanPlayer = computed(() => game.value?.players?.find((p) => p.id === game.value.human_player_id))
  computedState.livingPlayers = computed(() => game.value?.players?.filter((p) => p.alive) ?? [])
  computedState.canVotePlayers = computed(() => computedState.livingPlayers.value.filter((p) => p.id !== game.value?.human_player_id))
  computedState.publicLogs = computed(() => (game.value?.logs ?? []).filter(canSeeLog).slice(-10))
  computedState.chatLogs = computed(() =>
    (game.value?.logs ?? [])
      .filter((log) => canSeeLog(log) && !['法官', '系统', '狼人团队'].includes(log.speaker))
      .slice(-80)
  )
  computedState.judgeLogs = computed(() =>
    (game.value?.logs ?? [])
      .filter((log) =>
        log.visibility === 'system'
        || (canSeeLog(log) && ['法官', '系统', '狼人团队'].includes(log.speaker))
        || (canSeeLog(log) && judgeVisibleTypes.has(log.type))
        || (computedState.isWatch.value && log.phase === 'night' && log.visibility !== 'private')
      )
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
        currentGroup = { key: groupKey, day, phase, phaseLabel: phaseText[phase] || phase, logs: [] }
        groups.push(currentGroup)
      }
      currentGroup.logs.push(log)
    })
    return groups.slice(-10)
  })
  computedState.speakingPlayer = computed(() => {
    if (!game.value?.current_speaker_id) return null
    return game.value.players.find((p) => p.id === game.value.current_speaker_id)
  })
  computedState.displayPhase = computed(() => {
    if (!game.value) return 'LOBBY'
    return (phaseText[game.value.phase] || '').replace('{day}', game.value.day)
  })
  computedState.promptText = computed(() => {
    if (!game.value) return '选择模式开始游戏'
    if (game.value.winner) return game.value.winner
    if (game.value.waiting_for === 'speech') return '轮到你发言，所有智能体正在等待'
    if (game.value.waiting_for === 'vote') return '轮到你投票，提交后智能体继续行动'
    if (computedState.speakingPlayer.value) return `${playerLabel(computedState.speakingPlayer.value)} 正在发言`
    return phaseLabel[game.value.phase]
  })
  computedState.speakerMessage = computed(() => {
    const speaker = computedState.speakingPlayer.value
    if (!speaker) return game.value?.winner || computedState.promptText.value
    const logs = (game.value?.logs ?? [])
      .filter((log) => log.visibility !== 'private' && (log.actor_id === speaker.id || log.speaker === speaker.name))
    return normalizePlayerText(logs.at(-1)?.message || computedState.promptText.value)
  })
  computedState.speakerCarousel = computed(() => {
    const players = game.value?.players ?? []
    const current = computedState.speakingPlayer.value
    if (!players.length || !current) {
      return [{ key: 'speaker-judge', label: '法官', image: '/cards/judge.png', tone: 'current' }]
    }
    const order = players.filter((p) => p.alive)
    const index = order.findIndex((p) => p.id === current.id)
    const prev = order[(index - 1 + order.length) % order.length]
    const next = order[(index + 1) % order.length]
    return [
      { key: `speaker-${prev.id}`, label: playerLabel(prev), image: cardImage(prev), tone: 'prev' },
      { key: `speaker-${current.id}`, label: playerLabel(current), image: cardImage(current), tone: 'current' },
      { key: `speaker-${next.id}`, label: playerLabel(next), image: cardImage(next), tone: 'next' }
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
    if (!computedState.humanPlayer.value?.alive || !computedState.isHumanWhiteWolf.value || computedState.skillState.value.white_wolf_burst_used) return []
    return computedState.livingPlayers.value.filter((player) => player.id !== game.value?.human_player_id)
  })
  computedState.canWhiteWolfBurst = computed(() => computedState.whiteWolfTargets.value.length > 0 && !refs.isReplayMode.value && !computedState.isWatch.value)
  computedState.needsTarget = computed(() => {
    if (computedState.pendingActionType.value === 'witch_act') return witchChoice.value === 'poison'
    const selectedChoice = actionChoice.value
    const selectedChoiceOption = computedState.pendingChoiceOptions.value.find((option) => option.value === selectedChoice)
    if (selectedChoiceOption?.requiresTarget) return true
    if (computedState.pendingChoiceOptions.value.length) return false
    return Boolean(computedState.pendingActionType.value)
  })
  computedState.actionInstruction = computed(() => {
    if (computedState.pendingActionType.value === 'witch_act' && witchChoice.value === 'poison') return '法官提醒：点击一名玩家的 3D 模型使用毒药。'
    if (computedState.pendingActionType.value === 'witch_act' && witchChoice.value === 'antidote') {
      const attacked = computedState.pendingAction.value.options?.attacked_player
      return attacked ? `法官提醒：确认使用解药救 ${attacked} 号。` : '法官提醒：确认使用解药。'
    }
    if (computedState.pendingActionType.value === 'witch_act') return computedState.pendingAction.value.prompt || '女巫请选择是否发动技能。'
    if (computedState.pendingChoiceOptions.value.length) return computedState.pendingAction.value.prompt || '请选择本轮行动。'
    if (computedState.pendingActionType.value) return computedState.pendingAction.value.prompt || '法官提醒：点击一名玩家的 3D 模型选择目标。'
    if (game.value?.waiting_for === 'vote') return '投票环节，点击你要投票的玩家模型。'
    if (burstArmed.value) return '白狼王自爆已准备，点击要带走的玩家模型。'
    return ''
  })
  computedState.speechCountdownText = computed(() => {
    const value = Math.max(0, speechRemaining.value)
    const minutes = String(Math.floor(value / 60)).padStart(1, '0')
    const seconds = String(value % 60).padStart(2, '0')
    return `${minutes}:${seconds}`
  })
  computedState.pageVoteTally = computed(() => game.value?.vote_tally ?? [])
  computedState.sceneVoteTally = computed(() => computedState.pageVoteTally.value.map((row) => ({
    ...row,
    voters: (row.voter_ids || []).map((id) => `${playerNumberById(id)}号`)
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
    computedState.visualSeatPlayers.value.map((player, idx) => ({
      ...player,
      displaySeat: idx + 1,
      roleIcon: computedState.isWatch.value ? roleIconImage(player) : (player.is_human ? roleIconImage(player) : '/role-icons/未知.png'),
      isSheriff: player.is_sheriff || player.id === computedState.inferredSheriffId.value,
      speaking: player.id === game.value?.current_speaker_id
    }))
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
      actionName: decisionActionText[decision.action] || decision.action
    }))
  )

  return computedState
}
