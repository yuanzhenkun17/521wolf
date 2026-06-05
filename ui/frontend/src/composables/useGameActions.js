import { onBeforeUnmount, onMounted, watch } from 'vue'
import { API, createGameApi } from './gameApi.js'
import {
  canonicalActionType,
  canonicalChoice,
  isSpeechAction,
  normalizeGameSnapshot
} from './gameSnapshot.js'

function useGameActions(state, options = {}) {
  const apiClient = options.apiFetch ? { apiFetch: options.apiFetch, apiBase: options.apiBase || API } : createGameApi(options.apiBase || API)
  const { apiFetch, apiBase } = apiClient
  let historyApi = options.historyApi || {}
  let sceneApi = options.sceneApi || {}
  let timer = null
  let speechTimer = null
  let eventSource = null
  let lastPendingKey = ''
  let lastStartOptions = {}

  function setHistoryApi(api = {}) { historyApi = api || {} }

  function setSceneApi(api = {}) { sceneApi = api || {} }

  function resetLiveState() {
    state.isReplayMode.value = false
    state.lastLiveGame.value = null
    state.visualSeatSalt.value = Math.random().toString(36).slice(2)
    state.judgeBoardStarted.value = false
    state.judgeBoardStarting.value = false
    state.roleAssignmentComplete.value = false
    state.roleAssignmentCompleteNotice.value = false
    state.actionTarget.value = null
    state.actionChoice.value = ''
    state.witchChoice.value = 'skip'
    state.burstArmed.value = false
    lastPendingKey = ''
  }

  function pendingControlKey(game) {
    if (!game) return ''
    const pending = game.pending_human_action || {}
    const action = pending.action_type || game.pending_action?.type || game.waiting_for || ''
    const candidates = game.pending_action?.candidate_ids || pending.candidates || []
    return `${action}:${game.day}:${game.phase}:${pending.retry_count ?? ''}:${candidates.join(',')}`
  }

  function syncPendingControls(game) {
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

  function setGameSnapshot(raw, normalizeOptions = {}) {
    if (!raw) return null
    const normalized = normalizeGameSnapshot(raw, normalizeOptions)
    state.game.value = normalized
    syncPendingControls(normalized)
    return normalized
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

  function startGameBody(mode, options = {}) {
    const body = {
      max_days: positiveInt(options.max_days, 20, 1, 100),
      enable_sheriff: options.enable_sheriff !== false,
      player_count: positiveInt(options.player_count ?? state.playerCount.value, 12, 12, 12),
      human_player_id: mode === 'play' ? 1 : null
    }
    const seed = optionalInt(options.seed)
    const skillDir = String(options.skill_dir || '').trim()
    const roleVersions = compactRoleVersions(options.role_versions)
    if (seed !== undefined) body.seed = seed
    if (skillDir) body.skill_dir = skillDir
    if (roleVersions) body.role_versions = roleVersions
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

  async function loadCurrentGame({ silent = false, advance = false, mode = state.game.value?.mode } = {}) {
    const gameId = state.game.value?.game_id
    if (!gameId) return null
    if (!silent) state.loading.value = true
    state.error.value = ''
    try {
      const raw = await apiFetch(`/games/${encodeURIComponent(gameId)}${advance ? '?advance=1' : ''}`)
      const pending = raw?.human_player_id ? await fetchPendingHumanAction(gameId) : null
      return setGameSnapshot(raw, { mode, pending })
    } catch (err) {
      state.error.value = err?.message || '对局状态刷新失败。'
      return null
    } finally {
      if (!silent) state.loading.value = false
    }
  }

  async function refreshHealth() {
    try {
      const health = await apiFetch('/health')
      state.backendMode.value = health.mode || 'mock'
      state.externalStatus.value = health.external || null
    } catch {
      state.backendMode.value = 'offline'
      state.externalStatus.value = { supports_human: false, supports_sse: false }
    }
  }

  async function request(path, options = {}, normalizeOptions = {}) {
    state.loading.value = true
    state.error.value = ''
    try {
      const raw = await apiFetch(path, options)
      const pending = raw?.human_player_id ? await fetchPendingHumanAction(raw.game_id) : null
      const game = setGameSnapshot(raw, { ...normalizeOptions, pending })
      const isNavigationRequest = path === '/games'
      if (isNavigationRequest) state.currentView.value = 'match'
      historyApi.refreshHistoryList?.({ silent: true })
      return game
    } catch (err) {
      state.error.value = err?.message || '后端未连接或接口异常，请确认 FastAPI 服务正在运行。'
      stopWatch()
      return null
    } finally {
      state.loading.value = false
    }
  }

  async function startMode(payload) {
    const { mode, options: payloadOptions, hasOptions } = parseStartPayload(payload)
    const startOptions = hasOptions ? payloadOptions : lastStartOptions
    if (hasOptions) lastStartOptions = { ...payloadOptions }
    stopWatch()
    if (state.backendMode.value === 'offline') {
      state.error.value = '后端未连接，请先启动 FastAPI 服务。'
      return null
    }
    if (mode === 'play' && state.externalStatus.value?.supports_human === false) {
      state.error.value = '当前后端暂不支持人类加入，请使用观战模式。'
      return null
    }
    resetLiveState()
    const game = await request('/games', {
      method: 'POST',
      body: JSON.stringify(startGameBody(mode, startOptions))
    }, { mode })
    await refreshHealth()
    return game
  }

  async function resetGame() {
    stopWatch()
    const previousGameId = state.game.value?.game_id
    const mode = state.isWatch.value ? 'watch' : 'play'
    if (previousGameId) {
      await apiFetch(`/games/${encodeURIComponent(previousGameId)}/stop`, { method: 'POST' }).catch(() => null)
    }
    resetLiveState()
    return startMode(mode)
  }

  function stepGame() {
    if (state.isReplayMode.value) return Promise.resolve()
    return loadCurrentGame({ advance: state.backendMode.value === 'mock' })
  }

  function applyPendingHumanAction(pending) {
    if (!state.game.value) return
    setGameSnapshot(state.game.value, {
      mode: state.game.value.mode,
      pending
    })
  }

  function startWatch() {
    if (state.isReplayMode.value || !state.isWatch.value || state.watchRunning.value) return
    state.judgeBoardStarted.value = true
    state.roleAssignmentComplete.value = true
    state.watchRunning.value = true
    const gameId = state.game.value?.game_id

    if (state.backendMode.value !== 'mock' && gameId && typeof EventSource !== 'undefined') {
      if (timer) {
        window.clearInterval(timer)
        timer = null
      }
      const refreshExternalGame = () => {
        if (state.watchRunning.value && !state.loading.value && !state.game.value?.winner) {
          loadCurrentGame({ silent: true })
        }
      }
      refreshExternalGame()
      eventSource?.close?.()
      eventSource = new EventSource(`${apiBase}/games/${encodeURIComponent(gameId)}/events`)
      eventSource.addEventListener('log', refreshExternalGame)
      eventSource.addEventListener('decision_needed', (event) => {
        try {
          applyPendingHumanAction(JSON.parse(event.data))
        } catch {
          refreshExternalGame()
        }
      })
      eventSource.addEventListener('done', () => {
        loadCurrentGame({ silent: true }).finally(() => stopWatch())
      })
      eventSource.addEventListener('error', () => {
        eventSource?.close?.()
        eventSource = null
      })
      timer = window.setInterval(refreshExternalGame, 2200)
      return
    }

    stepGame()
    timer = window.setInterval(() => {
      if (!state.loading.value && !state.game.value?.winner) stepGame()
    }, 1500)
  }

  function startFromJudgeBoard() {
    if (state.judgeBoardStarting.value || state.watchRunning.value) return
    state.judgeBoardStarting.value = true
    state.judgeBoardStarted.value = true
    state.roleAssignmentComplete.value = false
    state.roleAssignmentCompleteNotice.value = false
    const finishAssignment = () => {
      state.roleAssignmentComplete.value = true
      state.roleAssignmentCompleteNotice.value = true
      state.judgeBoardStarting.value = false
      sceneApi.scheduleSyncCouncilScene?.()
      window.setTimeout(() => {
        state.roleAssignmentCompleteNotice.value = false
      }, 1400)
      if (state.isWatch.value) startWatch()
      else {
        stepGame()
        startPlayerPolling()
      }
    }
    Promise.resolve(sceneApi.waitForCouncilModels?.())
      .then(finishAssignment)
      .catch(finishAssignment)
      .finally(() => {
        state.judgeBoardStarting.value = false
      })
  }

  function stopWatch() {
    state.watchRunning.value = false
    eventSource?.close?.()
    eventSource = null
    if (timer) {
      window.clearInterval(timer)
      timer = null
    }
  }

  function startPlayerPolling() {
    if (state.isWatch.value || timer || typeof window === 'undefined') return
    timer = window.setInterval(() => {
      if (
        state.game.value &&
        !state.loading.value &&
        !state.game.value.winner &&
        state.game.value.waiting_for === 'none'
      ) {
        loadCurrentGame({ silent: true })
      }
    }, 1500)
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
    const gameId = state.game.value?.game_id
    if (state.isReplayMode.value || state.isWatch.value || !gameId || !actionType) {
      return Promise.resolve()
    }

    state.loading.value = true
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
      if (raw) setGameSnapshot(raw, { mode: state.game.value?.mode })
      else await loadCurrentGame({ silent: true })
      startPlayerPolling()
      historyApi.refreshHistoryList?.({ silent: true })
    } catch (err) {
      state.error.value = err?.message || '提交行动失败。'
    } finally {
      state.loading.value = false
    }
  }

  function submitSpeech(textOverride = null) {
    if (state.isReplayMode.value || state.isWatch.value) return Promise.resolve()
    clearSpeechTimer()
    const pendingActionType = state.game.value?.pending_human_action?.action_type
    const actionType = isSpeechAction(pendingActionType) ? pendingActionType : 'speak'
    return submitHumanAction(actionType, {
      text: textOverride == null ? state.speech.value : textOverride
    })
  }

  function submitVote() {
    if (state.isReplayMode.value || state.isWatch.value) return Promise.resolve()
    const actionType = state.pendingActionType.value || state.game.value?.pending_human_action?.action_type || 'exile_vote'
    return submitHumanAction(actionType, {
      target: Number(state.voteTarget.value)
    })
  }

  function submitAction(
    action = state.pendingActionType.value,
    targetId = state.actionTarget.value,
    choice = state.actionChoice.value || state.witchChoice.value
  ) {
    if (state.isReplayMode.value || state.isWatch.value) return Promise.resolve()
    const actionType = canonicalActionType(action || state.game.value?.pending_human_action?.action_type)
    if (!actionType) return Promise.resolve()
    const normalizedChoice = canonicalChoice(actionType, choice)
    return submitHumanAction(actionType, {
      target: targetId ? Number(targetId) : null,
      choice: normalizedChoice
    }).then(() => {
      state.actionTarget.value = null
      state.actionChoice.value = ''
      state.witchChoice.value = 'skip'
    })
  }

  function submitWhiteWolfBurst(targetId = state.actionTarget.value) {
    if (!targetId) return Promise.resolve()
    return submitAction('white_wolf_burst', targetId, 'burst').finally(() => {
      state.burstArmed.value = false
    })
  }

  function chooseScenePlayer(playerId) {
    const id = Number(playerId)
    if (!id) return
    if (state.burstArmed.value && state.whiteWolfTargets.value.some((player) => player.id === id)) {
      state.actionTarget.value = id
      submitWhiteWolfBurst(id)
      return
    }
    if (state.pendingActionType.value) {
      if (state.actionCandidates.value.some((player) => player.id === id)) {
        state.actionTarget.value = id
        if (state.pendingChoiceOptions.value.length && !state.actionChoice.value) return
        if (
          state.pendingActionType.value !== 'witch_act' ||
          ['poison', 'antidote'].includes(state.witchChoice.value)
        ) {
          submitAction(state.pendingActionType.value, id, state.actionChoice.value || state.witchChoice.value)
        }
      }
      return
    }
    if (
      state.game.value?.waiting_for === 'vote' &&
      state.canVotePlayers.value.some((player) => player.id === id)
    ) {
      state.voteTarget.value = id
      submitVote()
    }
  }

  if (options.installLifecycle !== false) {
    watch(() => state.game.value?.waiting_for, (waiting) => {
      if (!state.isWatch.value && !state.isReplayMode.value && waiting === 'speech') startSpeechTimer()
      else clearSpeechTimer()
    }, { immediate: true })

    onMounted(refreshHealth)

    onBeforeUnmount(() => {
      stopWatch()
      clearSpeechTimer()
    })
  }

  return {
    API, apiBase, apiFetch, setHistoryApi, setSceneApi,
    refreshHealth, request, startMode, resetGame,
    stepGame, startWatch, startFromJudgeBoard, stopWatch, toggleWatch,
    clearSpeechTimer, startSpeechTimer, submitSpeech, submitVote,
    submitAction, submitWhiteWolfBurst, chooseScenePlayer,
    loadCurrentGame, fetchPendingHumanAction
  }
}

export { API, createGameApi, useGameActions }
