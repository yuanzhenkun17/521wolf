import { computed } from 'vue'
import { decisionActionText, phaseLabel } from './gameStateShared.ts'
import {
  displayActionLabel,
  displayRoleLabel,
  normalizeHistoryDisplayText
} from '../components/history/historyDisplay.ts'
import { AUTHORITATIVE_DEATH_EVENTS, deathTargetIds } from './gameTimeline.ts'

type LooseRecord = Record<string, any>

const HISTORY_PHASE_ALIASES = {
  result: 'night',
  sheriff_election: 'sheriff',
  day_speech: 'speech',
  pk_speak: 'speech',
  finished: 'ended'
}

const HISTORY_PHASE_ORDER = [
  'setup',
  'night',
  'sheriff',
  'sheriff_vote',
  'sheriff_result',
  'speech',
  'exile_vote',
  'pk_vote',
  'vote',
  'ended'
]
const VOTE_ACTION_PHASES = {
  exile: 'exile_vote',
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

const HISTORY_PHASE_RANK = new Map(HISTORY_PHASE_ORDER.map((phase, index) => [phase, index]))
function normalizeHistoryPhase(phase: unknown = 'setup') {
  const key = String(phase || '')
  return HISTORY_PHASE_ALIASES[key] || key || 'setup'
}

function normalizeHistoryDay(day: unknown) {
  const value = Number(day)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function rowType(row: LooseRecord = {}) {
  return String(row?.type || row?.event_type || row?.action || row?.action_type || row?.kind || '').trim()
}

function votePhaseForRow(row: LooseRecord = {}) {
  return VOTE_ACTION_PHASES[rowType(row)] || ''
}

function rowHistoryPhase(row: LooseRecord = {}, fallback = 'setup') {
  const rawPhase = normalizeHistoryPhase(row?.phase ?? fallback)
  const votePhase = votePhaseForRow(row)
  if (rawPhase === 'vote' && votePhase && votePhase !== 'sheriff_vote') return votePhase
  if ((row?.phase == null || row?.phase === '') && votePhase) return votePhase
  return rawPhase
}

function historyPageKey(day: unknown, phase: unknown) {
  return `day-${normalizeHistoryDay(day)}-${normalizeHistoryPhase(phase)}`
}

function historyPageSortValue(page: LooseRecord | null | undefined) {
  if (!page) return 0
  const phase = normalizeHistoryPhase(page.phase)
  const rank = HISTORY_PHASE_RANK.has(phase) ? HISTORY_PHASE_RANK.get(phase) : HISTORY_PHASE_ORDER.length
  return normalizeHistoryDay(page.day) * 100 + rank
}

function isSetupHistoryPage(page: LooseRecord | null | undefined) {
  const keyPhase = String(page?.key || '').match(/^day-\d+-(.+)$/)?.[1]
  return normalizeHistoryPhase(page?.phase || keyPhase || '') === 'setup'
}

function firstVisibleHistoryPage(pages: LooseRecord[] = []) {
  return pages.find((page) => !isSetupHistoryPage(page)) || null
}

export function createHistoryDerivedState(refs: LooseRecord, computedState: LooseRecord, helpers: LooseRecord = {}) {
  const {
    selectedHistoryGame,
    selectedHistoryShell,
    selectedPhaseDetail,
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
    return historyPageKey(log?.day ?? 1, rowHistoryPhase(log))
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
      exile_vote: `第${day}天放逐投票`,
      pk_vote: `第${day}天对决投票`,
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
    const pagePhase = normalizeHistoryPhase(page.phase)
    const actionPhase = votePhaseForRow(decision)
    const rawPhase = rowHistoryPhase(decision, page.phase)
    if (actionPhase) {
      return normalizeHistoryDay(decision.day || page.day) === normalizeHistoryDay(page.day)
        && (actionPhase === pagePhase || (rawPhase === pagePhase && pagePhase === 'vote'))
    }
    const decisionPhase = normalizeHistoryPhase(decision.phase || page.phase)
    return normalizeHistoryDay(decision.day || page.day) === normalizeHistoryDay(page.day) && String(decisionPhase) === String(pagePhase)
  }

  computedState.historyPages = computed(() => {
    const indexedPages = selectedHistoryGame.value?.__historyPages
      || selectedHistoryGame.value?.history_pages
      || selectedHistoryGame.value?.phases
      || selectedHistoryShell.value?.__historyPages
      || selectedHistoryShell.value?.history_pages
      || selectedHistoryShell.value?.phases
    if (Array.isArray(indexedPages) && indexedPages.length) {
      const pages = indexedPages
        .map((page, index) => ({
          ...page,
          key: page.key || historyPageKey(page.day, page.phase),
          day: normalizeHistoryDay(page.day),
          phase: normalizeHistoryPhase(page.phase),
          logs: Array.isArray(page.logs) ? page.logs : [],
          decisions: Array.isArray(page.decisions) ? page.decisions : [],
          index
        }))
        .sort((a, b) => historyPageSortValue(a) - historyPageSortValue(b) || String(a.key).localeCompare(String(b.key)))
      if (!selectedHistoryPageKey.value && pages.length) {
        selectedHistoryPageKey.value = (firstVisibleHistoryPage(pages) || pages[0]).key
      }
      if (historyPhase.value === 'all') return pages
      if (historyPhase.value === 'vote') {
        return pages.filter((page) => ['vote', 'exile_vote', 'pk_vote', 'sheriff_vote'].includes(page.phase))
      }
      return pages.filter((page) => page.phase === historyPhase.value)
    }
    const logs = selectedHistoryGame.value?.logs ?? selectedPhaseDetail.value?.logs ?? []
    const decisions = selectedHistoryGame.value?.decisions ?? selectedPhaseDetail.value?.decisions ?? []
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
      ensurePage(log.day, rowHistoryPhase(log)).logs.push(log)
    })
    decisions.forEach((decision) => {
      ensurePage(decision.day, rowHistoryPhase(decision))
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
    if (!selectedHistoryPageKey.value && pages.length) {
      selectedHistoryPageKey.value = (firstVisibleHistoryPage(pages) || pages[0]).key
    }
    if (historyPhase.value === 'all') return pages
    if (historyPhase.value === 'vote') {
      return pages.filter((page) => ['vote', 'exile_vote', 'pk_vote', 'sheriff_vote'].includes(page.phase))
    }
    return pages.filter((page) => page.phase === historyPhase.value)
  })
  computedState.selectedHistoryPage = computed(() => {
    const pages = computedState.historyPages.value
    const selected = pages.find((page) => page.key === selectedHistoryPageKey.value)
    if (selected && !isSetupHistoryPage(selected)) return selected
    return firstVisibleHistoryPage(pages) || pages[0] || null
  })
  computedState.playerAliveAtPage = computed(() => {
    if (!selectedHistoryGame.value) return {}
    const alive = {}
    ;(selectedHistoryGame.value.players ?? []).forEach((p) => { alive[p.id] = true })
    const selectedPage = computedState.selectedHistoryPage.value
    if (!selectedPage) return alive
    const stateAfter = selectedPage.state_after || {}
    const aliveIds = selectedPage.alive_player_ids || stateAfter.alive
    const deadIds = selectedPage.dead_player_ids || stateAfter.dead
    if (Array.isArray(aliveIds) || Array.isArray(deadIds)) {
      ;(selectedHistoryGame.value.players ?? []).forEach((p) => {
        const id = p.id ?? p.seat
        if (Array.isArray(aliveIds) && aliveIds.map(String).includes(String(id))) alive[id] = true
        if (Array.isArray(deadIds) && deadIds.map(String).includes(String(id))) alive[id] = false
      })
      return alive
    }
    const logs = selectedHistoryGame.value.logs ?? selectedPhaseDetail.value?.logs ?? []
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
  computedState.historyLogs = computed(() =>
    selectedPhaseDetail.value?.logs
    || computedState.selectedHistoryPage.value?.logs
    || selectedHistoryGame.value?.logs
    || []
  )
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
    (selectedPhaseDetail.value?.decisions ?? selectedHistoryGame.value?.decisions ?? []).map((decision, index) => ({
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
    if (!page || !['vote', 'exile_vote', 'pk_vote', 'sheriff_vote'].includes(page.phase)) return []
    return tallyByTargetName(computedState.filteredHistoryDecisionRows.value.filter((decision) => {
      const phase = VOTE_ACTION_PHASES[decision.action] || ''
      if (page.phase === 'vote') return ['vote', 'exile_vote', 'pk_vote'].includes(decision.action)
      return phase === page.phase
    }))
  })
  computedState.voteDecisions = computed(() => {
    const page = computedState.selectedHistoryPage.value
    if (!page || !['vote', 'exile_vote', 'pk_vote', 'sheriff_vote'].includes(page.phase)) return []
    return computedState.filteredHistoryDecisionRows.value.filter((decision) => {
      const phase = VOTE_ACTION_PHASES[decision.action] || ''
      if (page.phase === 'vote') return ['vote', 'exile_vote', 'pk_vote'].includes(decision.action)
      return phase === page.phase
    })
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
    if (!page || !['vote', 'exile_vote', 'pk_vote', 'sheriff_vote'].includes(page.phase)) return []
    const grouped = new Map()
    for (const vote of computedState.voteDecisions.value) {
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
    const reviewRows = normalizeReviewScoreRows(reviewPayload)
    if (!reviewRows.length) return []
    return reviewRows.map((ev) => {
      const speech = optionalReviewScorePercent(firstReviewScoreValue(ev, ['speech_score', 'speech', 'speech_quality'], null))
      const vote = optionalReviewScorePercent(firstReviewScoreValue(ev, ['vote_score', 'vote', 'vote_accuracy'], null))
      const skill = optionalReviewScorePercent(firstReviewScoreValue(ev, ['skill_score', 'skill', 'skill_accuracy'], null))
      const logic = optionalReviewScorePercent(firstReviewScoreValue(ev, ['logic_score', 'logic', 'information_score', 'information'], null))
      const team = optionalReviewScorePercent(firstReviewScoreValue(ev, ['team_score', 'team', 'cooperation_score', 'cooperation', 'team_contribution'], null))
      const overall = firstReviewScoreValue(ev, ['role_score', 'overall_score', 'overall', 'total_score'], null)
      const availableDimensions = [speech, vote, skill, logic, team].filter((value) => value != null)
      return {
        player: playerForReviewScore(ev),
        speech,
        vote,
        skill,
        logic,
        team,
        risk_penalty: ev.risk_penalty ?? 0,
        role_score: overall == null
          ? (availableDimensions.length
            ? Math.round(availableDimensions.reduce((sum, value) => sum + value, 0) / availableDimensions.length)
            : 0)
          : reviewScorePercent(overall),
        information: logic,
        cooperation: team
      }
    })
  })
  computedState.activeAssessScores = computed(() =>
    computedState.playerAssessmentScores.value.map((item) => ({
      ...item,
      player: item.player,
      score: item[assessDimension.value] ?? 0
    }))
  )
  computedState.judgeStripMessage = computed(() => {
    const activePrompt = computedState.judgeLogs.value.findLast?.((log) => {
      const type = String(log?.type || log?.event_type || log?.action || log?.action_type || '')
      return type === 'speech_prompt' || type === 'action_request'
    })
    if (activePrompt) {
      const promptSequence = Number(activePrompt?.sequence ?? activePrompt?.index ?? 0)
      const resolvedAction = (refs.game.value?.logs ?? []).findLast?.((log: LooseRecord) => {
        const type = String(log?.type || log?.event_type || log?.action || log?.action_type || '')
        const sequence = Number(log?.sequence ?? log?.index ?? 0)
        return sequence > promptSequence
          && type !== 'speech_prompt'
          && type !== 'action_request'
          && Number(log?.actor_id ?? log?.actor) === Number(activePrompt?.actor_id ?? activePrompt?.actor)
      })
      if (!resolvedAction) {
        return [{ speaker: logSpeaker(activePrompt), message: logMessage(activePrompt) }]
      }
    }
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

  function tallyByTargetName(votes: LooseRecord[]) {
    const tally: Record<string, { target: string; targetName: string; count: number; voters: string[] }> = {}
    votes.forEach((vote) => {
      const key = vote.targetName || '未知'
      if (!tally[key]) tally[key] = { target: key, targetName: key, count: 0, voters: [] }
      tally[key].count++
      const voter = vote.actorName || historyPlayerLabelById(vote.actor_id)
      if (voter && !tally[key].voters.includes(voter)) tally[key].voters.push(voter)
    })
    return Object.values(tally).sort((a, b) => b.count - a.count)
  }

  function nightActionDetail(action: LooseRecord) {
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

  function normalizeReviewScoreRows(payload: LooseRecord | null | undefined) {
    if (!payload || payload.error) return []
    const candidates = [
      payload.player_evaluations,
      payload.player_scores,
      payload.agent_scores
    ]
    for (const candidate of candidates) {
      if (Array.isArray(candidate) && candidate.length) {
        return candidate
          .filter((item) => item && typeof item === 'object')
          .map((item) => ({ ...item, ...(item.scores || {}) }))
      }
      if (candidate && typeof candidate === 'object' && Object.keys(candidate).length) {
        return Object.entries(candidate).map(([seat, score]) => {
          const row: LooseRecord = score && typeof score === 'object' ? score as LooseRecord : { overall_score: score }
          return {
            player_seat: row.player_seat ?? row.player_id ?? row.seat ?? seat,
            ...row,
            ...(row.scores || {})
          }
        })
      }
    }
    return []
  }

  function playerForReviewScore(score: LooseRecord) {
    const rawId = score.player_seat ?? score.player_id ?? score.seat ?? score.id
    const players = selectedHistoryGame.value?.players ?? []
    const player = players.find((item) =>
      String(item.id) === String(rawId) || String(item.seat) === String(rawId)
    )
    return player || {
      id: rawId,
      seat: rawId,
      role: score.role || score.role_hint || ''
    }
  }

  function firstReviewScoreValue(score: LooseRecord, fields: string[], fallback: unknown = 0) {
    for (const field of fields) {
      if (score?.[field] != null) return score[field]
    }
    return fallback
  }

  function reviewScorePercent(value: unknown) {
    const number = Number(value)
    if (!Number.isFinite(number)) return 0
    if (number <= 1) return Math.round(Math.max(0, Math.min(number * 100, 100)))
    if (number <= 10) return Math.round(Math.max(0, Math.min(number * 10, 100)))
    return Math.round(Math.max(0, Math.min(number, 100)))
  }

  function optionalReviewScorePercent(value: unknown) {
    return value == null || value === '' ? undefined : reviewScorePercent(value)
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
