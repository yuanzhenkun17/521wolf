import { computed } from 'vue'
import { decisionActionText, phaseLabel } from './gameStateShared.js'
import {
  displayActionLabel,
  displayRoleLabel,
  normalizeHistoryDisplayText
} from '../components/history/historyDisplay.js'
import { AUTHORITATIVE_DEATH_EVENTS, deathTargetIds } from './gameTimeline.js'

const HISTORY_PHASE_ALIASES = {
  result: 'night',
  sheriff_election: 'sheriff',
  day_speech: 'speech',
  exile_vote: 'vote',
  pk_speak: 'speech',
  pk_vote: 'vote',
  finished: 'ended'
}

const HISTORY_PHASE_ORDER = [
  'setup',
  'night',
  'sheriff',
  'sheriff_vote',
  'sheriff_result',
  'speech',
  'vote',
  'ended'
]

const HISTORY_PHASE_RANK = new Map(HISTORY_PHASE_ORDER.map((phase, index) => [phase, index]))
function normalizeHistoryPhase(phase = 'setup') {
  return HISTORY_PHASE_ALIASES[phase] || phase || 'setup'
}

function normalizeHistoryDay(day) {
  const value = Number(day)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function historyPageKey(day, phase) {
  return `day-${normalizeHistoryDay(day)}-${normalizeHistoryPhase(phase)}`
}

function historyPageSortValue(page) {
  if (!page) return 0
  const phase = normalizeHistoryPhase(page.phase)
  const rank = HISTORY_PHASE_RANK.has(phase) ? HISTORY_PHASE_RANK.get(phase) : HISTORY_PHASE_ORDER.length
  return normalizeHistoryDay(page.day) * 100 + rank
}

export function createHistoryDerivedState(refs, computedState, helpers = {}) {
  const {
    selectedHistoryGame,
    historyPhase,
    selectedHistoryPageKey,
    assessDimension,
    reviewByGameId
  } = refs
  const {
    logSpeaker = (log) => log?.speaker || '',
    logMessage = (log) => log?.message || ''
  } = helpers

  function historyPlayerById(id) {
    return selectedHistoryGame.value?.players?.find((item) => item.id === id)
  }

  function historyPlayerLabelById(id) {
    const player = historyPlayerById(id)
    return player?.seat ? `${player.seat}号` : `${id}号`
  }

  function voteVoterLabels(votes = []) {
    return votes
      .map((vote) => vote.actorName || historyPlayerLabelById(vote.actor_id))
      .filter(Boolean)
  }

  function historyLogSpeaker(log) {
    const player = selectedHistoryGame.value?.players?.find((item) => item.id === log?.actor_id || item.name === log?.speaker)
    return player?.seat ? `${player.seat}号` : (log?.speaker || '')
  }

  function historyPhaseName(phase) {
    const normalized = normalizeHistoryPhase(phase)
    return phaseLabel[normalized] || normalized || '未知阶段'
  }

  function historyPageKeyFor(log) {
    return historyPageKey(log?.day ?? 1, log?.phase || 'setup')
  }

  function historyPageTitle(page) {
    const phase = normalizeHistoryPhase(page.phase)
    const day = normalizeHistoryDay(page.day)
    const phaseMap = {
      setup: '准备',
      night: `第${day}夜`,
      sheriff: '警长竞选',
      sheriff_vote: '警长投票',
      sheriff_result: '上警/退水',
      speech: `第${day}天`,
      vote: `第${day}天投票`,
      ended: '结果'
    }
    return phaseMap[phase] || phase
  }

  function historyNormalizeText(text = '') {
    let value = String(text || '')
    for (const player of selectedHistoryGame.value?.players ?? []) {
      value = value.replace(new RegExp(`${player.seat}\\s*号`, 'g'), `${player.seat}号`)
      if (player.name) value = value.replaceAll(player.name, `${player.seat}号`)
    }
    return normalizeHistoryDisplayText(value)
  }

  function historyDecisionMatchesPage(decision, page) {
    if (!page) return true
    const decisionPhase = normalizeHistoryPhase(decision.phase || page.phase)
    return normalizeHistoryDay(decision.day || page.day) === normalizeHistoryDay(page.day) && String(decisionPhase) === String(normalizeHistoryPhase(page.phase))
  }

  computedState.historyPages = computed(() => {
    const logs = selectedHistoryGame.value?.logs ?? []
    const decisions = selectedHistoryGame.value?.decisions ?? []
    const map = new Map()
    const ensurePage = (day, phase) => {
      const normalizedPhase = normalizeHistoryPhase(phase)
      const normalizedDay = normalizeHistoryDay(day)
      const key = historyPageKey(normalizedDay, normalizedPhase)
      if (!map.has(key)) {
        map.set(key, { key, day: normalizedDay, phase: normalizedPhase, logs: [], decisions: [] })
      }
      return map.get(key)
    }
    ensurePage(1, 'setup')
    logs.forEach((log) => {
      ensurePage(log.day, log.phase).logs.push(log)
    })
    decisions.forEach((decision) => {
      ensurePage(decision.day, decision.phase || 'setup')
    })
    const maxObservedDay = Math.max(
      1,
      ...logs.map((log) => normalizeHistoryDay(log.day)),
      ...decisions.map((decision) => normalizeHistoryDay(decision.day)),
      normalizeHistoryDay(selectedHistoryGame.value?.day)
    )
    if (selectedHistoryGame.value?.winner) ensurePage(maxObservedDay, 'ended')
    const pages = [...map.values()].sort((a, b) => historyPageSortValue(a) - historyPageSortValue(b) || String(a.key).localeCompare(String(b.key)))
    pages.forEach((page) => {
      page.decisions = decisions.filter((decision) => historyDecisionMatchesPage(decision, page))
    })
    if (!selectedHistoryPageKey.value && pages.length) selectedHistoryPageKey.value = pages[0].key
    if (historyPhase.value === 'all') return pages
    return pages.filter((page) => page.phase === historyPhase.value)
  })
  computedState.selectedHistoryPage = computed(() => {
    const pages = computedState.historyPages.value
    return pages.find((page) => page.key === selectedHistoryPageKey.value) || pages[0] || null
  })
  computedState.playerAliveAtPage = computed(() => {
    if (!selectedHistoryGame.value) return {}
    const alive = {}
    ;(selectedHistoryGame.value.players ?? []).forEach((p) => { alive[p.id] = true })
    const logs = selectedHistoryGame.value.logs ?? []
    const selectedPage = computedState.selectedHistoryPage.value
    if (!selectedPage) return alive
    const selectedSort = historyPageSortValue(selectedPage)
    const hasAuthoritativeDeathEvents = logs.some((log) => AUTHORITATIVE_DEATH_EVENTS.has(log.event_type || log.type || ''))
    for (const log of logs) {
      const logPage = { day: log.day, phase: normalizeHistoryPhase(log.phase) }
      if (historyPageSortValue(logPage) > selectedSort) continue
      for (const targetId of deathTargetIds(log, hasAuthoritativeDeathEvents)) {
        alive[targetId] = false
      }
    }
    return alive
  })
  computedState.historyLogs = computed(() => computedState.selectedHistoryPage.value?.logs ?? [])
  computedState.nightResult = computed(() => {
    if (!computedState.historyLogs.value.length) return ''
    const resultLog = computedState.historyLogs.value.find((log) => (log.event_type || log.type) === 'night_result')
    return resultLog ? historyNormalizeText(resultLog.message || '') : ''
  })
  computedState.sheriffResult = computed(() => {
    if (!computedState.historyLogs.value.length || !computedState.selectedHistoryPage.value) return null
    if (computedState.selectedHistoryPage.value.phase !== 'sheriff_result') return null
    const resultLog = computedState.historyLogs.value.find((log) => (log.event_type || log.type) === 'sheriff_result')
    const speechLogs = computedState.historyLogs.value.filter((log) => (log.event_type || log.type) === 'sheriff_speak')
    const withdrawLog = computedState.historyLogs.value.find((log) => (log.event_type || log.type) === 'sheriff_withdraw')
    return {
      message: resultLog ? historyNormalizeText(resultLog.message || '') : '',
      candidates: speechLogs.map((log) => historyNormalizeText(log.message || '')),
      hasWithdraw: Boolean(withdrawLog),
      withdrawMessage: withdrawLog ? historyNormalizeText(withdrawLog.message || '') : ''
    }
  })
  computedState.historyDecisionRows = computed(() =>
    (selectedHistoryGame.value?.decisions ?? []).map((decision, index) => ({
      ...decision,
      index: index + 1,
      actorName: decision.actor_name || historyPlayerLabelById(decision.actor_id),
      targetName: decision.target_name || (decision.target_id ? historyPlayerLabelById(decision.target_id) : '无目标'),
      reason: historyNormalizeText(decision.reason || ''),
      public_summary: historyNormalizeText(decision.public_summary || ''),
      private_reasoning: historyNormalizeText(decision.private_reasoning || ''),
      actionName: decisionActionText[decision.action] || displayActionLabel(decision.action),
      roleName: displayRoleLabel(decision.role || historyPlayerById(decision.actor_id)?.role_hint),
      selected_skill: decision.selected_skill || '',
      memory_summary: decision.memory_summary || [],
      memory_refs: decision.memory_refs || [],
      belief_snapshot: decision.belief_snapshot || null,
      raw_output: decision.raw_output || '',
      errors: decision.errors || [],
      policy_adjustments: decision.policy_adjustments || []
    }))
  )
  computedState.filteredHistoryDecisionRows = computed(() =>
    computedState.historyDecisionRows.value.filter((decision) => historyDecisionMatchesPage(decision, computedState.selectedHistoryPage.value))
  )
  computedState.sheriffVotes = computed(() => computedState.filteredHistoryDecisionRows.value.filter((decision) => decision.action === 'sheriff_vote'))
  computedState.sheriffVoteTally = computed(() => tallyByTargetName(computedState.sheriffVotes.value))
  computedState.currentVoteTally = computed(() => {
    const page = computedState.selectedHistoryPage.value
    if (!page || !['vote', 'sheriff_vote'].includes(page.phase)) return []
    return tallyByTargetName(computedState.filteredHistoryDecisionRows.value.filter((decision) => decision.action === 'vote' || decision.action === 'sheriff_vote'))
  })
  computedState.voteDecisions = computed(() => {
    const page = computedState.selectedHistoryPage.value
    if (!page || !['vote', 'sheriff_vote'].includes(page.phase)) return []
    return computedState.filteredHistoryDecisionRows.value.filter((decision) => decision.action === 'vote' || decision.action === 'sheriff_vote')
  })
  computedState.pageNightActions = computed(() => {
    const page = computedState.selectedHistoryPage.value
    if (!page || page.phase !== 'night') return []
    return computedState.filteredHistoryDecisionRows.value.filter((decision) =>
      ['kill', 'guard', 'inspect', 'poison', 'antidote', 'shoot', 'guard_protect', 'werewolf_kill', 'seer_check', 'witch_act', 'hunter_shoot'].includes(decision.action)
    )
  })
  computedState.pageVoteResults = computed(() => {
    const page = computedState.selectedHistoryPage.value
    if (!page || !['vote', 'sheriff_vote'].includes(page.phase)) return []
    const grouped = new Map()
    for (const vote of computedState.filteredHistoryDecisionRows.value.filter((decision) => ['vote', 'sheriff_vote'].includes(decision.action))) {
      const key = vote.target_id || 'unknown'
      if (!grouped.has(key)) grouped.set(key, { targetId: vote.target_id, targetName: vote.targetName, votes: [] })
      grouped.get(key).votes.push(vote)
    }
    return [...grouped.values()].sort((a, b) => b.votes.length - a.votes.length)
  })
  computedState.pageLastWords = computed(() => computedState.filteredHistoryDecisionRows.value.filter((decision) => decision.action === 'last_word'))
  computedState.pageSpeechDecisions = computed(() => {
    const page = computedState.selectedHistoryPage.value
    if (!page || !['speech', 'sheriff'].includes(page.phase)) return []
    return computedState.filteredHistoryDecisionRows.value.filter((decision) => ['speak', 'sheriff_speak'].includes(decision.action))
  })
  computedState.historyStats = computed(() => ({
    logs: selectedHistoryGame.value?.logs?.length ?? 0,
    decisions: selectedHistoryGame.value?.decisions?.length ?? 0,
    alive: selectedHistoryGame.value?.players?.filter((player) => player.alive).length ?? 0,
    total: selectedHistoryGame.value?.players?.length ?? 0
  }))
  computedState.playerAssessmentScores = computed(() => {
    const gameId = selectedHistoryGame.value?.game_id
    const review = gameId ? reviewByGameId.value[gameId] : null
    const reviewPayload = review?.data || review
    const evals = reviewPayload?.player_evaluations || reviewPayload?.player_scores
    if (evals?.length) {
      const players = selectedHistoryGame.value?.players ?? []
      return evals.map((ev) => {
        const player = players.find((p) => p.id === ev.player_seat) || { id: ev.player_seat, role: ev.role }
        const speech = ev.speech_score ?? 0
        const vote = ev.vote_score ?? 0
        const skill = ev.skill_score ?? 0
        const logic = ev.logic_score ?? ev.information_score ?? 0
        const team = ev.team_score ?? ev.cooperation_score ?? 0
        const overall = ev.role_score ?? ev.overall_score ?? 0
        return {
          player,
          speech: Math.round(speech * 100),
          vote: Math.round(vote * 100),
          skill: Math.round(skill * 100),
          logic: Math.round(logic * 100),
          team: Math.round(team * 100),
          risk_penalty: ev.risk_penalty ?? 0,
          role_score: Math.round(overall * 100),
          information: Math.round(logic * 100),
          cooperation: Math.round(team * 100)
        }
      })
    }
    return []
  })
  computedState.activeAssessScores = computed(() =>
    computedState.playerAssessmentScores.value.map((item) => ({
      ...item,
      player: item.player,
      score: item[assessDimension.value] ?? 0
    }))
  )
  computedState.judgeStripMessage = computed(() => {
    if (computedState.judgeBoardMessage.value) return [{ speaker: '法官', message: computedState.judgeBoardMessage.value }]
    const latestDecision = computedState.decisionRows.value.at(-1)
    if (latestDecision?.action?.startsWith('sheriff_')) {
      if (latestDecision.action === 'sheriff_elect') {
        const winner = latestDecision.targetName !== '无目标' ? latestDecision.targetName : latestDecision.actorName
        return [{ speaker: '法官', message: `警长竞选结束，${winner}当选警长。` }]
      }
      if (latestDecision.action === 'sheriff_transfer') return [{ speaker: '法官', message: `警徽移交给${latestDecision.targetName}。` }]
      if (latestDecision.action === 'sheriff_destroy') return [{ speaker: '法官', message: '警徽被撕毁，本局不再移交警徽。' }]
    }
    const rows = computedState.judgeLogs.value.map((log) => ({ speaker: logSpeaker(log), message: logMessage(log) }))
    return rows.length ? rows : [{ speaker: '法官', message: '等待法官记录。' }]
  })

  function tallyByTargetName(votes) {
    const tally = {}
    votes.forEach((vote) => {
      const key = vote.targetName || '未知'
      if (!tally[key]) tally[key] = { target: key, targetName: key, count: 0, voters: [] }
      tally[key].count++
      const voter = vote.actorName || historyPlayerLabelById(vote.actor_id)
      if (voter && !tally[key].voters.includes(voter)) tally[key].voters.push(voter)
    })
    return Object.values(tally).sort((a, b) => b.count - a.count)
  }

  function nightActionDetail(action) {
    const actor = action.actorName
    const target = action.targetName
    const currentAction = action.action
    const hasTarget = target && target !== '无目标'
    if (currentAction === 'kill' || currentAction === 'werewolf_kill') return hasTarget ? `狼人选择击杀${target}` : '狼人未选择击杀目标'
    if (currentAction === 'guard' || currentAction === 'guard_protect') return hasTarget ? `${actor}守护${target}` : `${actor}未选择守护目标`
    if (currentAction === 'inspect' || currentAction === 'seer_check') return hasTarget ? `${actor}查验${target}` : `${actor}未选择查验目标`
    if (currentAction === 'poison') return hasTarget ? `${actor}使用毒药${target}` : `${actor}不使用毒药`
    if (currentAction === 'witch_act') return hasTarget ? `${actor}使用药剂${target}` : `${actor}不使用药剂`
    if (currentAction === 'antidote') return hasTarget ? `${actor}使用解药${target}` : `${actor}不使用解药`
    if (currentAction === 'shoot' || currentAction === 'hunter_shoot') return hasTarget ? `${actor}开枪带走${target}` : `${actor}未选择开枪目标`
    return hasTarget ? `${actor}${displayActionLabel(currentAction)}${target}` : `${actor}${displayActionLabel(currentAction)}`
  }

  return {
    historyPlayerById,
    historyPlayerLabelById,
    historyLogSpeaker,
    historyPhaseName,
    historyPageKeyFor,
    historyPageTitle,
    historyNormalizeText,
    historyDecisionMatchesPage,
    tallyByTargetName,
    nightActionDetail,
    historyPages: computedState.historyPages,
    selectedHistoryPage: computedState.selectedHistoryPage,
    playerAliveAtPage: computedState.playerAliveAtPage,
    historyLogs: computedState.historyLogs,
    nightResult: computedState.nightResult,
    sheriffResult: computedState.sheriffResult,
    historyDecisionRows: computedState.historyDecisionRows,
    filteredHistoryDecisionRows: computedState.filteredHistoryDecisionRows,
    sheriffVotes: computedState.sheriffVotes,
    sheriffVoteTally: computedState.sheriffVoteTally,
    currentVoteTally: computedState.currentVoteTally,
    voteDecisions: computedState.voteDecisions,
    pageNightActions: computedState.pageNightActions,
    pageVoteResults: computedState.pageVoteResults,
    pageLastWords: computedState.pageLastWords,
    pageSpeechDecisions: computedState.pageSpeechDecisions,
    historyStats: computedState.historyStats,
    playerAssessmentScores: computedState.playerAssessmentScores,
    activeAssessScores: computedState.activeAssessScores,
    judgeStripMessage: computedState.judgeStripMessage
  }
}
