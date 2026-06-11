import { onBeforeUnmount, onMounted, watch } from 'vue'
import { API, createGameApi } from './gameApi.ts'
import { createLatestOnlyTracker } from './latestOnly.ts'
import { createNoticeAutoDismiss } from './noticeAutoDismiss.ts'
import { createResumableEventSource } from './resumableEventSource.ts'
import {
  canonicalActionType,
  canonicalChoice,
  isSpeechAction,
  normalizeDecisionEntry,
  normalizeGameSnapshot,
  normalizeLogEntry
} from './gameSnapshot.ts'
import {
  activeSessionFromGame,
  clearStoredGameSession,
  emptyActiveSession,
  isReturnableGame,
  isTerminalGame,
  readStoredGameSession,
  writeStoredGameSession
} from './gameSession.ts'
import { currentLegacyView, syncCurrentViewToLegacyHash, writeCurrentViewRoute } from '../router/legacyViewNavigation'
import type { AppView, NoticeType } from '../types/ui'
import type { GameStartRequest } from '../types/game'
import { applyLogToPlayers, applyLogsToPlayers } from './gameTimeline.ts'

type LooseRecord = Record<string, any>
type ApiFetch = (path: string, options?: RequestInit & LooseRecord) => Promise<any>
type TimerId = number | null
type ViewRoute = AppView | ''

interface GameActionsOptions {
  apiFetch?: ApiFetch
  apiBase?: string
  historyApi?: LooseRecord
  sceneApi?: LooseRecord
  installLifecycle?: boolean
  restoreStoredGameOnMount?: boolean | 'immediate'
  restoreStoredGameDelayMs?: number
}

interface GameSnapshotOptions extends LooseRecord {
  mode?: string
  pending?: unknown
}

interface StartOptions extends LooseRecord {
  max_days?: unknown
  player_count?: unknown
  seed?: unknown
  skill_dir?: unknown
  role_versions?: unknown
  model_profile_id?: unknown
}

interface StartNoticeOptions {
  successType?: NoticeType
  successMessage?: string
}

const SPEECH_EVENT_TYPES = new Set([
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

function emptyMatchNotice() {
  return { type: '', message: '' }
}

function normalizeErrorMessage(error: unknown) {
  return String((error as LooseRecord | null | undefined)?.message || '').trim()
}

function localizeMatchError(error: unknown, fallback: string) {
  const message = normalizeErrorMessage(error)
  if (!message) return fallback
  const lower = message.toLowerCase()
  if (
    lower.includes('failed to fetch') ||
    lower.includes('networkerror') ||
    lower.includes('load failed') ||
    lower.includes('fetch')
  ) {
    return '后端连接失败，请确认服务正在运行。'
  }
  if (lower.includes('not found') || lower.includes('404')) {
    return '对局已不存在，请返回大厅重新开始。'
  }
  if (lower.includes('already finished') || lower.includes('finished') || lower.includes('terminal')) {
    return '对局已结束，无法继续操作。'
  }
  if (lower.includes('no pending') || lower.includes('not pending') || lower.includes('not waiting')) {
    return '当前没有等待你处理的行动。'
  }
  if (lower.includes('invalid') || lower.includes('illegal') || lower.includes('非法')) {
    return '行动参数无效，请重新选择。'
  }
  if (lower.includes('timeout') || lower.includes('timed out')) {
    return '请求超时，请稍后重试。'
  }
  return message
}

function actionSuccessMessage(actionType: unknown) {
  const action = canonicalActionType(actionType)
  if (isSpeechAction(action)) return '发言已提交。'
  if (action === 'exile_vote' || action === 'pk_vote' || action === 'sheriff_vote' || action === 'vote') return '投票已提交。'
  if (action === 'white_wolf_explode') return '白狼王行动已提交。'
  if (action === 'witch_act') return '女巫行动已提交。'
  return '行动已提交。'
}

function useGameActions(state: LooseRecord, options: GameActionsOptions = {}) {
  const apiClient: { apiFetch: ApiFetch; apiBase: string } = options.apiFetch
    ? { apiFetch: options.apiFetch, apiBase: options.apiBase || API }
    : createGameApi(options.apiBase || API)
  const { apiFetch, apiBase } = apiClient
  let historyApi = options.historyApi || {}
  let sceneApi = options.sceneApi || {}
  let timer: TimerId = null
  let speechTimer: TimerId = null
  let eventSource: EventSource | null = null
  let eventSourceGameId: string | null = null
  let roleAssignmentTimer: TimerId = null
  let roleAssignmentNoticeTimer: TimerId = null
  let mountedRestoreTimer: TimerId = null
  let mountedRestoreIdle = false
  let lastPendingKey = ''
  let lastStartOptions: StartOptions = {}
  const healthRequests = createLatestOnlyTracker()
  const gameSnapshotRequests = createLatestOnlyTracker()
  const humanActionRequests = createLatestOnlyTracker()
  const visibleLoadingRequests = new Set()
  const noticeAutoDismiss = createNoticeAutoDismiss(state.matchNotice, {
    enabled: options.installLifecycle !== false,
    onDismiss(notice) {
      if (notice.type !== 'error' && state.error.value === notice.message) state.error.value = ''
    }
  })

  function setHistoryApi(api: LooseRecord = {}) { historyApi = api || {} }

  function setSceneApi(api: LooseRecord = {}) { sceneApi = api || {} }

  function setMatchNotice(type: NoticeType, message: string) {
    if (!state.matchNotice) return
    state.matchNotice.value = message ? { type, message } : emptyMatchNotice()
  }

  function clearMatchNotice() {
    setMatchNotice('', '')
  }

  function beginVisibleLoading(enabled = true): symbol | null {
    if (!enabled) return null
    const key = Symbol('loading')
    visibleLoadingRequests.add(key)
    state.loading.value = true
    return key
  }

  function endVisibleLoading(key: symbol | null) {
    if (!key) return
    visibleLoadingRequests.delete(key)
    state.loading.value = visibleLoadingRequests.size > 0
  }

  function invalidateLiveHttpRequests() {
    gameSnapshotRequests.invalidate()
    humanActionRequests.invalidate()
  }

  function preloadCouncilAssets() {
    if (typeof window === 'undefined') return
    const preload = () => {
      import('../CouncilHallScene.ts').catch(() => {})
    }
    if (typeof window.requestIdleCallback === 'function') {
      window.requestIdleCallback(preload, { timeout: 1800 })
      return
    }
    window.setTimeout(preload, 120)
  }

  function waitForDelay(ms: number) {
    if (typeof window === 'undefined' || ms <= 0) return Promise.resolve()
    return new Promise<void>((resolve) => window.setTimeout(resolve, ms))
  }

  async function waitForCouncilSceneApi(timeoutMs = 7000) {
    if (options.installLifecycle === false || typeof window === 'undefined') return sceneApi
    const startedAt = Date.now()
    while (Date.now() - startedAt < timeoutMs) {
      if (typeof sceneApi.waitForCouncilModels === 'function') return sceneApi
      await waitForDelay(80)
    }
    return sceneApi
  }

  async function waitForCouncilEntryReady() {
    if (options.installLifecycle === false) return
    state.judgeBoardStarted.value = true
    state.judgeBoardStarting.value = true
    state.roleAssignmentComplete.value = false
    const api = await waitForCouncilSceneApi()
    try {
      if (typeof api.waitForCouncilModels === 'function') {
        await Promise.race([
          Promise.resolve(api.waitForCouncilModels()),
          waitForDelay(18000)
        ])
      }
    } catch {
      // The match intro should not deadlock on a scene preload failure.
    } finally {
      api.scheduleSyncCouncilScene?.()
    }
  }

  function closeLiveTransport() {
    state.watchRunning.value = false
    liveStream.closeAll()
    eventSource = null
    eventSourceGameId = null
    if (timer) {
      window.clearInterval(timer)
      timer = null
    }
  }

  function clearRoleAssignmentTimers() {
    if (roleAssignmentTimer && typeof window !== 'undefined') {
      window.clearTimeout(roleAssignmentTimer)
    }
    if (roleAssignmentNoticeTimer && typeof window !== 'undefined') {
      window.clearTimeout(roleAssignmentNoticeTimer)
    }
    roleAssignmentTimer = null
    roleAssignmentNoticeTimer = null
  }

  function clearMountedRestoreTimer() {
    if (!mountedRestoreTimer || typeof window === 'undefined') return
    if (mountedRestoreIdle && typeof window.cancelIdleCallback === 'function') {
      window.cancelIdleCallback(mountedRestoreTimer)
    } else {
      window.clearTimeout(mountedRestoreTimer)
    }
    mountedRestoreTimer = null
    mountedRestoreIdle = false
  }

  function scheduleMountedRestore() {
    if (options.restoreStoredGameOnMount === false || typeof window === 'undefined') return
    const restore = () => {
      mountedRestoreTimer = null
      mountedRestoreIdle = false
      void restoreStoredGame({ silent: true, navigate: true, start: true })
    }
    const hashView = currentLegacyView()
    if (hashView === 'match' || options.restoreStoredGameOnMount === 'immediate') {
      restore()
      return
    }
    if (typeof window.requestIdleCallback === 'function') {
      mountedRestoreIdle = true
      mountedRestoreTimer = window.requestIdleCallback(restore, { timeout: 1500 })
      return
    }
    mountedRestoreTimer = window.setTimeout(restore, Number(options.restoreStoredGameDelayMs ?? 350))
  }

  function completeRoleAssignmentForGame(gameId: unknown, { notice = true }: { notice?: boolean } = {}) {
    if (!isReturnableGame(state.liveGame.value) || state.liveGame.value?.game_id !== gameId) return
    state.roleAssignmentComplete.value = true
    state.judgeBoardStarting.value = false
    sceneApi.scheduleSyncCouncilScene?.()
    if (!notice || typeof window === 'undefined') return
    state.roleAssignmentCompleteNotice.value = true
    if (roleAssignmentNoticeTimer) window.clearTimeout(roleAssignmentNoticeTimer)
    roleAssignmentNoticeTimer = window.setTimeout(() => {
      roleAssignmentNoticeTimer = null
      state.roleAssignmentCompleteNotice.value = false
    }, 1400)
  }

  function enterStartedGame(game: LooseRecord | null, { notice = false, skipIntro = false }: { notice?: boolean; skipIntro?: boolean } = {}) {
    if (!isReturnableGame(game)) return false
    clearRoleAssignmentTimers()
    state.judgeBoardStarted.value = true
    state.judgeBoardStarting.value = false
    state.roleAssignmentComplete.value = true
    state.roleAssignmentCompleteNotice.value = false
    if (skipIntro) state.skipIntroGameId.value = game.game_id
    completeRoleAssignmentForGame(game.game_id, { notice })
    return true
  }

  function scheduleRoleAssignmentComplete(gameId: unknown, delayMs = 800) {
    if (!gameId || state.roleAssignmentComplete.value || typeof window === 'undefined') return
    if (options.installLifecycle === false) {
      completeRoleAssignmentForGame(gameId, { notice: false })
      return
    }
    if (roleAssignmentTimer) window.clearTimeout(roleAssignmentTimer)
    roleAssignmentTimer = window.setTimeout(() => {
      roleAssignmentTimer = null
      completeRoleAssignmentForGame(gameId)
    }, delayMs)
  }

  function finishGameSession({
    clearGame = false,
    route = '',
    resetLive = false,
    refreshHistory = false
  }: {
    clearGame?: boolean
    route?: ViewRoute
    resetLive?: boolean
    refreshHistory?: boolean
  } = {}) {
    const finishedGameId = state.liveGame.value?.game_id || state.activeSession.value?.gameId
    invalidateLiveHttpRequests()
    closeLiveTransport()
    clearSpeechTimer()
    clearStoredGameSession()
    if (clearGame && finishedGameId) resetLiveEventId(finishedGameId)
    if (resetLive) resetLiveState()
    else {
      state.activeSession.value = emptyActiveSession()
      lastPendingKey = ''
    }
    state.returnToMatchAvailable.value = false
    if (clearGame) state.liveGame.value = null
    if (route) writeCurrentViewRoute(state.currentView, route)
    if (refreshHistory) historyApi.refreshHistoryList?.({ silent: true })
  }

  function stopGameInBackground(gameId: unknown, { refreshHistory = false }: { refreshHistory?: boolean } = {}) {
    if (!gameId) {
      if (refreshHistory) historyApi.refreshHistoryList?.({ silent: true })
      return Promise.resolve(null)
    }
    return apiFetch(`/games/${encodeURIComponent(String(gameId))}/stop`, { method: 'POST' })
      .catch((err) => {
        setMatchNotice('warning', localizeMatchError(err, '后台停止对局失败。'))
        return { stopFailed: true }
      })
      .finally(() => {
        if (refreshHistory) historyApi.refreshHistoryList?.({ silent: true })
      })
  }

  function resetLiveState() {
    invalidateLiveHttpRequests()
    clearRoleAssignmentTimers()
    state.isReplayMode.value = false
    state.lastLiveGame.value = null
    state.replayGame.value = null
    state.skipIntroGameId.value = null
    state.visualSeatSalt.value = Math.random().toString(36).slice(2)
    state.judgeBoardStarted.value = false
    state.judgeBoardStarting.value = false
    state.roleAssignmentComplete.value = false
    state.roleAssignmentCompleteNotice.value = false
    state.actionTarget.value = null
    state.actionChoice.value = ''
    state.witchChoice.value = 'skip'
    state.burstArmed.value = false
    state.activeSession.value = emptyActiveSession()
    clearStoredGameSession()
    liveStream.resetAllEventIds()
    lastPendingKey = ''
  }

  function makeLiveEventSourceUrl(gameId: string, lastEventId = '') {
    const base = `${apiBase}/games/${encodeURIComponent(gameId)}/events`
    if (!lastEventId) return base
    return `${base}?lastEventId=${encodeURIComponent(lastEventId)}`
  }

  function resetLiveEventId(gameId: string) {
    liveStream.resetEventId(gameId)
  }

  function pendingControlKey(game: LooseRecord | null | undefined) {
    if (!game) return ''
    const pending = game.pending_human_action || {}
    const action = pending.action_type || game.pending_action?.type || game.waiting_for || ''
    const candidates = game.pending_action?.candidate_ids || pending.candidates || []
    return `${action}:${game.day}:${game.phase}:${pending.retry_count ?? ''}:${candidates.join(',')}`
  }

  function hasPendingHumanAction(game: LooseRecord | null | undefined = state.liveGame.value) {
    const pending = game?.pending_human_action
    if (!pending) return false
    const pendingPlayerId = Number(pending.player_id)
    const humanPlayerId = Number(game?.human_player_id)
    return !pendingPlayerId || !humanPlayerId || pendingPlayerId === humanPlayerId
  }

  function syncPendingControls(game: LooseRecord | null | undefined) {
    const key = pendingControlKey(game)
    if (key !== lastPendingKey) {
      state.actionTarget.value = null
      state.actionChoice.value = ''
      if (game?.pending_action?.type !== 'witch_act') state.witchChoice.value = 'skip'
      state.burstArmed.value = false
      lastPendingKey = key
    }

    const candidates = game?.pending_action?.candidate_ids || []
    if (candidates.length && state.actionTarget.value != null && !candidates.includes(Number(state.actionTarget.value))) {
      state.actionTarget.value = null
    }
    if (
      state.canVotePlayers.value.length &&
      !state.canVotePlayers.value.some((p) => p.id === Number(state.voteTarget.value))
    ) {
      state.voteTarget.value = state.canVotePlayers.value[0].id
    }
  }

  function setGameSnapshot(raw: unknown, normalizeOptions: GameSnapshotOptions = {}) {
    if (!raw) return null
    const normalized = normalizeGameSnapshot(raw, normalizeOptions)
    if (!normalized) return null
    const privilegedSnapshot = normalized.mode === 'watch' || state.isReplayMode.value || normalized.winner
    const gameForState = privilegedSnapshot
      ? { ...normalized, players: applyLogsToPlayers(normalized.players, normalized.logs || []) }
      : normalized
    state.liveGame.value = gameForState
    state.activeSession.value = activeSessionFromGame(gameForState, {
      mode: normalizeOptions.mode,
      sseConnected: state.activeSession.value.sseConnected && state.activeSession.value.gameId === gameForState.game_id
    })
    if (isTerminalGame(gameForState)) {
      resetLiveEventId(gameForState.game_id)
      finishGameSession()
    } else {
      writeStoredGameSession(gameForState, { mode: normalizeOptions.mode })
    }
    syncPendingControls(gameForState)
    return gameForState
  }

  function eventKey(log) {
    return [
      log.sequence ?? log.index ?? '',
      log.type || log.event_type || log.action || log.action_type || log.kind || '',
      log.day ?? '',
      log.phase || '',
      log.actor_id ?? log.actor ?? log.player_id ?? log.playerId ?? log.speaker_id ?? log.speakerId ?? '',
      log.target_id ?? log.target ?? '',
      log.message ?? log._message ?? log.content ?? log.text ?? log.public_summary ?? log.public_text ?? ''
    ].join('|')
  }

  function decisionKey(decision) {
    return decision.id || decision.decision_id || [
      decision.index ?? '',
      decision.action || decision.action_type || '',
      decision.player_id ?? decision.actor_id ?? '',
      decision.day ?? '',
      decision.phase || ''
    ].join('|')
  }

  function applyLiveLog(raw) {
    const liveGame = state.liveGame.value
    if (!liveGame || state.isReplayMode.value) return
    const log = normalizeLogEntry(raw)
    const logs = liveGame.logs || []
    if (logs.some((item) => eventKey(item) === eventKey(log))) return
    const nextLogs = [...logs, log]
    const type = log.type || log.event_type || ''
    const patch = {
      ...liveGame,
      logs: nextLogs,
      events: nextLogs,
      day: Number.isFinite(Number(log.day)) ? Number(log.day) : liveGame.day,
      phase: log.phase || liveGame.phase,
      players: applyLogToPlayers(liveGame.players, log)
    }
    const actorId = Number(log.actor_id ?? log.player_id ?? log.playerId ?? log.speaker_id ?? log.speakerId)
    if (SPEECH_EVENT_TYPES.has(type) && Number.isFinite(actorId) && actorId > 0) {
      patch.current_speaker_id = actorId
    }
    setGameSnapshot(patch, { mode: liveGame.mode, pending: liveGame.pending_human_action })
  }

  function applyLiveDecision(raw) {
    const liveGame = state.liveGame.value
    if (!liveGame || state.isReplayMode.value) return
    const decisions = liveGame.decisions || []
    const decision = normalizeDecisionEntry(raw, decisions.length + 1)
    if (decisions.some((item) => decisionKey(item) === decisionKey(decision))) return
    setGameSnapshot({
      ...liveGame,
      decisions: [...decisions, decision]
    }, { mode: liveGame.mode, pending: liveGame.pending_human_action })
  }

  function parseStartPayload(payload) {
    if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
      const { mode = 'watch', options: nestedOptions, settings: nestedSettings, ...directOptions } = payload
      const payloadOptions = nestedOptions || nestedSettings || directOptions
      return {
        mode,
        options: payloadOptions,
        hasOptions: Object.keys(payloadOptions).length > 0
      }
    }
    return { mode: payload || 'watch', options: {}, hasOptions: false }
  }

  function positiveInt(value, fallback, min = 1, max = Number.MAX_SAFE_INTEGER) {
    const number = Number(value)
    if (!Number.isFinite(number)) return fallback
    return Math.max(min, Math.min(max, Math.round(number)))
  }

  function optionalInt(value) {
    if (value === '' || value == null) return undefined
    const number = Number(value)
    return Number.isInteger(number) ? number : undefined
  }

  function compactRoleVersions(value) {
    if (!value || typeof value !== 'object') return undefined
    const entries = Object.entries(value)
      .filter(([role, versionId]) => role && versionId)
      .map(([role, versionId]) => [role, String(versionId)])
    return entries.length ? Object.fromEntries(entries) : undefined
  }

  function startGameBody(mode: string, options: StartOptions = {}): GameStartRequest {
    const body: GameStartRequest = {
      max_days: positiveInt(options.max_days, 20, 1, 100),
      player_count: positiveInt(options.player_count ?? state.playerCount.value, 12, 12, 12),
      human_player_id: mode === 'play' ? 1 : null
    }
    const seed = optionalInt(options.seed)
    const skillDir = String(options.skill_dir || '').trim()
    const roleVersions = compactRoleVersions(options.role_versions)
    const modelProfileId = String(options.model_profile_id || '').trim()
    if (seed !== undefined) body.seed = seed
    if (skillDir) body.skill_dir = skillDir
    if (roleVersions) body.role_versions = roleVersions
    if (modelProfileId) body.model_profile_id = modelProfileId
    return body
  }

  async function fetchPendingHumanAction(gameId) {
    if (!gameId) return null
    try {
      return await apiFetch(`/games/${encodeURIComponent(gameId)}/human-action`)
    } catch {
      return null
    }
  }

  async function pendingFromSnapshot(raw, gameId = raw?.game_id) {
    if (!raw?.human_player_id) return null
    if (raw.pending_human_action !== undefined) return raw.pending_human_action
    return fetchPendingHumanAction(gameId)
  }

  async function loadCurrentGame({ silent = false, advance = false, mode = state.liveGame.value?.mode } = {}) {
    const gameId = state.liveGame.value?.game_id
    if (!gameId) return null
    const token = gameSnapshotRequests.next()
    const loadingKey = beginVisibleLoading(!silent)
    state.error.value = ''
    try {
      const raw = await apiFetch(`/games/${encodeURIComponent(gameId)}${advance ? '?advance=1' : ''}`)
      const pending = await pendingFromSnapshot(raw, gameId)
      if (!token.isLatest() || state.liveGame.value?.game_id !== gameId) return null
      return setGameSnapshot(raw, { mode, pending })
    } catch (err) {
      if (token.isLatest() && !silent) state.error.value = err?.message || '对局状态刷新失败。'
      return null
    } finally {
      endVisibleLoading(loadingKey)
    }
  }

  async function loadGameById(gameId, { silent = false, mode = '' } = {}) {
    if (!gameId) return null
    const token = gameSnapshotRequests.next()
    const loadingKey = beginVisibleLoading(!silent)
    state.error.value = ''
    try {
      const raw = await apiFetch(`/games/${encodeURIComponent(gameId)}`)
      const pending = await pendingFromSnapshot(raw, gameId)
      if (!token.isLatest()) return null
      return setGameSnapshot(raw, { mode, pending })
    } catch (err) {
      if (token.isLatest() && !silent) state.error.value = err?.message || '对局恢复失败。'
      return null
    } finally {
      endVisibleLoading(loadingKey)
    }
  }

  async function restoreStoredGame({ navigate = true, silent = true, start = true } = {}) {
    const session = readStoredGameSession()
    const hashView = currentLegacyView(state.currentView.value)
    if (!session?.gameId || isReturnableGame(state.liveGame.value)) {
      if (navigate && hashView === 'match' && !isReturnableGame(state.liveGame.value)) {
        writeCurrentViewRoute(state.currentView, 'lobby')
      }
      return state.liveGame.value
    }
    const restored = await loadGameById(session.gameId, { silent, mode: session.mode })
    if (!isReturnableGame(restored)) {
      clearStoredGameSession()
      if (navigate && hashView === 'match') {
        writeCurrentViewRoute(state.currentView, 'lobby')
      }
      return null
    }
    state.judgeBoardStarted.value = true
    state.roleAssignmentComplete.value = true
    state.skipIntroGameId.value = restored.game_id
    preloadCouncilAssets()
    if (navigate && hashView === 'match') syncCurrentViewToLegacyHash(state.currentView, 'match')
    if (start) {
      if (state.isWatch.value) startWatch()
      else startPlayerPolling({ immediate: true })
    }
    return restored
  }

  async function refreshHealth() {
    const token = healthRequests.next()
    try {
      const health = await apiFetch('/health')
      if (!token.isLatest()) return
      state.backendMode.value = health.mode || 'mock'
      state.externalStatus.value = health.external || null
      state.runtimeHealth.value = health || null
    } catch {
      if (token.isLatest()) {
        state.backendMode.value = 'offline'
        state.externalStatus.value = { supports_human: false, supports_sse: false }
        state.runtimeHealth.value = { status: 'error', ready: false, external: state.externalStatus.value }
      }
    }
  }

  async function request(path, options = {}, normalizeOptions = {}) {
    const token = gameSnapshotRequests.next()
    const loadingKey = beginVisibleLoading()
    state.error.value = ''
    try {
      const raw = await apiFetch(path, options)
      const pending = await pendingFromSnapshot(raw)
      if (!token.isLatest()) return null
      const game = setGameSnapshot(raw, { ...normalizeOptions, pending })
      const isNavigationRequest = path === '/games'
      if (isNavigationRequest) writeCurrentViewRoute(state.currentView, 'match')
      historyApi.refreshHistoryList?.({ silent: true })
      return game
    } catch (err) {
      if (token.isLatest()) {
        state.error.value = localizeMatchError(err, '后端未连接或接口异常，请确认 FastAPI 服务正在运行。')
        stopWatch()
      }
      return null
    } finally {
      endVisibleLoading(loadingKey)
    }
  }

  async function startMode(payload: unknown, noticeOptions: StartNoticeOptions = {}) {
    const { mode, options: payloadOptions, hasOptions } = parseStartPayload(payload)
    const startOptions = hasOptions ? payloadOptions : lastStartOptions
    if (hasOptions) lastStartOptions = { ...payloadOptions }
    clearMatchNotice()
    stopWatch()
    if (state.backendMode.value === 'offline') {
      const message = '后端未连接，请先启动 FastAPI 服务。'
      state.error.value = message
      setMatchNotice('error', message)
      return null
    }
    if (mode === 'play' && state.externalStatus.value?.supports_human === false) {
      const message = '当前后端暂不支持人类加入，请使用观战模式。'
      state.error.value = message
      setMatchNotice('warning', message)
      return null
    }
    resetLiveState()
    preloadCouncilAssets()
    const bootLoadingKey = beginVisibleLoading()
    let bootLoadingActive = Boolean(bootLoadingKey)
    let game: LooseRecord | null = null
    try {
      game = await request('/games', {
        method: 'POST',
        body: JSON.stringify(startGameBody(mode, startOptions))
      }, { mode })
      endVisibleLoading(bootLoadingKey)
      bootLoadingActive = false
      if (enterStartedGame(game, { skipIntro: false })) {
        if ((game.mode || mode) === 'watch') {
          startWatch()
        } else {
          startPlayerPolling({ immediate: true })
        }
        setMatchNotice(
          noticeOptions.successType || 'success',
          noticeOptions.successMessage || ((game.mode || mode) === 'watch' ? '观战对局已开始。' : '玩家对局已开始。')
        )
      } else if (!game) {
        setMatchNotice('error', state.error.value || '对局创建失败，请稍后重试。')
      }
    } finally {
      if (bootLoadingActive) endVisibleLoading(bootLoadingKey)
    }
    await refreshHealth()
    return game
  }

  async function resetGame() {
    clearMatchNotice()
    stopWatch()
    const previousGameId = state.liveGame.value?.game_id
    const mode = state.isWatch.value ? 'watch' : 'play'
    let stopFailed = false
    if (previousGameId) {
      await apiFetch(`/games/${encodeURIComponent(previousGameId)}/stop`, { method: 'POST' }).catch(() => {
        stopFailed = true
        return null
      })
    }
    resetLiveState()
    return startMode(mode, {
      successType: stopFailed ? 'warning' : 'success',
      successMessage: stopFailed ? '已重开对局；旧对局后台停止失败。' : '已重开对局。'
    })
  }

  async function exitGame() {
    const previousGameId = state.liveGame.value?.game_id
    invalidateLiveHttpRequests()
    closeLiveTransport()
    state.error.value = ''
    clearMatchNotice()
    finishGameSession({ clearGame: true, route: 'lobby', resetLive: true, refreshHistory: !previousGameId })
    stopGameInBackground(previousGameId, { refreshHistory: true }).then((result) => {
      if (previousGameId && result?.stopFailed) {
        const message = '已返回大厅，但后台停止对局失败。'
        setMatchNotice('warning', message)
        state.error.value = message
      }
    })
  }

  function stepGame() {
    if (state.isReplayMode.value) return Promise.resolve()
    return loadCurrentGame({ advance: state.backendMode.value === 'mock' })
  }

  function applyPendingHumanAction(pending) {
    const liveGame = state.liveGame.value
    if (!liveGame) return
    setGameSnapshot(liveGame, {
      mode: liveGame.mode,
      pending
    })
  }

  const liveStream = createResumableEventSource({
    events: ['log', 'decision', 'decision_needed', 'done'],
    backoff: true,
    makeUrl: makeLiveEventSourceUrl,
    shouldReconnect(gameId) {
      return state.watchRunning.value
        && isReturnableGame(state.liveGame.value)
        && state.liveGame.value?.game_id === gameId
    },
    isTerminal(event) {
      return event.type === 'done'
    },
    onOpen({ id, source }) {
      eventSource = source
      eventSourceGameId = id
      state.activeSession.value = { ...state.activeSession.value, sseConnected: true }
    },
    onError({ id, source }) {
      if (eventSource === source) eventSource = null
      eventSourceGameId = id
      state.activeSession.value = { ...state.activeSession.value, sseConnected: false }
      state.watchRunning.value = isReturnableGame(state.liveGame.value)
    },
    async onEvent({ event, payload, parseError }) {
      if (parseError) {
        refreshLiveGameSilently()
        return
      }
      if (event.type === 'log') {
        try {
          applyLiveLog(payload)
        } catch {
          refreshLiveGameSilently()
        }
        return
      }
      if (event.type === 'decision') {
        try {
          applyLiveDecision(payload)
        } catch {
          refreshLiveGameSilently()
        }
        return
      }
      if (event.type === 'decision_needed') {
        try {
          applyPendingHumanAction(payload)
        } catch {
          refreshLiveGameSilently()
        }
        return
      }
      if (event.type === 'done') {
        eventSource = null
        eventSourceGameId = null
        try {
          setGameSnapshot(payload, { mode: state.liveGame.value?.mode })
        } catch {
          loadCurrentGame({ silent: true })
        }
        historyApi.refreshHistoryList?.({ silent: true })
      }
    }
  })

  function startWatch() {
    const liveGame = state.liveGame.value
    const gameId = liveGame?.game_id
    if (state.isReplayMode.value || !isReturnableGame(liveGame)) return
    if (state.watchRunning.value && eventSource && eventSourceGameId === gameId) return
    state.judgeBoardStarted.value = true
    if (!state.roleAssignmentComplete.value) {
      state.roleAssignmentCompleteNotice.value = false
      scheduleRoleAssignmentComplete(gameId)
    }
    state.watchRunning.value = true
    state.activeSession.value = activeSessionFromGame(liveGame)

    if (state.backendMode.value !== 'mock' && gameId && typeof EventSource !== 'undefined') {
      ensureLivePolling(5000)
      connectEventSource(gameId)
      return
    }

    stepGame()
    timer = window.setInterval(() => {
      if (!state.loading.value && isReturnableGame(state.liveGame.value)) stepGame()
    }, 1500)
  }

  function refreshLiveGameSilently() {
    if (state.watchRunning.value && !state.loading.value && isReturnableGame(state.liveGame.value)) {
      loadCurrentGame({ silent: true })
    }
  }

  function ensureLivePolling(intervalMs) {
    if (timer || typeof window === 'undefined') return
    timer = window.setInterval(refreshLiveGameSilently, intervalMs)
  }

  function connectEventSource(gameId) {
    if (!gameId || typeof EventSource === 'undefined') return
    if (!state.watchRunning.value || !isReturnableGame(state.liveGame.value)) return
    if (liveStream.has(gameId)) return
    if (eventSource && eventSourceGameId !== gameId) liveStream.close(eventSourceGameId)
    eventSourceGameId = gameId
    eventSource = liveStream.connect(gameId)
  }

  function startFromJudgeBoard() {
    if (state.judgeBoardStarting.value || state.watchRunning.value) return
    const game = state.liveGame.value
    if (!isReturnableGame(game)) return
    state.judgeBoardStarting.value = true
    state.judgeBoardStarted.value = true
    state.roleAssignmentCompleteNotice.value = false
    enterStartedGame(game, { notice: true, skipIntro: false })
    if (state.isWatch.value) {
      startWatch()
    } else {
      progressPlayerGame()
      startPlayerPolling()
    }
    Promise.resolve(sceneApi.waitForCouncilModels?.())
      .then(() => sceneApi.scheduleSyncCouncilScene?.())
      .catch(() => sceneApi.scheduleSyncCouncilScene?.())
      .finally(() => {
        state.judgeBoardStarting.value = false
      })
  }

  function stopWatch() {
    closeLiveTransport()
    state.activeSession.value = isReturnableGame(state.liveGame.value)
      ? activeSessionFromGame(state.liveGame.value)
      : emptyActiveSession()
  }

  function shouldAdvancePlayerGame() {
    return state.backendMode.value === 'mock'
  }

  function progressPlayerGame() {
    if (
      state.isWatch.value ||
      state.isReplayMode.value ||
      state.loading.value ||
      !isReturnableGame(state.liveGame.value) ||
      state.liveGame.value.waiting_for !== 'none'
    ) return null
    return loadCurrentGame({ silent: true, advance: shouldAdvancePlayerGame() })
  }

  function startPlayerPolling({ immediate = false } = {}) {
    if (state.isWatch.value || typeof window === 'undefined') return
    if (immediate) progressPlayerGame()
    if (timer) return
    timer = window.setInterval(progressPlayerGame, 1500)
  }

  function toggleWatch() {
    if (state.watchRunning.value) {
      stopWatch()
      return
    }
    startWatch()
  }

  function clearSpeechTimer() {
    if (speechTimer) {
      window.clearInterval(speechTimer)
      speechTimer = null
    }
  }

  function startSpeechTimer() {
    clearSpeechTimer()
    state.speechRemaining.value = 180
    speechTimer = window.setInterval(() => {
      state.speechRemaining.value -= 1
      if (state.speechRemaining.value <= 0) {
        clearSpeechTimer()
        submitSpeech('')
      }
    }, 1000)
  }

  async function submitHumanAction(actionType, { target = null, choice = null, text = '' } = {}) {
    const liveGame = state.liveGame.value
    const gameId = liveGame?.game_id
    if (state.isReplayMode.value || state.isWatch.value || !gameId || !actionType || !hasPendingHumanAction(liveGame)) {
      if (!state.isReplayMode.value && !state.isWatch.value && gameId) {
        setMatchNotice('warning', '当前没有等待你处理的行动。')
      }
      return Promise.resolve()
    }

    const actionToken = humanActionRequests.next()
    const snapshotToken = gameSnapshotRequests.next()
    clearMatchNotice()
    setGameSnapshot({
      ...liveGame,
      current_speaker_id: null,
      waiting_for: 'none',
      pending_action: null,
      pending_human_action: null
    }, { mode: liveGame.mode, pending: null })
    const loadingKey = beginVisibleLoading()
    state.error.value = ''
    try {
      const raw = await apiFetch(`/games/${encodeURIComponent(gameId)}/action`, {
        method: 'POST',
        body: JSON.stringify({
          action_type: canonicalActionType(actionType),
          target,
          choice,
          text
        })
      })
      if (!actionToken.isLatest() || !snapshotToken.isLatest() || state.liveGame.value?.game_id !== gameId) return false
      if (raw) {
        setGameSnapshot(raw, { mode: liveGame.mode })
      } else {
        await loadCurrentGame({ silent: true })
      }
      if (actionToken.isLatest() && state.liveGame.value?.game_id === gameId) {
        historyApi.refreshHistoryList?.({ silent: true })
        setMatchNotice('success', actionSuccessMessage(actionType))
      }
      return true
    } catch (err) {
      if (actionToken.isLatest() && state.liveGame.value?.game_id === gameId) {
        const message = localizeMatchError(err, '提交行动失败。')
        state.error.value = message
        setMatchNotice('error', message)
        await loadCurrentGame({ silent: true })
      }
      return false
    } finally {
      endVisibleLoading(loadingKey)
      if (actionToken.isLatest() && state.liveGame.value?.game_id === gameId) {
        startPlayerPolling({ immediate: true })
      }
    }
  }

  function submitSpeech(textOverride = null) {
    if (state.isReplayMode.value || state.isWatch.value) return Promise.resolve()
    clearSpeechTimer()
    const pendingActionType = state.liveGame.value?.pending_human_action?.action_type
    const actionType = isSpeechAction(pendingActionType) ? pendingActionType : 'speak'
    return submitHumanAction(actionType, {
      text: textOverride == null ? state.speech.value : textOverride
    })
  }

  function submitVote() {
    if (state.isReplayMode.value || state.isWatch.value) return Promise.resolve()
    const actionType = state.pendingActionType.value || state.liveGame.value?.pending_human_action?.action_type || 'exile_vote'
    const selectedTarget = state.actionTarget.value == null ? null : Number(state.actionTarget.value)
    return submitHumanAction(actionType, {
      target: selectedTarget
    })
  }

  function submitAction(
    action = state.pendingActionType.value,
    targetId = state.actionTarget.value,
    choice = null
  ) {
    if (state.isReplayMode.value || state.isWatch.value) return Promise.resolve()
    const gameId = state.liveGame.value?.game_id
    const actionType = canonicalActionType(action || state.liveGame.value?.pending_human_action?.action_type)
    if (!actionType) return Promise.resolve()
    if (actionType === 'white_wolf_explode' && state.pendingActionType.value !== 'white_wolf_explode') {
      return Promise.resolve()
    }
    const selectedChoice = choice ?? (actionType === 'witch_act' ? state.witchChoice.value : state.actionChoice.value)
    const normalizedChoice = canonicalChoice(actionType, selectedChoice)
    return submitHumanAction(actionType, {
      target: targetId ? Number(targetId) : null,
      choice: normalizedChoice
    }).then(() => {
      if (state.liveGame.value?.game_id !== gameId) return
      state.actionTarget.value = null
      state.actionChoice.value = ''
      state.witchChoice.value = 'skip'
    })
  }

  function submitWhiteWolfBurst(targetId = state.actionTarget.value) {
    if (!targetId || state.pendingActionType.value !== 'white_wolf_explode' || !state.canWhiteWolfBurst.value) return Promise.resolve()
    const gameId = state.liveGame.value?.game_id
    return submitAction('white_wolf_burst', targetId, 'burst').finally(() => {
      if (state.liveGame.value?.game_id !== gameId) return
      state.burstArmed.value = false
    })
  }

  function chooseScenePlayer(playerId) {
    const id = Number(playerId)
    if (!id) return
    if (!hasPendingHumanAction()) return
    if (state.burstArmed.value && state.whiteWolfTargets.value.some((player) => player.id === id)) {
      state.actionTarget.value = id
      return
    }
    if (state.pendingActionType.value) {
      if (state.actionCandidates.value.some((player) => player.id === id)) {
        state.actionTarget.value = id
      }
      return
    }
    if (
      state.liveGame.value?.waiting_for === 'vote' &&
      state.canVotePlayers.value.some((player) => player.id === id)
    ) {
      state.actionTarget.value = id
      state.voteTarget.value = id
    }
  }

  if (options.installLifecycle !== false) {
    watch(() => [
      state.liveGame.value?.waiting_for,
      state.liveGame.value?.pending_human_action?.action_type,
      state.liveGame.value?.pending_human_action?.player_id
    ], ([waiting]) => {
      if (!state.isWatch.value && !state.isReplayMode.value && waiting === 'speech' && hasPendingHumanAction()) startSpeechTimer()
      else clearSpeechTimer()
    }, { immediate: true })

    onMounted(() => {
      void refreshHealth()
      scheduleMountedRestore()
    })

    onBeforeUnmount(() => {
      stopWatch()
      clearMountedRestoreTimer()
      clearRoleAssignmentTimers()
      clearSpeechTimer()
      noticeAutoDismiss.dispose()
    })
  }

  return {
    API, apiBase, apiFetch, setHistoryApi, setSceneApi,
    refreshHealth, request, startMode, resetGame, exitGame,
    stepGame, startWatch, startFromJudgeBoard, stopWatch, toggleWatch,
    clearSpeechTimer, startSpeechTimer, submitSpeech, submitVote,
    submitAction, submitWhiteWolfBurst, chooseScenePlayer,
    loadCurrentGame, loadGameById, restoreStoredGame, fetchPendingHumanAction, applyLiveLog, applyLiveDecision
  }
}

export { API, createGameApi, useGameActions }
