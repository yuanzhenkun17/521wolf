import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, ref } from 'vue'
import { useGameState } from '../src/composables/useGameState.js'
import { useGameActions } from '../src/composables/useGameActions.js'
import { useGameHistory } from '../src/composables/useGameHistory.js'
import { useGameAudio } from '../src/composables/useGameAudio.js'
import { useEvolutionWorkbench } from '../src/composables/useEvolutionWorkbench.js'
import { useEvaluationWorkbench } from '../src/composables/useEvaluationWorkbench.js'
import { normalizeGameSnapshot } from '../src/composables/gameSnapshot.js'
import { buildSceneEffects } from '../src/composables/sceneEffects.js'
import {
  ACTIVE_GAME_STORAGE_KEY,
  activeSessionFromGame,
  clearStoredGameSession,
  emptyActiveSession,
  isReturnableGame,
  isTerminalGame,
  readStoredGameSession,
  writeStoredGameSession
} from '../src/composables/gameSession.js'

function createMemoryStorage() {
  const values = new Map()
  return {
    getItem: (key) => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    clear: () => values.clear()
  }
}

function createDeferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function createTimerHarness() {
  const timeouts = new Map()
  const intervals = new Map()
  let nextId = 1
  return {
    setTimeout(callback) {
      const id = nextId++
      timeouts.set(id, callback)
      return id
    },
    clearTimeout(id) {
      timeouts.delete(id)
    },
    setInterval(callback) {
      const id = nextId++
      intervals.set(id, callback)
      return id
    },
    clearInterval(id) {
      intervals.delete(id)
    },
    runNextTimeout() {
      const [id, callback] = timeouts.entries().next().value || []
      if (!id) return false
      timeouts.delete(id)
      callback()
      return true
    },
    timeoutCount() {
      return timeouts.size
    },
    intervalCount() {
      return intervals.size
    }
  }
}

function withWindow(callback, { hash = '', eventSource = undefined } = {}) {
  const originalWindow = globalThis.window
  const originalEventSource = globalThis.EventSource
  const timers = createTimerHarness()
  const localStorage = createMemoryStorage()
  globalThis.window = {
    location: { hash },
    localStorage,
    setTimeout: timers.setTimeout,
    clearTimeout: timers.clearTimeout,
    setInterval: timers.setInterval,
    clearInterval: timers.clearInterval,
    addEventListener() {},
    removeEventListener() {}
  }
  if (eventSource === undefined) delete globalThis.EventSource
  else globalThis.EventSource = eventSource
  return Promise.resolve()
    .then(() => callback({ timers, localStorage }))
    .finally(() => {
      if (originalWindow === undefined) delete globalThis.window
      else globalThis.window = originalWindow
      if (originalEventSource === undefined) delete globalThis.EventSource
      else globalThis.EventSource = originalEventSource
    })
}

function game(id, extra = {}) {
  return {
    game_id: id,
    mode: 'watch',
    status: 'running',
    day: 1,
    phase: 'night',
    player_count: 2,
    players: [
      { id: 1, seat: 1, name: '1号', role_hint: '村民', alive: true },
      { id: 2, seat: 2, name: '2号', role_hint: '狼人', alive: true }
    ],
    logs: [],
    decisions: [],
    waiting_for: 'none',
    ...extra
  }
}

test('game session helpers only return active sessions for non-terminal games', () => {
  const running = game('running')
  const completed = game('completed', { winner: 'villagers', status: 'completed' })

  assert.equal(isTerminalGame(running), false)
  assert.equal(isReturnableGame(running), true)
  assert.equal(isTerminalGame(completed), true)
  assert.equal(isReturnableGame(completed), false)
  assert.deepEqual(activeSessionFromGame(running, { sseConnected: true }), {
    gameId: 'running',
    mode: 'watch',
    running: true,
    sseConnected: true
  })
  assert.deepEqual(activeSessionFromGame(completed, { sseConnected: true }), {
    gameId: 'completed',
    mode: 'watch',
    running: false,
    sseConnected: false
  })
  assert.deepEqual(emptyActiveSession(), { gameId: null, mode: '', running: false, sseConnected: false })
})

test('stored game sessions persist only returnable games', () => withWindow(() => {
  const running = game('running')
  const completed = game('completed', { winner: 'villagers', status: 'completed' })

  assert.equal(writeStoredGameSession(running)?.gameId, 'running')
  assert.deepEqual(readStoredGameSession(), {
    gameId: 'running',
    mode: 'watch',
    updatedAt: readStoredGameSession().updatedAt
  })

  writeStoredGameSession(completed)
  assert.equal(readStoredGameSession(), null)
  assert.equal(window.localStorage.getItem(ACTIVE_GAME_STORAGE_KEY), null)

  writeStoredGameSession(running)
  clearStoredGameSession()
  assert.equal(readStoredGameSession(), null)
}))

test('display game switches between live and replay without overwriting live game', () => {
  const state = useGameState()
  const live = game('live')
  const replay = game('replay')

  state.liveGame.value = live
  assert.equal(state.game.value.game_id, live.game_id)

  state.isReplayMode.value = true
  state.replayGame.value = replay
  assert.equal(state.game.value.game_id, replay.game_id)

  state.game.value = game('replay-updated')
  assert.equal(state.liveGame.value.game_id, live.game_id)
  assert.equal(state.replayGame.value.game_id, 'replay-updated')

  state.isReplayMode.value = false
  assert.equal(state.game.value.game_id, live.game_id)
})

test('history replay writes replayGame and restores the live game on exit', () => withWindow(() => {
  const state = useGameState()
  const live = game('live-game')
  state.liveGame.value = live
  state.selectedHistoryGame.value = game('history-game', {
    winner: 'villagers',
    logs: [
      { type: 'setup', day: 1, phase: 'setup', message: 'start', speaker: '法官' },
      { type: 'speech', day: 1, phase: 'speech', actor_id: 1, message: 'hello', speaker: '1号' }
    ]
  })
  const history = useGameHistory(state, { installLifecycle: false, apiFetch: async () => ({}) })

  history.enterReplayAt(1)
  assert.equal(state.liveGame.value.game_id, live.game_id)
  assert.equal(state.replayGame.value.game_id, 'history-game')
  assert.equal(state.game.value, state.replayGame.value)

  history.exitReplayMode()
  assert.equal(state.replayGame.value, null)
  assert.equal(state.liveGame.value.game_id, live.game_id)
  assert.equal(state.game.value.game_id, live.game_id)
}))

test('exitGame stops the live game even when replay mode is active', () => withWindow(async () => {
  const state = useGameState()
  const stoppedPaths = []
  state.liveGame.value = game('live-game')
  state.isReplayMode.value = true
  state.replayGame.value = game('history-game')

  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path) => {
      stoppedPaths.push(path)
      return {}
    }
  })

  await actions.exitGame()

  assert.deepEqual(stoppedPaths, ['/games/live-game/stop'])
  assert.equal(state.liveGame.value, null)
  assert.equal(state.replayGame.value, null)
  assert.equal(state.isReplayMode.value, false)
  assert.equal(state.currentView.value, 'lobby')
}))

test('restoreStoredGame reloads a returnable game and skips the intro', () => withWindow(async () => {
  const state = useGameState()
  const restored = game('stored-game')
  writeStoredGameSession(restored)
  const paths = []
  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path) => {
      paths.push(path)
      if (path === '/games/stored-game') return restored
      throw new Error(`unexpected ${path}`)
    }
  })

  await actions.restoreStoredGame({ start: false, silent: false })

  assert.deepEqual(paths, ['/games/stored-game'])
  assert.equal(state.liveGame.value.game_id, 'stored-game')
  assert.equal(state.roleAssignmentComplete.value, true)
  assert.equal(state.judgeBoardStarted.value, true)
  assert.equal(state.skipIntroGameId.value, 'stored-game')
  assert.equal(readStoredGameSession().gameId, 'stored-game')
}))

test('restoreStoredGame routes stale match links back to lobby', () => withWindow(async () => {
  const state = useGameState()
  writeStoredGameSession(game('stored-game'))
  window.location.hash = '#match'
  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async () => game('stored-game', { winner: 'villagers', status: 'completed' })
  })

  await actions.restoreStoredGame({ start: false, silent: false })

  assert.equal(state.liveGame.value.game_id, 'stored-game')
  assert.equal(isReturnableGame(state.liveGame.value), false)
  assert.equal(state.currentView.value, 'lobby')
  assert.equal(window.location.hash, '')
  assert.equal(readStoredGameSession(), null)
}))

test('pending human vote actions normalize aliases and candidate objects', () => {
  const snapshot = normalizeGameSnapshot(game('pending-vote', {
    mode: 'play',
    human_player_id: 1,
    players: [
      { id: 1, seat: 1, name: '1号', role_hint: '村民', alive: true },
      { id: 2, seat: 2, name: '2号', role_hint: '狼人', alive: true },
      { id: 3, seat: 3, name: '3号', role_hint: '女巫', alive: true }
    ],
    pending_human_action: {
      action_type: 'vote',
      player_id: 1,
      candidates: [{ id: 2 }, { player_id: 3 }]
    }
  }), { mode: 'play' })

  assert.equal(snapshot.waiting_for, 'vote')
  assert.equal(snapshot.pending_action.type, 'exile_vote')
  assert.deepEqual(snapshot.pending_action.candidate_ids, [2, 3])
  assert.equal(snapshot.pending_action.target_required, false)
  assert.equal(snapshot.pending_action.allow_no_target, true)
  assert.equal(snapshot.pending_human_action.action_type, 'exile_vote')
  assert.deepEqual(snapshot.pending_human_action.candidate_ids, [2, 3])
  assert.equal(snapshot.pending_human_action.target_required, false)
  assert.equal(snapshot.pending_human_action.allow_no_target, true)
})

test('pending target contract treats votes and hunter as optional target actions', () => {
  const players = [
    { id: 1, seat: 1, name: '1号', role_hint: '猎人', alive: true },
    { id: 2, seat: 2, name: '2号', role_hint: '狼人', alive: true },
    { id: 3, seat: 3, name: '3号', role_hint: '女巫', alive: true }
  ]
  const state = useGameState()

  state.liveGame.value = normalizeGameSnapshot(game('pending-hunter', {
    mode: 'play',
    human_player_id: 1,
    players,
    pending_human_action: {
      action_type: 'hunter_shoot',
      player_id: 1,
      candidate_ids: [2, 3]
    }
  }), { mode: 'play' })

  assert.equal(state.pendingActionType.value, 'hunter_shoot')
  assert.equal(state.pendingAction.value.target_required, false)
  assert.equal(state.pendingAction.value.allow_no_target, true)
  assert.equal(state.needsTarget.value, false)
  assert.deepEqual(state.actionCandidates.value.map((player) => player.id), [2, 3])

  state.liveGame.value = normalizeGameSnapshot(game('pending-guard', {
    mode: 'play',
    human_player_id: 1,
    players,
    pending_human_action: {
      action_type: 'guard_protect',
      player_id: 1,
      candidate_ids: [2, 3]
    }
  }), { mode: 'play' })

  assert.equal(state.pendingActionType.value, 'guard_protect')
  assert.equal(state.pendingAction.value.target_required, true)
  assert.equal(state.pendingAction.value.allow_no_target, false)
  assert.equal(state.needsTarget.value, true)
})

test('vote action can submit abstention with null target', () => withWindow(async () => {
  const state = useGameState()
  const requests = []
  const initial = normalizeGameSnapshot(game('vote-pending', {
    mode: 'play',
    human_player_id: 1,
    phase: 'vote',
    players: [
      { id: 1, seat: 1, name: '1号', role_hint: '村民', alive: true },
      { id: 2, seat: 2, name: '2号', role_hint: '狼人', alive: true },
      { id: 3, seat: 3, name: '3号', role_hint: '女巫', alive: true }
    ],
    pending_human_action: {
      action_type: 'exile_vote',
      player_id: 1,
      candidate_ids: [2, 3]
    }
  }), { mode: 'play' })
  state.liveGame.value = initial
  state.actionTarget.value = null
  state.voteTarget.value = 2

  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path, options = {}) => {
      requests.push({
        path,
        body: options.body ? JSON.parse(options.body) : null
      })
      if (path === '/games/vote-pending/action') {
        return game('vote-pending', {
          mode: 'play',
          human_player_id: 1,
          phase: 'vote',
          players: initial.players,
          pending_human_action: null,
          waiting_for: 'none'
        })
      }
      throw new Error(`unexpected ${path}`)
    }
  })

  assert.equal(state.needsTarget.value, false)
  await actions.submitVote()

  assert.deepEqual(requests.slice(0, 1), [{
    path: '/games/vote-pending/action',
    body: {
      action_type: 'exile_vote',
      target: null,
      choice: null,
      text: ''
    }
  }])
}))

test('loadCurrentGame uses pending_human_action from snapshot without extra pending fetch', () => withWindow(async () => {
  const state = useGameState()
  const paths = []
  state.liveGame.value = game('pending-from-snapshot', {
    mode: 'play',
    human_player_id: 1
  })
  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path) => {
      paths.push(path)
      if (path === '/games/pending-from-snapshot') {
        return game('pending-from-snapshot', {
          mode: 'play',
          human_player_id: 1,
          pending_human_action: {
            action_type: 'vote',
            player_id: 1,
            candidates: [{ id: 2 }]
          }
        })
      }
      throw new Error(`unexpected ${path}`)
    }
  })

  await actions.loadCurrentGame()

  assert.deepEqual(paths, ['/games/pending-from-snapshot'])
  assert.equal(state.liveGame.value.waiting_for, 'vote')
  assert.equal(state.pendingActionType.value, 'exile_vote')
}))

test('loadCurrentGame ignores stale snapshots after a newer game is loaded', () => withWindow(async () => {
  const state = useGameState()
  const slowSnapshot = createDeferred()
  state.liveGame.value = game('slow-game')
  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path) => {
      if (path === '/games/slow-game') return slowSnapshot.promise
      if (path === '/games/new-game') return game('new-game', { day: 2 })
      throw new Error(`unexpected ${path}`)
    }
  })

  const staleRefresh = actions.loadCurrentGame()
  await Promise.resolve()
  await actions.loadGameById('new-game')
  assert.equal(state.liveGame.value.game_id, 'new-game')

  slowSnapshot.resolve(game('slow-game', { day: 9 }))
  await staleRefresh

  assert.equal(state.liveGame.value.game_id, 'new-game')
  assert.equal(state.liveGame.value.day, 2)
  assert.equal(state.loading.value, false)
}))

test('witch skip submits none and clears pending human action', () => withWindow(async () => {
  const state = useGameState()
  const requests = []
  const initial = normalizeGameSnapshot(game('witch-pending', {
    mode: 'play',
    human_player_id: 1,
    phase: 'night',
    players: [
      { id: 1, seat: 1, name: '1号', role_hint: '女巫', alive: true },
      { id: 2, seat: 2, name: '2号', role_hint: '狼人', alive: true },
      { id: 3, seat: 3, name: '3号', role_hint: '村民', alive: true }
    ],
    pending_human_action: {
      action_type: 'witch_act',
      player_id: 1,
      candidate_ids: [],
      metadata: {
        antidote_available: false,
        poison_available: false
      }
    }
  }), { mode: 'play' })
  state.liveGame.value = initial

  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path, options = {}) => {
      requests.push({
        path,
        body: options.body ? JSON.parse(options.body) : null
      })
      if (path === '/games/witch-pending/action') {
        return game('witch-pending', {
          mode: 'play',
          human_player_id: 1,
          phase: 'night',
          players: initial.players,
          pending_human_action: null,
          waiting_for: 'none'
        })
      }
      throw new Error(`unexpected ${path}`)
    }
  })

  await actions.submitAction('witch_act', null, 'skip')

  assert.deepEqual(requests.slice(0, 1), [{
    path: '/games/witch-pending/action',
    body: {
      action_type: 'witch_act',
      target: null,
      choice: 'none',
      text: ''
    }
  }])
  assert.equal(state.liveGame.value.pending_human_action, null)
  assert.equal(state.liveGame.value.waiting_for, 'none')
}))

test('targeted non-witch actions do not inherit witch skip choice', () => withWindow(async () => {
  const state = useGameState()
  const requests = []
  const initial = normalizeGameSnapshot(game('guard-pending', {
    mode: 'play',
    human_player_id: 1,
    phase: 'night',
    players: [
      { id: 1, seat: 1, name: '1号', role_hint: '守卫', alive: true },
      { id: 2, seat: 2, name: '2号', role_hint: '村民', alive: true },
      { id: 3, seat: 3, name: '3号', role_hint: '狼人', alive: true }
    ],
    pending_human_action: {
      action_type: 'guard_protect',
      player_id: 1,
      candidate_ids: [2, 3],
      metadata: {}
    }
  }), { mode: 'play' })
  state.liveGame.value = initial
  state.witchChoice.value = 'skip'

  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path, options = {}) => {
      requests.push({
        path,
        body: options.body ? JSON.parse(options.body) : null
      })
      if (path === '/games/guard-pending/action') {
        return game('guard-pending', {
          mode: 'play',
          human_player_id: 1,
          phase: 'night',
          players: initial.players,
          pending_human_action: null,
          waiting_for: 'none'
        })
      }
      throw new Error(`unexpected ${path}`)
    }
  })

  await actions.submitAction('guard_protect', 2)

  assert.deepEqual(requests.slice(0, 1), [{
    path: '/games/guard-pending/action',
    body: {
      action_type: 'guard_protect',
      target: 2,
      choice: null,
      text: ''
    }
  }])
  assert.equal(state.liveGame.value.pending_human_action, null)
  assert.equal(state.liveGame.value.waiting_for, 'none')
}))

test('white wolf burst is only available for backend white wolf pending action', () => withWindow(async () => {
  const players = [
    { id: 1, seat: 1, name: '1号', role_hint: '白狼王', alive: true },
    { id: 2, seat: 2, name: '2号', role_hint: '村民', alive: true },
    { id: 3, seat: 3, name: '3号', role_hint: '预言家', alive: true }
  ]
  const state = useGameState()
  const requests = []
  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path, options = {}) => {
      requests.push({ path, body: options.body ? JSON.parse(options.body) : null })
      return game('white-wolf-pending', {
        mode: 'play',
        human_player_id: 1,
        players,
        waiting_for: 'none',
        pending_human_action: null
      })
    }
  })

  state.liveGame.value = normalizeGameSnapshot(game('white-wolf-idle', {
    mode: 'play',
    human_player_id: 1,
    players,
    pending_human_action: null
  }), { mode: 'play' })
  state.burstArmed.value = true

  assert.equal(state.isHumanWhiteWolf.value, true)
  assert.equal(state.canWhiteWolfBurst.value, false)
  assert.deepEqual(state.whiteWolfTargets.value, [])
  actions.chooseScenePlayer(2)
  assert.equal(state.actionTarget.value, null)
  await actions.submitWhiteWolfBurst(2)
  assert.deepEqual(requests, [])

  state.liveGame.value = normalizeGameSnapshot(game('white-wolf-pending', {
    mode: 'play',
    human_player_id: 1,
    players,
    pending_human_action: {
      action_type: 'white_wolf_explode',
      player_id: 1,
      candidate_ids: [2],
      metadata: {}
    }
  }), { mode: 'play' })
  state.burstArmed.value = true

  assert.equal(state.pendingActionType.value, 'white_wolf_explode')
  assert.equal(state.canWhiteWolfBurst.value, true)
  assert.deepEqual(state.whiteWolfTargets.value.map((player) => player.id), [2])
  actions.chooseScenePlayer(3)
  assert.equal(state.actionTarget.value, null)
  actions.chooseScenePlayer(2)
  assert.equal(state.actionTarget.value, 2)
  await actions.submitWhiteWolfBurst()

  assert.deepEqual(requests.slice(0, 1), [{
    path: '/games/white-wolf-pending/action',
    body: {
      action_type: 'white_wolf_explode',
      target: 2,
      choice: 'explode',
      text: ''
    }
  }])
}))

test('startMode in play mode starts the match without skipping the model intro', () => withWindow(async ({ timers }) => {
  const state = useGameState()
  const paths = []
  const playGame = game('play-game', {
    mode: 'play',
    human_player_id: 1,
    pending_human_action: null,
    player_count: 12,
    players: Array.from({ length: 12 }, (_, index) => ({
      id: index + 1,
      seat: index + 1,
      name: `${index + 1}号`,
      role_hint: index === 0 ? '村民' : (index === 1 ? '狼人' : '预言家'),
      alive: true
    }))
  })
  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path) => {
      paths.push(path)
      if (path === '/games') return playGame
      if (path === '/games/play-game?advance=1') return playGame
      if (path === '/health') return { mode: 'mock', external: { supports_human: true } }
      throw new Error(`unexpected ${path}`)
    }
  })

  await actions.startMode({ mode: 'play' })
  await Promise.resolve()

  assert.deepEqual(paths, ['/games', '/games/play-game?advance=1', '/health'])
  assert.equal(state.liveGame.value.game_id, 'play-game')
  assert.equal(state.isWatch.value, false)
  assert.equal(state.judgeBoardStarted.value, true)
  assert.equal(state.roleAssignmentComplete.value, true)
  assert.equal(state.skipIntroGameId.value, null)
  assert.equal(state.playerIdentityList.value.find((player) => player.id === 1).role_hint, '村民')
  assert.equal(state.playerIdentityList.value.find((player) => player.id === 2).role_hint, '未知')
  assert.equal(timers.intervalCount(), 1)
}))

test('startMode in watch mode starts god view without skipping the model intro', () => withWindow(async ({ timers }) => {
  const state = useGameState()
  const paths = []
  const watchGame = game('watch-game', {
    mode: 'watch',
    human_player_id: null,
    pending_human_action: null,
    player_count: 12,
    players: Array.from({ length: 12 }, (_, index) => ({
      id: index + 1,
      seat: index + 1,
      name: `${index + 1}号`,
      role_hint: index === 0 ? '村民' : (index === 1 ? '狼人' : '预言家'),
      alive: true
    }))
  })
  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path) => {
      paths.push(path)
      if (path === '/games') return watchGame
      if (path === '/games/watch-game?advance=1') return watchGame
      if (path === '/health') return { mode: 'mock', external: { supports_human: true } }
      throw new Error(`unexpected ${path}`)
    }
  })

  await actions.startMode({ mode: 'watch' })
  await Promise.resolve()

  assert.deepEqual(paths, ['/games', '/games/watch-game?advance=1', '/health'])
  assert.equal(state.liveGame.value.game_id, 'watch-game')
  assert.equal(state.isWatch.value, true)
  assert.equal(state.watchRunning.value, true)
  assert.equal(state.judgeBoardStarted.value, true)
  assert.equal(state.roleAssignmentComplete.value, true)
  assert.equal(state.skipIntroGameId.value, null)
  assert.equal(state.playerIdentityList.value.find((player) => player.id === 2).role_hint, '狼人')
  assert.equal(state.playerIdentityList.value.find((player) => player.id === 2).role_visible, true)
  assert.equal(timers.intervalCount(), 1)
}))

test('startMode does not send enable_sheriff from the frontend start request', () => withWindow(async () => {
  const state = useGameState()
  let startBody = null
  const watchGame = game('watch-game', {
    mode: 'watch',
    human_player_id: null,
    player_count: 12,
    players: Array.from({ length: 12 }, (_, index) => ({
      id: index + 1,
      seat: index + 1,
      name: `${index + 1}号`,
      role_hint: '未知',
      alive: true
    }))
  })
  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path, options = {}) => {
      if (path === '/games') {
        startBody = JSON.parse(options.body)
        return watchGame
      }
      if (path === '/games/watch-game?advance=1') return watchGame
      if (path === '/health') return { mode: 'mock', external: { supports_human: true } }
      throw new Error(`unexpected ${path}`)
    }
  })

  await actions.startMode({ mode: 'watch', options: { max_days: 7, enable_sheriff: false } })

  assert.equal(startBody.max_days, 7)
  assert.equal(Object.hasOwn(startBody, 'enable_sheriff'), false)
}))

test('player mode hides other identities for villagers and reveals wolf teammates for wolves', () => {
  const state = useGameState()
  state.backendMode.value = 'api'
  state.liveGame.value = normalizeGameSnapshot(game('villager-view', {
    mode: 'play',
    human_player_id: 1,
    players: [
      { id: 1, seat: 1, name: '1号', role_hint: '村民', alive: true },
      { id: 2, seat: 2, name: '2号', role_hint: '狼人', alive: true },
      { id: 3, seat: 3, name: '3号', role_hint: '女巫', alive: true }
    ]
  }), { mode: 'play' })

  const villagerView = state.playerIdentityList.value
  assert.equal(villagerView.find((player) => player.id === 1).role_hint, '村民')
  assert.equal(villagerView.find((player) => player.id === 2).role_hint, '未知')
  assert.equal(villagerView.find((player) => player.id === 2).role_visible, false)
  assert.equal(villagerView.find((player) => player.id === 3).roleIcon, '/role-icons/未知.png')

  state.liveGame.value = normalizeGameSnapshot(game('wolf-view', {
    mode: 'play',
    human_player_id: 1,
    players: [
      { id: 1, seat: 1, name: '1号', role_hint: '白狼王', alive: true },
      { id: 2, seat: 2, name: '2号', role_hint: '狼人', alive: true },
      { id: 3, seat: 3, name: '3号', role_hint: '预言家', alive: true }
    ]
  }), { mode: 'play' })

  const wolfView = state.playerIdentityList.value
  assert.equal(wolfView.find((player) => player.id === 1).role_hint, '白狼王')
  assert.equal(wolfView.find((player) => player.id === 2).role_hint, '狼人')
  assert.equal(wolfView.find((player) => player.id === 2).role_visible, true)
  assert.equal(wolfView.find((player) => player.id === 3).role_hint, '未知')
  assert.equal(wolfView.find((player) => player.id === 3).role_visible, false)
})

test('player mode hides private night action logs from chat records', () => {
  const actionLogs = [
    { type: 'guard_protect', actor_id: 7, speaker: '7号', message: '守卫完成守护选择。', visibility: 'public' },
    { type: 'action', action_type: 'seer_check', actor_id: 3, speaker: '3号', message: '预言家查验1号为好人。', visibility: 'public' },
    { type: 'witch_act', actor_id: 4, speaker: '4号', message: '女巫完成用药选择。', visibility: 'public' },
    { type: 'speech', phase: 'speech', actor_id: 1, speaker: '1号', message: '我是好人', visibility: 'public' },
    { type: 'night_result', phase: 'night', speaker: '法官', message: '昨夜平安', visibility: 'public' }
  ]
  const players = [
    { id: 1, seat: 1, name: '1号', role_hint: '村民', alive: true },
    { id: 3, seat: 3, name: '3号', role_hint: '预言家', alive: true },
    { id: 4, seat: 4, name: '4号', role_hint: '女巫', alive: true },
    { id: 7, seat: 7, name: '7号', role_hint: '守卫', alive: true }
  ]
  const state = useGameState()
  state.liveGame.value = normalizeGameSnapshot(game('player-log-view', {
    mode: 'play',
    human_player_id: 1,
    phase: 'night',
    players,
    logs: actionLogs
  }), { mode: 'play' })

  const playerMessages = state.chatLogs.value.map((log) => log._message)
  assert.deepEqual(playerMessages, ['我是好人'])
  assert.deepEqual(state.matchRecordLogs.value.map((log) => log._message), ['我是好人'])
  assert.equal(state.publicLogs.value.some((log) => /守卫|预言家|女巫/.test(log.message)), false)
  assert.equal(state.judgeLogs.value.some((log) => log.message === '昨夜平安'), true)

  state.liveGame.value = normalizeGameSnapshot(game('watch-log-view', {
    mode: 'watch',
    phase: 'night',
    players,
    logs: actionLogs
  }), { mode: 'watch' })

  const watchMessages = state.chatLogs.value.map((log) => log._message)
  assert.equal(watchMessages.includes('守卫完成守护选择。'), true)
  assert.equal(watchMessages.includes('预言家查验1号为好人。'), true)
  assert.deepEqual(
    state.matchRecordLogs.value.map((log) => log._message),
    actionLogs.map((log) => log.message)
  )
})

test('watch match records localize backend action enum messages', () => {
  const state = useGameState()
  state.liveGame.value = normalizeGameSnapshot(game('watch-localized-action-log', {
    mode: 'watch',
    phase: 'sheriff',
    players: [
      { id: 11, seat: 11, name: '11号', role_hint: '村民', alive: true }
    ],
    logs: [
      {
        type: 'action_request',
        day: 1,
        phase: 'sheriff',
        actor_id: 11,
        speaker: '法官',
        message: '请求 11号执行 sheriff_vote',
        visibility: 'private'
      }
    ]
  }), { mode: 'watch' })

  const [record] = state.matchRecordLogs.value
  assert.equal(record._kindLabel, '行动请求')
  assert.equal(record._message, '请求11号执行警长投票')
  assert.equal(record._message.includes('sheriff_vote'), false)
})

test('live vote tally keeps voter labels and clears outside vote phases', () => {
  const state = useGameState()
  const players = Array.from({ length: 6 }, (_, index) => ({
    id: index + 1,
    seat: index + 1,
    name: `${index + 1}号`,
    role_hint: '村民',
    alive: true
  }))
  state.liveGame.value = normalizeGameSnapshot(game('live-vote-tally', {
    mode: 'watch',
    phase: 'vote',
    players,
    vote_tally: [
      { target_id: '3', count: 2, voter_ids: [1, 2] },
      { target_id: 4, count: 3 }
    ],
    decisions: [
      { action: 'vote', actor_id: 5, target_id: 3, day: 1, phase: 'vote' }
    ]
  }), { mode: 'watch' })

  assert.deepEqual(state.pageVoteTally.value, [
    { target_id: 3, targetName: '3号', voter_ids: [1, 2, 5], count: 3 },
    { target_id: 4, targetName: '4号', voter_ids: [], count: 3 }
  ])
  assert.deepEqual(state.sceneVoteTally.value.map((row) => ({
    target_id: row.target_id,
    count: row.count,
    voters: row.voters
  })), [
    { target_id: 3, count: 3, voters: ['1号', '2号', '5号'] },
    { target_id: 4, count: 3, voters: [] }
  ])

  state.liveGame.value = normalizeGameSnapshot({
    ...state.liveGame.value,
    phase: 'speech',
    waiting_for: 'none'
  }, { mode: 'watch' })

  assert.deepEqual(state.pageVoteTally.value, [])
  assert.deepEqual(state.sceneVoteTally.value, [])
})

test('live vote tally scopes decision replay to current vote action and day', () => {
  const state = useGameState()
  const players = Array.from({ length: 6 }, (_, index) => ({
    id: index + 1,
    seat: index + 1,
    name: `${index + 1}号`,
    role_hint: '村民',
    alive: true
  }))
  state.liveGame.value = normalizeGameSnapshot(game('live-vote-scope', {
    mode: 'watch',
    day: 2,
    phase: 'vote',
    waiting_for: 'vote',
    pending_action: { type: 'pk_vote' },
    players,
    vote_tally: [],
    decisions: [
      { action: 'exile_vote', actor_id: 1, target_id: 4, day: 1, phase: 'vote' },
      { action: 'exile_vote', actor_id: 2, target_id: 4, day: 1, phase: 'vote' },
      { action: 'exile_vote', actor_id: 3, target_id: 5, day: 2, phase: 'vote' },
      { action: 'pk_vote', actor_id: 6, target_id: 3, day: 2, phase: 'vote' }
    ]
  }), { mode: 'watch' })

  assert.deepEqual(state.pageVoteTally.value, [
    { target_id: 3, targetName: '3号', voter_ids: [6], count: 1 }
  ])
})

test('scene effects expose full night outcomes only for watch and replay views', () => {
  const players = [
    { id: 1, seat: 1, name: '1号', role_hint: '村民', alive: true },
    { id: 2, seat: 2, name: '2号', role_hint: '守卫', alive: true },
    { id: 3, seat: 3, name: '3号', role_hint: '女巫', alive: true },
    { id: 4, seat: 4, name: '4号', role_hint: '狼人', alive: true }
  ]
  const fullOutcomeGame = normalizeGameSnapshot(game('scene-outcomes', {
    mode: 'watch',
    players,
    logs: [
      {
        type: 'night_end',
        day: 1,
        phase: 'night',
        message: '昨夜平安',
        payload: { killed_target: 2, protected_target: 2, saved: false, deaths: [] }
      },
      {
        type: 'night_death_reveal',
        day: 2,
        phase: 'speech',
        message: '昨夜平安',
        payload: { killed_target: 3, protected_target: null, saved: true, deaths: [] }
      },
      {
        type: 'night_death_reveal',
        day: 3,
        phase: 'speech',
        message: '昨夜死亡玩家：4号',
        payload: { poisoned_target: 4, deaths: [4] }
      },
      { type: 'exile_vote_end', day: 3, phase: 'vote', target_id: 2, message: '2号出局' }
    ]
  }), { mode: 'watch' })

  const watchTypes = buildSceneEffects(fullOutcomeGame, { isWatch: true }).map((effect) => effect.type)
  assert.equal(watchTypes.includes('wolf_guarded'), true)
  assert.equal(watchTypes.includes('wolf_saved'), true)
  assert.equal(watchTypes.includes('poison_kill'), true)
  assert.equal(watchTypes.includes('exile_out'), true)
  assert.equal(watchTypes.filter((type) => type === 'night_death').length, 0)

  const playerGame = normalizeGameSnapshot(game('scene-player-outcomes', {
    mode: 'play',
    human_player_id: 1,
    players,
    logs: [
      {
        type: 'night_death_reveal',
        day: 1,
        phase: 'speech',
        visibility: 'public',
        message: '昨夜平安',
        payload: { killed_target: 2, protected_target: 2, saved: false, deaths: [] }
      },
      {
        type: 'night_death_reveal',
        day: 2,
        phase: 'speech',
        visibility: 'public',
        message: '昨夜死亡玩家：3号',
        payload: { killed_target: 3, protected_target: null, saved: false, deaths: [3] }
      }
    ]
  }), { mode: 'play' })

  const playerTypes = buildSceneEffects(playerGame, {
    canSeeLog: () => true,
    isWatch: false,
    isReplayMode: false
  }).map((effect) => effect.type)
  assert.deepEqual(playerTypes, ['night_death'])
})

test('scene effects include public skill kills and witch action aliases', () => {
  const players = [
    { id: 1, seat: 1, name: '1号', role_hint: '猎人', alive: true },
    { id: 2, seat: 2, name: '2号', role_hint: '狼人', alive: true },
    { id: 3, seat: 3, name: '3号', role_hint: '女巫', alive: true },
    { id: 4, seat: 4, name: '4号', role_hint: '村民', alive: true },
    { id: 5, seat: 5, name: '5号', role_hint: '白狼王', alive: true }
  ]
  const aliasGame = normalizeGameSnapshot(game('scene-skill-aliases', {
    mode: 'watch',
    players,
    logs: [
      {
        type: 'night_end',
        day: 1,
        phase: 'night',
        message: '第1夜结束，死亡玩家：无',
        speaker: '法官',
        payload: { killed_target: 4, protected_target: null, saved: true, deaths: [] }
      },
      {
        type: 'night_end',
        day: 2,
        phase: 'night',
        message: '第2夜结束，死亡玩家：2号',
        speaker: '法官',
        payload: { poisoned_target: 2, deaths: [2] }
      }
    ],
    decisions: [
      { action: 'werewolf_kill', actor_id: 2, target_id: 4, day: 1, phase: 'night', sequence: 1 },
      { action: 'antidote', actor_id: 3, target_id: 4, day: 1, phase: 'night', sequence: 2 },
      { action: 'poison', actor_id: 3, target_id: 2, day: 2, phase: 'night', sequence: 1 },
      { action: 'hunter_shoot', actor_id: 1, target_id: 5, day: 2, phase: 'speech', sequence: 2 },
      { action: 'white_wolf_explode', actor_id: 5, target_id: 4, day: 3, phase: 'speech', sequence: 1, choice: 'explode' }
    ]
  }), { mode: 'watch' })

  const effects = buildSceneEffects(aliasGame, { isWatch: true })
  const types = effects.map((effect) => effect.type)
  assert.equal(types.includes('wolf_saved'), true)
  assert.equal(types.includes('poison_kill'), true)
  assert.equal(types.filter((type) => type === 'night_death').length, 2)

  const playerEffects = buildSceneEffects(aliasGame, {
    canSeeLog: () => false,
    isWatch: false,
    isReplayMode: false
  })
  assert.deepEqual(playerEffects.map((effect) => effect.type), ['night_death', 'night_death'])
})

test('white wolf pass does not create replay deaths or scene effects', () => withWindow(() => {
  const players = [
    { id: 1, seat: 1, name: '1号', role_hint: '白狼王', alive: true },
    { id: 2, seat: 2, name: '2号', role_hint: '村民', alive: true }
  ]
  const passGame = game('white-wolf-pass-replay', {
    players,
    logs: [
      { type: 'setup', day: 1, phase: 'setup', message: 'start', speaker: '法官' },
      {
        type: 'white_wolf_explode',
        day: 1,
        phase: 'speech',
        actor_id: 1,
        target_id: 2,
        message: '1号选择暂不自爆',
        payload: { choice: 'pass' }
      }
    ],
    decisions: [
      {
        action: 'white_wolf_explode',
        actor_id: 1,
        target_id: 2,
        day: 1,
        phase: 'speech',
        choice: 'pass'
      }
    ]
  })
  const state = useGameState()
  const history = useGameHistory(state, { installLifecycle: false, apiFetch: async () => ({}) })
  const frame = history.buildReplaySnapshotByCursor(passGame, 2)

  assert.equal(frame.players.find((player) => player.id === 1).alive, true)
  assert.equal(frame.players.find((player) => player.id === 2).alive, true)
  assert.deepEqual(
    buildSceneEffects(passGame, { isReplayMode: true }).filter((effect) => effect.type === 'night_death'),
    []
  )
}))

test('werewolf choice decisions wait for the final night outcome effect', () => {
  const players = [
    { id: 1, seat: 1, name: '1号', role_hint: '村民', alive: true },
    { id: 2, seat: 2, name: '2号', role_hint: '女巫', alive: true },
    { id: 3, seat: 3, name: '3号', role_hint: '守卫', alive: true },
    { id: 4, seat: 4, name: '4号', role_hint: '狼人', alive: true },
    { id: 5, seat: 5, name: '5号', role_hint: '狼人', alive: true },
    { id: 6, seat: 6, name: '6号', role_hint: '狼人', alive: true }
  ]
  const choiceOnlyGame = normalizeGameSnapshot(game('wolf-choice-effects', {
    mode: 'watch',
    players,
    decisions: [
      { action: 'werewolf_kill', actor_id: 4, target_id: 1, day: 1, phase: 'night', sequence: 1 },
      { action: 'werewolf_kill', actor_id: 5, target_id: 2, day: 1, phase: 'night', sequence: 2 },
      { action: 'werewolf_kill', actor_id: 6, target_id: 3, day: 1, phase: 'night', sequence: 3 }
    ]
  }), { mode: 'watch' })
  assert.equal(buildSceneEffects(choiceOnlyGame, { isWatch: true }).some((effect) => effect.type === 'wolf_kill'), false)

  const outcomeGame = normalizeGameSnapshot({
    ...choiceOnlyGame,
    logs: [
      {
        type: 'night_end',
        day: 1,
        phase: 'night',
        message: '第1夜结束，死亡玩家：2号',
        speaker: '法官',
        payload: { killed_target: 2, protected_target: null, saved: false, deaths: [2] }
      }
    ]
  }, { mode: 'watch' })
  const wolfKills = buildSceneEffects(outcomeGame, { isWatch: true }).filter((effect) => effect.type === 'wolf_kill')
  assert.equal(wolfKills.length, 1)
  assert.equal(wolfKills[0].targetId, 2)
  assert.equal(wolfKills[0].source, 'log')
})

test('live watch log application mirrors replay death reconstruction', () => withWindow(() => {
  const players = [
    { id: 1, seat: 1, name: '1号', role_hint: '村民', alive: true },
    { id: 2, seat: 2, name: '2号', role_hint: '守卫', alive: true },
    { id: 3, seat: 3, name: '3号', role_hint: '女巫', alive: true },
    { id: 4, seat: 4, name: '4号', role_hint: '狼人', alive: true }
  ]
  const logs = [
    { type: 'night_start', day: 1, phase: 'night', message: 'night', speaker: '法官' },
    {
      type: 'night_end',
      day: 1,
      phase: 'night',
      message: '死亡结果将在警长竞选后公布',
      speaker: '法官',
      payload: { killed_target: 1, protected_target: 2, saved: false, deferred_death_reveal: true }
    },
    {
      type: 'night_death_reveal',
      day: 1,
      phase: 'speech',
      message: '第1天天亮，公布昨夜死亡玩家：[1]',
      speaker: '法官',
      payload: { killed_target: 1, protected_target: 2, saved: false, deaths: [1] }
    },
    {
      type: 'night_end',
      day: 2,
      phase: 'night',
      message: '第2夜结束，死亡玩家：无',
      speaker: '法官',
      payload: { killed_target: 2, protected_target: 2, saved: false, deaths: [] }
    },
    {
      type: 'night_death_reveal',
      day: 3,
      phase: 'speech',
      message: '昨夜死亡玩家：3号',
      speaker: '法官',
      payload: { poisoned_target: 3, deaths: [3] }
    },
    { type: 'exile_vote_end', day: 3, phase: 'vote', target_id: 4, message: '4号出局', speaker: '法官' }
  ]
  const state = useGameState()
  const actions = useGameActions(state, { installLifecycle: false, apiFetch: async () => ({}) })
  state.liveGame.value = normalizeGameSnapshot(game('live-watch-deaths', {
    mode: 'watch',
    players,
    logs: []
  }), { mode: 'watch' })

  actions.applyLiveLog(logs[0])
  actions.applyLiveLog(logs[1])
  assert.equal(state.liveGame.value.players.find((player) => player.id === 1).alive, true)

  logs.slice(2).forEach((log) => actions.applyLiveLog(log))
  const history = useGameHistory(state, { installLifecycle: false, apiFetch: async () => ({}) })
  const replay = history.buildReplaySnapshotByCursor(normalizeGameSnapshot(game('replay-watch-deaths', {
    mode: 'watch',
    players,
    logs
  }), { mode: 'watch' }), logs.length)

  assert.deepEqual(
    state.liveGame.value.players.map((player) => [player.id, player.alive]),
    replay.players.map((player) => [player.id, player.alive])
  )
  assert.equal(state.liveGame.value.players.find((player) => player.id === 1).alive, false)
  assert.equal(state.liveGame.value.players.find((player) => player.id === 2).alive, true)
  assert.equal(state.liveGame.value.players.find((player) => player.id === 3).alive, false)
  assert.equal(state.liveGame.value.players.find((player) => player.id === 4).alive, false)
}))

test('live watch polling cannot resurrect players already killed by logs', async () => {
  const players = [
    { id: 1, seat: 1, name: '1号', role_hint: '村民', alive: true },
    { id: 2, seat: 2, name: '2号', role_hint: '狼人', alive: true }
  ]
  const deathLog = { type: 'death', day: 1, phase: 'speech', target_id: 1, message: '1号死亡', speaker: '法官' }
  const state = useGameState()
  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path) => {
      if (path === '/games/live-resurrection') {
        return game('live-resurrection', {
          mode: 'watch',
          players,
          logs: [deathLog]
        })
      }
      return {}
    }
  })
  state.liveGame.value = normalizeGameSnapshot(game('live-resurrection', {
    mode: 'watch',
    players,
    logs: []
  }), { mode: 'watch' })

  actions.applyLiveLog(deathLog)
  assert.equal(state.liveGame.value.players.find((player) => player.id === 1).alive, false)

  await actions.loadCurrentGame({ silent: true })
  assert.equal(state.liveGame.value.players.find((player) => player.id === 1).alive, false)
})

test('SSE errors keep polling active and schedule reconnect', () => withWindow(({ timers }) => {
  const instances = []
  class FakeEventSource {
    constructor(url) {
      this.url = url
      this.listeners = {}
      this.closed = false
      instances.push(this)
    }

    addEventListener(type, callback) {
      this.listeners[type] = callback
    }

    close() {
      this.closed = true
    }

    emit(type, data = {}, options = {}) {
      this.listeners[type]?.({
        type,
        data: JSON.stringify(data),
        lastEventId: options.lastEventId || '',
        id: options.id || ''
      })
    }
  }

  globalThis.EventSource = FakeEventSource
  const state = useGameState()
  state.backendMode.value = 'api'
  state.liveGame.value = game('sse-game')
  const actions = useGameActions(state, {
    installLifecycle: false,
    apiBase: '/api',
    apiFetch: async (path) => {
      if (path === '/games/sse-game') return state.liveGame.value
      return {}
    }
  })

  actions.startWatch()
  assert.equal(instances.length, 1)
  assert.equal(instances[0].url, '/api/games/sse-game/events')
  assert.equal(timers.intervalCount(), 1)
  instances[0].emit('open')
  assert.equal(state.activeSession.value.sseConnected, true)

  instances[0].emit('log', { type: 'speech', message: 'hello' }, { lastEventId: '9' })
  instances[0].emit('error')
  assert.equal(state.watchRunning.value, true)
  assert.equal(state.activeSession.value.sseConnected, false)
  assert.equal(timers.timeoutCount(), 1)

  timers.runNextTimeout()
  assert.equal(instances.length, 2)
  assert.equal(instances[1].url, '/api/games/sse-game/events?lastEventId=9')
  actions.stopWatch()
}))

test('game audio dispose clears delayed TTS retry timers', () => withWindow(async ({ timers }) => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => {
    throw new Error('tts unavailable')
  }

  try {
    const runtime = {
      currentView: ref('match'),
      game: ref(null),
      isReplayMode: ref(false),
      externalStatus: ref({ tts: 'configured' }),
      apiBase: ref('/api'),
      roleAssignmentComplete: ref(true)
    }
    const audio = useGameAudio(runtime, { installLifecycle: false })

    runtime.game.value = game('audio-tts', { phase: 'speech', waiting_for: 'speech', logs: [] })
    await nextTick()
    runtime.game.value = game('audio-tts', {
      phase: 'speech',
      waiting_for: 'speech',
      logs: [
        { type: 'speech', actor_id: 1, speaker: '1号', message: '我是好人', visibility: 'public' }
      ]
    })
    await nextTick()
    await Promise.resolve()
    await Promise.resolve()

    assert.equal(timers.timeoutCount(), 1)
    audio.dispose()
    assert.equal(timers.timeoutCount(), 0)
  } finally {
    if (originalFetch === undefined) delete globalThis.fetch
    else globalThis.fetch = originalFetch
  }
}))

test('history list uses paginated API and load more appends without changing selection', () => withWindow(async () => {
  const state = useGameState()
  const requests = []
  const rows = [
    game('history-1', { winner: 'villagers' }),
    game('history-2', { winner: 'werewolves' }),
    game('history-3', { winner: 'villagers' })
  ]
  const evolutionRows = [
    game('evolution-1', { winner: 'villagers' }),
    game('evolution-2', { winner: 'werewolves' })
  ]
  const apiFetch = async (path) => {
    requests.push(path)
    const [route, query = ''] = path.split('?')
    if (route === '/games') {
      const params = new URLSearchParams(query)
      const sourceRows = params.get('source') === 'evolution' ? evolutionRows : rows
      const offset = Number(params.get('offset') || 0)
      const limit = Number(params.get('limit') || sourceRows.length)
      const page = sourceRows.slice(offset, offset + limit)
      return {
        games: page,
        pagination: {
          total: sourceRows.length,
          offset,
          limit,
          returned: page.length,
          has_more: offset + page.length < sourceRows.length
        },
        counts: { all: rows.length + evolutionRows.length, normal: rows.length, benchmark: 0, evolution: evolutionRows.length },
        facets: {
          source: { all: rows.length + evolutionRows.length, normal: rows.length, benchmark: 0, evolution: evolutionRows.length },
          status: { completed: rows.length + evolutionRows.length }
        }
      }
    }
    const gameIdMatch = route.match(/^\/games\/([^/]+)$/)
    if (gameIdMatch) {
      return [...rows, ...evolutionRows].find((item) => item.game_id === decodeURIComponent(gameIdMatch[1]))
    }
    if (/^\/games\/[^/]+\/review$/.test(route)) return { summary: 'ok' }
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    historyListLimit: 2,
    apiFetch
  })

  await history.refreshHistoryList()
  assert.deepEqual(requests, ['/games?limit=2&offset=0'])
  assert.deepEqual(state.gameHistory.value.map((item) => item.game_id), ['history-1', 'history-2'])
  assert.equal(state.selectedHistoryGameId.value, 'history-1')
  assert.equal(history.historyHasMore.value, true)
  assert.deepEqual(history.historyCounts.value, { all: 5, normal: 3, benchmark: 0, evolution: 2 })
  assert.deepEqual(history.historyFacets.value.source, { all: 5, normal: 3, benchmark: 0, evolution: 2 })

  state.selectedHistoryGameId.value = 'history-2'
  await history.loadMoreHistory()
  assert.equal(requests.at(-1), '/games?limit=2&offset=2')
  assert.deepEqual(state.gameHistory.value.map((item) => item.game_id), ['history-1', 'history-2', 'history-3'])
  assert.equal(state.selectedHistoryGameId.value, 'history-2')
  assert.equal(history.historyHasMore.value, false)

  await history.setHistorySourceFilter('evolution')
  assert.equal(requests.includes('/games?limit=2&offset=0&source=evolution'), true)
  assert.equal(state.selectedHistoryGameId.value, 'evolution-1')
  assert.equal(state.selectedHistoryGame.value.game_id, 'evolution-1')
  assert.equal(history.historyHasMore.value, false)
}))

test('history load more stale requests do not leave the button loading', () => withWindow(async () => {
  const state = useGameState()
  let resolveSlowPage
  const slowPage = new Promise((resolve) => { resolveSlowPage = resolve })
  const apiFetch = async (path) => {
    if (path === '/games?limit=1&offset=0') {
      return {
        games: [game('history-1')],
        pagination: { total: 2, offset: 0, limit: 1, returned: 1, has_more: true }
      }
    }
    if (path === '/games?limit=1&offset=1') return slowPage
    if (path === '/games?limit=1&offset=0&source=benchmark') {
      return {
        games: [game('benchmark-1')],
        pagination: { total: 1, offset: 0, limit: 1, returned: 1, has_more: false }
      }
    }
    if (path === '/games/benchmark-1') return game('benchmark-1')
    if (path === '/games/benchmark-1/review') return { summary: 'ok' }
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    historyListLimit: 1,
    apiFetch
  })

  await history.refreshHistoryList()
  const loadingMore = history.loadMoreHistory()
  assert.equal(history.historyLoadingMore.value, true)

  await history.setHistorySourceFilter('benchmark')
  assert.equal(history.historyLoadingMore.value, false)
  assert.equal(state.selectedHistoryGameId.value, 'benchmark-1')

  resolveSlowPage({
    games: [game('history-2')],
    pagination: { total: 2, offset: 1, limit: 1, returned: 1, has_more: false }
  })
  await loadingMore
  assert.equal(history.historyLoadingMore.value, false)
  assert.deepEqual(state.gameHistory.value.map((item) => item.game_id), ['benchmark-1'])
}))

test('history detail ignores stale selection responses', () => withWindow(async () => {
  const state = useGameState()
  const slowDetail = createDeferred()
  const apiFetch = async (path) => {
    if (path === '/games/history-a') return slowDetail.promise
    if (path === '/games/history-b') return game('history-b', { day: 2, winner: 'villagers' })
    if (/^\/games\/[^/]+\/review$/.test(path)) return { summary: 'ok' }
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    apiFetch
  })

  const staleSelection = history.selectHistoryGame('history-a')
  await Promise.resolve()
  await history.selectHistoryGame('history-b')
  assert.equal(state.selectedHistoryGameId.value, 'history-b')
  assert.equal(state.selectedHistoryGame.value.game_id, 'history-b')

  slowDetail.resolve(game('history-a', { day: 9, winner: 'werewolves' }))
  await staleSelection

  assert.equal(state.selectedHistoryGameId.value, 'history-b')
  assert.equal(state.selectedHistoryGame.value.game_id, 'history-b')
  assert.equal(state.selectedHistoryGame.value.day, 2)
  assert.equal(state.historyLoading.value, false)
}))

test('evolution workbench paginates runs and selected sample games', async () => {
  const requests = []
  const runA = {
    run_id: 'evo-run-a',
    role: 'seer',
    status: 'completed',
    started_at: '2026-06-07T10:00:00'
  }
  const runB = {
    run_id: 'evo-run-b',
    role: 'witch',
    status: 'completed',
    started_at: '2026-06-07T09:00:00'
  }
  const trainingHistoryGameId = 'evolution:evo-run-a:training:training_001'
  const sampleRows = {
    training: [{ game_id: 'train-1', history_game_id: trainingHistoryGameId }, { game_id: 'train-2' }],
    baseline: [{ game_id: 'base-1' }],
    candidate: [{ game_id: 'cand-1' }]
  }
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/roles') return { roles: ['seer', 'witch'] }
    if (/^\/roles\/[^/]+\/versions$/.test(path)) return { versions: [] }
    if (/^\/roles\/[^/]+\/leaderboard$/.test(path)) return { entries: [] }
    if (path.startsWith('/evolution-runs?')) {
      const params = new URLSearchParams(path.split('?')[1] || '')
      const offset = Number(params.get('offset') || 0)
      const limit = Number(params.get('limit') || 1)
      const page = [runA, runB].slice(offset, offset + limit)
      return {
        runs: page,
        batches: [],
        pagination: {
          total: 2,
          offset,
          limit,
          returned: page.length,
          has_more: offset + page.length < 2
        }
      }
    }
    if (path === '/evolution-runs/evo-run-a') return { ...runA, progress: { percent: 1 }, diagnostics: [] }
    if (path === '/evolution-runs/evo-run-b') return { ...runB, progress: { percent: 1 }, diagnostics: [] }
    if (/^\/evolution-runs\/[^/]+\/diff$/.test(path)) return { diffs: [] }
    const gamesMatch = path.match(/^\/evolution-runs\/[^/]+\/games\?(.*)$/)
    if (gamesMatch) {
      const params = new URLSearchParams(gamesMatch[1])
      const bucket = params.get('phase') === 'training' ? 'training' : params.get('side')
      const rows = sampleRows[bucket] || []
      const offset = Number(params.get('offset') || 0)
      const limit = Number(params.get('limit') || 1)
      const page = rows.slice(offset, offset + limit)
      return {
        games: page,
        pagination: {
          total: rows.length,
          offset,
          limit,
          returned: page.length,
          has_more: offset + page.length < rows.length
        }
      }
    }
    if (/^\/evolution-runs\/[^/]+\/games\/[^/]+\/(archive|decisions|events)/.test(path)) {
      return path.endsWith('/archive?phase=training')
        ? { title: 'train-1', history_game_id: trainingHistoryGameId }
        : (path.includes('/decisions') ? { decisions: [] } : { events: [] })
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvolutionWorkbench({
    installLifecycle: false,
    runListLimit: 1,
    sampleGameListLimit: 1,
    apiFetch
  })

  await workbench.refreshAll()
  assert.equal(requests.find((path) => path.startsWith('/evolution-runs?')), '/evolution-runs?limit=1&offset=0&source=evolution')
  assert.equal(requests.includes('/evolution-runs/evo-run-a'), true)
  assert.equal(requests.includes('/evolution-runs/evo-run-a/games?phase=training&limit=1&offset=0'), true)
  assert.equal(requests.includes('/evolution-runs/evo-run-a/games?phase=battle&side=baseline&limit=1&offset=0'), true)
  assert.equal(requests.includes('/evolution-runs/evo-run-a/games?phase=battle&side=candidate&limit=1&offset=0'), true)
  assert.deepEqual(workbench.runRows.value.map((run) => run.id), ['evo-run-a'])
  assert.deepEqual(workbench.selectedGames.value.training.map((item) => item.game_id), ['train-1'])
  assert.equal(workbench.selectedRunId.value, 'evo-run-a')
  assert.equal(workbench.selectedGameId.value, 'train-1')
  assert.equal(workbench.selectedSampleHistoryGameId.value, trainingHistoryGameId)

  await workbench.loadMoreRuns()
  assert.equal(requests.at(-1), '/evolution-runs?limit=1&offset=1&source=evolution')
  assert.deepEqual(workbench.runRows.value.map((run) => run.id), ['evo-run-a', 'evo-run-b'])
  assert.equal(workbench.selectedRunId.value, 'evo-run-a')

  await workbench.loadMoreSampleGames('training')
  assert.equal(requests.at(-1), '/evolution-runs/evo-run-a/games?phase=training&limit=1&offset=1')
  assert.deepEqual(workbench.selectedGames.value.training.map((item) => item.game_id), ['train-1', 'train-2'])
  assert.equal(workbench.selectedGameId.value, 'train-1')
})

test('evolution batch selection keeps batch detail separate from run samples and diff', async () => {
  const requests = []
  const batch = {
    kind: 'role_evolution_batch',
    batch_id: 'evo-batch-a',
    roles: ['seer', 'witch'],
    status: 'completed',
    started_at: '2026-06-07T12:00:00',
    progress: { percent: 0.5, completed_roles: 1, total_roles: 2 },
    config: { training_games: 5, battle_games: 4 },
    runs: [
      { run_id: 'evo-run-seer', role: 'seer', status: 'completed', progress: { percent: 1 } },
      { run_id: 'evo-run-witch', role: 'witch', status: 'training', progress: { percent: 0.25 } }
    ]
  }
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/roles') return { roles: ['seer', 'witch'] }
    if (/^\/roles\/[^/]+\/versions$/.test(path)) return { versions: [] }
    if (/^\/roles\/[^/]+\/leaderboard$/.test(path)) return { entries: [] }
    if (path === '/evolution-runs?limit=80&offset=0&source=evolution') {
      return {
        runs: [],
        batches: [batch],
        pagination: { total: 1, offset: 0, limit: 80, returned: 1, has_more: false }
      }
    }
    if (path === '/evolution-runs/evo-batch-a') return batch
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  assert.equal(workbench.selectedRunId.value, 'evo-batch-a')
  assert.equal(workbench.selectedIsBatch.value, true)
  assert.equal(workbench.selectedRun.value.entityType, 'batch')
  assert.equal(workbench.selectedRun.value.roleCount, 2)
  assert.equal(workbench.selectedRun.value.completedRoleCount, 1)
  assert.equal(workbench.selectedRun.value.overallProgressPercent, 50)
  assert.equal(workbench.selectedRun.value.trainingProgressLabel, '0 / 10')
  assert.equal(workbench.selectedRun.value.battleProgressLabel, '0 / 16')
  assert.deepEqual(workbench.selectedDiff.value, [])
  assert.deepEqual(workbench.selectedGames.value, { training: [], baseline: [], candidate: [] })
  assert.equal(workbench.selectedSampleState.value.unsupported, true)
  assert.match(workbench.selectedSampleHistoryUnavailableReason.value, /批量任务/)
  assert.equal(requests.some((path) => path.includes('/diff')), false)
  assert.equal(requests.some((path) => path.includes('/games')), false)
})

test('evolution run progress exposes overall stage training and battle progress separately', async () => {
  const run = {
    run_id: 'evo-progress-run',
    role: 'seer',
    status: 'battling',
    current_stage: 'battling',
    started_at: '2026-06-07T13:00:00',
    training_game_count: 20,
    battle_game_count: 10,
    training_completed: 20,
    battle_completed: 4,
    progress: {
      stage: 'battling',
      percent: 0.4,
      completed_games: 4,
      target_games: 20
    }
  }
  const apiFetch = async (path) => {
    if (path === '/roles') return { roles: ['seer'] }
    if (path === '/roles/seer/versions') return { versions: [] }
    if (path === '/roles/seer/leaderboard') return { entries: [] }
    if (path === '/evolution-runs?limit=80&offset=0&source=evolution') {
      return {
        runs: [run],
        batches: [],
        pagination: { total: 1, offset: 0, limit: 80, returned: 1, has_more: false }
      }
    }
    if (path === '/evolution-runs/evo-progress-run') return run
    if (path === '/evolution-runs/evo-progress-run/diff') return { diffs: [] }
    if (/^\/evolution-runs\/evo-progress-run\/games/.test(path)) {
      return { games: [], pagination: { total: 0, offset: 0, limit: 80, returned: 0, has_more: false } }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  assert.equal(workbench.selectedIsRun.value, true)
  assert.equal(workbench.selectedRun.value.overallProgressPercent, 60)
  assert.equal(workbench.selectedRun.value.overallProgressLabel, '24 / 40')
  assert.equal(workbench.selectedRun.value.stageProgressPercent, 40)
  assert.equal(workbench.selectedRun.value.stageProgressLabel, '4 / 20')
  assert.equal(workbench.selectedRun.value.trainingProgressPercent, 100)
  assert.equal(workbench.selectedRun.value.trainingProgressLabel, '20 / 20')
  assert.equal(workbench.selectedRun.value.battleProgressPercent, 20)
  assert.equal(workbench.selectedRun.value.battleProgressLabel, '4 / 20')
  assert.equal(workbench.selectedRunSummary.value.overallProgressPercent, 60)
})

test('evolution sample loading surfaces list and detail failures', async () => {
  const run = {
    run_id: 'evo-sample-errors',
    role: 'witch',
    status: 'completed',
    started_at: '2026-06-07T14:00:00'
  }
  const apiFetch = async (path) => {
    if (path === '/roles') return { roles: ['witch'] }
    if (path === '/roles/witch/versions') return { versions: [] }
    if (path === '/roles/witch/leaderboard') return { entries: [] }
    if (path === '/evolution-runs?limit=80&offset=0&source=evolution') {
      return {
        runs: [run],
        batches: [],
        pagination: { total: 1, offset: 0, limit: 80, returned: 1, has_more: false }
      }
    }
    if (path === '/evolution-runs/evo-sample-errors') return run
    if (path === '/evolution-runs/evo-sample-errors/diff') return { diffs: [] }
    if (path === '/evolution-runs/evo-sample-errors/games?phase=training&limit=80&offset=0') {
      throw new Error('training api failed')
    }
    if (path === '/evolution-runs/evo-sample-errors/games?phase=battle&side=baseline&limit=80&offset=0') {
      return {
        games: [{ game_id: 'base-1' }],
        pagination: { total: 1, offset: 0, limit: 80, returned: 1, has_more: false }
      }
    }
    if (path === '/evolution-runs/evo-sample-errors/games?phase=battle&side=candidate&limit=80&offset=0') {
      return { games: [], pagination: { total: 0, offset: 0, limit: 80, returned: 0, has_more: false } }
    }
    if (path === '/evolution-runs/evo-sample-errors/games/base-1/archive?phase=battle&side=baseline') {
      throw new Error('archive failed')
    }
    if (path === '/evolution-runs/evo-sample-errors/games/base-1/decisions?phase=battle&side=baseline') {
      return { decisions: [{ action: 'vote' }] }
    }
    if (path === '/evolution-runs/evo-sample-errors/games/base-1/events?phase=battle&side=baseline') {
      throw new Error('events failed')
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  assert.equal(workbench.selectedSampleState.value.error, 'training api failed')
  assert.equal(workbench.selectedSampleBucketError.value, '')
  assert.equal(workbench.selectedGameBucket.value, 'baseline')
  assert.equal(workbench.selectedGameId.value, 'base-1')
  assert.equal(workbench.selectedGameDetail.value.error, '')
  assert.match(workbench.selectedGameDetail.value.warning, /档案、事件读取失败/)
  assert.deepEqual(workbench.selectedGameDetail.value.decisions, [{ action: 'vote' }])
  assert.match(workbench.selectedSampleHistoryUnavailableReason.value, /缺少历史对局 ID/)

  await workbench.selectSampleGame('training')
  assert.equal(workbench.selectedSampleBucketError.value, 'training api failed')
})

test('evolution run selection ignores stale sample responses', async () => {
  const requests = []
  const runA = {
    run_id: 'run-a',
    role: 'seer',
    status: 'completed',
    started_at: '2026-06-07T10:00:00'
  }
  const runB = {
    run_id: 'run-b',
    role: 'witch',
    status: 'completed',
    started_at: '2026-06-07T11:00:00'
  }
  const runBTrainingHistoryGameId = 'evolution:run-b:training:training_001'
  const slowTraining = createDeferred()
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/roles') return { roles: ['seer', 'witch'] }
    if (/^\/roles\/[^/]+\/versions$/.test(path)) return { versions: [] }
    if (/^\/roles\/[^/]+\/leaderboard$/.test(path)) return { entries: [] }
    if (path === '/evolution-runs?limit=80&offset=0&source=evolution') {
      return {
        runs: [runB, runA],
        batches: [],
        pagination: { total: 2, offset: 0, limit: 80, returned: 2, has_more: false }
      }
    }
    if (path === '/evolution-runs/run-a') return { ...runA, progress: { percent: 1 }, diagnostics: [] }
    if (path === '/evolution-runs/run-b') return { ...runB, progress: { percent: 1 }, diagnostics: [] }
    if (path === '/evolution-runs/run-a/diff') return { diffs: [{ file: 'a.md' }] }
    if (path === '/evolution-runs/run-b/diff') return { diffs: [{ file: 'b.md' }] }
    if (path === '/evolution-runs/run-a/games?phase=training&limit=80&offset=0') return slowTraining.promise
    if (path === '/evolution-runs/run-a/games?phase=battle&side=baseline&limit=80&offset=0') {
      return { games: [{ game_id: 'a-base' }], pagination: { total: 1, offset: 0, limit: 80, returned: 1, has_more: false } }
    }
    if (path === '/evolution-runs/run-a/games?phase=battle&side=candidate&limit=80&offset=0') {
      return { games: [{ game_id: 'a-cand' }], pagination: { total: 1, offset: 0, limit: 80, returned: 1, has_more: false } }
    }
    if (path === '/evolution-runs/run-b/games?phase=training&limit=80&offset=0') {
      return {
        games: [{ game_id: 'b-train', history_game_id: runBTrainingHistoryGameId }],
        pagination: { total: 1, offset: 0, limit: 80, returned: 1, has_more: false }
      }
    }
    if (path === '/evolution-runs/run-b/games?phase=battle&side=baseline&limit=80&offset=0') {
      return { games: [], pagination: { total: 0, offset: 0, limit: 80, returned: 0, has_more: false } }
    }
    if (path === '/evolution-runs/run-b/games?phase=battle&side=candidate&limit=80&offset=0') {
      return { games: [], pagination: { total: 0, offset: 0, limit: 80, returned: 0, has_more: false } }
    }
    if (path === '/evolution-runs/run-b/games/b-train/archive?phase=training') {
      return { title: 'b-train', history_game_id: runBTrainingHistoryGameId }
    }
    if (path === '/evolution-runs/run-b/games/b-train/decisions?phase=training') return { decisions: [{ action: 'vote' }] }
    if (path === '/evolution-runs/run-b/games/b-train/events?phase=training') return { events: [{ type: 'setup' }] }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvolutionWorkbench({
    installLifecycle: false,
    apiFetch
  })

  await workbench.refreshAll()
  assert.equal(requests.includes('/evolution-runs/run-b'), true)
  assert.equal(workbench.selectedRunId.value, 'run-b')
  assert.deepEqual(workbench.selectedGames.value.training.map((item) => item.game_id), ['b-train'])
  assert.equal(workbench.selectedSampleHistoryGameId.value, runBTrainingHistoryGameId)

  const staleSelection = workbench.selectRun('run-a')
  await Promise.resolve()
  await workbench.selectRun('run-b')
  slowTraining.resolve({
    games: [{ game_id: 'a-train', history_game_id: 'evolution:run-a:training:training_001' }],
    pagination: { total: 1, offset: 0, limit: 80, returned: 1, has_more: false }
  })
  await staleSelection

  assert.equal(requests.includes('/evolution-runs/run-a'), true)
  assert.equal(workbench.selectedRunId.value, 'run-b')
  assert.deepEqual(workbench.selectedGames.value.training.map((item) => item.game_id), ['b-train'])
  assert.equal(workbench.selectedGameDetail.value.archive.title, 'b-train')
  assert.equal(workbench.selectedSampleHistoryGameId.value, runBTrainingHistoryGameId)
})

test('benchmark SSE reconnect resumes from the last event id and closes on terminal events', () => withWindow(async ({ timers }) => {
  const instances = []
  class FakeEventSource {
    constructor(url) {
      this.url = url
      this.listeners = {}
      this.closed = false
      instances.push(this)
    }

    addEventListener(type, callback) {
      this.listeners[type] = callback
    }

    close() {
      this.closed = true
    }

    emit(type, data = {}, options = {}) {
      return this.listeners[type]?.({
        type,
        data: JSON.stringify(data),
        lastEventId: options.lastEventId || '',
        id: options.id || ''
      })
    }
  }
  globalThis.EventSource = FakeEventSource

  let currentBatch = {
    kind: 'benchmark_batch',
    batch_id: 'bench-live',
    roles: ['seer'],
    status: 'running',
    started_at: '2026-06-07T10:00:00',
    progress: { percent: 0.1 }
  }
  const apiFetch = async (path) => {
    if (path === '/roles') return { roles: ['seer'] }
    if (path === '/roles/seer/leaderboard') return { entries: [] }
    if (path === '/roles/seer/versions') return { versions: [] }
    if (path === '/evolution-runs') return { runs: [], batches: [currentBatch] }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiBase: '/api', apiFetch })
  await workbench.refreshAll()

  assert.equal(instances.length, 1)
  assert.equal(instances[0].url, '/api/benchmark/batch/bench-live/events')

  currentBatch = { ...currentBatch, status: 'running', progress: { percent: 0.55 } }
  await instances[0].emit('progress', currentBatch, { lastEventId: '5' })
  assert.equal(workbench.benchmarkEvents.value[0].type, 'progress')
  assert.equal(workbench.batchRunRows.value[0].progress.percent, 0.55)

  instances[0].emit('error')
  assert.equal(instances[0].closed, true)
  assert.equal(timers.timeoutCount(), 1)

  timers.runNextTimeout()
  assert.equal(instances.length, 2)
  assert.equal(instances[1].url, '/api/benchmark/batch/bench-live/events?lastEventId=5')

  currentBatch = { ...currentBatch, status: 'completed', progress: { percent: 1 } }
  await instances[1].emit('completed', currentBatch, { lastEventId: '6' })
  assert.equal(instances[1].closed, true)
  assert.equal(timers.timeoutCount(), 0)

  instances[1].emit('error')
  assert.equal(timers.timeoutCount(), 0)
}))

test('evaluation workbench normalizes benchmark decision judge aggregate', async () => {
  const apiFetch = async (path) => {
    if (path === '/roles') return { roles: ['seer'] }
    if (path === '/roles/seer/leaderboard') return { entries: [] }
    if (path === '/roles/seer/versions') return { versions: [] }
    if (path === '/evolution-runs') {
      return {
        runs: [],
        batches: [
          {
            kind: 'benchmark_batch',
            batch_id: 'bench-judge',
            roles: ['seer'],
            status: 'completed',
            started_at: '2026-06-07T10:00:00',
            result: {
              score_summary: {
                decision_judge_aggregate: {
                  avg_score: 6.75,
                  bad_rate: 0.25,
                  judged_decisions: 4,
                  top_mistake_tags: [
                    { tag: 'low_information_gain', count: 2 },
                    { tag: 'vote_alignment', count: 1 }
                  ]
                }
              }
            }
          }
        ]
      }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  const row = workbench.batchRunRows.value[0]
  assert.equal(row.id, 'bench-judge')
  assert.equal(row.judgeScoreLabel, '6.8')
  assert.equal(row.judgeBadRatePct, 25)
  assert.equal(row.judgeDecisionCount, 4)
  assert.deepEqual(row.judgeTags, [
    { tag: 'low_information_gain', count: 2 },
    { tag: 'vote_alignment', count: 1 }
  ])
})

test('evolution SSE reconnect resumes from the last event id per run and clears stale retry timers', () => withWindow(async ({ timers }) => {
  const instances = []
  const requests = []
  class FakeEventSource {
    constructor(url) {
      this.url = url
      this.listeners = {}
      this.closed = false
      instances.push(this)
    }

    addEventListener(type, callback) {
      this.listeners[type] = callback
    }

    close() {
      this.closed = true
    }

    emit(type, data = {}, options = {}) {
      return this.listeners[type]?.({
        type,
        data: JSON.stringify(data),
        lastEventId: options.lastEventId || '',
        id: options.id || ''
      })
    }
  }
  globalThis.EventSource = FakeEventSource

  const runA = {
    run_id: 'evo-run-a',
    role: 'seer',
    status: 'training',
    started_at: '2026-06-07T10:00:00'
  }
  const runB = {
    run_id: 'evo-run-b',
    role: 'witch',
    status: 'training',
    started_at: '2026-06-07T09:00:00'
  }
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/roles') return { roles: ['seer', 'witch'] }
    if (/^\/roles\/[^/]+\/versions$/.test(path)) return { versions: [] }
    if (/^\/roles\/[^/]+\/leaderboard$/.test(path)) return { entries: [] }
    if (path.startsWith('/evolution-runs?')) {
      return {
        runs: [runA, runB],
        batches: [],
        pagination: { total: 2, offset: 0, limit: 80, returned: 2, has_more: false }
      }
    }
    if (path === '/evolution-runs/evo-run-a') return { ...runA, progress: { percent: 0.2 }, diagnostics: [] }
    if (path === '/evolution-runs/evo-run-b') return { ...runB, progress: { percent: 0.2 }, diagnostics: [] }
    if (/^\/evolution-runs\/[^/]+\/diff$/.test(path)) return { diffs: [] }
    if (/^\/evolution-runs\/[^/]+\/games/.test(path)) return { games: [] }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiBase: '/api', apiFetch })
  await workbench.refreshAll()

  assert.equal(instances.length, 1)
  assert.equal(instances[0].url, '/api/evolution-runs/evo-run-a/events')
  assert.equal(requests.includes('/evolution-runs/evo-run-a'), true)

  await instances[0].emit('progress', { status: 'training' }, { lastEventId: '7' })
  instances[0].emit('error')
  assert.equal(timers.timeoutCount(), 1)

  await workbench.selectRun('evo-run-b')
  assert.equal(timers.timeoutCount(), 0)
  assert.equal(instances.length, 2)
  assert.equal(instances[1].url, '/api/evolution-runs/evo-run-b/events')
  assert.equal(requests.includes('/evolution-runs/evo-run-b'), true)

  await instances[1].emit('completed', { status: 'completed' }, { lastEventId: '3' })
  assert.equal(instances[1].closed, true)
  instances[1].emit('error')
  assert.equal(timers.timeoutCount(), 0)

  await workbench.selectRun('evo-run-a')
  assert.equal(instances.length, 3)
  assert.equal(instances[2].url, '/api/evolution-runs/evo-run-a/events?lastEventId=7')

  await instances[2].emit('completed', { status: 'completed' }, { lastEventId: '8' })
  assert.equal(instances[2].closed, true)
}))

test('replay reconstruction applies deaths, sheriff badge transfer, ties, and winner', () => withWindow(() => {
  const state = useGameState()
  state.selectedHistoryGame.value = game('history-game', {
    winner: 'villagers',
    status: 'completed',
    logs: [
      { type: 'setup', day: 1, phase: 'setup', message: 'start', speaker: '法官' },
      { type: 'sheriff_result', day: 1, phase: 'sheriff_result', target_id: 1, message: '1号当选', speaker: '法官' },
      { type: 'speech', day: 1, phase: 'speech', actor_id: 1, message: 'claim', speaker: '1号' },
      { type: 'exile', day: 1, phase: 'vote', target_id: 2, message: '2号出局', speaker: '法官' },
      { type: 'sheriff_badge_transfer', day: 1, phase: 'vote', target_id: 1, message: '移交警徽', speaker: '法官' },
      { type: 'finished', day: 1, phase: 'ended', message: 'villagers win', speaker: '法官' }
    ],
    decisions: [
      { action: 'vote', actor_id: 1, target_id: 2, day: 1, phase: 'vote' },
      { action: 'vote', actor_id: 2, target_id: 1, day: 1, phase: 'vote' }
    ]
  })
  const history = useGameHistory(state, { installLifecycle: false, apiFetch: async () => ({}) })

  const beforeEnd = history.buildReplaySnapshotByCursor(state.selectedHistoryGame.value, 5)
  assert.equal(beforeEnd.players.find((player) => player.id === 2).alive, false)
  assert.equal(beforeEnd.players.find((player) => player.id === 1).is_sheriff, true)
  assert.equal(beforeEnd.winner, null)
  assert.equal(beforeEnd.decisions.length, 2)

  const final = history.buildReplaySnapshotByCursor(state.selectedHistoryGame.value, 6)
  assert.equal(final.winner, 'villagers')
  assert.equal(final.status, 'completed')
}))

test('replay reconstruction removes revealed night kill targets', () => withWindow(() => {
  const state = useGameState()
  const history = useGameHistory(state, { installLifecycle: false, apiFetch: async () => ({}) })

  const killedGame = game('history-night-kill', {
    logs: [
      { type: 'night_start', day: 1, phase: 'night', message: 'night', speaker: '法官' },
      {
        type: 'night_end',
        day: 1,
        phase: 'night',
        message: '死亡结果将在警长竞选后公布',
        speaker: '法官',
        payload: { killed_target: 1, protected_target: 2, saved: false, deferred_death_reveal: true }
      },
      { type: 'sheriff_run', day: 1, phase: 'sheriff_election', actor_id: 1, message: '警上发言', speaker: '1号' },
      {
        type: 'night_death_reveal',
        day: 1,
        phase: 'day_speech',
        message: '第1天天亮，公布昨夜死亡玩家：[1]',
        speaker: '法官',
        payload: { killed_target: 1, protected_target: 2, saved: false, deaths: [1] }
      },
      { type: 'death', day: 1, phase: 'day_speech', target_id: 1, message: '1号死亡', speaker: '法官' }
    ]
  })

  const beforeOutcome = history.buildReplaySnapshotByCursor(killedGame, 1)
  assert.equal(beforeOutcome.players.find((player) => player.id === 1).alive, true)

  const afterOutcome = history.buildReplaySnapshotByCursor(killedGame, 2)
  assert.equal(afterOutcome.players.find((player) => player.id === 1).alive, true)

  const sheriffFrame = history.buildReplaySnapshotByCursor(killedGame, 3)
  assert.equal(sheriffFrame.players.find((player) => player.id === 1).alive, true)
  assert.equal(sheriffFrame.current_speaker_id, null)

  const revealFrame = history.buildReplaySnapshotByCursor(killedGame, 4)
  assert.equal(revealFrame.players.find((player) => player.id === 1).alive, false)
  assert.equal(revealFrame.current_speaker_id, null)

  const guardedGame = game('history-guarded-kill', {
    logs: [
      { type: 'night_start', day: 1, phase: 'night', message: 'night', speaker: '法官' },
      {
        type: 'night_end',
        day: 1,
        phase: 'night',
        message: '第1夜结束，死亡玩家：无',
        speaker: '法官',
        payload: { killed_target: 1, protected_target: 1, saved: false, deaths: [] }
      }
    ]
  })
  const guardedFrame = history.buildReplaySnapshotByCursor(guardedGame, 2)
  assert.equal(guardedFrame.players.find((player) => player.id === 1).alive, true)

  const immediateGame = game('history-immediate-night-kill', {
    logs: [
      { type: 'night_start', day: 1, phase: 'night', message: 'night', speaker: '法官' },
      {
        type: 'night_end',
        day: 1,
        phase: 'night',
        message: '第1夜结束，死亡玩家：[1]',
        speaker: '法官',
        payload: { killed_target: 1, protected_target: 2, saved: false }
      }
    ]
  })
  const immediateFrame = history.buildReplaySnapshotByCursor(immediateGame, 2)
  assert.equal(immediateFrame.players.find((player) => player.id === 1).alive, false)
}))

test('replay current speaker highlights speak logs and ignores sheriff run choices', () => withWindow(() => {
  const state = useGameState()
  const history = useGameHistory(state, { installLifecycle: false, apiFetch: async () => ({}) })
  const source = game('history-current-speaker', {
    logs: [
      { type: 'setup', day: 1, phase: 'setup', message: 'start', speaker: '法官' },
      { type: 'sheriff_run', day: 1, phase: 'sheriff_election', actor_id: 1, message: '1号上警', speaker: '1号' },
      { type: 'speak', day: 1, phase: 'speech', actor_id: 2, message: '2号发言', speaker: '2号' }
    ]
  })

  const runFrame = history.buildReplaySnapshotByCursor(source, 2)
  assert.equal(runFrame.current_speaker_id, null)

  const speakFrame = history.buildReplaySnapshotByCursor(source, 3)
  assert.equal(speakFrame.current_speaker_id, 2)
}))

test('replay snapshots rebuild vote tally from replay progress', () => withWindow(() => {
  const state = useGameState()
  state.selectedHistoryGame.value = game('history-vote-tally', {
    vote_tally: [{ target_id: 9, count: 7, voter_ids: [1, 2, 3, 4, 5, 6, 7] }],
    logs: [
      { type: 'setup', day: 1, phase: 'setup', message: 'start', speaker: '法官' },
      { type: 'speech', day: 1, phase: 'speech', actor_id: 1, message: 'claim', speaker: '1号' },
      { type: 'vote_prompt', day: 1, phase: 'vote', message: 'vote', speaker: '法官' },
      { type: 'vote', day: 1, phase: 'vote', actor_id: 1, target_id: 2, message: '1 vote 2', speaker: '1号' },
      { type: 'vote', day: 1, phase: 'vote', actor_id: 2, target_id: 1, message: '2 vote 1', speaker: '2号' },
      { type: 'night_start', day: 2, phase: 'night', message: 'night', speaker: '法官' }
    ],
    decisions: [
      { action: 'vote', actor_id: 1, target_id: 2, day: 1, phase: 'vote' },
      { action: 'vote', actor_id: 2, target_id: 1, day: 1, phase: 'vote' }
    ]
  })
  const history = useGameHistory(state, { installLifecycle: false, apiFetch: async () => ({}) })

  const speechFrame = history.buildReplaySnapshotByCursor(state.selectedHistoryGame.value, 2)
  assert.deepEqual(speechFrame.vote_tally, [])

  const firstVoteFrame = history.buildReplaySnapshotByCursor(state.selectedHistoryGame.value, 4)
  assert.deepEqual(firstVoteFrame.vote_tally, [{ target_id: 2, count: 1, voter_ids: [1] }])

  const nightFrame = history.buildReplaySnapshotByCursor(state.selectedHistoryGame.value, 6)
  assert.deepEqual(nightFrame.vote_tally, [])
}))

test('replay cursor waits for vote result logs before showing decision tally', () => withWindow(() => {
  const state = useGameState()
  const history = useGameHistory(state, { installLifecycle: false, apiFetch: async () => ({}) })
  const source = game('history-vote-result-gate', {
    logs: [
      { type: 'setup', day: 1, phase: 'setup', message: 'start', speaker: '法官' },
      { type: 'exile_vote_start', day: 1, phase: 'vote', message: '开始投票', speaker: '法官' },
      { type: 'exile_vote_end', day: 1, phase: 'vote', target_id: 2, message: '2号出局', speaker: '法官' }
    ],
    decisions: [
      { action: 'exile_vote', actor_id: 1, target_id: 2, day: 1, phase: 'vote' },
      { action: 'exile_vote', actor_id: 2, target_id: 1, day: 1, phase: 'vote' },
      { action: 'exile_vote', actor_id: 3, target_id: 2, day: 1, phase: 'vote' },
      { action: 'exile_vote', actor_id: 4, target_id: 2, day: 1, phase: 'vote' }
    ]
  })

  const startFrame = history.buildReplaySnapshotByCursor(source, 2)
  assert.deepEqual(startFrame.decisions, [])
  assert.deepEqual(startFrame.vote_tally, [])

  const endFrame = history.buildReplaySnapshotByCursor(source, 3)
  assert.deepEqual(endFrame.vote_tally, [
    { target_id: 2, count: 3, voter_ids: [1, 3, 4] },
    { target_id: 1, count: 1, voter_ids: [2] }
  ])
}))

test('replay/history separates legacy exile and PK votes that share phase vote', () => withWindow(() => {
  const state = useGameState()
  const history = useGameHistory(state, { installLifecycle: false, apiFetch: async () => ({}) })
  const players = Array.from({ length: 6 }, (_, index) => ({
    id: index + 1,
    seat: index + 1,
    name: `${index + 1}号`,
    role_hint: '村民',
    alive: true
  }))
  const source = game('history-legacy-exile-pk-votes', {
    players,
    logs: [
      { type: 'setup', day: 1, phase: 'setup', message: 'start', speaker: '法官' },
      { type: 'exile_vote_start', day: 1, phase: 'vote', message: '开始放逐投票', speaker: '法官' },
      { type: 'exile_vote_end', day: 1, phase: 'vote', target_id: 4, message: '4号进入对决', speaker: '法官' },
      { type: 'pk_vote_start', day: 1, phase: 'vote', message: '开始对决投票', speaker: '法官' },
      { type: 'pk_vote_end', day: 1, phase: 'vote', target_id: 6, message: '6号出局', speaker: '法官' }
    ],
    decisions: [
      { action: 'exile_vote', actor_id: 1, target_id: 4, day: 1, phase: 'vote' },
      { action: 'exile_vote', actor_id: 2, target_id: 4, day: 1, phase: 'vote' },
      { action: 'exile_vote', actor_id: 3, target_id: 5, day: 1, phase: 'vote' },
      { action: 'pk_vote', actor_id: 1, target_id: 6, day: 1, phase: 'vote' },
      { action: 'pk_vote', actor_id: 2, target_id: 6, day: 1, phase: 'vote' },
      { action: 'pk_vote', actor_id: 3, target_id: 5, day: 1, phase: 'vote' }
    ]
  })

  const exileStartFrame = history.buildReplaySnapshotByCursor(source, 2)
  assert.equal(exileStartFrame.phase, 'exile_vote')
  assert.deepEqual(exileStartFrame.vote_tally, [])

  const exileEndFrame = history.buildReplaySnapshotByCursor(source, 3)
  assert.equal(exileEndFrame.phase, 'exile_vote')
  assert.deepEqual(exileEndFrame.vote_tally, [
    { target_id: 4, count: 2, voter_ids: [1, 2] },
    { target_id: 5, count: 1, voter_ids: [3] }
  ])

  const pkStartFrame = history.buildReplaySnapshotByCursor(source, 4)
  assert.equal(pkStartFrame.phase, 'pk_vote')
  assert.deepEqual(pkStartFrame.vote_tally, [])

  const pkEndFrame = history.buildReplaySnapshotByCursor(source, 5)
  assert.equal(pkEndFrame.phase, 'pk_vote')
  assert.deepEqual(pkEndFrame.vote_tally, [
    { target_id: 6, count: 2, voter_ids: [1, 2] },
    { target_id: 5, count: 1, voter_ids: [3] }
  ])

  state.selectedHistoryGame.value = source
  state.selectedHistoryPageKey.value = 'day-1-exile_vote'
  assert.deepEqual(state.voteDecisions.value.map((decision) => decision.action), ['exile_vote', 'exile_vote', 'exile_vote'])
  assert.deepEqual(state.currentVoteTally.value, [
    { target: '4号', targetName: '4号', count: 2, voters: ['1号', '2号'] },
    { target: '5号', targetName: '5号', count: 1, voters: ['3号'] }
  ])

  state.selectedHistoryPageKey.value = 'day-1-pk_vote'
  assert.deepEqual(state.voteDecisions.value.map((decision) => decision.action), ['pk_vote', 'pk_vote', 'pk_vote'])
  assert.deepEqual(state.currentVoteTally.value, [
    { target: '6号', targetName: '6号', count: 2, voters: ['1号', '2号'] },
    { target: '5号', targetName: '5号', count: 1, voters: ['3号'] }
  ])
}))
