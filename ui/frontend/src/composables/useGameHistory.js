import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { createGameApi } from './gameApi.js'
import { normalizeGameSnapshot } from './gameSnapshot.js'
import { createLatestOnlyMap, createLatestOnlyTracker } from './latestOnly.js'
import {
  displayDayLabel,
  displayPhaseLabel,
  normalizeHistoryDisplayText
} from '../components/history/historyDisplay.js'
import { isReturnableGame, writeViewHash } from './gameSession.js'
import {
  AUTHORITATIVE_DEATH_EVENTS,
  deathTargetIds,
  eventTargetId,
  sheriffIdAfterLog
} from './gameTimeline.js'

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
const SPEECH_EVENT_TYPES = new Set(['speech', 'sheriff_run', 'sheriff_speak', 'pk_speak', 'last_word'])
const REPLAY_VOTE_PHASES = new Set(['vote', 'sheriff_vote'])
const REPLAY_VOTE_ACTIONS = new Set(['vote', 'exile_vote', 'pk_vote', 'sheriff_vote'])
const REPLAY_SPEEDS = [0.5, 1, 2, 4]
const REPLAY_BASE_INTERVAL_MS = 900
const DEFAULT_HISTORY_PAGE_SIZE = 80
const EMPTY_HISTORY_COUNTS = { all: 0, normal: 0, benchmark: 0, evolution: 0 }

function normalizeHistoryPhase(phase = 'setup') {
  return HISTORY_PHASE_ALIASES[phase] || phase || 'setup'
}

function normalizeHistoryDay(day) {
  const value = Number(day)
  return Number.isFinite(value) && value > 0 ? value : 1
}

function historyPageSortValue(page) {
  if (!page) return 0
  const phase = normalizeHistoryPhase(page.phase)
  const rank = HISTORY_PHASE_RANK.has(phase) ? HISTORY_PHASE_RANK.get(phase) : HISTORY_PHASE_ORDER.length
  return normalizeHistoryDay(page.day) * 100 + rank
}

function numericHistoryId(value) {
  const id = Number(value)
  return Number.isFinite(id) && id > 0 ? id : null
}

function actorId(row) {
  return numericHistoryId(row?.actor_id ?? row?.player_id ?? row?.actor ?? row?.playerId ?? row?.payload?.actor_id)
}

function voteActionPhase(row) {
  const action = String(row?.action || row?.action_type || row?.type || row?.event_type || row?.kind || '').trim()
  if (!REPLAY_VOTE_ACTIONS.has(action)) return ''
  return normalizeHistoryPhase(action)
}

function replayVotesForPage(rows = [], page = {}) {
  const currentDay = normalizeHistoryDay(page.day)
  const currentPhase = normalizeHistoryPhase(page.phase)
  return rows.reduce((votes, row, index) => {
    const actionPhase = voteActionPhase(row)
    if (actionPhase !== currentPhase) return votes
    const rowDay = normalizeHistoryDay(row.day ?? currentDay)
    const rowPhase = normalizeHistoryPhase(row.phase ?? currentPhase)
    if (rowDay !== currentDay || rowPhase !== currentPhase) return votes
    const voterId = actorId(row)
    const targetId = numericHistoryId(eventTargetId(row))
    if (!voterId || !targetId) return votes
    votes.push({ voterId, targetId, index })
    return votes
  }, [])
}

function tallyReplayVotes(votes = []) {
  const voteByActor = new Map()
  votes.forEach((vote) => {
    voteByActor.set(vote.voterId, vote)
  })

  const grouped = new Map()
  for (const vote of voteByActor.values()) {
    if (!grouped.has(vote.targetId)) grouped.set(vote.targetId, { target_id: vote.targetId, count: 0, voter_ids: [] })
    const row = grouped.get(vote.targetId)
    row.voter_ids.push(vote.voterId)
    row.count = row.voter_ids.length
  }
  return [...grouped.values()].sort((a, b) => b.count - a.count || a.target_id - b.target_id)
}

function buildReplayVoteTally(decisions = [], page = {}, logs = [], sourceLogs = logs) {
  const currentPhase = normalizeHistoryPhase(page.phase)
  if (!REPLAY_VOTE_PHASES.has(currentPhase)) return []

  const sourceHasStructuredVoteLogs = replayVotesForPage(sourceLogs, page).length > 0
  const votes = sourceHasStructuredVoteLogs
    ? replayVotesForPage(logs, page)
    : replayVotesForPage(decisions, page)
  return tallyReplayVotes(votes)
}

function historyGamePath(gameId) {
  return encodeURIComponent(String(gameId || ''))
}

function createPagination(limit) {
  return {
    total: 0,
    offset: 0,
    limit,
    returned: 0,
    has_more: false
  }
}

function paginationFromResponse(data, rows, { offset, limit }) {
  const raw = data?.pagination || {}
  const returned = Number(raw.returned ?? rows.length ?? 0)
  const total = Number(raw.total ?? (offset + returned))
  return {
    total: Number.isFinite(total) ? total : rows.length,
    offset: Number(raw.offset ?? offset) || 0,
    limit: raw.limit == null ? limit : Number(raw.limit),
    returned: Number.isFinite(returned) ? returned : rows.length,
    has_more: Boolean(raw.has_more)
  }
}

function historyCountsFromResponse(data, rows) {
  const raw = data?.counts || data?.facets?.source || {}
  return {
    ...EMPTY_HISTORY_COUNTS,
    ...Object.fromEntries(
      Object.entries(raw)
        .filter(([key]) => key)
        .map(([key, value]) => [key, Number(value) || 0])
    ),
    all: Number(raw.all ?? data?.pagination?.total ?? rows.length ?? 0) || 0
  }
}

function historyFacetsFromResponse(data, counts) {
  const raw = data?.facets && typeof data.facets === 'object' ? data.facets : {}
  return {
    ...raw,
    source: {
      ...counts,
      ...(raw.source && typeof raw.source === 'object' ? raw.source : {})
    }
  }
}

function mergeHistoryGames(existing, incoming) {
  const seen = new Set()
  return [...existing, ...incoming].filter((game) => {
    const key = String(game?.game_id || '')
    if (!key) return true
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function useGameHistory(state, options = {}) {
  const { apiFetch } = options.apiFetch ? { apiFetch: options.apiFetch } : createGameApi(options.apiBase)
  let actionApi = options.actionApi || {}
  let sceneApi = options.sceneApi || {}
  let replayTimer = null
  const logOpenRequests = createLatestOnlyTracker()
  const historySelectionRequests = createLatestOnlyTracker()
  const historyListRequests = createLatestOnlyTracker()
  const archiveRequests = createLatestOnlyMap()
  const reviewRequests = createLatestOnlyMap()
  const historyPageSize = Math.max(1, Number(options.historyListLimit || DEFAULT_HISTORY_PAGE_SIZE))
  const historyPagination = ref(createPagination(historyPageSize))
  const historyLoadingMore = ref(false)
  const historySourceFilter = ref('all')
  const historyCounts = ref({ ...EMPTY_HISTORY_COUNTS })
  const historyFacets = ref({ source: { ...EMPTY_HISTORY_COUNTS }, status: {} })
  const historyHasMore = computed(() => Boolean(historyPagination.value.has_more))

  function setActionApi(api = {}) {
    actionApi = api || {}
  }

  function setSceneApi(api = {}) {
    sceneApi = api || {}
  }

  function historyQuery(offset = 0) {
    const params = new URLSearchParams()
    params.set('limit', String(historyPageSize))
    params.set('offset', String(Math.max(0, offset || 0)))
    if (historySourceFilter.value && historySourceFilter.value !== 'all') {
      params.set('source', historySourceFilter.value)
    }
    return `?${params.toString()}`
  }

  async function fetchHistoryPage(offset = 0) {
    const data = await apiFetch(`/games${historyQuery(offset)}`)
    const rows = data.games ?? []
    const pagination = paginationFromResponse(data, rows, { offset, limit: historyPageSize })
    const counts = historyCountsFromResponse(data, rows)
    const facets = historyFacetsFromResponse(data, counts)
    return { rows, pagination, counts, facets }
  }

  function applyHistoryMetadata({ pagination, counts, facets }) {
    historyPagination.value = pagination
    historyCounts.value = counts
    historyFacets.value = facets
  }

  async function refreshHistoryList({ silent = false, resetSelection = false } = {}) {
    const token = historyListRequests.next()
    historyLoadingMore.value = false
    if (!silent) state.historyLoading.value = true
    try {
      const { rows, pagination, counts, facets } = await fetchHistoryPage(0)
      if (!token.isLatest()) return false
      state.gameHistory.value = rows
      applyHistoryMetadata({ pagination, counts, facets })
      if (resetSelection) {
        const firstGameId = state.gameHistory.value[0]?.game_id || ''
        state.selectedHistoryGameId.value = firstGameId
        if (state.selectedHistoryGame.value?.game_id !== firstGameId) {
          state.selectedHistoryGame.value = null
        }
      } else if (!state.selectedHistoryGameId.value && state.gameHistory.value.length) {
        state.selectedHistoryGameId.value = state.gameHistory.value[0].game_id
      }
      return true
    } catch {
      if (token.isLatest() && !silent) state.error.value = '历史对局读取失败，请确认后端服务正在运行。'
      return false
    } finally {
      if (token.isLatest() && !silent) state.historyLoading.value = false
    }
  }

  async function loadMoreHistory() {
    if (historyLoadingMore.value || state.historyLoading.value || !historyPagination.value.has_more) return
    const token = historyListRequests.next()
    historyLoadingMore.value = true
    try {
      const nextOffset = historyPagination.value.offset + historyPagination.value.returned
      const { rows, pagination, counts, facets } = await fetchHistoryPage(nextOffset)
      if (!token.isLatest()) return
      state.gameHistory.value = mergeHistoryGames(state.gameHistory.value, rows)
      applyHistoryMetadata({ pagination, counts, facets })
    } catch (err) {
      if (token.isLatest()) state.error.value = err?.message || '历史对局读取失败，请确认后端服务正在运行。'
    } finally {
      if (token.isLatest()) historyLoadingMore.value = false
    }
  }

  async function setHistorySourceFilter(source = 'all') {
    const next = ['normal', 'benchmark', 'evolution'].includes(source) ? source : 'all'
    if (historySourceFilter.value === next) return
    historySourceFilter.value = next
    const applied = await refreshHistoryList({ resetSelection: true })
    if (!applied) return
    const targetGameId = state.selectedHistoryGameId.value
    if (targetGameId) await selectHistoryGame(targetGameId)
  }

  async function selectHistoryGame(gameId, { fromOpenPage = false } = {}) {
    if (!gameId) return
    if (!fromOpenPage) logOpenRequests.invalidate()
    const token = historySelectionRequests.next()
    state.selectedHistoryGameId.value = gameId
    state.historyPhase.value = 'all'
    state.selectedHistoryPageKey.value = ''
    state.historyLoading.value = true
    state.error.value = ''
    try {
      const [gameData] = await Promise.all([
        apiFetch(`/games/${historyGamePath(gameId)}`),
        loadReview(gameId)
      ])
      if (!token.isLatest() || state.selectedHistoryGameId.value !== gameId) return
      state.selectedHistoryGame.value = normalizeGameSnapshot(gameData, { mode: 'watch' })
    } catch {
      if (token.isLatest()) state.error.value = '历史对局详情读取失败。'
    } finally {
      if (token.isLatest()) state.historyLoading.value = false
    }
  }

  function blockNavigationDuringLiveMatch() {
    if (!isReturnableGame(state.liveGame.value)) return false
    state.currentView.value = 'match'
    state.skipIntroGameId.value = state.liveGame.value.game_id
    state.returnToMatchAvailable.value = false
    writeViewHash('match')
    return true
  }

  async function openLogPage(gameId = state.selectedHistoryGameId.value, { rememberOrigin = true } = {}) {
    if (blockNavigationDuringLiveMatch()) return
    const token = logOpenRequests.next()
    state.returnToMatchAvailable.value = rememberOrigin && isReturnableGame(state.liveGame.value)
    state.currentView.value = 'logs'
    writeViewHash('logs')
    await refreshHistoryList()
    if (!token.isLatest()) return
    const targetGameId = gameId || state.selectedHistoryGameId.value || state.gameHistory.value[0]?.game_id
    await selectHistoryGame(targetGameId, { fromOpenPage: true })
  }

  function openEvolutionPage({ rememberOrigin = true } = {}) {
    if (blockNavigationDuringLiveMatch()) return
    state.returnToMatchAvailable.value = rememberOrigin && isReturnableGame(state.liveGame.value)
    state.currentView.value = 'evolution'
    writeViewHash('evolution')
  }

  function openBenchmarkPage({ rememberOrigin = true } = {}) {
    if (blockNavigationDuringLiveMatch()) return
    state.returnToMatchAvailable.value = rememberOrigin && isReturnableGame(state.liveGame.value)
    state.currentView.value = 'benchmark'
    writeViewHash('benchmark')
  }

  function syncHashRoute({ rememberOrigin = false } = {}) {
    const hash = typeof window === 'undefined' ? '' : window.location.hash
    if (hash === '#logs') {
      if (state.currentView.value === 'logs' && state.selectedHistoryGame.value) return
      void openLogPage(state.selectedHistoryGameId.value, { rememberOrigin })
      return
    }
    if (hash === '#evolution') {
      openEvolutionPage({ rememberOrigin })
      return
    }
    if (hash === '#benchmark') {
      openBenchmarkPage({ rememberOrigin })
      return
    }
    if (hash === '#match' && isReturnableGame(state.liveGame.value)) {
      state.currentView.value = 'match'
      state.skipIntroGameId.value = state.liveGame.value.game_id
      return
    }
    if (hash === '#match' && state.isReplayMode.value && state.replayGame.value) {
      state.currentView.value = 'match'
      return
    }
    if (hash === '#match') {
      void actionApi.restoreStoredGame?.({ navigate: true, silent: true, start: true })
    }
  }

  function goLobby() {
    if (blockNavigationDuringLiveMatch()) return
    state.returnToMatchAvailable.value = isReturnableGame(state.liveGame.value)
    state.currentView.value = 'lobby'
    writeViewHash('lobby')
  }

  function backToMatch() {
    state.returnToMatchAvailable.value = false
    if (isReturnableGame(state.liveGame.value)) {
      state.currentView.value = 'match'
      state.skipIntroGameId.value = state.liveGame.value.game_id
      writeViewHash('match')
      if (!state.watchRunning.value) {
        state.watchRunning.value = false
        actionApi.startWatch?.()
      }
    } else {
      state.currentView.value = 'lobby'
      writeViewHash('lobby')
    }
  }

  function buildReplaySnapshot(source, page) {
    if (!source || !page) return null
    const selectedSort = historyPageSortValue(page)
    const logs = (source.logs ?? []).filter((log) =>
      historyPageSortValue({ day: log.day, phase: normalizeHistoryPhase(log.phase) }) <= selectedSort
    )
    const decisions = (source.decisions ?? []).filter((decision) => {
      const decisionPage = {
        day: normalizeHistoryDay(decision.day || page.day),
        phase: normalizeHistoryPhase(decision.phase || page.phase)
      }
      return historyPageSortValue(decisionPage) <= selectedSort
    })
    const players = (source.players ?? []).map((player) => ({ ...player, alive: true, is_sheriff: false }))
    let sheriffId = null
    let currentSpeakerId = null
    const playerById = (id) => players.find((player) => player.id === id)
    const hasAuthoritativeDeathEvents = logs.some((log) => AUTHORITATIVE_DEATH_EVENTS.has(log.event_type || log.type || ''))
    for (const log of logs) {
      const type = log.event_type || log.type || ''
      for (const targetId of deathTargetIds(log, hasAuthoritativeDeathEvents)) {
        const dead = playerById(targetId)
        if (dead) dead.alive = false
      }
      sheriffId = sheriffIdAfterLog(log, sheriffId)
      if (SPEECH_EVENT_TYPES.has(type)) currentSpeakerId = log.actor_id || currentSpeakerId
    }
    players.forEach((player) => { player.is_sheriff = player.id === sheriffId })
    return {
      ...source,
      players,
      logs,
      decisions,
      vote_tally: buildReplayVoteTally(decisions, page, logs, replayEvents(source)),
      day: page.day,
      phase: page.phase,
      current_speaker_id: currentSpeakerId,
      sheriff_id: sheriffId,
      winner: source.winner && ['ended', 'result'].includes(page.phase) ? source.winner : null,
      waiting_for: 'none'
    }
  }

  function replayEvents(source = state.selectedHistoryGame.value) {
    return source?.logs || source?.events || []
  }

  function replayPhaseLabel(phase) {
    const normalized = normalizeHistoryPhase(phase)
    return displayPhaseLabel(normalized)
  }

  function replayCursorForPage(source, page) {
    if (!source || !page) return 0
    const selectedSort = historyPageSortValue(page)
    return replayEvents(source).filter((log) =>
      historyPageSortValue({ day: log.day, phase: normalizeHistoryPhase(log.phase) }) <= selectedSort
    ).length
  }

  function replayEventLabel(log, cursor, total) {
    if (!log || cursor <= 0) return total ? '准备开始' : '无事件'
    const day = normalizeHistoryDay(log.day)
    const phase = replayPhaseLabel(log.phase)
    const speaker = log.speaker && !['法官', '系统'].includes(log.speaker) ? `${log.speaker} · ` : ''
    const message = normalizeHistoryDisplayText(log.message || log.type || log.event_type || '事件').replace(/\s+/g, ' ').trim()
    const clipped = message.length > 42 ? `${message.slice(0, 42)}...` : message
    return `${displayDayLabel(day)} · ${phase} · ${speaker}${clipped}`
  }

  function decisionsForReplayCursor(source, shownLogs, cursorSort) {
    const allDecisions = source.decisions ?? []
    if (!shownLogs.length) return []
    const latest = shownLogs.at(-1)
    const latestDay = normalizeHistoryDay(latest.day)
    const latestPhase = normalizeHistoryPhase(latest.phase)
    const phaseLogsTotal = replayEvents(source).filter((log) =>
      normalizeHistoryDay(log.day) === latestDay && normalizeHistoryPhase(log.phase) === latestPhase
    ).length || 1
    const phaseLogsShown = shownLogs.filter((log) =>
      normalizeHistoryDay(log.day) === latestDay && normalizeHistoryPhase(log.phase) === latestPhase
    ).length
    const samePhaseDecisionLimit = Math.ceil((phaseLogsShown / phaseLogsTotal) * allDecisions.filter((decision) =>
      normalizeHistoryDay(decision.day || latestDay) === latestDay
      && normalizeHistoryPhase(decision.phase || latestPhase) === latestPhase
    ).length)
    let samePhaseSeen = 0
    return allDecisions.filter((decision) => {
      const decisionPage = {
        day: normalizeHistoryDay(decision.day || latestDay),
        phase: normalizeHistoryPhase(decision.phase || latestPhase)
      }
      const decisionSort = historyPageSortValue(decisionPage)
      if (decisionSort < cursorSort) return true
      if (decisionSort > cursorSort) return false
      samePhaseSeen += 1
      return samePhaseSeen <= samePhaseDecisionLimit
    })
  }

  function buildReplaySnapshotByCursor(source, cursor = state.replayCursor.value) {
    if (!source) return null
    const events = replayEvents(source)
    const total = events.length
    const clamped = Math.max(0, Math.min(total, Number(cursor) || 0))
    const logs = events.slice(0, clamped)
    const latestLog = logs.at(-1) || {}
    const day = latestLog.day ?? source.day ?? 1
    const phase = normalizeHistoryPhase(latestLog.phase || (clamped >= total && source.winner ? 'ended' : 'setup'))
    const cursorSort = historyPageSortValue({ day, phase })
    const decisions = decisionsForReplayCursor(source, logs, cursorSort)
    const voteTally = buildReplayVoteTally(decisions, { day, phase }, logs, events)
    const players = (source.players ?? []).map((player) => ({ ...player, alive: true, is_sheriff: false }))
    const playerById = (id) => players.find((player) => Number(player.id) === Number(id))
    const hasAuthoritativeDeathEvents = events.some((log) => AUTHORITATIVE_DEATH_EVENTS.has(log.event_type || log.type || ''))
    let sheriffId = null
    let currentSpeakerId = null

    for (const log of logs) {
      const type = log.event_type || log.type || ''
      for (const targetId of deathTargetIds(log, hasAuthoritativeDeathEvents)) {
        const dead = playerById(targetId)
        if (dead) dead.alive = false
      }
      sheriffId = sheriffIdAfterLog(log, sheriffId)
      if (SPEECH_EVENT_TYPES.has(type)) currentSpeakerId = log.actor_id || currentSpeakerId
    }

    const latestType = latestLog.event_type || latestLog.type || ''
    if (!SPEECH_EVENT_TYPES.has(latestType)) currentSpeakerId = null
    players.forEach((player) => { player.is_sheriff = Number(player.id) === Number(sheriffId) })
    const atEnd = total === 0 || clamped >= total
    return {
      ...source,
      players,
      logs,
      events: logs,
      decisions,
      vote_tally: voteTally,
      day,
      phase,
      current_speaker_id: currentSpeakerId,
      sheriff_id: sheriffId,
      winner: atEnd ? source.winner : null,
      status: atEnd && source.winner ? (source.status || 'completed') : 'replaying',
      waiting_for: 'none',
      pending_action: null,
      pending_human_action: null
    }
  }

  function stopReplayTimer() {
    if (replayTimer) {
      window.clearInterval(replayTimer)
      replayTimer = null
    }
    state.replayPlaying.value = false
  }

  function applyReplayCursor(cursor = state.replayCursor.value) {
    const source = state.selectedHistoryGame.value
    if (!source) return null
    const total = replayEvents(source).length
    const clamped = Math.max(0, Math.min(total, Number(cursor) || 0))
    const snapshot = buildReplaySnapshotByCursor(source, clamped)
    if (!snapshot) return null
    state.replayCursor.value = clamped
    state.replayTotal.value = total
    state.replayEventLabel.value = replayEventLabel(snapshot.logs.at(-1), clamped, total)
    state.replayPageKey.value = state.selectedHistoryPage?.value?.key || state.replayPageKey.value || ''
    state.replayGame.value = snapshot
    if (clamped >= total) stopReplayTimer()
    nextTick(() => sceneApi.scheduleSyncCouncilScene?.())
    return snapshot
  }

  function replayIntervalMs() {
    const speed = Number(state.replaySpeed.value) || 1
    return Math.max(120, Math.round(REPLAY_BASE_INTERVAL_MS / speed))
  }

  function playReplay() {
    if (!state.isReplayMode.value || !state.selectedHistoryGame.value || typeof window === 'undefined') return
    const total = replayEvents(state.selectedHistoryGame.value).length
    if (state.replayCursor.value >= total) applyReplayCursor(0)
    stopReplayTimer()
    state.replayPlaying.value = true
    replayTimer = window.setInterval(() => {
      const next = Math.min(state.replayTotal.value, state.replayCursor.value + 1)
      applyReplayCursor(next)
      if (next >= state.replayTotal.value) stopReplayTimer()
    }, replayIntervalMs())
  }

  function pauseReplay() {
    stopReplayTimer()
  }

  function stepReplay(delta = 1) {
    stopReplayTimer()
    return applyReplayCursor(state.replayCursor.value + Number(delta || 0))
  }

  function seekReplay(cursor) {
    stopReplayTimer()
    return applyReplayCursor(cursor)
  }

  function setReplaySpeed(speed) {
    const number = Number(speed)
    state.replaySpeed.value = REPLAY_SPEEDS.includes(number) ? number : 1
    if (state.replayPlaying.value) playReplay()
  }

  function enterReplayAt(cursor = 0) {
    const source = state.selectedHistoryGame.value
    if (!source) return
    actionApi.stopWatch?.()
    if (!state.isReplayMode.value) {
      state.lastLiveGame.value = isReturnableGame(state.liveGame.value) ? state.liveGame.value : null
    }
    state.isReplayMode.value = true
    state.replaySourceGameId.value = source.game_id || null
    state.replayTotal.value = replayEvents(source).length
    state.judgeBoardStarted.value = true
    state.roleAssignmentComplete.value = true
    applyReplayCursor(cursor)
    state.currentView.value = 'match'
    writeViewHash('match')
  }

  function enterReplayPage(page = state.selectedHistoryPage.value) {
    enterReplayAt(replayCursorForPage(state.selectedHistoryGame.value, page))
  }

  async function replayHistoryGame(gameItem = state.selectedHistoryGame.value) {
    const gameId = typeof gameItem === 'object' ? gameItem?.game_id : gameItem
    const loadedGameId = state.selectedHistoryGame.value?.game_id
    const needsDetail = gameId && (
      state.selectedHistoryGameId.value !== gameId
      || loadedGameId !== gameId
      || !Array.isArray(state.selectedHistoryGame.value?.logs)
    )
    if (needsDetail) {
      await selectHistoryGame(gameId)
      await nextTick()
    }
    if (!state.selectedHistoryGame.value) {
      state.error.value = '回放源数据尚未载入，请稍后重试。'
      return
    }
    enterReplayAt(0)
  }

  function returnToHistoryFromReplay() {
    pauseReplay()
    state.currentView.value = 'logs'
    writeViewHash('logs')
    state.returnToMatchAvailable.value = false
  }

  function exitReplayMode() {
    if (!state.isReplayMode.value) return
    stopReplayTimer()
    state.isReplayMode.value = false
    state.replaySourceGameId.value = null
    state.replayPageKey.value = ''
    state.replayCursor.value = 0
    state.replayPlaying.value = false
    state.replayTotal.value = 0
    state.replayEventLabel.value = ''
    state.replayGame.value = null
    if (isReturnableGame(state.lastLiveGame.value) && !state.liveGame.value) state.liveGame.value = state.lastLiveGame.value
    const hasLiveGame = isReturnableGame(state.liveGame.value)
    state.currentView.value = hasLiveGame ? 'match' : 'lobby'
    if (hasLiveGame) state.skipIntroGameId.value = state.liveGame.value.game_id
    writeViewHash(hasLiveGame ? 'match' : 'lobby')
    state.returnToMatchAvailable.value = false
    if (hasLiveGame) {
      state.watchRunning.value = false
      actionApi.startWatch?.()
    }
  }

  async function loadArchive(gameId = state.selectedHistoryGameId.value) {
    if (!gameId || (state.archiveByGameId.value[gameId] && !state.archiveByGameId.value[gameId].error)) return
    const token = archiveRequests.next(gameId)
    state.archiveLoading.value = true
    try {
      const archive = await apiFetch(`/games/${historyGamePath(gameId)}/archive`)
      if (!token.isLatest()) return
      state.archiveByGameId.value = { ...state.archiveByGameId.value, [gameId]: archive }
    } catch (err) {
      if (token.isLatest()) {
        state.archiveByGameId.value = { ...state.archiveByGameId.value, [gameId]: { error: err.message || '档案读取失败' } }
      }
    } finally {
      if (token.isLatest()) state.archiveLoading.value = false
    }
  }

  async function loadReview(gameId = state.selectedHistoryGameId.value) {
    if (!gameId || (state.reviewByGameId.value[gameId] && !state.reviewByGameId.value[gameId].error)) return
    const token = reviewRequests.next(gameId)
    state.reviewLoading.value = true
    try {
      const review = await apiFetch(`/games/${historyGamePath(gameId)}/review`)
      if (!token.isLatest()) return
      state.reviewByGameId.value = { ...state.reviewByGameId.value, [gameId]: review }
    } catch (err) {
      if (token.isLatest()) {
        state.reviewByGameId.value = { ...state.reviewByGameId.value, [gameId]: { error: err.message || '复盘报告读取失败' } }
      }
    } finally {
      if (token.isLatest()) state.reviewLoading.value = false
    }
  }

  if (options.installLifecycle !== false) {
    const handleHashChange = () => syncHashRoute({ rememberOrigin: false })
    onMounted(() => {
      refreshHistoryList({ silent: true })
      syncHashRoute({ rememberOrigin: false })
      if (typeof window !== 'undefined') window.addEventListener('hashchange', handleHashChange)
    })
    onBeforeUnmount(() => {
      stopReplayTimer()
      if (typeof window !== 'undefined') window.removeEventListener('hashchange', handleHashChange)
    })
  }

  return {
    setActionApi,
    setSceneApi,
    historyPagination,
    historyLoadingMore,
    historySourceFilter,
    historyCounts,
    historyFacets,
    historyHasMore,
    refreshHistoryList,
    loadMoreHistory,
    setHistorySourceFilter,
    selectHistoryGame,
    openLogPage,
    openEvolutionPage,
    openBenchmarkPage,
    syncHashRoute,
    goLobby,
    backToMatch,
    buildReplaySnapshot,
    buildReplaySnapshotByCursor,
    enterReplayAt,
    enterReplayPage,
    applyReplayCursor,
    playReplay,
    pauseReplay,
    stepReplay,
    seekReplay,
    setReplaySpeed,
    stopReplayTimer,
    replayHistoryGame,
    returnToHistoryFromReplay,
    exitReplayMode,
    loadArchive,
    loadReview
  }
}

export { useGameHistory }
