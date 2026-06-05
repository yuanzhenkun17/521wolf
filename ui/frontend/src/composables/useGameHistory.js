import { nextTick, onMounted } from 'vue'
import { createGameApi } from './gameApi.js'
import { normalizeGameSnapshot } from './gameSnapshot.js'

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
const AUTHORITATIVE_DEATH_EVENTS = new Set([
  'death',
  'exile',
  'exile_vote_end',
  'pk_vote_end',
  'white_wolf_burst_kill',
  'white_wolf_burst_death',
  'white_wolf_explosion'
])
const FALLBACK_DEATH_EVENTS = new Set(['werewolf_kill', 'hunter_shoot'])

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

function eventTargetId(log) {
  return log?.target_id ?? log?.target ?? log?.payload?.target ?? log?.payload?.player_id ?? null
}

function eventKillsPlayer(log, hasAuthoritativeDeathEvents) {
  const type = log?.event_type || log?.type || ''
  if (AUTHORITATIVE_DEATH_EVENTS.has(type)) return true
  return !hasAuthoritativeDeathEvents && FALLBACK_DEATH_EVENTS.has(type)
}

function useGameHistory(state, options = {}) {
  const { apiFetch } = options.apiFetch ? { apiFetch: options.apiFetch } : createGameApi(options.apiBase)
  let actionApi = options.actionApi || {}
  let sceneApi = options.sceneApi || {}

  function setActionApi(api = {}) {
    actionApi = api || {}
  }

  function setSceneApi(api = {}) {
    sceneApi = api || {}
  }

  async function refreshHistoryList({ silent = false } = {}) {
    if (!silent) state.historyLoading.value = true
    try {
      const data = await apiFetch('/games')
      state.gameHistory.value = data.games ?? []
      if (!state.selectedHistoryGameId.value && state.gameHistory.value.length) {
        state.selectedHistoryGameId.value = state.gameHistory.value[0].game_id
      }
    } catch {
      if (!silent) state.error.value = '历史对局读取失败，请确认后端服务正在运行。'
    } finally {
      if (!silent) state.historyLoading.value = false
    }
  }

  async function selectHistoryGame(gameId) {
    if (!gameId) return
    state.selectedHistoryGameId.value = gameId
    state.historyPhase.value = 'all'
    state.selectedHistoryPageKey.value = ''
    state.historyLoading.value = true
    state.error.value = ''
    try {
      state.selectedHistoryGame.value = normalizeGameSnapshot(await apiFetch(`/games/${gameId}`), { mode: 'watch' })
    } catch {
      state.error.value = '历史对局详情读取失败。'
    } finally {
      state.historyLoading.value = false
    }
  }

  async function openLogPage(gameId = state.selectedHistoryGameId.value, { rememberOrigin = true } = {}) {
    state.returnToMatchAvailable.value = rememberOrigin && state.currentView.value === 'match' && Boolean(state.game.value)
    actionApi.stopWatch?.()
    state.currentView.value = 'logs'
    window.location.hash = 'logs'
    await refreshHistoryList()
    await selectHistoryGame(gameId || state.gameHistory.value[0]?.game_id)
  }

  function openEvolutionPage({ rememberOrigin = true } = {}) {
    state.returnToMatchAvailable.value = rememberOrigin && state.currentView.value === 'match' && Boolean(state.game.value)
    actionApi.stopWatch?.()
    state.currentView.value = 'evolution'
    window.location.hash = 'evolution'
  }

  function goLobby() {
    actionApi.stopWatch?.()
    state.returnToMatchAvailable.value = false
    state.currentView.value = 'lobby'
    window.location.hash = ''
    state.game.value = null
  }

  function backToMatch() {
    window.location.hash = ''
    state.returnToMatchAvailable.value = false
    if (state.game.value) {
      state.currentView.value = 'match'
      if (state.isWatch.value && !state.game.value.winner) {
        state.watchRunning.value = false
        actionApi.startWatch?.()
      }
    } else {
      state.currentView.value = 'lobby'
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
      if (eventKillsPlayer(log, hasAuthoritativeDeathEvents)) {
        const dead = playerById(eventTargetId(log) || log.actor_id)
        if (dead) dead.alive = false
      }
      if (['sheriff_election_end', 'sheriff_result'].includes(type)) sheriffId = log.payload?.winner || log.target_id || log.actor_id || sheriffId
      if (type === 'sheriff_transfer') sheriffId = log.target_id || sheriffId
      if (type === 'sheriff_destroy') sheriffId = null
      if (['speech', 'sheriff_speak', 'pk_speak', 'last_word'].includes(type)) currentSpeakerId = log.actor_id || currentSpeakerId
    }
    players.forEach((player) => { player.is_sheriff = player.id === sheriffId })
    return {
      ...source,
      players,
      logs,
      decisions,
      day: page.day,
      phase: page.phase,
      current_speaker_id: currentSpeakerId,
      sheriff_id: sheriffId,
      winner: source.winner && ['ended', 'result'].includes(page.phase) ? source.winner : null,
      waiting_for: 'none'
    }
  }

  function enterReplayPage(page = state.selectedHistoryPage.value) {
    const snapshot = buildReplaySnapshot(state.selectedHistoryGame.value, page)
    if (!snapshot) return
    actionApi.stopWatch?.()
    if (!state.isReplayMode.value) state.lastLiveGame.value = state.game.value
    state.isReplayMode.value = true
    state.replaySourceGameId.value = state.selectedHistoryGame.value?.game_id || null
    state.replayPageKey.value = page.key
    state.game.value = snapshot
    state.judgeBoardStarted.value = true
    state.roleAssignmentComplete.value = true
    state.currentView.value = 'match'
    window.location.hash = 'match'
    nextTick(() => sceneApi.scheduleSyncCouncilScene?.())
  }

  async function replayHistoryGame(gameItem = state.selectedHistoryGame.value) {
    const gameId = typeof gameItem === 'object' ? gameItem?.game_id : gameItem
    if (gameId && state.selectedHistoryGameId.value !== gameId) {
      await selectHistoryGame(gameId)
      await nextTick()
    }
    enterReplayPage(state.selectedHistoryPage.value)
  }

  function returnToHistoryFromReplay() {
    state.currentView.value = 'logs'
    window.location.hash = 'logs'
    state.returnToMatchAvailable.value = false
  }

  function exitReplayMode() {
    if (!state.isReplayMode.value) return
    state.isReplayMode.value = false
    state.replaySourceGameId.value = null
    state.replayPageKey.value = ''
    if (state.lastLiveGame.value) state.game.value = state.lastLiveGame.value
    else state.game.value = null
    state.currentView.value = state.game.value ? 'match' : 'lobby'
    window.location.hash = state.game.value ? 'match' : ''
    state.returnToMatchAvailable.value = false
    if (state.game.value && state.isWatch.value && !state.game.value.winner) {
      state.watchRunning.value = false
      actionApi.startWatch?.()
    }
  }

  async function loadArchive(gameId = state.selectedHistoryGameId.value) {
    if (!gameId || state.archiveByGameId.value[gameId]) return
    state.archiveLoading.value = true
    try {
      state.archiveByGameId.value = { ...state.archiveByGameId.value, [gameId]: await apiFetch(`/games/${gameId}/archive`) }
    } catch (err) {
      state.archiveByGameId.value = { ...state.archiveByGameId.value, [gameId]: { error: err.message || '档案读取失败' } }
    } finally {
      state.archiveLoading.value = false
    }
  }

  async function loadReview(gameId = state.selectedHistoryGameId.value) {
    if (!gameId || state.reviewByGameId.value[gameId]) return
    state.reviewLoading.value = true
    try {
      state.reviewByGameId.value = { ...state.reviewByGameId.value, [gameId]: await apiFetch(`/games/${gameId}/review`) }
    } catch (err) {
      state.reviewByGameId.value = { ...state.reviewByGameId.value, [gameId]: { error: err.message || '复盘报告读取失败' } }
    } finally {
      state.reviewLoading.value = false
    }
  }

  if (options.installLifecycle !== false) {
    onMounted(() => {
      refreshHistoryList({ silent: true })
      if (state.currentView.value === 'logs') openLogPage(state.selectedHistoryGameId.value, { rememberOrigin: false })
      if (state.currentView.value === 'evolution') openEvolutionPage({ rememberOrigin: false })
    })
  }

  return {
    setActionApi,
    setSceneApi,
    refreshHistoryList,
    selectHistoryGame,
    openLogPage,
    openEvolutionPage,
    goLobby,
    backToMatch,
    buildReplaySnapshot,
    enterReplayPage,
    replayHistoryGame,
    returnToHistoryFromReplay,
    exitReplayMode,
    loadArchive,
    loadReview
  }
}

export { useGameHistory }
