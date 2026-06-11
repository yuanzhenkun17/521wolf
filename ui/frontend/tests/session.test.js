import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'vitest'
import { createRenderer, nextTick, ref } from 'vue'
import { useGameState } from '../src/composables/useGameState.ts'
import { useGameActions } from '../src/composables/useGameActions.ts'
import { useGameHistory } from '../src/composables/useGameHistory.ts'
import { useGameAudio } from '../src/composables/useGameAudio.ts'
import { useEvolutionWorkbench } from '../src/composables/useEvolutionWorkbench.ts'
import { useEvaluationWorkbench } from '../src/composables/useEvaluationWorkbench.ts'
import { createNoticeAutoDismiss } from '../src/composables/noticeAutoDismiss.ts'
import { normalizeGameSnapshot } from '../src/composables/gameSnapshot.ts'
import { buildSceneEffects } from '../src/composables/sceneEffects.ts'
import {
  ACTIVE_GAME_STORAGE_KEY,
  activeSessionFromGame,
  clearStoredGameSession,
  emptyActiveSession,
  isReturnableGame,
  isTerminalGame,
  readStoredGameSession,
  writeStoredGameSession
} from '../src/composables/gameSession.ts'
import { viewFromHash } from '../src/router/legacyViewNavigation'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

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
    runNextInterval() {
      const [, callback] = intervals.entries().next().value || []
      if (!callback) return false
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

async function flushPromises(count = 6) {
  for (let index = 0; index < count; index += 1) await Promise.resolve()
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

const lifecycleRenderer = createRenderer({
  patchProp() {},
  insert(child, parent, anchor = null) {
    child.parent = parent
    parent.children ||= []
    if (!anchor) {
      parent.children.push(child)
      return
    }
    const index = parent.children.indexOf(anchor)
    if (index === -1) parent.children.push(child)
    else parent.children.splice(index, 0, child)
  },
  remove(child) {
    const children = child.parent?.children
    if (!children) return
    const index = children.indexOf(child)
    if (index >= 0) children.splice(index, 1)
  },
  createElement(type) {
    return { type, children: [] }
  },
  createText(text) {
    return { type: 'text', text }
  },
  createComment(text) {
    return { type: 'comment', text }
  },
  setText(node, text) {
    node.text = text
  },
  setElementText(node, text) {
    node.children = [text]
  },
  parentNode(node) {
    return node.parent || null
  },
  nextSibling(node) {
    const children = node.parent?.children || []
    const index = children.indexOf(node)
    return index >= 0 ? children[index + 1] || null : null
  }
})

function mountLifecycleComposable(setup) {
  const root = { type: 'root', children: [] }
  const app = lifecycleRenderer.createApp({
    setup() {
      setup()
      return () => null
    }
  })
  app.mount(root)
  return () => app.unmount()
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

function historyPhasePath(gameId, { day = 1, phase = 'setup', logOffset = 0, logLimit = 1000, decisionOffset = 0, decisionLimit = 500 } = {}) {
  const params = new URLSearchParams()
  params.set('day', String(day))
  params.set('phase', phase)
  params.set('log_offset', String(logOffset))
  params.set('log_limit', String(logLimit))
  params.set('decision_offset', String(decisionOffset))
  params.set('decision_limit', String(decisionLimit))
  return `/games/${encodeURIComponent(gameId)}/phase?${params.toString()}`
}

test('game actions use route-first view navigation instead of direct hash writes', () => {
  const source = readSource('../src/composables/useGameActions.ts')

  assert.match(
    source,
    /import \{[^}]*currentLegacyView[^}]*writeCurrentViewRoute[^}]*\} from '..\/router\/legacyViewNavigation'/
  )
  assert.doesNotMatch(source, /\bwriteViewHash\b/)
  assert.doesNotMatch(source, /state\.currentView\.value\s*=(?!=)/)
  assert.match(source, /syncCurrentViewToLegacyHash\(state\.currentView, 'match'\)/)
  assert.match(source, /writeCurrentViewRoute\(state\.currentView, 'match'\)/)
  assert.match(source, /writeCurrentViewRoute\(state\.currentView, 'lobby'\)/)
})

test('match boot overlay includes replay model loading', () => {
  const source = readSource('../src/App.vue')

  assert.doesNotMatch(source, /&&\s*!replayStore\.isReplayMode/)
  assert.match(source, /const matchGamePresent = computed\(\(\) => replayStore\.isReplayMode/)
  assert.match(source, /!matchGamePresent\.value/)
  assert.match(source, /读取回放/)
  assert.match(source, /加载回放模型/)
})

test('game history uses route-first view navigation instead of direct view or hash writes', () => {
  const source = readSource('../src/composables/useGameHistory.ts')

  assert.match(
    source,
    /import \{[^}]*currentLegacyHash[^}]*syncCurrentViewToLegacyHash[^}]*writeCurrentViewRoute[^}]*writeViewRoute[^}]*\} from '..\/router\/legacyViewNavigation'/
  )
  assert.doesNotMatch(source, /state\.currentView\.value\s*=(?!=)/)
  assert.doesNotMatch(source, /window\.location\.hash\s*=/)
  assert.match(source, /writeCurrentViewRoute\(state\.currentView, view, query, options\)/)
  assert.match(source, /syncCurrentViewToLegacyHash\(state\.currentView, view\)/)
  assert.match(source, /writeLogsRoute\(\{ gameId: targetGameId, workspace: targetWorkspace \}, state\.currentView\)/)
})

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

test('game state initializes the current view from the legacy hash', () => withWindow(() => {
  const state = useGameState()

  assert.equal(state.currentView.value, 'benchmark')
}, { hash: '#benchmark?batch_id=bench-run-7' }))

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

test('history replay waits for council models before completing match entry', () => withWindow(async () => {
  const state = useGameState()
  const ready = createDeferred()
  let waitForModels = 0
  let syncScene = 0
  let history

  state.selectedHistoryGame.value = game('history-replay-ready', {
    winner: 'villagers',
    logs: [
      { type: 'setup', day: 1, phase: 'setup', message: 'start', speaker: '法官' },
      { type: 'speech', day: 1, phase: 'speech', actor_id: 1, message: 'hello', speaker: '1号' }
    ]
  })

  const unmount = mountLifecycleComposable(() => {
    history = useGameHistory(state, {
      apiFetch: async () => ({ games: [], pagination: { total: 0, offset: 0, limit: 8, returned: 0, has_more: false } }),
      sceneApi: {
        waitForCouncilModels() {
          waitForModels += 1
          return ready.promise
        },
        scheduleSyncCouncilScene() {
          syncScene += 1
        }
      }
    })
  })

  history.enterReplayAt(1)
  await flushPromises()

  assert.equal(state.isReplayMode.value, true)
  assert.equal(state.currentView.value, 'match')
  assert.equal(state.replayGame.value.game_id, 'history-replay-ready')
  assert.equal(state.judgeBoardStarted.value, true)
  assert.equal(state.judgeBoardStarting.value, true)
  assert.equal(state.roleAssignmentComplete.value, false)
  assert.equal(waitForModels, 1)

  ready.resolve()
  await flushPromises(10)

  assert.equal(state.judgeBoardStarting.value, false)
  assert.equal(state.roleAssignmentComplete.value, true)
  assert.equal(syncScene >= 1, true)
  unmount()
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

test('exitGame returns to lobby without waiting for stop response', () => withWindow(async () => {
  const state = useGameState()
  const stopRequest = createDeferred()
  const stoppedPaths = []
  state.liveGame.value = game('slow-stop-game')
  state.currentView.value = 'match'

  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path) => {
      stoppedPaths.push(path)
      return stopRequest.promise
    }
  })

  await actions.exitGame()

  assert.deepEqual(stoppedPaths, ['/games/slow-stop-game/stop'])
  assert.equal(state.liveGame.value, null)
  assert.equal(state.currentView.value, 'lobby')
  assert.equal(state.loading.value, false)

  stopRequest.resolve({})
  await stopRequest.promise
}))

test('exitGame reports a warning when the background stop request fails', () => withWindow(async () => {
  const state = useGameState()
  state.liveGame.value = game('stop-fails')
  state.currentView.value = 'match'

  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path) => {
      if (path === '/games/stop-fails/stop') throw new Error('Failed to fetch')
      throw new Error(`unexpected ${path}`)
    }
  })

  await actions.exitGame()
  await flushPromises()

  assert.equal(state.liveGame.value, null)
  assert.equal(state.currentView.value, 'lobby')
  assert.deepEqual(state.matchNotice.value, {
    type: 'warning',
    message: '已返回大厅，但后台停止对局失败。'
  })
  assert.equal(state.error.value, '已返回大厅，但后台停止对局失败。')
}))

test('startMode reports a local notice when the backend is offline', () => withWindow(async () => {
  const state = useGameState()
  state.backendMode.value = 'offline'
  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async () => {
      throw new Error('should not call api')
    }
  })

  const started = await actions.startMode({ mode: 'watch' })

  assert.equal(started, null)
  assert.equal(state.currentView.value, 'lobby')
  assert.deepEqual(state.matchNotice.value, {
    type: 'error',
    message: '后端未连接，请先启动 FastAPI 服务。'
  })
  assert.equal(state.error.value, '后端未连接，请先启动 FastAPI 服务。')
}))

test('startMode stays in the lobby when model preflight rejects game start', () => withWindow(async () => {
  const state = useGameState()
  state.backendMode.value = 'api'
  state.currentView.value = 'lobby'
  const paths = []
  const message = '模型连接不可用，不能开始游戏。'
  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path) => {
      paths.push(path)
      if (path === '/games') throw new Error(message)
      if (path === '/health') return { mode: 'api', external: { supports_human: true } }
      throw new Error(`unexpected ${path}`)
    }
  })

  const started = await actions.startMode({ mode: 'watch' })

  assert.equal(started, null)
  assert.deepEqual(paths, ['/games', '/health'])
  assert.equal(state.currentView.value, 'lobby')
  assert.equal(window.location.hash, '')
  assert.equal(state.liveGame.value, null)
  assert.equal(state.loading.value, false)
  assert.equal(state.judgeBoardStarted.value, false)
  assert.equal(state.judgeBoardStarting.value, false)
  assert.deepEqual(state.matchNotice.value, { type: 'error', message })
  assert.equal(state.error.value, message)
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

test('mounted game actions delays stored game restore away from match view', () => withWindow(async ({ timers }) => {
  const state = useGameState()
  const restored = game('stored-game')
  writeStoredGameSession(restored)
  const requests = []

  const unmount = mountLifecycleComposable(() => {
    useGameActions(state, {
      apiFetch: async (path) => {
        requests.push(path)
        if (path === '/health') return { mode: 'api', external: { supports_human: true } }
        if (path === '/games/stored-game') return restored
        throw new Error(`unexpected ${path}`)
      }
    })
  })

  await nextTick()
  await flushPromises()
  assert.deepEqual(requests, ['/health'])
  assert.equal(state.liveGame.value, null)
  assert.equal(timers.timeoutCount(), 1)

  timers.runNextTimeout()
  await flushPromises()

  assert.equal(requests.includes('/games/stored-game'), true)
  assert.equal(state.liveGame.value?.game_id, 'stored-game')
  assert.equal(state.currentView.value, 'benchmark')
  unmount()
}, { hash: '#benchmark' }))

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
  assert.deepEqual(state.matchNotice.value, {
    type: 'success',
    message: '女巫行动已提交。'
  })
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
  assert.deepEqual(state.matchNotice.value, {
    type: 'success',
    message: '行动已提交。'
  })
}))

test('submitHumanAction reports a localized error notice when the backend rejects the action', () => withWindow(async () => {
  const state = useGameState()
  const initial = normalizeGameSnapshot(game('reject-action', {
    mode: 'play',
    human_player_id: 1,
    phase: 'vote',
    players: [
      { id: 1, seat: 1, name: '1号', role_hint: '村民', alive: true },
      { id: 2, seat: 2, name: '2号', role_hint: '狼人', alive: true }
    ],
    pending_human_action: {
      action_type: 'exile_vote',
      player_id: 1,
      candidate_ids: [2]
    }
  }), { mode: 'play' })
  state.liveGame.value = initial
  state.actionTarget.value = 2

  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path) => {
      if (path === '/games/reject-action/action') throw new Error('no pending human action')
      if (path === '/games/reject-action') return initial
      throw new Error(`unexpected ${path}`)
    }
  })

  await actions.submitVote()

  assert.deepEqual(state.matchNotice.value, {
    type: 'error',
    message: '当前没有等待你处理的行动。'
  })
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
  assert.equal(window.location.hash, '#match')
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

test('startMode opens the live stream before council model warmup finishes', () => withWindow(async () => {
  const state = useGameState()
  state.backendMode.value = 'api'
  const paths = []
  let waitForModels = 0
  let syncScene = 0
  const watchGame = game('wait-scene-game', {
    mode: 'watch',
    human_player_id: null,
    pending_human_action: null,
    player_count: 12,
    players: Array.from({ length: 12 }, (_, index) => ({
      id: index + 1,
      seat: index + 1,
      name: `${index + 1}号`,
      role_hint: index === 0 ? '村民' : '狼人',
      alive: true
    }))
  })
  const actions = useGameActions(state, {
    sceneApi: {
      waitForCouncilModels() {
        waitForModels += 1
        return new Promise(() => {})
      },
      scheduleSyncCouncilScene() {
        syncScene += 1
      }
    },
    apiFetch: async (path) => {
      paths.push(path)
      if (path === '/games') return watchGame
      if (path === '/health') return { mode: 'api', external: { supports_human: true } }
      throw new Error(`unexpected ${path}`)
    }
  })

  let resolved = false
  const started = actions.startMode({ mode: 'watch' }).then(() => {
    resolved = true
  })
  await flushPromises()

  await started

  assert.deepEqual(paths, ['/games', '/health'])
  assert.equal(resolved, true)
  assert.equal(window.location.hash, '#match')
  assert.equal(state.liveGame.value.game_id, 'wait-scene-game')
  assert.equal(state.judgeBoardStarted.value, true)
  assert.equal(state.judgeBoardStarting.value, false)
  assert.equal(state.roleAssignmentComplete.value, true)
  assert.equal(state.watchRunning.value, true)
  assert.equal(waitForModels, 0)
  assert.equal(syncScene >= 1, true)
}, {
  eventSource: class FakeEventSource {
    constructor() {}
    addEventListener() {}
    close() {}
  }
}))

test('resetGame restarts the match and warns when stopping the old game fails', () => withWindow(async () => {
  const state = useGameState()
  const paths = []
  const nextGame = game('reset-next', {
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
  state.liveGame.value = game('reset-old', { mode: 'watch' })

  const actions = useGameActions(state, {
    installLifecycle: false,
    apiFetch: async (path) => {
      paths.push(path)
      if (path === '/games/reset-old/stop') throw new Error('stop failed')
      if (path === '/games') return nextGame
      if (path === '/games/reset-next?advance=1') return nextGame
      if (path === '/health') return { mode: 'mock', external: { supports_human: true } }
      throw new Error(`unexpected ${path}`)
    }
  })

  await actions.resetGame()

  assert.deepEqual(paths, [
    '/games/reset-old/stop',
    '/games',
    '/games/reset-next?advance=1',
    '/health'
  ])
  assert.equal(state.liveGame.value.game_id, 'reset-next')
  assert.deepEqual(state.matchNotice.value, {
    type: 'warning',
    message: '已重开对局；旧对局后台停止失败。'
  })
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

test('startMode sends the selected model profile to game start', () => withWindow(async () => {
  const state = useGameState()
  let startBody = null
  const watchGame = game('profile-watch-game', {
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
      if (path === '/games/profile-watch-game?advance=1') return watchGame
      if (path === '/health') return { mode: 'mock', external: { supports_human: true } }
      throw new Error(`unexpected ${path}`)
    }
  })

  await actions.startMode({ mode: 'watch', options: { model_profile_id: 'profile-game-main' } })

  assert.equal(startBody.model_profile_id, 'profile-game-main')
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
  assert.equal(villagerView.find((player) => player.id === 3).roleIcon, '/role-icons/optimized/未知.webp')

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

test('watch TTS backpressure queues SSE events and pauses live polling', () => withWindow(async ({ timers }) => {
  const instances = []
  class FakeEventSource {
    constructor(url) {
      this.url = url
      this.listeners = {}
      instances.push(this)
    }

    addEventListener(type, callback) {
      this.listeners[type] = callback
    }

    close() {}

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
  const state = useGameState()
  const requests = []
  const ttsNarrationActive = ref(true)
  state.backendMode.value = 'api'
  state.liveGame.value = game('sse-tts-pause', {
    mode: 'watch',
    phase: 'speech',
    waiting_for: 'none',
    logs: []
  })
  const actions = useGameActions(state, {
    installLifecycle: false,
    apiBase: '/api',
    apiFetch: async (path) => {
      requests.push(path)
      if (path === '/games/sse-tts-pause') return state.liveGame.value
      throw new Error(`unexpected ${path}`)
    }
  })
  actions.setAudioApi({ ttsNarrationActive })

  actions.startWatch()
  assert.equal(instances.length, 1)
  assert.equal(timers.intervalCount(), 1)

  timers.runNextInterval()
  await flushPromises()
  assert.deepEqual(requests, [])

  await instances[0].emit('log', {
    type: 'speech',
    actor_id: 1,
    speaker: '1号',
    message: '第一句',
    visibility: 'public'
  }, { lastEventId: '1' })
  assert.equal(state.liveGame.value.logs.length, 0)

  ttsNarrationActive.value = false
  await nextTick()
  await flushPromises(10)
  assert.equal(state.liveGame.value.logs.length, 1)
  assert.equal(state.liveGame.value.logs[0].message, '第一句')

  timers.runNextInterval()
  await flushPromises()
  assert.deepEqual(requests, ['/games/sse-tts-pause'])

  await instances[0].emit('log', {
    type: 'speech',
    actor_id: 2,
    speaker: '2号',
    message: '第二句',
    visibility: 'public'
  }, { lastEventId: '2' })
  await flushPromises()
  assert.equal(state.liveGame.value.logs.length, 2)
  assert.equal(state.liveGame.value.logs[1].message, '第二句')
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
    await flushPromises()

    assert.equal(timers.timeoutCount(), 1)
    assert.match(audio.ttsError.value, /发言朗读/)
    audio.dispose()
    assert.equal(timers.timeoutCount(), 0)
  } finally {
    if (originalFetch === undefined) delete globalThis.fetch
    else globalThis.fetch = originalFetch
  }
}))

test('game audio reads the latest speech after role assignment completes', () => withWindow(async () => {
  const originalFetch = globalThis.fetch
  const requests = []
  const startedAt = []

  class FakeAudioContext {
    constructor() {
      this.currentTime = 1
      this.destination = {}
      this.state = 'running'
    }
    createBuffer(_channels, frameCount, sampleRate) {
      return {
        duration: frameCount / sampleRate,
        getChannelData: () => new Float32Array(frameCount)
      }
    }
    createBufferSource() {
      return {
        connect() {},
        disconnect() {},
        start: (when) => startedAt.push(when),
        stop() {}
      }
    }
    createGain() {
      return {
        gain: { value: 0 },
        connect() {},
        disconnect() {}
      }
    }
    resume() {
      return Promise.resolve()
    }
    close() {
      return Promise.resolve()
    }
  }
  window.AudioContext = FakeAudioContext

  globalThis.fetch = async (url) => {
    requests.push(String(url))
    let reads = 0
    return {
      ok: true,
      headers: { get: (key) => key === 'X-TTS-Sample-Rate' ? '24000' : null },
      body: {
        getReader: () => ({
          async read() {
            reads += 1
            return reads === 1
              ? { done: false, value: new Uint8Array([0, 0, 255, 127]) }
              : { done: true }
          },
          releaseLock() {}
        })
      }
    }
  }

  try {
    const runtime = {
      currentView: ref('match'),
      game: ref(null),
      isReplayMode: ref(false),
      externalStatus: ref({ tts: 'configured' }),
      apiBase: ref('/api'),
      roleAssignmentComplete: ref(false)
    }
    const audio = useGameAudio(runtime, { installLifecycle: false })

    runtime.game.value = game('audio-role-ready-tts', {
      phase: 'speech',
      waiting_for: 'speech',
      logs: [
        { type: 'speech', actor_id: 3, speaker: '3号', message: '我先起跳预言家。', visibility: 'public' }
      ]
    })
    await nextTick()
    await flushPromises()

    assert.deepEqual(requests, [])

    runtime.roleAssignmentComplete.value = true
    await nextTick()
    await flushPromises()

    assert.deepEqual(requests, ['/api/tts/speech/stream'])
    assert.equal(startedAt.length, 1)
    audio.dispose()
  } finally {
    if (originalFetch === undefined) delete globalThis.fetch
    else globalThis.fetch = originalFetch
  }
}))

test('game audio uses the realtime TTS stream endpoint', () => withWindow(async () => {
  const originalFetch = globalThis.fetch
  const requests = []
  const startedAt = []

  class FakeAudioContext {
    constructor() {
      this.currentTime = 1
      this.destination = {}
      this.state = 'running'
    }
    createBuffer(channels, frameCount, sampleRate) {
      assert.equal(channels, 1)
      assert.equal(sampleRate, 24000)
      return {
        duration: frameCount / sampleRate,
        getChannelData: () => new Float32Array(frameCount)
      }
    }
    createBufferSource() {
      return {
        connect() {},
        disconnect() {},
        start: (when) => startedAt.push(when),
        stop() {}
      }
    }
    createGain() {
      return {
        gain: { value: 0 },
        connect() {},
        disconnect() {}
      }
    }
    resume() {
      return Promise.resolve()
    }
    close() {
      return Promise.resolve()
    }
  }
  window.AudioContext = FakeAudioContext

  globalThis.fetch = async (url) => {
    requests.push(String(url))
    assert.equal(String(url), '/api/tts/speech/stream')
    let reads = 0
    return {
      ok: true,
      headers: { get: (key) => key === 'X-TTS-Sample-Rate' ? '24000' : null },
      body: {
        getReader: () => ({
          async read() {
            reads += 1
            return reads === 1
              ? { done: false, value: new Uint8Array([0, 0, 255, 127]) }
              : { done: true }
          },
          releaseLock() {}
        })
      }
    }
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

    runtime.game.value = game('audio-stream-tts', { phase: 'speech', waiting_for: 'speech', logs: [] })
    await nextTick()
    runtime.game.value = game('audio-stream-tts', {
      phase: 'speech',
      waiting_for: 'speech',
      logs: [
        { type: 'speech', actor_id: 2, speaker: '2号', message: '我这里先表水。', visibility: 'public' }
      ]
    })
    await nextTick()
    await flushPromises()

    assert.deepEqual(requests, ['/api/tts/speech/stream'])
    assert.equal(startedAt.length, 1)
    audio.dispose()
  } finally {
    if (originalFetch === undefined) delete globalThis.fetch
    else globalThis.fetch = originalFetch
  }
}))

test('game audio queues player speeches without interrupting active TTS', () => withWindow(async ({ timers }) => {
  const originalFetch = globalThis.fetch
  const requests = []
  const sources = []
  const stoppedSources = []

  class FakeAudioContext {
    constructor() {
      this.currentTime = 1
      this.destination = {}
      this.state = 'running'
    }
    createBuffer(_channels, frameCount, sampleRate) {
      return {
        duration: frameCount / sampleRate,
        getChannelData: () => new Float32Array(frameCount)
      }
    }
    createBufferSource() {
      const source = {
        onended: null,
        connect() {},
        disconnect() {},
        start() {
          sources.push(source)
        },
        stop() {
          stoppedSources.push(source)
        }
      }
      return source
    }
    createGain() {
      return {
        gain: { value: 0 },
        connect() {},
        disconnect() {}
      }
    }
    resume() {
      return Promise.resolve()
    }
    close() {
      return Promise.resolve()
    }
  }
  window.AudioContext = FakeAudioContext

  globalThis.fetch = async (_url, options = {}) => {
    requests.push(JSON.parse(options.body))
    let reads = 0
    return {
      ok: true,
      headers: { get: (key) => key === 'X-TTS-Sample-Rate' ? '24000' : null },
      body: {
        getReader: () => ({
          async read() {
            reads += 1
            return reads === 1
              ? { done: false, value: new Uint8Array([0, 0, 255, 127]) }
              : { done: true }
          },
          releaseLock() {}
        })
      }
    }
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
    const firstSpeech = { type: 'speech', actor_id: 1, speaker: '1号', message: '我先发言。', visibility: 'public' }
    const secondSpeech = { type: 'speech', actor_id: 2, speaker: '2号', message: '我接着发言。', visibility: 'public' }

    runtime.game.value = game('audio-queued-tts', {
      phase: 'speech',
      waiting_for: 'speech',
      logs: [firstSpeech]
    })
    await nextTick()
    await flushPromises(10)

    assert.equal(requests.length, 1)
    assert.match(requests[0].text, /我先发言。$/)
    assert.equal(sources.length, 1)
    assert.equal(audio.ttsNarrationActive.value, true)

    runtime.game.value = game('audio-queued-tts', {
      phase: 'speech',
      waiting_for: 'speech',
      logs: [firstSpeech, secondSpeech]
    })
    await nextTick()
    await flushPromises(10)

    assert.equal(requests.length, 1)
    assert.match(requests[0].text, /我先发言。$/)
    assert.equal(stoppedSources.length, 0)
    assert.equal(audio.ttsQueuedCount.value, 1)

    sources[0].onended?.()
    assert.equal(timers.timeoutCount(), 1)
    timers.runNextTimeout()
    await flushPromises(10)

    assert.equal(requests.length, 2)
    assert.match(requests[0].text, /我先发言。$/)
    assert.match(requests[1].text, /我接着发言。$/)
    assert.equal(stoppedSources.length, 0)
    audio.dispose()
  } finally {
    if (originalFetch === undefined) delete globalThis.fetch
    else globalThis.fetch = originalFetch
  }
}))

test('game audio does not scan or request TTS outside match view', () => withWindow(async () => {
  const originalFetch = globalThis.fetch
  const requests = []
  globalThis.fetch = async (url) => {
    requests.push(String(url))
    throw new Error('tts should stay idle outside match')
  }

  try {
    const runtime = {
      currentView: ref('benchmark'),
      game: ref(null),
      isReplayMode: ref(false),
      externalStatus: ref({ tts: 'configured' }),
      apiBase: ref('/api'),
      roleAssignmentComplete: ref(true)
    }
    const audio = useGameAudio(runtime, { installLifecycle: false })

    runtime.game.value = game('audio-idle-tts', {
      phase: 'speech',
      waiting_for: 'speech',
      logs: [
        { type: 'speech', actor_id: 1, speaker: '1号', message: '我这里先表水。', visibility: 'public' }
      ]
    })
    await nextTick()
    await flushPromises()

    assert.deepEqual(requests, [])
    audio.dispose()
  } finally {
    if (originalFetch === undefined) delete globalThis.fetch
    else globalThis.fetch = originalFetch
  }
}))

test('game audio never requests TTS in replay mode', () => withWindow(async () => {
  const originalFetch = globalThis.fetch
  const requests = []
  globalThis.fetch = async (url) => {
    requests.push(String(url))
    throw new Error('tts should stay disabled in replay')
  }

  try {
    const runtime = {
      currentView: ref('match'),
      game: ref(null),
      isReplayMode: ref(true),
      externalStatus: ref({ tts: 'configured' }),
      apiBase: ref('/api'),
      roleAssignmentComplete: ref(true)
    }
    const audio = useGameAudio(runtime, { installLifecycle: false })

    runtime.game.value = game('audio-replay-tts', {
      phase: 'speech',
      waiting_for: 'speech',
      logs: [
        { type: 'speech', actor_id: 1, speaker: '1号', message: '这句来自回放。', visibility: 'public' }
      ]
    })
    await nextTick()
    await flushPromises()
    audio.toggleTts()
    await flushPromises()

    assert.deepEqual(requests, [])
    assert.equal(audio.ttsNarrationActive.value, false)
    audio.dispose()
  } finally {
    if (originalFetch === undefined) delete globalThis.fetch
    else globalThis.fetch = originalFetch
  }
}))

test('mounted history does not prefetch the game list outside logs by default', () => withWindow(async () => {
  const state = useGameState()
  const requests = []

  const unmount = mountLifecycleComposable(() => {
    useGameHistory(state, {
      apiFetch: async (path) => {
        requests.push(path)
        return { games: [], pagination: { total: 0, offset: 0, limit: 8, returned: 0, has_more: false } }
      }
    })
  })

  await nextTick()
  await flushPromises()

  assert.deepEqual(requests, [])
  assert.deepEqual(state.gameHistory.value, [])
  unmount()
}))

test('opening logs loads the first listed game detail by default', () => withWindow(async () => {
  const state = useGameState()
  const requests = []
  const rows = [
    game('history-first', { winner: 'villagers' }),
    game('history-second', { winner: 'werewolves' })
  ]
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/games?limit=2&offset=0') {
      return {
        games: rows,
        pagination: { total: rows.length, offset: 0, limit: 2, returned: rows.length, has_more: false }
      }
    }
    if (path === '/games/history-first?view=history-shell') {
      return game('history-first', {
        day: 3,
        winner: 'villagers',
        phases: [{ key: 'day-1-setup', day: 1, phase: 'setup', log_count: 1 }]
      })
    }
    if (path === historyPhasePath('history-first')) {
      return {
        game_id: 'history-first',
        day: 1,
        phase: 'setup',
        logs: [{ sequence: 1, day: 1, phase: 'setup', event_type: 'game_init', message: 'started' }],
        decisions: []
      }
    }
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    historyListLimit: 2,
    apiFetch
  })

  await history.openLogPage()

  assert.deepEqual(requests, [
    '/games?limit=2&offset=0',
    '/games/history-first?view=history-shell',
    historyPhasePath('history-first')
  ])
  assert.equal(state.currentView.value, 'logs')
  assert.equal(state.selectedHistoryGameId.value, 'history-first')
  assert.equal(state.selectedHistoryGame.value.game_id, 'history-first')
  assert.equal(state.selectedHistoryGame.value.day, 1)
  assert.equal(state.selectedHistoryGame.value.logs[0].message, 'started')
}))

test('history detail and replay preserve evidence source context for benchmark games', () => withWindow(async () => {
  const state = useGameState()
  const requests = []
  const evidenceSource = {
    log_source: 'benchmark',
    log_source_label: '批量评测',
    source_run_id: 'bench_run_42',
    source_phase: 'battle',
    source_phase_label: '对战',
    seed: 4242,
    role_versions: { seer: 'seer_canary' }
  }
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/games?limit=2&offset=0') {
      return {
        games: [
          game('benchmark-context', {
            log_source: 'benchmark',
            source_run_id: 'bench_run_42',
            source_phase: 'battle',
            seed: 4242,
            role_versions: { seer: 'seer_canary' },
            evidence_source: evidenceSource
          })
        ],
        pagination: { total: 1, offset: 0, limit: 2, returned: 1, has_more: false }
      }
    }
    if (path === '/games/benchmark-context?view=history-shell') {
      return game('benchmark-context', {
        detail_view: 'history-shell',
        log_source: 'benchmark',
        source_run_id: 'bench_run_42',
        source_phase: 'battle',
        seed: 4242,
        role_versions: { seer: 'seer_canary' },
        evidence_source: evidenceSource,
        phases: [{ key: 'day-1-setup', day: 1, phase: 'setup', log_count: 1 }]
      })
    }
    if (path === historyPhasePath('benchmark-context')) {
      return {
        game_id: 'benchmark-context',
        day: 1,
        phase: 'setup',
        logs: [{ sequence: 1, day: 1, phase: 'setup', event_type: 'game_init', message: 'benchmark started' }],
        decisions: []
      }
    }
    if (path === '/games/benchmark-context/replay?cursor=0&limit=500') {
      return {
        game_id: 'benchmark-context',
        log_source: 'benchmark',
        source_run_id: 'bench_run_42',
        source_phase: 'battle',
        seed: 4242,
        role_versions: { seer: 'seer_canary' },
        evidence_source: evidenceSource,
        logs: [{ sequence: 1, day: 1, phase: 'setup', event_type: 'game_init', message: 'benchmark replay' }],
        decisions: [],
        event_count: 1,
        cursor: 0,
        limit: 500,
        next_cursor: 1,
        has_more: false
      }
    }
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    historyListLimit: 2,
    apiFetch
  })

  await history.openLogPage()

  assert.equal(state.selectedHistoryGame.value.log_source, 'benchmark')
  assert.equal(state.selectedHistoryGame.value.source_run_id, 'bench_run_42')
  assert.deepEqual(state.selectedHistoryGame.value.role_versions, { seer: 'seer_canary' })
  assert.deepEqual(state.selectedHistoryGame.value.evidence_source, evidenceSource)

  await history.replayHistoryGame('benchmark-context')

  assert.equal(state.currentView.value, 'match')
  assert.equal(state.replayByGameId.value['benchmark-context'].source_phase, 'battle')
  assert.deepEqual(state.replayByGameId.value['benchmark-context'].role_versions, { seer: 'seer_canary' })
  assert.deepEqual(state.replayByGameId.value['benchmark-context'].evidence_source, evidenceSource)
  assert.equal(requests.includes('/games/benchmark-context/replay?cursor=0&limit=500'), true)
}))

test('logs hash deep link selects the requested benchmark replay game', () => withWindow(async () => {
  assert.equal(viewFromHash('#logs?game_id=benchmark-game-2'), 'logs')

  const state = useGameState()
  const requests = []
  const rows = [
    game('history-first', { winner: 'villagers' }),
    game('benchmark-game-2', { source: 'benchmark', winner: 'werewolves' })
  ]
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/games?limit=3&offset=0') {
      return {
        games: rows,
        pagination: { total: rows.length, offset: 0, limit: 3, returned: rows.length, has_more: false }
      }
    }
    if (path === '/games/benchmark-game-2?view=history-shell') {
      return game('benchmark-game-2', {
        source: 'benchmark',
        winner: 'werewolves',
        phases: [{ key: 'day-1-setup', day: 1, phase: 'setup', log_count: 1 }]
      })
    }
    if (path === historyPhasePath('benchmark-game-2')) {
      return {
        game_id: 'benchmark-game-2',
        day: 1,
        phase: 'setup',
        logs: [{ sequence: 1, day: 1, phase: 'setup', event_type: 'game_init', message: 'benchmark replay' }],
        decisions: []
      }
    }
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    historyListLimit: 3,
    apiFetch
  })

  history.syncHashRoute()
  await flushPromises(10)

  assert.deepEqual(requests, [
    '/games?limit=3&offset=0',
    '/games/benchmark-game-2?view=history-shell',
    historyPhasePath('benchmark-game-2')
  ])
  assert.equal(state.currentView.value, 'logs')
  assert.equal(state.selectedHistoryGameId.value, 'benchmark-game-2')
  assert.equal(state.selectedHistoryGame.value.game_id, 'benchmark-game-2')
  assert.equal(state.selectedHistoryGame.value.logs[0].message, 'benchmark replay')
}, { hash: '#logs?game_id=benchmark-game-2' }))

test('logs route query deep link selects the requested history game and workspace', () => withWindow(async () => {
  const state = useGameState()
  const requests = []
  const rows = [
    game('history-first', { winner: 'villagers' }),
    game('benchmark-game-2', { source: 'benchmark', winner: 'werewolves' })
  ]
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/games?limit=3&offset=0') {
      return {
        games: rows,
        pagination: { total: rows.length, offset: 0, limit: 3, returned: rows.length, has_more: false }
      }
    }
    if (path === '/games/benchmark-game-2?view=history-shell') {
      return game('benchmark-game-2', {
        source: 'benchmark',
        winner: 'werewolves',
        phases: [{ key: 'day-1-setup', day: 1, phase: 'setup', log_count: 1 }]
      })
    }
    if (path === historyPhasePath('benchmark-game-2')) {
      return {
        game_id: 'benchmark-game-2',
        day: 1,
        phase: 'setup',
        logs: [{ sequence: 1, day: 1, phase: 'setup', event_type: 'game_init', message: 'route replay' }],
        decisions: []
      }
    }
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    historyListLimit: 3,
    apiFetch,
    route: {
      name: 'logs',
      path: '/logs',
      query: { game_id: 'benchmark-game-2', workspace: 'archive' },
      hash: ''
    }
  })

  history.syncHashRoute()
  await flushPromises(10)

  assert.deepEqual(requests, [
    '/games?limit=3&offset=0',
    '/games/benchmark-game-2?view=history-shell',
    historyPhasePath('benchmark-game-2')
  ])
  assert.equal(state.currentView.value, 'logs')
  assert.equal(state.historyWorkspaceTab.value, 'archive')
  assert.equal(state.selectedHistoryGameId.value, 'benchmark-game-2')
  assert.equal(state.selectedHistoryGame.value.game_id, 'benchmark-game-2')
  assert.equal(state.selectedHistoryGame.value.logs[0].message, 'route replay')
  assert.equal(window.location.hash, '#logs?game_id=benchmark-game-2&workspace=archive')
}))

test('legacy evidence hash is ignored as an invalid route', () => withWindow(async () => {
  assert.equal(viewFromHash('#evidence?game_id=benchmark-game-2'), 'lobby')

  const state = useGameState()
  const requests = []
  const history = useGameHistory(state, {
    installLifecycle: false,
    historyListLimit: 3,
    apiFetch: async (path) => {
      requests.push(path)
      throw new Error(`unexpected ${path}`)
    }
  })

  history.syncHashRoute()
  await flushPromises(4)

  assert.deepEqual(requests, [])
  assert.equal(state.currentView.value, 'lobby')
  assert.equal(state.historyWorkspaceTab.value, 'phase')
  assert.equal(state.selectedHistoryGameId.value, null)
  assert.equal(state.selectedHistoryGame.value, null)
  assert.equal(state.archiveByGameId.value['benchmark-game-2'], undefined)
  assert.equal(state.reviewByGameId.value['benchmark-game-2'], undefined)
  assert.equal(window.location.hash, '#evidence?game_id=benchmark-game-2')
}, { hash: '#evidence?game_id=benchmark-game-2' }))

test('evolution hash deep links keep query when the global router opens the page', () => withWindow(() => {
  const state = useGameState()
  const history = useGameHistory(state, { installLifecycle: false, apiFetch: async () => ({}) })

  window.location.hash = '#evolution?run_id=deep-run&proposal_id=proposal-b'
  history.openEvolutionPage({ rememberOrigin: false })

  assert.equal(state.currentView.value, 'evolution')
  assert.equal(window.location.hash, '#evolution?run_id=deep-run&proposal_id=proposal-b')
}))

test('benchmark hash deep links keep query when the global router opens the page', () => withWindow(() => {
  const state = useGameState()
  const history = useGameHistory(state, { installLifecycle: false, apiFetch: async () => ({}) })

  window.location.hash = '#benchmark?batch_id=bench-run-7'
  history.openBenchmarkPage({ rememberOrigin: false })

  assert.equal(state.currentView.value, 'benchmark')
  assert.equal(window.location.hash, '#benchmark?batch_id=bench-run-7')
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
    const phaseMatch = route.match(/^\/games\/([^/]+)\/phase$/)
    if (phaseMatch) {
      const gameId = decodeURIComponent(phaseMatch[1])
      return {
        game_id: gameId,
        day: 1,
        phase: 'setup',
        logs: [{ sequence: 1, day: 1, phase: 'setup', event_type: 'game_init', message: `${gameId} started` }],
        decisions: []
      }
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
  assert.equal(state.selectedHistoryGame.value.logs[0].message, 'evolution-1 started')
  assert.equal(history.historyHasMore.value, false)
}))

test('history page changes select and load the first game on the new page', () => withWindow(async () => {
  const state = useGameState()
  const requests = []
  const rows = [
    game('history-1', { winner: 'villagers' }),
    game('history-2', { winner: 'werewolves' }),
    game('history-3', { winner: 'villagers' })
  ]
  const apiFetch = async (path) => {
    requests.push(path)
    const [route, query = ''] = path.split('?')
    if (route === '/games') {
      const params = new URLSearchParams(query)
      const offset = Number(params.get('offset') || 0)
      const limit = Number(params.get('limit') || rows.length)
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
    const gameIdMatch = route.match(/^\/games\/([^/]+)$/)
    if (gameIdMatch) return rows.find((item) => item.game_id === decodeURIComponent(gameIdMatch[1]))
    const phaseMatch = route.match(/^\/games\/([^/]+)\/phase$/)
    if (phaseMatch) {
      const gameId = decodeURIComponent(phaseMatch[1])
      return {
        game_id: gameId,
        day: 1,
        phase: 'setup',
        logs: [{ sequence: 1, day: 1, phase: 'setup', event_type: 'game_init', message: `${gameId} detail` }],
        decisions: []
      }
    }
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    historyListLimit: 2,
    apiFetch
  })

  await history.refreshHistoryList()
  assert.equal(state.selectedHistoryGameId.value, 'history-1')

  const changed = await history.goHistoryPage(2)

  assert.equal(changed, true)
  assert.deepEqual(state.gameHistory.value.map((item) => item.game_id), ['history-3'])
  assert.equal(state.selectedHistoryGameId.value, 'history-3')
  assert.equal(state.selectedHistoryGame.value.game_id, 'history-3')
  assert.equal(state.selectedHistoryGame.value.logs[0].message, 'history-3 detail')
  assert.deepEqual(requests, [
    '/games?limit=2&offset=0',
    '/games?limit=2&offset=2',
    '/games/history-3?view=history-shell',
    historyPhasePath('history-3', { phase: 'ended' })
  ])
}))

test('history shell defaults to the first visible phase instead of setup', () => withWindow(async () => {
  const state = useGameState()
  const requests = []
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/games/history-visible?view=history-shell') {
      return game('history-visible', {
        phases: [
          { key: 'day-1-setup', day: 1, phase: 'setup', log_count: 1 },
          { key: 'day-1-night', day: 1, phase: 'night', log_count: 2 }
        ]
      })
    }
    if (path === historyPhasePath('history-visible', { phase: 'night' })) {
      return {
        game_id: 'history-visible',
        day: 1,
        phase: 'night',
        logs: [{ sequence: 2, day: 1, phase: 'night', event_type: 'night_start', message: 'night' }],
        decisions: []
      }
    }
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    apiFetch
  })

  await history.selectHistoryGame('history-visible')

  assert.equal(state.selectedHistoryPageKey.value, 'day-1-night')
  assert.equal(state.selectedHistoryGame.value.__activePhaseKey, 'day-1-night')
  assert.equal(state.selectedHistoryGame.value.phase, 'night')
  assert.deepEqual(requests, [
    '/games/history-visible?view=history-shell',
    historyPhasePath('history-visible', { phase: 'night' })
  ])
}))

test('deleteHistoryGame refreshes the history list and surfaces a success notice', () => withWindow(async () => {
  const state = useGameState()
  const requests = []
  let rows = [
    game('history-1', { winner: 'villagers' }),
    game('history-2', { winner: 'werewolves' })
  ]
  const apiFetch = async (path, options = {}) => {
    requests.push({ path, method: options.method || 'GET' })
    const [route, query = ''] = path.split('?')
    if (route === '/games') {
      const params = new URLSearchParams(query)
      const offset = Number(params.get('offset') || 0)
      const limit = Number(params.get('limit') || rows.length)
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
    if (route === '/games/history-1' && options.method === 'DELETE') {
      rows = rows.filter((item) => item.game_id !== 'history-1')
      return null
    }
    if (path === '/games/history-2?view=history-shell') {
      return {
        ...rows.find((item) => item.game_id === 'history-2'),
        phases: [{ key: 'day-1-setup', day: 1, phase: 'setup', log_count: 1 }]
      }
    }
    if (path === historyPhasePath('history-2')) {
      return {
        game_id: 'history-2',
        day: 1,
        phase: 'setup',
        logs: [{ sequence: 1, day: 1, phase: 'setup', event_type: 'game_init', message: 'started' }],
        decisions: []
      }
    }
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    historyListLimit: 8,
    apiFetch
  })

  await history.refreshHistoryList()
  state.selectedHistoryGame.value = game('history-1')
  state.archiveByGameId.value = { 'history-1': { title: 'cached' } }
  state.reviewByGameId.value = { 'history-1': { summary: 'cached' } }

  const deleted = await history.deleteHistoryGame('history-1')

  assert.equal(deleted, true)
  assert.deepEqual(requests.map((request) => `${request.method} ${request.path}`), [
    'GET /games?limit=8&offset=0',
    'DELETE /games/history-1',
    'GET /games?limit=8&offset=0',
    'GET /games/history-2?view=history-shell',
    `GET ${historyPhasePath('history-2')}`
  ])
  assert.deepEqual(state.gameHistory.value.map((item) => item.game_id), ['history-2'])
  assert.equal(state.selectedHistoryGameId.value, 'history-2')
  assert.equal(state.selectedHistoryGame.value.game_id, 'history-2')
  assert.equal(state.archiveByGameId.value['history-1'], undefined)
  assert.equal(state.reviewByGameId.value['history-1'], undefined)
  assert.equal(history.historyNotice.value.type, 'success')
  assert.match(history.historyNotice.value.message, /已删除/)
  assert.equal(state.error.value, '')
}))

test('deleteHistoryGame keeps protected benchmark games and shows a warning notice', () => withWindow(async () => {
  const state = useGameState()
  const requests = []
  const rows = [
    game('benchmark-1', { source: 'benchmark', winner: 'villagers' }),
    game('history-2', { winner: 'werewolves' })
  ]
  const apiFetch = async (path, options = {}) => {
    requests.push({ path, method: options.method || 'GET' })
    const [route, query = ''] = path.split('?')
    if (route === '/games') {
      const params = new URLSearchParams(query)
      const offset = Number(params.get('offset') || 0)
      const limit = Number(params.get('limit') || rows.length)
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
    if (route === '/games/benchmark-1' && options.method === 'DELETE') {
      throw new Error('benchmark game requires force delete')
    }
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    historyListLimit: 8,
    apiFetch
  })

  await history.refreshHistoryList()
  state.selectedHistoryGameId.value = 'benchmark-1'
  state.selectedHistoryGame.value = game('benchmark-1')

  const deleted = await history.deleteHistoryGame('benchmark-1')

  assert.equal(deleted, false)
  assert.deepEqual(requests.map((request) => `${request.method} ${request.path}`), [
    'GET /games?limit=8&offset=0',
    'DELETE /games/benchmark-1'
  ])
  assert.deepEqual(state.gameHistory.value.map((item) => item.game_id), ['benchmark-1', 'history-2'])
  assert.equal(state.selectedHistoryGameId.value, 'benchmark-1')
  assert.equal(state.selectedHistoryGame.value.game_id, 'benchmark-1')
  assert.equal(history.historyNotice.value.type, 'warning')
  assert.match(history.historyNotice.value.message, /评测证据/)
  assert.equal(state.error.value, history.historyNotice.value.message)
}))

test('deleteHistoryGame refreshes history when the backend reports a missing game', () => withWindow(async () => {
  const state = useGameState()
  const requests = []
  let rows = [
    game('history-missing', { winner: 'villagers' }),
    game('history-2', { winner: 'werewolves' })
  ]
  const apiFetch = async (path, options = {}) => {
    requests.push({ path, method: options.method || 'GET' })
    const [route, query = ''] = path.split('?')
    if (route === '/games') {
      const params = new URLSearchParams(query)
      rows = rows.filter((item) => item.game_id !== 'history-missing')
      const offset = Number(params.get('offset') || 0)
      const limit = Number(params.get('limit') || rows.length)
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
    if (route === '/games/history-missing' && options.method === 'DELETE') {
      throw new Error('game not found')
    }
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    historyListLimit: 8,
    apiFetch
  })

  state.gameHistory.value = rows
  state.selectedHistoryGameId.value = 'history-missing'
  state.selectedHistoryGame.value = game('history-missing')
  state.archiveByGameId.value = { 'history-missing': { title: 'cached' } }
  state.reviewByGameId.value = { 'history-missing': { summary: 'cached' } }

  const deleted = await history.deleteHistoryGame('history-missing')

  assert.equal(deleted, false)
  assert.deepEqual(requests.map((request) => `${request.method} ${request.path}`), [
    'DELETE /games/history-missing',
    'GET /games?limit=8&offset=0'
  ])
  assert.deepEqual(state.gameHistory.value.map((item) => item.game_id), ['history-2'])
  assert.equal(state.selectedHistoryGameId.value, 'history-2')
  assert.equal(state.selectedHistoryGame.value, null)
  assert.equal(state.archiveByGameId.value['history-missing'], undefined)
  assert.equal(state.reviewByGameId.value['history-missing'], undefined)
  assert.equal(history.historyNotice.value.type, 'warning')
  assert.match(history.historyNotice.value.message, /已刷新/)
  assert.equal(state.error.value, history.historyNotice.value.message)
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
    if (path === '/games/benchmark-1?view=history-shell') {
      return game('benchmark-1', {
        phases: [{ key: 'day-1-setup', day: 1, phase: 'setup', log_count: 1 }]
      })
    }
    if (path === historyPhasePath('benchmark-1')) {
      return {
        game_id: 'benchmark-1',
        day: 1,
        phase: 'setup',
        logs: [{ sequence: 1, day: 1, phase: 'setup', event_type: 'game_init', message: 'started' }],
        decisions: []
      }
    }
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
    if (path === '/games/history-a?view=history-shell') return slowDetail.promise
    if (path === '/games/history-b?view=history-shell') {
      return game('history-b', {
        day: 2,
        winner: 'villagers',
        phases: [{ key: 'day-2-night', day: 2, phase: 'night', log_count: 1 }]
      })
    }
    if (path === historyPhasePath('history-b', { day: 2, phase: 'night' })) {
      return {
        game_id: 'history-b',
        day: 2,
        phase: 'night',
        logs: [{ sequence: 1, day: 2, phase: 'night', event_type: 'night_start', message: 'night' }],
        decisions: []
      }
    }
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

test('history phase detail load more appends paginated logs and decisions', () => withWindow(async () => {
  const state = useGameState()
  const requests = []
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/games/history-paged?view=history-shell') {
      return game('history-paged', {
        day: 1,
        phase: 'speech',
        phases: [{ key: 'day-1-speech', day: 1, phase: 'speech', log_count: 3, decision_count: 2 }]
      })
    }
    if (path === historyPhasePath('history-paged', { day: 1, phase: 'speech' })) {
      return {
        game_id: 'history-paged',
        day: 1,
        phase: 'speech',
        summary: { log_count: 3, decision_count: 2 },
        logs: [{ sequence: 1, day: 1, phase: 'speech', event_type: 'speech', message: 'first log' }],
        decisions: [{ id: 'decision-1', day: 1, phase: 'speech', action: 'speech', actor_id: 1 }],
        pagination: {
          logs: { total: 3, offset: 0, limit: 1000, returned: 1, has_more: true },
          decisions: { total: 2, offset: 0, limit: 500, returned: 1, has_more: true }
        }
      }
    }
    if (path === historyPhasePath('history-paged', { day: 1, phase: 'speech', logOffset: 1, decisionOffset: 1 })) {
      return {
        game_id: 'history-paged',
        day: 1,
        phase: 'speech',
        summary: { log_count: 3, decision_count: 2 },
        logs: [
          { sequence: 2, day: 1, phase: 'speech', event_type: 'speech', message: 'second log' },
          { sequence: 3, day: 1, phase: 'speech', event_type: 'speech', message: 'third log' }
        ],
        decisions: [{ id: 'decision-2', day: 1, phase: 'speech', action: 'speech', actor_id: 2 }],
        pagination: {
          logs: { total: 3, offset: 1, limit: 1000, returned: 2, has_more: false },
          decisions: { total: 2, offset: 1, limit: 500, returned: 1, has_more: false }
        }
      }
    }
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    apiFetch
  })

  await history.selectHistoryGame('history-paged')
  assert.deepEqual(state.selectedHistoryGame.value.logs.map((log) => log.message), ['first log'])
  assert.deepEqual(state.selectedHistoryGame.value.decisions.map((decision) => decision.id), ['decision-1'])
  assert.equal(state.selectedPhaseDetail.value.pagination.logs.has_more, true)
  assert.equal(state.selectedPhaseDetail.value.pagination.decisions.has_more, true)

  const detail = await history.loadMoreHistoryPhaseDetail('history-paged', 'day-1-speech')

  assert.deepEqual(requests, [
    '/games/history-paged?view=history-shell',
    historyPhasePath('history-paged', { day: 1, phase: 'speech' }),
    historyPhasePath('history-paged', { day: 1, phase: 'speech', logOffset: 1, decisionOffset: 1 })
  ])
  assert.deepEqual(detail.logs.map((log) => log.message), ['first log', 'second log', 'third log'])
  assert.deepEqual(detail.decisions.map((decision) => decision.id), ['decision-1', 'decision-2'])
  assert.equal(detail.pagination.logs.has_more, false)
  assert.equal(detail.pagination.decisions.has_more, false)
  assert.deepEqual(state.selectedHistoryGame.value.logs.map((log) => log.message), ['first log', 'second log', 'third log'])
  assert.deepEqual(state.phaseDetailByGameId.value['history-paged']['day-1-speech'].logs.map((log) => log.message), ['first log', 'second log', 'third log'])
  assert.equal(state.phaseLoadingByKey.value['history-paged:day-1-speech'], false)
}))

test('history detail failures surface a local notice', () => withWindow(async () => {
  const state = useGameState()
  const apiFetch = async (path) => {
    if (path === '/games/history-fail?view=history-shell') throw new Error('detail backend down')
    if (path === '/games/history-fail/review') return { summary: 'ok' }
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    apiFetch
  })

  await history.selectHistoryGame('history-fail')

  assert.equal(state.selectedHistoryGame.value, null)
  assert.equal(state.historyLoading.value, false)
  assert.deepEqual(history.historyNotice.value, {
    type: 'error',
    message: 'detail backend down'
  })
  assert.equal(state.error.value, 'detail backend down')
}))

test('history archive and review loaders surface local notices', () => withWindow(async () => {
  const state = useGameState()
  state.selectedHistoryGameId.value = 'history-1'
  const apiFetch = async (path) => {
    if (path === '/games/history-1/archive') return { game_id: 'history-1', status: 'ok' }
    if (path === '/games/history-1/review') throw new Error('review unavailable')
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    apiFetch
  })

  await history.loadArchive()

  assert.equal(state.archiveByGameId.value['history-1'].status, 'ok')
  assert.deepEqual(history.historyNotice.value, {
    type: '',
    message: ''
  })

  await history.loadReview()

  assert.deepEqual(state.reviewByGameId.value['history-1'], { error: 'review unavailable' })
  assert.deepEqual(history.historyNotice.value, {
    type: 'error',
    message: 'review unavailable'
  })
  assert.equal(state.error.value, 'review unavailable')
}))

test('history replay loads cursor chunks on demand', () => withWindow(async () => {
  const state = useGameState()
  const requests = []
  const secondChunk = createDeferred()
  const replayPlayers = [
    { id: 1, seat: 1, name: '1号', role_hint: '村民', alive: true },
    { id: 2, seat: 2, name: '2号', role_hint: '狼人', alive: true }
  ]
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/games/replay-paged/replay?cursor=0&limit=500') {
      return {
        game_id: 'replay-paged',
        winner: 'villagers',
        players: replayPlayers,
        logs: [
          { sequence: 1, day: 1, phase: 'setup', event_type: 'game_init', message: 'start' },
          { sequence: 2, day: 1, phase: 'speech', event_type: 'speech', actor_id: 1, message: 'hello' }
        ],
        decisions: [{ id: 'decision-1', day: 1, phase: 'speech', action: 'speech', actor_id: 1 }],
        event_count: 4,
        cursor: 0,
        limit: 500,
        next_cursor: 2,
        has_more: true
      }
    }
    if (path === '/games/replay-paged/replay?cursor=2&limit=500') return secondChunk.promise
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    apiFetch
  })

  await history.replayHistoryGame('replay-paged')

  assert.equal(state.isReplayMode.value, true)
  assert.equal(state.currentView.value, 'match')
  assert.equal(state.replayTotal.value, 4)
  assert.equal(state.replayCursor.value, 0)
  assert.equal(state.replayByGameId.value['replay-paged'].logs.length, 2)
  assert.equal(state.replayLoadingByGameId.value['replay-paged'], true)
  assert.deepEqual(requests, [
    '/games/replay-paged/replay?cursor=0&limit=500',
    '/games/replay-paged/replay?cursor=2&limit=500'
  ])

  const seek = history.seekReplay(4)
  secondChunk.resolve({
    game_id: 'replay-paged',
    winner: 'villagers',
    players: replayPlayers,
    logs: [
      { sequence: 3, day: 1, phase: 'exile_vote', event_type: 'exile_vote_start', message: 'vote' },
      { sequence: 4, day: 1, phase: 'ended', event_type: 'game_end', message: 'finished' }
    ],
    decisions: [{ id: 'decision-2', day: 1, phase: 'exile_vote', action: 'vote', actor_id: 2, target_id: 1 }],
    event_count: 4,
    cursor: 2,
    limit: 500,
    next_cursor: 4,
    has_more: false
  })
  await seek

  assert.equal(requests.filter((path) => path === '/games/replay-paged/replay?cursor=2&limit=500').length, 1)
  assert.equal(state.replayLoadingByGameId.value['replay-paged'], false)
  assert.equal(state.replayCursor.value, 4)
  assert.equal(state.replayGame.value.logs.length, 4)
  assert.equal(state.replayGame.value.winner, 'villagers')
  assert.equal(state.replayByGameId.value['replay-paged'].logs.length, 4)
}))

test('history replay ignores failed background prefetch and restarts playback from the end', () => withWindow(async ({ timers }) => {
  const state = useGameState()
  const requests = []
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/games/replay-restart/replay?cursor=0&limit=500') {
      return {
        game_id: 'replay-restart',
        winner: 'villagers',
        players: [{ id: 1, seat: 1, name: '1号', role_hint: '村民', alive: true }],
        logs: [
          { sequence: 1, day: 1, phase: 'setup', event_type: 'game_init', message: 'start' },
          { sequence: 2, day: 1, phase: 'ended', event_type: 'game_end', message: 'end' }
        ],
        cursor: 0,
        limit: 500,
        next_cursor: 2,
        has_more: true
      }
    }
    if (path === '/games/replay-restart/replay?cursor=2&limit=500') throw new Error('background failed')
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    apiFetch
  })

  await history.replayHistoryGame('replay-restart')
  await flushPromises()

  assert.equal(state.replayByGameId.value['replay-restart'].logs.length, 2)
  assert.equal(state.replayByGameId.value['replay-restart'].error, undefined)
  assert.equal(state.error.value, '')

  await history.seekReplay(2)
  assert.equal(state.replayCursor.value, 2)
  assert.equal(state.replayPlaying.value, false)

  await history.playReplay()
  assert.equal(state.replayCursor.value, 0)
  assert.equal(state.replayPlaying.value, true)

  timers.runNextInterval()
  await flushPromises()
  assert.equal(state.replayCursor.value, 1)
  assert.equal(requests.filter((path) => path === '/games/replay-restart/replay?cursor=2&limit=500').length, 1)
}))

test('history replay ignores stale slow seek results', () => withWindow(async () => {
  const state = useGameState()
  const slowChunk = createDeferred()
  const requests = []
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/games/replay-stale/replay?cursor=0&limit=500') {
      return {
        game_id: 'replay-stale',
        players: [{ id: 1, seat: 1, name: '1号', role_hint: '村民', alive: true }],
        logs: [
          { sequence: 1, day: 1, phase: 'setup', event_type: 'game_init', message: 'start' },
          { sequence: 2, day: 1, phase: 'speech', event_type: 'speech', message: 'talk' }
        ],
        event_count: 4,
        cursor: 0,
        limit: 500,
        next_cursor: 2,
        has_more: true
      }
    }
    if (path === '/games/replay-stale/replay?cursor=2&limit=500') return slowChunk.promise
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    apiFetch
  })

  await history.replayHistoryGame('replay-stale')
  const staleSeek = history.seekReplay(4)
  await history.seekReplay(1)
  assert.equal(state.replayCursor.value, 1)

  slowChunk.resolve({
    game_id: 'replay-stale',
    logs: [
      { sequence: 3, day: 1, phase: 'vote', event_type: 'exile_vote_start', message: 'vote' },
      { sequence: 4, day: 1, phase: 'ended', event_type: 'game_end', message: 'end' }
    ],
    event_count: 4,
    cursor: 2,
    limit: 500,
    next_cursor: 4,
    has_more: false
  })
  await staleSeek

  assert.equal(state.replayCursor.value, 1)
  assert.equal(state.replayByGameId.value['replay-stale'].logs.length, 4)
  assert.equal(requests.filter((path) => path === '/games/replay-stale/replay?cursor=2&limit=500').length, 1)
}))

test('history replay reports foreground chunk failures without unhandled rejection', () => withWindow(async ({ timers }) => {
  const state = useGameState()
  const apiFetch = async (path) => {
    if (path === '/games/replay-fail/replay?cursor=0&limit=500') {
      return {
        game_id: 'replay-fail',
        players: [{ id: 1, seat: 1, name: '1号', role_hint: '村民', alive: true }],
        logs: [{ sequence: 1, day: 1, phase: 'setup', event_type: 'game_init', message: 'start' }],
        event_count: 2,
        cursor: 0,
        limit: 500,
        next_cursor: 1,
        has_more: true
      }
    }
    if (path === '/games/replay-fail/replay?cursor=1&limit=500') throw new Error('chunk unavailable')
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    apiFetch
  })

  await history.replayHistoryGame('replay-fail')
  const seek = await history.seekReplay(2)

  assert.equal(seek, null)
  assert.equal(state.replayCursor.value, 0)
  assert.deepEqual(history.historyNotice.value, {
    type: 'error',
    message: 'chunk unavailable'
  })

  await history.seekReplay(1)
  assert.equal(state.replayCursor.value, 1)

  await history.playReplay()
  timers.runNextInterval()
  await flushPromises(12)

  assert.equal(state.replayPlaying.value, false)
  assert.equal(state.error.value, 'chunk unavailable')
}))

test('history replay shows a notice when source detail cannot be loaded', () => withWindow(async () => {
  const state = useGameState()
  const apiFetch = async (path) => {
    if (path === '/games/replay-missing/replay?cursor=0&limit=500') throw new Error('game not found')
    throw new Error(`unexpected ${path}`)
  }
  const history = useGameHistory(state, {
    installLifecycle: false,
    apiFetch
  })

  await history.replayHistoryGame('replay-missing')

  assert.equal(state.isReplayMode.value, false)
  assert.deepEqual(history.historyNotice.value, {
    type: 'error',
    message: '回放源数据尚未读取，请稍后重试。'
  })
  assert.equal(state.error.value, '回放源数据尚未读取，请稍后重试。')
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
  assert.deepEqual(workbench.notice.value, { type: 'success', message: '已加载更多运行记录。' })

  await workbench.loadMoreSampleGames('training')
  assert.equal(requests.at(-1), '/evolution-runs/evo-run-a/games?phase=training&limit=1&offset=1')
  assert.deepEqual(workbench.selectedGames.value.training.map((item) => item.game_id), ['train-1', 'train-2'])
  assert.equal(workbench.selectedGameId.value, 'train-1')
  assert.deepEqual(workbench.notice.value, { type: 'success', message: '已加载更多训练样本局。' })
})

test('notice auto dismiss clears success and warning but keeps errors', () => withWindow(({ timers }) => {
  const notice = ref({ type: '', message: '' })
  const dismissed = []
  const autoDismiss = createNoticeAutoDismiss(notice, {
    onDismiss: (item) => dismissed.push(item)
  })

  notice.value = { type: 'success', message: '操作完成' }
  assert.equal(timers.timeoutCount(), 1)

  notice.value = { type: 'warning', message: '请注意' }
  assert.equal(timers.timeoutCount(), 1)
  timers.runNextTimeout()
  assert.deepEqual(notice.value, { type: '', message: '' })
  assert.deepEqual(dismissed, [{ type: 'warning', message: '请注意' }])

  notice.value = { type: 'error', message: '失败原因' }
  assert.equal(timers.timeoutCount(), 0)
  assert.deepEqual(notice.value, { type: 'error', message: '失败原因' })

  autoDismiss.dispose()
}))

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

test('evolution proposal review normalizes attribution report from proposal API', async () => {
  const run = {
    run_id: 'evo-attribution-run',
    role: 'seer',
    status: 'reviewing',
    started_at: '2026-06-07T12:30:00'
  }
  const attribution = {
    schema_version: 'proposal_attribution_report_v1',
    status: 'attribution_inconclusive',
    review_required: true,
    budget: {
      enabled: true,
      budget_scope: 'not_run',
      scenario_budget: 0,
      full_game_budget: 0,
      max_proposals: 2
    },
    rows: [
      { proposal_id: 'p1', status: 'attribution_inconclusive', estimated_contribution: null },
      { proposal_id: 'p2', status: 'attribution_inconclusive', requires_ablation: true, estimated_contribution: null }
    ]
  }
  const apiFetch = async (path) => {
    if (path === '/evolution-runs/evo-attribution-run/proposals') {
      return {
        run_id: 'evo-attribution-run',
        role: 'seer',
        proposals: [{ proposal_id: 'p1', status: 'pending', target_file: 'seer.md' }],
        proposal_review: { total: 2, generated_count: 2, pending_count: 2 },
        gate_report: {
          decision: 'review_required',
          proposal_attribution: attribution
        },
        proposal_attribution_report: attribution,
        run: {
          ...run,
          proposal_attribution_report: attribution
        }
      }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch })
  workbench.selectedRunId.value = 'evo-attribution-run'
  workbench.selectedRun.value = run

  await workbench.loadProposalReview('evo-attribution-run')

  assert.equal(workbench.selectedProposalReview.value.proposalAttribution.status, 'attribution_inconclusive')
  assert.equal(workbench.selectedProposalReview.value.proposalAttribution.statusLabel, '需复核')
  assert.equal(workbench.selectedProposalReview.value.proposalAttribution.rowCount, 2)
  assert.equal(workbench.selectedProposalReview.value.gate.proposalAttributionLabel, '需复核')
  assert.equal(workbench.selectedProposalReview.value.summary.proposalAttributionRowCount, 2)
  assert.equal(workbench.selectedProposalReview.value.summary.proposalAttributionReviewRequired, true)
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

test('evolution workbench shows success notice after starting a single run', async () => {
  const requests = []
  let runs = []
  const createdRun = {
    run_id: 'evo-new',
    role: 'seer',
    status: 'training',
    started_at: '2026-06-07T15:00:00'
  }
  const apiFetch = async (path, options = {}) => {
    requests.push({ path, body: options.body ? JSON.parse(options.body) : null })
    if (path === '/roles') return { roles: ['seer'] }
    if (path === '/roles/seer/versions') return { versions: [] }
    if (path === '/roles/seer/leaderboard') return { entries: [] }
    if (path === '/evolution-runs') {
      runs = [createdRun]
      return { run_id: 'evo-new' }
    }
    if (path === '/evolution-runs?limit=80&offset=0&source=evolution') {
      return {
        runs,
        batches: [],
        pagination: { total: runs.length, offset: 0, limit: 80, returned: runs.length, has_more: false }
      }
    }
    if (path === '/evolution-runs/evo-new') return createdRun
    if (path === '/evolution-runs/evo-new/diff') return { diffs: [] }
    if (path === '/evolution-runs/evo-new/proposals') return { proposals: [] }
    if (/^\/evolution-runs\/evo-new\/games\?/.test(path)) {
      return { games: [], pagination: { total: 0, offset: 0, limit: 80, returned: 0, has_more: false } }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch })
  workbench.selectedRole.value = 'seer'
  workbench.form.value.auto_promote = false
  await workbench.startSingle()

  assert.deepEqual(requests.find((item) => item.path === '/evolution-runs')?.body, {
    roles: ['seer'],
    training_games: 20,
    battle_games: 20,
    max_days: 20,
    auto_promote: false
  })
  assert.deepEqual(workbench.notice.value, { type: 'success', message: '单角色进化已启动。' })
  assert.equal(workbench.error.value, '')
  assert.equal(workbench.selectedRunId.value, 'evo-new')
})

test('evolution workbench sends the selected model profile when starting a single run', async () => {
  const requests = []
  let runs = []
  const createdRun = {
    run_id: 'evo-profile-new',
    role: 'seer',
    status: 'training',
    started_at: '2026-06-07T15:00:00'
  }
  const apiFetch = async (path, options = {}) => {
    requests.push({ path, body: options.body ? JSON.parse(options.body) : null })
    if (path.startsWith('/health/preflight?scope=evolution_start')) {
      return {
        ready: true,
        status: 'ok',
        gate: { ready: true, status: 'ok', blockers: [], warnings: [], actions: [] },
        checks: { llm_connectivity: { status: 'ok' } }
      }
    }
    if (path === '/roles') return { roles: ['seer'] }
    if (path === '/roles/seer/versions') return { versions: [] }
    if (path === '/roles/seer/leaderboard') return { entries: [] }
    if (path === '/evolution-runs') {
      runs = [createdRun]
      return { run_id: 'evo-profile-new' }
    }
    if (path === '/evolution-runs?limit=80&offset=0&source=evolution') {
      return {
        runs,
        batches: [],
        pagination: { total: runs.length, offset: 0, limit: 80, returned: runs.length, has_more: false }
      }
    }
    if (path === '/evolution-runs/evo-profile-new') return createdRun
    if (path === '/evolution-runs/evo-profile-new/diff') return { diffs: [] }
    if (path === '/evolution-runs/evo-profile-new/proposals') return { proposals: [] }
    if (/^\/evolution-runs\/evo-profile-new\/games\?/.test(path)) {
      return { games: [], pagination: { total: 0, offset: 0, limit: 80, returned: 0, has_more: false } }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch })
  workbench.selectedRole.value = 'seer'
  workbench.form.value.auto_promote = false
  workbench.form.value.model_profile_id = 'profile-evolution-main'
  await workbench.startSingle()

  assert.deepEqual(requests.find((item) => item.path === '/evolution-runs')?.body, {
    roles: ['seer'],
    training_games: 20,
    battle_games: 20,
    max_days: 20,
    auto_promote: false,
    model_profile_id: 'profile-evolution-main'
  })
  assert.deepEqual(workbench.notice.value, { type: 'success', message: '单角色进化已启动。' })
})

test('evolution workbench maps run action failures to warning notices', async () => {
  const apiFetch = async (path) => {
    if (path === '/evolution-runs/missing-run/actions') throw new Error('run not found')
    if (path === '/evolution-runs/batch-1/actions') throw new Error('batch does not support promote')
    if (path === '/evolution-runs/unreviewed/actions') {
      throw new Error('evolution promote requires at least one accepted or applied proposal before publishing')
    }
    if (path === '/evolution-runs/trust-incomplete/actions') {
      const err = new Error('Evolution baseline promote requires a complete trust bundle.')
      err.code = 'evolution_trust_bundle_incomplete'
      throw err
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch })
  await workbench.runAction('missing-run', 'promote')

  assert.deepEqual(workbench.notice.value, {
    type: 'warning',
    message: '运行不存在，请刷新列表。'
  })
  assert.equal(workbench.error.value, '运行不存在，请刷新列表。')

  await workbench.runAction('batch-1', 'promote')
  assert.deepEqual(workbench.notice.value, {
    type: 'warning',
    message: '批量任务不支持该操作，请选择子运行。'
  })
  assert.equal(workbench.error.value, '批量任务不支持该操作，请选择子运行。')

  await workbench.runAction('unreviewed', 'promote')
  assert.deepEqual(workbench.notice.value, {
    type: 'warning',
    message: '至少接受或应用一个提案后才能晋升。'
  })
  assert.equal(workbench.error.value, '至少接受或应用一个提案后才能晋升。')

  await workbench.runAction('trust-incomplete', 'promote')
  assert.deepEqual(workbench.notice.value, {
    type: 'warning',
    message: '信任包不完整，不能晋升为基线。'
  })
  assert.equal(workbench.error.value, '信任包不完整，不能晋升为基线。')
})

test('evolution workbench gates promote on explicit proposal review state', () => {
  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch: async () => ({}) })
  workbench.selectedRun.value = { id: 'evo-review', entityType: 'run', status: 'reviewing' }
  workbench.selectedProposalReview.value = {
    loading: false,
    error: '',
    unsupported: false,
    summary: { accepted: 0, applied: 0 }
  }

  assert.equal(workbench.selectedCanPromote.value, false)
  assert.equal(workbench.selectedPromoteDisabledReason.value, '至少接受或应用一个提案后才能晋升。')

  workbench.selectedProposalReview.value = {
    loading: false,
    error: '',
    unsupported: false,
    summary: { accepted: 1, applied: 0 }
  }
  assert.equal(workbench.selectedCanPromote.value, true)
  assert.equal(workbench.selectedPromoteDisabledReason.value, '')
  assert.equal(workbench.baselinePromoteTrustDisabledReason.value, '')

  workbench.selectedProposalReview.value = {
    loading: false,
    error: '',
    unsupported: false,
    summary: { accepted: 0, applied: 1 }
  }
  assert.equal(workbench.selectedCanPromote.value, true)

  workbench.selectedRun.value = { id: 'evo-review', entityType: 'run', status: 'promoted' }
  assert.equal(workbench.selectedCanPromote.value, false)
  assert.equal(workbench.selectedPromoteDisabledReason.value, '只有待评审运行可以晋升。')
})

test('evolution workbench requires complete trust bundle for baseline promote only', () => {
  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch: async () => ({}) })
  workbench.selectedRun.value = { id: 'evo-shadow', entityType: 'run', status: 'reviewing' }
  workbench.selectedProposalReview.value = {
    loading: false,
    error: '',
    unsupported: false,
    summary: { accepted: 1, applied: 0 }
  }

  assert.equal(workbench.selectedCanPromote.value, true)
  assert.equal(workbench.selectedPromoteDisabledReason.value, '')

  workbench.selectedRun.value = {
    id: 'evo-baseline',
    entityType: 'run',
    status: 'reviewing',
    release_decision: 'baseline_promote'
  }
  assert.equal(workbench.selectedCanPromote.value, false)
  assert.equal(workbench.selectedPromoteDisabledReason.value, '缺少完整信任包，不能晋升为基线。')
  assert.equal(workbench.baselinePromoteTrustDisabledReason.value, '缺少完整信任包，不能晋升为基线。')

  workbench.selectedProposalReview.value = {
    loading: false,
    error: '',
    unsupported: false,
    summary: { accepted: 1, applied: 0 },
    trustBundle: {
      trust_bundle_id: 'trust_bundle_incomplete',
      bundle_hash: 'a'.repeat(64),
      gate_report_id: 'gate_incomplete',
      proposal_ids: ['p1'],
      completeness: {
        complete: false,
        score: 0.8,
        missing: ['training_evidence']
      }
    }
  }
  assert.equal(workbench.selectedCanPromote.value, false)
  assert.equal(
    workbench.selectedPromoteDisabledReason.value,
    '信任包不完整，不能晋升为基线。缺失：训练证据。'
  )
  assert.equal(
    workbench.baselinePromoteTrustDisabledReason.value,
    '信任包不完整，不能晋升为基线。缺失：训练证据。'
  )

  workbench.selectedProposalReview.value = {
    loading: false,
    error: '',
    unsupported: false,
    summary: { accepted: 1, applied: 0 },
    trustBundle: {
      trust_bundle_id: 'trust_bundle_without_gate',
      bundle_hash: 'c'.repeat(64),
      training_game_ids: ['train_1'],
      proposal_ids: ['p1'],
      completeness: {
        complete: true,
        score: 1,
        missing: []
      }
    }
  }
  assert.equal(workbench.selectedCanPromote.value, false)
  assert.equal(
    workbench.selectedPromoteDisabledReason.value,
    '信任包不完整，不能晋升为基线。缺失：门禁报告。'
  )
  assert.equal(
    workbench.baselinePromoteTrustDisabledReason.value,
    '信任包不完整，不能晋升为基线。缺失：门禁报告。'
  )

  workbench.selectedProposalReview.value = {
    loading: false,
    error: '',
    unsupported: false,
    summary: { accepted: 1, applied: 0 },
    trustBundle: {
      trust_bundle_id: 'trust_bundle_complete',
      bundle_hash: 'b'.repeat(64),
      gate_report_id: 'gate_complete',
      training_game_ids: ['train_1'],
      proposal_ids: ['p1'],
      completeness: {
        complete: true,
        score: 1,
        missing: []
      }
    }
  }
  assert.equal(workbench.selectedCanPromote.value, true)
  assert.equal(workbench.selectedPromoteDisabledReason.value, '')
  assert.equal(workbench.baselinePromoteTrustDisabledReason.value, '')
})

test('evolution workbench opens normalized trust bundle audit from proposal review', () => {
  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch: async () => ({}) })
  workbench.selectedRunId.value = 'evo-trust-run'
  workbench.selectedRun.value = {
    id: 'evo-trust-run',
    run_id: 'evo-trust-run',
    entityType: 'run',
    role: 'seer',
    status: 'reviewing'
  }
  workbench.selectedProposalReview.value = {
    loading: false,
    error: '',
    unsupported: false,
    summary: { accepted: 1, applied: 0 },
    trustBundle: {
      trust_bundle_id: 'trust_review_1',
      bundle_hash: 'hash_review_1',
      gate_report_id: 'gate_review_1',
      rollback_target: 'seer_baseline_0',
      training_game_ids: ['train_a', 'train_b'],
      proposal_ids: ['proposal_a'],
      battle_pair_seeds: [260607],
      completeness: {
        complete: true,
        score: 1,
        missing: []
      }
    }
  }

  workbench.openTrustBundleDrawer('review')

  assert.equal(workbench.trustBundleDrawerOpen.value, true)
  assert.equal(workbench.trustBundleAudit.value.source, 'review')
  assert.equal(workbench.trustBundleAudit.value.hasTrustBundle, true)
  assert.equal(workbench.trustBundleAudit.value.trust_bundle_id, 'trust_review_1')
  assert.equal(workbench.trustBundleAudit.value.bundle_hash, 'hash_review_1')
  assert.equal(workbench.trustBundleAudit.value.gate_report_id, 'gate_review_1')
  assert.equal(workbench.trustBundleAudit.value.rollback_target, 'seer_baseline_0')
  assert.deepEqual(workbench.trustBundleAudit.value.training_game_ids, ['train_a', 'train_b'])
  assert.deepEqual(workbench.trustBundleAudit.value.proposal_ids, ['proposal_a'])
  assert.equal(workbench.trustBundleAudit.value.completeness.status, 'complete')
  assert.equal(workbench.trustBundleAudit.value.paired_seeds[0].seed, '260607')

  workbench.closeTrustBundleDrawer()
  assert.equal(workbench.trustBundleDrawerOpen.value, false)
})

test('evolution workbench refreshes trust bundle audit from authority endpoint', async () => {
  const requests = []
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/evolution-runs/evo-trust-run/trust-bundle') {
      return {
        kind: 'evolution_trust_bundle',
        run_id: 'evo-trust-run',
        role: 'seer',
        version_id: 'seer_v2',
        trust_bundle_id: 'trust_authority_1',
        bundle_hash: 'hash_authority_1',
        gate_report_id: 'gate_authority_1',
        trust_bundle: {
          trust_bundle_id: 'trust_authority_1',
          bundle_hash: 'hash_authority_1',
          gate_report_id: 'gate_authority_1',
          rollback_target: 'seer_baseline_0',
          training_game_ids: ['history_train_a'],
          proposal_ids: ['proposal_authority'],
          battle_pair_seeds: [260700],
          completeness: {
            complete: true,
            score: 1,
            missing: []
          }
        }
      }
    }
    throw new Error(`unexpected ${path}`)
  }
  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch })
  workbench.selectedRunId.value = 'evo-trust-run'
  workbench.selectedRun.value = {
    id: 'evo-trust-run',
    run_id: 'evo-trust-run',
    entityType: 'run',
    role: 'seer',
    status: 'reviewing'
  }
  workbench.selectedProposalReview.value = {
    loading: false,
    error: '',
    unsupported: false,
    summary: { accepted: 1, applied: 0 },
    trustBundle: {
      trust_bundle_id: 'trust_cached_1',
      bundle_hash: 'hash_cached_1',
      gate_report_id: 'gate_cached_1',
      rollback_target: 'seer_baseline_0',
      training_game_ids: ['history_train_cached'],
      proposal_ids: ['proposal_cached'],
      completeness: { complete: true, score: 1, missing: [] }
    }
  }

  await workbench.openTrustBundleDrawer('review', {
    version: {
      role: 'seer',
      version_id: 'seer_v2'
    }
  })

  assert.deepEqual(requests, ['/evolution-runs/evo-trust-run/trust-bundle'])
  assert.equal(workbench.trustBundleDrawerOpen.value, true)
  assert.equal(workbench.trustBundleAuditLoading.value, false)
  assert.equal(workbench.trustBundleAudit.value.source, 'authority')
  assert.equal(workbench.trustBundleAudit.value.authorityStatus, 'mismatch')
  assert.equal(workbench.trustBundleAudit.value.authorityMessage, '权威信任包与当前页面缓存不一致。')
  assert.deepEqual(workbench.trustBundleAudit.value.mismatchLabels, ['trust_bundle_id', 'bundle_hash', 'gate_report_id'])
  assert.equal(workbench.trustBundleAudit.value.trust_bundle_id, 'trust_authority_1')
  assert.equal(workbench.trustBundleAudit.value.bundle_hash, 'hash_authority_1')
  assert.equal(workbench.trustBundleAudit.value.gate_report_id, 'gate_authority_1')
  assert.deepEqual(workbench.trustBundleAudit.value.training_game_ids, ['history_train_a'])
  assert.equal(workbench.trustBundleAudit.value.training_evidence[0].href, '#logs?game_id=history_train_a&workspace=archive')
  assert.equal(workbench.trustBundleAudit.value.proposal_evidence[0].href, '#evolution?run_id=evo-trust-run&proposal_id=proposal_authority')
  assert.equal(workbench.trustBundleAudit.value.source_run_href, '#evolution?run_id=evo-trust-run')
  assert.equal(workbench.trustBundleAudit.value.gate_report_href, '#evolution?run_id=evo-trust-run&gate_report_id=gate_authority_1')
  assert.equal(workbench.trustBundleAudit.value.paired_seeds[0].seed, '260700')
  assert.ok(workbench.trustBundleAudit.value.consistency_checks.every((item) => (
    item.field && item.label && item.status && item.message
  )))
  const checksByField = Object.fromEntries(
    workbench.trustBundleAudit.value.consistency_checks.map((item) => [item.field, item])
  )
  assert.equal(checksByField.trust_bundle_id.status, 'mismatch')
  assert.equal(checksByField.trust_bundle_id.cached_value, 'trust_cached_1')
  assert.equal(checksByField.trust_bundle_id.authority_value, 'trust_authority_1')
  assert.match(checksByField.trust_bundle_id.message, /权威包/)
  assert.equal(checksByField.bundle_hash.status, 'mismatch')
  assert.equal(checksByField.gate_report_id.status, 'mismatch')
  assert.equal(checksByField.source_run_id.status, 'match')
  assert.equal(checksByField.source_run_id.authority_value, 'evo-trust-run')
  assert.equal(checksByField.role.status, 'match')
  assert.equal(checksByField.version_id.status, 'match')
  assert.equal(checksByField.version_id.authority_value, 'seer_v2')
})

test('evolution workbench consumes run proposal and gate hash deep links', () => withWindow(async () => {
  const requests = []
  const run = {
    run_id: 'deep-run',
    role: 'seer',
    status: 'reviewing',
    started_at: '2026-06-08T10:00:00'
  }
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/roles/overview') throw new Error('overview unavailable')
    if (path === '/roles') return { roles: ['seer'] }
    if (path === '/roles/seer/versions') return { versions: [] }
    if (path === '/roles/seer/leaderboard') return { entries: [] }
    if (path === '/evolution-runs?limit=80&offset=0&source=evolution') {
      return {
        runs: [],
        batches: [],
        pagination: { total: 0, offset: 0, limit: 80, returned: 0, has_more: false }
      }
    }
    if (path === '/evolution-runs/deep-run') return run
    if (path === '/evolution-runs/deep-run/diff') return { diffs: [] }
    if (/^\/evolution-runs\/deep-run\/games\?/.test(path)) {
      return { games: [], pagination: { total: 0, offset: 0, limit: 80, returned: 0, has_more: false } }
    }
    if (path === '/evolution-runs/deep-run/proposals') {
      return {
        run_id: 'deep-run',
        role: 'seer',
        proposals: [{ proposal_id: 'proposal-b', status: 'pending', target_file: 'seer.md', summary: 'update seer plan' }],
        gate_report: { gate_report_id: 'gate-1', decision: 'review_required' },
        trust_bundle: {
          trust_bundle_id: 'trust-deep-1',
          bundle_hash: 'hash-deep-1',
          gate_report_id: 'gate-1',
          training_game_ids: ['train-deep-1'],
          proposal_ids: ['proposal-b'],
          completeness: { complete: true, score: 1, missing: [] }
        }
      }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  assert.equal(workbench.selectedRunId.value, 'deep-run')
  assert.equal(workbench.selectedRun.value.role, 'seer')
  assert.deepEqual(workbench.runRows.value.map((item) => item.id), ['deep-run'])
  assert.equal(workbench.selectedProposalRows.value[0].apiId, 'proposal-b')
  assert.equal(workbench.trustBundleDrawerOpen.value, true)
  assert.equal(workbench.trustBundleAudit.value.trust_bundle_id, 'trust-deep-1')
  assert.equal(workbench.trustBundleAudit.value.gate_report_id, 'gate-1')
  assert.equal(workbench.evolutionDeepLinkTarget.value.status, 'applied')
  assert.equal(workbench.evolutionDeepLinkTarget.value.panel, 'review')
  assert.deepEqual(workbench.evolutionDeepLinkTarget.value.pending, [])
  assert.equal(workbench.evolutionDeepLinkTarget.value.selected_run_id, 'deep-run')
  assert.equal(requests.includes('/evolution-runs/deep-run/trust-bundle'), false)
}, { hash: '#evolution?run_id=deep-run&proposal_id=proposal-b&gate_report_id=gate-1' }))

test('evolution workbench consumes role version hash deep links without defaulting to first run', () => withWindow(async () => {
  const requests = []
  const visibleRun = {
    run_id: 'other-run',
    role: 'witch',
    status: 'completed',
    started_at: '2026-06-08T09:00:00'
  }
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/roles/overview') throw new Error('overview unavailable')
    if (path === '/roles') return { roles: ['seer', 'witch'] }
    if (path === '/roles/seer/versions') return { versions: [{ version_id: 'seer_v2', source: 'candidate' }] }
    if (path === '/roles/witch/versions') return { versions: [] }
    if (/^\/roles\/[^/]+\/leaderboard$/.test(path)) return { entries: [] }
    if (path === '/roles/seer/versions/seer_v2') {
      return {
        role: 'seer',
        version_id: 'seer_v2',
        trust_bundle_id: 'trust-version',
        source_run_id: 'deep-run',
        metrics: { win_rate: 0.61 }
      }
    }
    if (path === '/evolution-runs?limit=80&offset=0&source=evolution') {
      return {
        runs: [visibleRun],
        batches: [],
        pagination: { total: 1, offset: 0, limit: 80, returned: 1, has_more: false }
      }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  assert.equal(workbench.selectedRole.value, 'seer')
  assert.equal(workbench.selectedVersionId.value, 'seer_v2')
  assert.equal(workbench.selectedVersionDetail.value.data.version_id, 'seer_v2')
  assert.equal(workbench.selectedRunId.value, '')
  assert.equal(workbench.evolutionDeepLinkTarget.value.status, 'applied')
  assert.equal(workbench.evolutionDeepLinkTarget.value.panel, 'versions')
  assert.equal(requests.includes('/evolution-runs/other-run'), false)
}, { hash: '#evolution?role=seer&version_id=seer_v2' }))

test('evolution workbench trust bundle audit exposes missing empty state', () => {
  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch: async () => ({}) })
  workbench.selectedRunId.value = 'evo-missing-trust'
  workbench.selectedRun.value = {
    id: 'evo-missing-trust',
    run_id: 'evo-missing-trust',
    entityType: 'run',
    role: 'seer',
    status: 'reviewing',
    gate_report_id: 'gate_without_trust'
  }
  workbench.selectedProposalReview.value = {
    loading: false,
    error: '',
    unsupported: false,
    summary: { accepted: 1, applied: 0 }
  }

  workbench.openTrustBundleDrawer('review')

  assert.equal(workbench.trustBundleAudit.value.hasTrustBundle, false)
  assert.match(workbench.trustBundleAudit.value.emptyMessage, /缺少信任包/)
  assert.equal(workbench.trustBundleAudit.value.completeness.status, 'missing')
  assert.deepEqual(workbench.trustBundleAudit.value.missingKeys, ['trust_bundle'])
})

test('evolution workbench opens trust audit from version detail metadata', () => {
  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch: async () => ({}) })
  workbench.selectedVersionDetail.value = {
    loading: false,
    error: '',
    data: {
      role: 'seer',
      version_id: 'seer_v2',
      trust_bundle_id: 'trust_version_2',
      bundle_hash: 'hash_version_2',
      gate_report_id: 'gate_version_2',
      source_run_id: 'evo-source-run',
      rollback_target: 'seer_v1'
    }
  }

  workbench.openTrustBundleDrawer('version')

  assert.equal(workbench.trustBundleAudit.value.source, 'version')
  assert.equal(workbench.trustBundleAudit.value.sourceLabel, '版本详情')
  assert.equal(workbench.trustBundleAudit.value.version_id, 'seer_v2')
  assert.equal(workbench.trustBundleAudit.value.trust_bundle_id, 'trust_version_2')
  assert.equal(workbench.trustBundleAudit.value.gate_report_id, 'gate_version_2')
  assert.equal(workbench.trustBundleAudit.value.source_run_id, 'evo-source-run')
  assert.equal(workbench.trustBundleAudit.value.rollback_target, 'seer_v1')
  assert.equal(workbench.trustBundleAudit.value.completeness.status, 'unknown')
})

test('evolution workbench maps proposal action failures to warning notices', async () => {
  const apiFetch = async (path) => {
    if (path === '/evolution-runs/evo-review/proposals/apply-accepted') {
      throw new Error('no accepted proposals to apply')
    }
    if (path === '/evolution-runs/evo-review/proposals/proposal-a/accept') {
      throw new Error('proposal not found')
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvolutionWorkbench({ installLifecycle: false, apiFetch })
  await workbench.applyAcceptedProposals('evo-review')

  assert.deepEqual(workbench.notice.value, {
    type: 'warning',
    message: '没有已接受提案可应用。'
  })
  assert.equal(workbench.error.value, '没有已接受提案可应用。')

  await workbench.acceptProposal({ id: 'proposal-a' }, 'evo-review')
  assert.deepEqual(workbench.notice.value, {
    type: 'warning',
    message: '提案不存在，请刷新审核面板。'
  })
  assert.equal(workbench.error.value, '提案不存在，请刷新审核面板。')
})

test('evolution workbench maps rollback and load-more failures to local notices', async () => {
  const apiFetch = async (path) => {
    if (path === '/roles/seer/rollback/v-missing') throw new Error('version not found')
    if (path === '/evolution-runs?limit=1&offset=1&source=evolution') throw new Error('run not found')
    if (path === '/evolution-runs/evo-run/games?phase=training&limit=1&offset=1') throw new Error('run not found')
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvolutionWorkbench({
    installLifecycle: false,
    runListLimit: 1,
    sampleGameListLimit: 1,
    apiFetch
  })

  await workbench.rollback('seer', 'v-missing')
  assert.deepEqual(workbench.notice.value, {
    type: 'warning',
    message: '版本不存在，请刷新版本列表。'
  })
  assert.equal(workbench.error.value, '版本不存在，请刷新版本列表。')

  workbench.runPagination.value = { total: 2, offset: 0, limit: 1, returned: 1, has_more: true }
  await workbench.loadMoreRuns()
  assert.deepEqual(workbench.notice.value, {
    type: 'warning',
    message: '运行不存在，请刷新列表。'
  })
  assert.equal(workbench.error.value, '运行不存在，请刷新列表。')

  workbench.selectedRunId.value = 'evo-run'
  workbench.sampleGamePagination.value = {
    training: { total: 2, offset: 0, limit: 1, returned: 1, has_more: true },
    baseline: { total: 0, offset: 0, limit: 1, returned: 0, has_more: false },
    candidate: { total: 0, offset: 0, limit: 1, returned: 0, has_more: false }
  }
  await workbench.loadMoreSampleGames('training')
  assert.deepEqual(workbench.notice.value, {
    type: 'warning',
    message: '运行不存在，请刷新列表。'
  })
  assert.equal(workbench.selectedSampleState.value.error, '运行不存在，请刷新列表。')
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

test('evaluation workbench starts selected benchmark suite and filters leaderboard by evaluation set', () => withWindow(async () => {
  const requests = []
  const suite = {
    id: 'role-baseline-quick-v1',
    version: 1,
    name: 'Role Baseline Quick',
    target_type: 'role_version',
    roles: ['seer'],
    game_count: 3,
    max_days: 5,
    seed_set_id: 'role-baseline-quick-202606',
    seed_count: 3,
    seed_preview: [260600, 260601, 260602],
    cost_tier: 'smoke',
    evaluation_set_id: 'role-baseline-quick-v1@v1',
    last_run: {
      batch_id: 'bench-suite-last-run',
      status: 'completed',
      current_stage: 'completed',
      result_count: 1,
      diagnostic_count: 0
    },
    latest_snapshot: {
      snapshot_id: 'snap-suite-latest',
      title: 'Quick suite release',
      row_count: 2,
      content_hash: 'sha256:abcdef',
      created_at: '2026-06-09T10:00:00+08:00'
    }
  }
  let batches = []
  const apiFetch = async (path, options = {}) => {
    requests.push({ path, body: options.body ? JSON.parse(options.body) : null })
    if (path === '/benchmarks') return { items: [suite] }
    if (path === '/roles') return { roles: ['seer', 'witch'] }
    if (/^\/roles\/[^/]+\/leaderboard\?evaluation_set_id=role-baseline-quick-v1%40v1$/.test(path)) {
      return { entries: [] }
    }
    if (/^\/roles\/[^/]+\/versions$/.test(path)) return { versions: [] }
    if (path === '/evolution-runs') return { runs: [], batches }
    if (path === '/benchmark') {
      batches = [{
        kind: 'benchmark_batch',
        batch_id: 'bench-suite-new',
        roles: ['seer'],
        status: 'queued',
        started_at: '2026-06-07T10:00:00',
        benchmark: {
          id: suite.id,
          version: suite.version,
          evaluation_set_id: suite.evaluation_set_id
        }
      }]
      return { batch_id: 'bench-suite-new' }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  assert.equal(workbench.selectedBenchmarkId.value, 'role-baseline-quick-v1')
  assert.equal(workbench.selectedRole.value, 'seer')
  assert.deepEqual(workbench.roleRows.value.map((role) => role.key), ['seer'])
  assert.equal(workbench.form.value.battle_games, 3)
  assert.equal(workbench.form.value.max_days, 5)
  assert.equal(workbench.selectedBenchmarkTargetType.value, 'role_version')
  assert.equal(workbench.selectedBenchmarkCanLaunch.value, true)
  assert.equal(workbench.selectedBenchmarkSuite.value.seed_count, 3)
  assert.deepEqual(workbench.selectedBenchmarkSuite.value.seed_preview, ['260600', '260601', '260602'])
  assert.equal(workbench.selectedBenchmarkSuite.value.cost_tier, 'smoke')
  assert.equal(workbench.selectedBenchmarkSuite.value.last_run.batch_id, 'bench-suite-last-run')
  assert.equal(workbench.selectedBenchmarkSuite.value.latest_snapshot.snapshot_id, 'snap-suite-latest')
  assert.equal(
    requests.some((item) => item.path === '/roles/seer/leaderboard?evaluation_set_id=role-baseline-quick-v1%40v1'),
    true
  )

  await workbench.startEvaluation()

  assert.deepEqual(requests.find((item) => item.path === '/benchmark')?.body, {
    benchmark_id: 'role-baseline-quick-v1',
    roles: ['seer'],
    battle_games: 3,
    max_days: 5
  })
  assert.equal(workbench.filteredBatchRunRows.value[0].id, 'bench-suite-new')
}))

test('evaluation workbench blocks launch for non-launchable benchmark suites', () => withWindow(async () => {
  const requests = []
  const suite = {
    id: 'role-deprecated-v1',
    version: 1,
    name: 'Role Deprecated',
    target_type: 'role_version',
    roles: ['seer'],
    game_count: 3,
    max_days: 5,
    seed_set_id: 'role-baseline-quick-202606',
    seed_count: 3,
    seed_preview: [260600, 260607, 260619],
    evaluation_set_id: 'role-deprecated-v1@v1',
    config_hash: 'sha256:deprecated-suite',
    status: 'deprecated',
    launchable: false,
    launch_disabled_reason: '该评测套件已废弃，只保留历史审计，不能启动。',
    metrics: { primary: 'avg_role_score', secondary: ['target_side_win_rate'] },
    gates: { min_completed_games: 1 },
    judge: { enable_decision_judge: true, judge_max_decisions: 10 }
  }
  const apiFetch = async (path, options = {}) => {
    requests.push({ path, body: options.body ? JSON.parse(options.body) : null })
    if (path === '/benchmarks') return { items: [suite] }
    if (path === '/roles') return { roles: ['seer'] }
    if (/^\/roles\/[^/]+\/leaderboard\?evaluation_set_id=role-deprecated-v1%40v1$/.test(path)) return { entries: [] }
    if (/^\/roles\/[^/]+\/versions$/.test(path)) return { versions: [] }
    if (path === '/evolution-runs') return { runs: [], batches: [] }
    if (path === '/benchmark/plan') throw new Error('plan should not be requested for deprecated suite')
    if (path === '/benchmark') throw new Error('launch should not be requested for deprecated suite')
    if (path.startsWith('/benchmark/diagnostics')) return { diagnostics: [], summary: {} }
    if (path.startsWith('/benchmark/snapshots')) return { snapshots: [] }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  assert.equal(workbench.selectedBenchmarkId.value, 'role-deprecated-v1')
  assert.equal(workbench.selectedBenchmarkSuite.value.status, 'deprecated')
  assert.equal(workbench.selectedBenchmarkSuite.value.statusLabel, '废弃')
  assert.equal(workbench.selectedBenchmarkSuite.value.launchable, false)
  assert.equal(
    workbench.selectedBenchmarkSuiteLaunchDisabledReason.value,
    '该评测套件已废弃，只保留历史审计，不能启动。'
  )
  assert.equal(workbench.selectedBenchmarkCanLaunch.value, false)
  assert.equal(workbench.benchmarkPlan.value, null)
  assert.equal(workbench.benchmarkPlanError.value, '该评测套件已废弃，只保留历史审计，不能启动。')

  await workbench.startEvaluation()

  assert.equal(workbench.notice.value.type, 'warning')
  assert.equal(workbench.error.value, '该评测套件已废弃，只保留历史审计，不能启动。')
  assert.equal(requests.some((item) => item.path === '/benchmark'), false)
  assert.equal(requests.some((item) => item.path === '/benchmark/plan'), false)
}))

test('evaluation workbench falls back to legacy benchmark runs when suite has no scoped batches', () => withWindow(async () => {
  const suite = {
    id: 'role-baseline-quick-v1',
    version: 1,
    name: 'Role Baseline Quick',
    target_type: 'role_version',
    roles: ['seer'],
    game_count: 3,
    max_days: 5,
    evaluation_set_id: 'role-baseline-quick-v1@v1'
  }
  const legacyBatch = {
    kind: 'benchmark_batch',
    batch_id: 'bench-legacy-run',
    roles: ['seer'],
    status: 'completed',
    started_at: '2026-06-07T10:00:00'
  }
  const apiFetch = async (path) => {
    if (path === '/benchmarks') return { items: [suite] }
    if (path === '/roles') return { roles: ['seer'] }
    if (/^\/roles\/[^/]+\/leaderboard/.test(path)) return { entries: [] }
    if (/^\/roles\/[^/]+\/versions$/.test(path)) return { versions: [] }
    if (path === '/evolution-runs') return { runs: [], batches: [legacyBatch] }
    if (path === '/benchmark/plan') return { budget: {}, estimates: {}, warnings: [] }
    if (path.startsWith('/benchmark/diagnostics')) return { diagnostics: [], summary: {} }
    if (path.startsWith('/benchmark/snapshots')) return { snapshots: [] }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  assert.equal(workbench.selectedBenchmarkId.value, 'role-baseline-quick-v1')
  assert.equal(workbench.selectedSuiteBatchRunRows.value.length, 0)
  assert.equal(workbench.unscopedBenchmarkRunRows.value.length, 1)
  assert.equal(workbench.selectedBenchmarkUsingLegacyRuns.value, true)
  assert.equal(workbench.filteredBatchRunRows.value[0].id, 'bench-legacy-run')
}))

test('evaluation workbench can switch to ad-hoc model scope without evaluation set filtering', () => withWindow(async () => {
  const requests = []
  const suite = {
    id: 'model-baseline-standard-v1',
    version: 1,
    name: 'Model Baseline Standard',
    target_type: 'model',
    roles: ['seer'],
    game_count: 30,
    max_days: 5,
    evaluation_set_id: 'model-baseline-standard-v1@v1'
  }
  const apiFetch = async (path, options = {}) => {
    requests.push({ path, body: options.body ? JSON.parse(options.body) : null })
    if (path === '/benchmarks') return { items: [suite] }
    if (path === '/roles') return { roles: ['seer'] }
    if (path === '/models/leaderboard?evaluation_set_id=model-baseline-standard-v1%40v1') return { entries: [] }
    if (path === '/models/leaderboard') {
      return {
        entries: [{
          scope: 'model',
          model_id: 'qwen-max',
          model_config_hash: 'runtime-hash',
          strength_score: 0.81,
          avg_role_score: 0.81,
          target_side_win_rate: 0.64,
          rankable: true
        }]
      }
    }
    if (path === '/evolution-runs') return { runs: [], batches: [] }
    if (path === '/benchmark/plan') return { budget: {}, estimates: {}, warnings: [] }
    if (path.startsWith('/benchmark/diagnostics')) return { diagnostics: [], summary: {} }
    if (path.startsWith('/benchmark/snapshots')) return { snapshots: [] }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  assert.equal(workbench.selectedBenchmarkId.value, 'model-baseline-standard-v1')
  assert.equal(workbench.modelLeaderboardRows.value.length, 0)

  workbench.selectLegacyBenchmarkScope('model')
  await flushPromises(20)

  assert.equal(workbench.selectedBenchmarkId.value, '')
  assert.equal(workbench.selectedBenchmarkIsModelSuite.value, true)
  assert.equal(workbench.selectedBenchmarkSuiteLabel.value, '临时模型评测')
  assert.equal(workbench.modelLeaderboardRows.value[0].model_id, 'qwen-max')
  assert.equal(requests.some((item) => item.path === '/models/leaderboard'), true)
}))

test('evaluation workbench sends selected role target version for role-version benchmark suite', () => withWindow(async () => {
  const requests = []
  const suite = {
    id: 'role-baseline-quick-v1',
    version: 1,
    name: 'Role Baseline Quick',
    target_type: 'role_version',
    roles: ['seer', 'witch'],
    game_count: 3,
    max_days: 5,
    seed_set_id: 'role-baseline-quick-202606',
    evaluation_set_id: 'role-baseline-quick-v1@v1'
  }
  const apiFetch = async (path, options = {}) => {
    requests.push({ path, body: options.body ? JSON.parse(options.body) : null })
    if (path === '/benchmarks') return { items: [suite] }
    if (path === '/roles') return { roles: ['seer', 'witch'] }
    if (/^\/roles\/[^/]+\/leaderboard\?evaluation_set_id=role-baseline-quick-v1%40v1$/.test(path)) return { entries: [] }
    if (/^\/roles\/[^/]+\/versions$/.test(path)) return { versions: [] }
    if (path === '/evolution-runs') return { runs: [], batches: [] }
    if (path === '/benchmark') return { batch_id: 'bench-role-target-version' }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()
  workbench.selectRole('witch')
  workbench.form.value.target_version_id = 'witch_candidate_v2'
  await flushPromises()
  await workbench.startEvaluation()

  assert.equal(workbench.selectedRole.value, 'witch')
  assert.deepEqual(workbench.roleRows.value.map((role) => role.key), ['seer', 'witch'])
  assert.deepEqual(requests.find((item) => item.path === '/benchmark')?.body, {
    benchmark_id: 'role-baseline-quick-v1',
    roles: ['witch'],
    target_versions: { witch: 'witch_candidate_v2' },
    battle_games: 3,
    max_days: 5
  })
}))

test('evaluation workbench allows canary target and blocks shadow target versions', () => withWindow(async () => {
  const requests = []
  const suite = {
    id: 'role-baseline-quick-v1',
    version: 1,
    name: 'Role Baseline Quick',
    target_type: 'role_version',
    roles: ['witch'],
    game_count: 3,
    max_days: 5,
    seed_set_id: 'role-baseline-quick-202606',
    evaluation_set_id: 'role-baseline-quick-v1@v1'
  }
  const versions = [
    {
      version_id: 'witch_baseline_v1',
      source: 'registry',
      is_baseline: true,
      release_stage: 'baseline'
    },
    {
      version_id: 'witch_canary_v2',
      source: 'candidate',
      release_stage: 'canary',
      provenance: { source: 'evolution', release_stage: 'canary' }
    },
    {
      version_id: 'witch_shadow_v3',
      source: 'candidate',
      release_stage: 'shadow',
      provenance: { source: 'evolution', release_stage: 'shadow' }
    }
  ]
  const apiFetch = async (path, options = {}) => {
    const method = options.method || 'GET'
    requests.push({ path, method, body: options.body ? JSON.parse(options.body) : null })
    if (path === '/benchmarks') return { items: [suite] }
    if (path === '/roles/overview?evaluation_set_id=role-baseline-quick-v1%40v1') {
      return {
        roles: ['witch'],
        versions: { witch: versions },
        leaderboards: {
          witch: {
            entries: [
              {
                target_version_id: 'witch_baseline_v1',
                target_role_role_weighted_score: 0.62,
                target_side_win_rate: 0.51,
                game_count: 12,
                rankable: true
              },
              {
                target_version_id: 'witch_canary_v2',
                target_role_role_weighted_score: 0.71,
                target_side_win_rate: 0.58,
                game_count: 12,
                rankable: true
              },
              {
                target_version_id: 'witch_shadow_v3',
                target_role_role_weighted_score: 0.74,
                target_side_win_rate: 0.6,
                game_count: 12,
                rankable: true
              }
            ]
          }
        }
      }
    }
    if (path === '/benchmark/plan') {
      return {
        benchmark_id: suite.id,
        target_type: 'role_version',
        evaluation_set_id: suite.evaluation_set_id,
        seed_set_id: suite.seed_set_id,
        total_games: 3,
        budget: { estimated_units: 9, limit_units: 30, exceeded: false, status: 'ok' },
        rankable: { eligible: true, gate_count: 3 }
      }
    }
    if (path === '/evolution-runs') return { runs: [], batches: [] }
    if (path === '/benchmark') return { batch_id: 'bench-canary-target' }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  assert.equal(workbench.selectedRole.value, 'witch')
  assert.deepEqual(
    workbench.roleLeaderboardRows.value.map((row) => [row.version_id, row.release_stage]),
    [
      ['witch_baseline_v1', 'baseline']
    ]
  )
  assert.deepEqual(
    workbench.currentBenchmarkLeaderboardRows.value.map((row) => [row.version_id, row.release_stage]),
    [
      ['witch_baseline_v1', 'baseline']
    ]
  )
  assert.deepEqual(
    workbench.roleTargetVersionRows.value.map((row) => [row.version_id, row.release_stage, row.targetDisabled]),
    [
      ['witch_baseline_v1', 'baseline', false],
      ['witch_canary_v2', 'canary', false],
      ['witch_shadow_v3', 'shadow', true]
    ]
  )

  workbench.form.value.target_version_id = 'witch_canary_v2'
  await flushPromises(10)
  assert.equal(workbench.selectedRoleTargetVersionBlockedReason.value, '')
  assert.equal(workbench.selectedBenchmarkCanLaunch.value, true)
  await workbench.startEvaluation()

  const benchmarkRequestsAfterCanary = requests.filter((item) => item.path === '/benchmark')
  assert.equal(benchmarkRequestsAfterCanary.length, 1)
  assert.deepEqual(benchmarkRequestsAfterCanary[0].body, {
    benchmark_id: 'role-baseline-quick-v1',
    roles: ['witch'],
    target_versions: { witch: 'witch_canary_v2' },
    battle_games: 3,
    max_days: 5
  })

  workbench.form.value.target_version_id = 'witch_shadow_v3'
  await flushPromises(10)
  assert.equal(workbench.selectedRoleTargetVersion.value.version_id, 'witch_shadow_v3')
  assert.equal(workbench.selectedRoleTargetVersionBlockedReason.value, '影子版本需先晋升金丝雀后才能评测。')
  assert.equal(workbench.selectedBenchmarkCanLaunch.value, false)
  assert.equal(workbench.benchmarkPlan.value, null)
  assert.equal(workbench.benchmarkPlanError.value, '影子版本需先晋升金丝雀后才能评测。')

  await workbench.startEvaluation()
  assert.equal(workbench.notice.value.type, 'warning')
  assert.equal(workbench.error.value, '影子版本需先晋升金丝雀后才能评测。')
  assert.equal(requests.filter((item) => item.path === '/benchmark').length, 1)
}))

test('evaluation workbench exposes benchmark boundary and budget plan before launch', () => withWindow(async () => {
  const requests = []
  const suite = {
    id: 'role-baseline-quick-v1',
    version: 1,
    label: 'Role Baseline Quick v1',
    name: 'Role Baseline Quick',
    target_type: 'role_version',
    roles: ['seer'],
    game_count: 3,
    max_days: 5,
    seed_set_id: 'role-baseline-quick-202606',
    seed_count: 3,
    seed_preview: [260600, 260601, 260602],
    cost_tier: 'smoke',
    evaluation_set_id: 'role-baseline-quick-v1@v1',
    config_hash: 'sha256:role-plan'
  }
  const apiFetch = async (path, options = {}) => {
    requests.push({ path, body: options.body ? JSON.parse(options.body) : null })
    if (path === '/benchmarks') return { items: [suite] }
    if (path === '/roles') return { roles: ['seer'] }
    if (/^\/roles\/[^/]+\/leaderboard\?evaluation_set_id=role-baseline-quick-v1%40v1$/.test(path)) return { entries: [] }
    if (/^\/roles\/[^/]+\/versions$/.test(path)) return { versions: [] }
    if (path === '/evolution-runs') return { runs: [], batches: [] }
    if (path === '/benchmark/plan') {
      return {
        benchmark_id: suite.id,
        target_type: 'role_version',
        evaluation_set_id: suite.evaluation_set_id,
        seed_set_id: suite.seed_set_id,
        benchmark_config_hash: suite.config_hash,
        dry_run: true,
        total_games: 3,
        eval_batch_count: 1,
        judge_decisions: 36,
        estimated_tokens: 225900,
        estimated_cost: 0.4518,
        currency: 'USD',
        expected_duration_seconds: 97,
        concurrency_policy: {
          policy: 'bounded_sequential_eval_batches',
          game_concurrency: 3,
          judge_concurrency: 2,
          expected_duration_seconds: 97
        },
        assumptions: [
          'game_decision_units = total_games * max_days * 12 players',
          'judge_decision_units = total_games * judge_max_decisions when decision judge is enabled',
          'estimated_tokens = game units and judge units multiplied by planner token assumptions',
          'estimated_cost uses planner token cost assumptions and is reported before launch'
        ],
        budget: {
          estimated_units: 36,
          limit_units: 50,
          estimated_tokens: 225900,
          estimated_cost: 0.4518,
          currency: 'USD',
          exceeded: { value: false, reasons: [], evidence: [] },
          status: 'ok'
        },
        rankable: {
          eligible: true,
          gate_count: 3
        }
      }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  const suiteBoundary = workbench.selectedBenchmarkSuite.value
  assert.equal(workbench.selectedBenchmarkId.value, 'role-baseline-quick-v1')
  assert.equal(workbench.selectedBenchmarkTargetType.value, 'role_version')
  assert.equal(workbench.selectedBenchmarkEvaluationSetId.value, 'role-baseline-quick-v1@v1')
  assert.equal(workbench.selectedBenchmarkSuiteLabel.value, 'Role Baseline Quick v1')
  assert.equal(suiteBoundary.seed_set_id, 'role-baseline-quick-202606')
  assert.equal(suiteBoundary.seed_count, 3)
  assert.deepEqual(suiteBoundary.seed_preview, ['260600', '260601', '260602'])
  assert.equal(suiteBoundary.cost_tier, 'smoke')
  assert.equal(workbench.form.value.battle_games, 3)
  assert.equal(workbench.form.value.max_days, 5)
  assert.equal(workbench.launchBattleGames.value, 3)
  assert.equal(workbench.launchMaxDays.value, 5)
  assert.equal(workbench.benchmarkPlan.value.evaluation_set_id, 'role-baseline-quick-v1@v1')
  assert.equal(workbench.benchmarkPlan.value.seed_set_id, 'role-baseline-quick-202606')
  assert.equal(workbench.benchmarkPlan.value.total_games, 3)
  assert.equal(workbench.benchmarkPlan.value.dry_run, true)
  assert.equal(workbench.benchmarkPlan.value.estimated_tokens, 225900)
  assert.equal(workbench.benchmarkPlan.value.estimated_cost, 0.4518)
  assert.equal(workbench.benchmarkPlan.value.currency, 'USD')
  assert.equal(workbench.benchmarkPlan.value.expected_duration_seconds, 97)
  assert.equal(workbench.benchmarkPlan.value.concurrency_policy.judge_concurrency, 2)
  assert.equal(workbench.benchmarkPlan.value.assumptions.length, 4)
  assert.equal(workbench.benchmarkPlan.value.budget.estimated_units, 36)
  assert.deepEqual(workbench.benchmarkPlan.value.budget.exceeded, { value: false, reasons: [], evidence: [] })
  assert.equal(workbench.benchmarkPlanBudgetExceeded.value, false)
  assert.equal(workbench.selectedBenchmarkCanLaunch.value, true)
  assert.deepEqual(requests.find((item) => item.path === '/benchmark/plan')?.body, {
    benchmark_id: 'role-baseline-quick-v1',
    roles: ['seer'],
    battle_games: 3,
    max_days: 5
  })
}))

test('evaluation workbench blocks launch from structured budget evidence without treating false evidence as truthy', () => withWindow(async () => {
  const requests = []
  const suite = {
    id: 'role-baseline-quick-v1',
    version: 1,
    label: 'Role Baseline Quick v1',
    name: 'Role Baseline Quick',
    target_type: 'role_version',
    roles: ['seer'],
    game_count: 3,
    max_days: 5,
    seed_set_id: 'role-baseline-quick-202606',
    evaluation_set_id: 'role-baseline-quick-v1@v1'
  }
  const apiFetch = async (path, options = {}) => {
    requests.push({ path, body: options.body ? JSON.parse(options.body) : null })
    if (path === '/benchmarks') return { items: [suite] }
    if (path === '/roles') return { roles: ['seer'] }
    if (/^\/roles\/[^/]+\/leaderboard\?evaluation_set_id=role-baseline-quick-v1%40v1$/.test(path)) return { entries: [] }
    if (/^\/roles\/[^/]+\/versions$/.test(path)) return { versions: [] }
    if (path === '/evolution-runs') return { runs: [], batches: [] }
    if (path === '/benchmark/plan') {
      return {
        benchmark_id: suite.id,
        target_type: 'role_version',
        evaluation_set_id: suite.evaluation_set_id,
        seed_set_id: suite.seed_set_id,
        dry_run: true,
        total_games: 3,
        estimated_tokens: 225900,
        estimated_cost: 0.4518,
        currency: 'USD',
        expected_duration_seconds: 97,
        concurrency_policy: {
          policy: 'bounded_sequential_eval_batches',
          game_concurrency: 3,
          judge_concurrency: 2,
          expected_duration_seconds: 97
        },
        assumptions: ['planner contract'],
        budget: {
          estimated_units: 210,
          limit_units: 100,
          limit_cost: 0.1,
          estimated_tokens: 225900,
          estimated_cost: 0.4518,
          currency: 'USD',
          exceeded: {
            value: true,
            reasons: ['estimated_units_exceed_limit_units', 'estimated_cost_exceed_limit_cost'],
            evidence: [
              { metric: 'estimated_units', estimated: 210, limit: 100, delta: 110, unit: 'llm_call_unit' },
              { metric: 'estimated_cost', estimated: 0.4518, limit: 0.1, delta: 0.3518, unit: 'USD' }
            ]
          }
        },
        launchable: false,
        warnings: [
          {
            kind: 'budget_exceeded',
            message: '预计评测成本超过预算上限',
            reasons: ['estimated_units_exceed_limit_units', 'estimated_cost_exceed_limit_cost'],
            evidence: [
              { metric: 'estimated_units', estimated: 210, limit: 100, delta: 110, unit: 'llm_call_unit' },
              { metric: 'estimated_cost', estimated: 0.4518, limit: 0.1, delta: 0.3518, unit: 'USD' }
            ]
          }
        ]
      }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  workbench.form.value.budget_limit_units = 100
  workbench.form.value.budget_limit_cost = 0.1
  workbench.form.value.stop_after_budget_units = 120
  await workbench.refreshAll()

  assert.equal(workbench.benchmarkPlan.value.dry_run, true)
  assert.equal(workbench.benchmarkPlan.value.budget.exceeded.value, true)
  assert.deepEqual(workbench.benchmarkPlan.value.budget.exceeded.reasons, [
    'estimated_units_exceed_limit_units',
    'estimated_cost_exceed_limit_cost'
  ])
  assert.equal(workbench.benchmarkPlanBudgetExceeded.value, true)
  assert.equal(workbench.selectedBenchmarkCanLaunch.value, false)
  assert.equal(requests.filter((item) => item.path === '/benchmark').length, 0)
  assert.deepEqual(requests.find((item) => item.path === '/benchmark/plan')?.body, {
    benchmark_id: 'role-baseline-quick-v1',
    roles: ['seer'],
    battle_games: 3,
    max_days: 5,
    budget_limit_units: 100,
    budget_limit_cost: 0.1,
    stop_after_budget_units: 120
  })
}))

test('evaluation workbench keeps model benchmark suite out of role-version leaderboard and launches model scope', () => withWindow(async () => {
  const requests = []
  const suite = {
    id: 'model-baseline-standard-v1',
    version: 1,
    name: 'Model Baseline Standard',
    target_type: 'model',
    roles: ['seer', 'witch'],
    game_count: 30,
    max_days: 5,
    seed_set_id: 'model-baseline-standard-202606',
    seed_count: 30,
    seed_preview: ['271000', '271001', '271002', '271003', '271004'],
    cost_tier: 'release',
    evaluation_set_id: 'model-baseline-standard-v1@v1'
  }
  let batches = [{
    kind: 'benchmark_batch',
    batch_id: 'model-suite-run',
    roles: ['seer', 'witch'],
    status: 'completed',
    started_at: '2026-06-07T10:00:00',
    benchmark: {
      id: suite.id,
      version: suite.version,
      target_type: suite.target_type,
      evaluation_set_id: suite.evaluation_set_id
    }
  }]
  const apiFetch = async (path, options = {}) => {
    requests.push({ path, body: options.body ? JSON.parse(options.body) : null })
    if (path === '/benchmarks') return { items: [suite] }
    if (path === '/roles') return { roles: ['seer', 'witch', 'guard'] }
    if (path === '/models/leaderboard?evaluation_set_id=model-baseline-standard-v1%40v1') {
      return {
        entries: [{
          scope: 'model',
          subject_id: 'runtime_hash_v1',
          model_id: 'qwen-max',
          model_config_hash: 'runtime_hash_v1',
          strength_score: 0.68,
          avg_role_score: 0.66,
          target_side_win_rate: 0.57,
          game_count: 30,
          rankable: true
        }]
      }
    }
    if (path === '/evolution-runs') return { runs: [], batches }
    if (path === '/benchmark') {
      batches = [{
        kind: 'benchmark_batch',
        batch_id: 'model-suite-new',
        roles: ['seer', 'witch'],
        status: 'queued',
        started_at: '2026-06-07T11:00:00',
        benchmark: {
          id: suite.id,
          version: suite.version,
          target_type: suite.target_type,
          evaluation_set_id: suite.evaluation_set_id
        }
      }]
      return { batch_id: 'model-suite-new' }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  assert.equal(workbench.selectedBenchmarkId.value, 'model-baseline-standard-v1')
  assert.equal(workbench.selectedBenchmarkTargetType.value, 'model')
  assert.equal(workbench.selectedBenchmarkIsModelSuite.value, true)
  assert.equal(workbench.selectedBenchmarkCanLaunch.value, true)
  assert.deepEqual(workbench.selectedBenchmarkSuite.value.roles, ['seer', 'witch'])
  assert.equal(workbench.form.value.battle_games, 30)
  assert.equal(workbench.form.value.max_days, 5)
  assert.equal(workbench.selectedBenchmarkSuite.value.seed_count, 30)
  assert.deepEqual(workbench.selectedBenchmarkSuite.value.seed_preview, ['271000', '271001', '271002', '271003', '271004'])
  assert.equal(workbench.selectedBenchmarkSuite.value.cost_tier, 'release')
  assert.equal(workbench.filteredBatchRunRows.value[0].benchmarkTargetType, 'model')
  assert.equal(workbench.modelLeaderboardRows.value[0].model_id, 'qwen-max')
  assert.equal(requests.some((item) => item.path.startsWith('/models/leaderboard')), true)
  assert.equal(requests.some((item) => /^\/roles\/[^/]+\/leaderboard/.test(item.path)), false)
  assert.equal(requests.some((item) => item.path.includes('/versions')), false)

  workbench.selectedRole.value = ''
  workbench.form.value.model_id = 'qwen-max'
  workbench.form.value.model_config_hash = 'runtime_hash_v1'
  await flushPromises()
  assert.equal(workbench.selectedBenchmarkCanLaunch.value, true)
  await workbench.startEvaluation()

  const launchBody = requests.find((item) => item.path === '/benchmark')?.body
  assert.deepEqual(launchBody, {
    benchmark_id: 'model-baseline-standard-v1',
    target_type: 'model',
    model_id: 'qwen-max',
    model_config_hash: 'runtime_hash_v1',
    battle_games: 30,
    max_days: 5
  })
  assert.equal(Object.hasOwn(launchBody, 'roles'), false)
  assert.equal(Object.hasOwn(launchBody, 'target_versions'), false)
  assert.equal(workbench.filteredBatchRunRows.value[0].id, 'model-suite-new')
  assert.deepEqual(workbench.notice.value, { type: 'success', message: '评测已启动。' })
}))

test('evaluation workbench launches model benchmark with selected model profile only', () => withWindow(async () => {
  const requests = []
  const suite = {
    id: 'model-profile-standard-v1',
    version: 1,
    name: 'Model Profile Standard',
    target_type: 'model',
    roles: ['seer'],
    game_count: 12,
    max_days: 4,
    evaluation_set_id: 'model-profile-standard-v1@v1'
  }
  let batches = []
  const apiFetch = async (path, options = {}) => {
    requests.push({ path, body: options.body ? JSON.parse(options.body) : null })
    if (path.startsWith('/health/preflight?scope=benchmark_start')) {
      return {
        ready: true,
        status: 'ok',
        gate: { ready: true, status: 'ok', blockers: [], warnings: [], actions: [] },
        checks: { llm_connectivity: { status: 'ok' } }
      }
    }
    if (path === '/settings/model-profiles') {
      return {
        profiles: [{
          profile_id: 'profile-benchmark-main',
          name: '主评测模型',
          provider: 'openai-compatible',
          model: 'qwen-max',
          enabled: true,
          has_api_key: true,
          default_scopes: { benchmark: true },
          last_test_status: 'ok',
          model_config_hash: 'profile-hash'
        }]
      }
    }
    if (path === '/benchmarks') return { items: [suite] }
    if (path === '/roles') return { roles: ['seer'] }
    if (path === '/models/leaderboard?evaluation_set_id=model-profile-standard-v1%40v1') return { entries: [] }
    if (path === '/benchmark/plan') return { budget: {}, estimates: {}, warnings: [] }
    if (path === '/evolution-runs') return { runs: [], batches }
    if (path === '/benchmark') {
      batches = [{
        kind: 'benchmark_batch',
        batch_id: 'model-profile-run',
        roles: ['seer'],
        status: 'queued',
        started_at: '2026-06-07T11:00:00',
        benchmark: {
          id: suite.id,
          version: suite.version,
          target_type: suite.target_type,
          evaluation_set_id: suite.evaluation_set_id
        }
      }]
      return { batch_id: 'model-profile-run' }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  assert.equal(workbench.form.value.model_profile_id, 'profile-benchmark-main')
  workbench.form.value.model_id = 'manual-model'
  workbench.form.value.model_config_hash = 'manual-hash'
  await flushPromises()
  await workbench.startEvaluation()

  const launchBody = requests.find((item) => item.path === '/benchmark')?.body
  assert.deepEqual(launchBody, {
    benchmark_id: 'model-profile-standard-v1',
    target_type: 'model',
    model_profile_id: 'profile-benchmark-main',
    battle_games: 12,
    max_days: 4
  })
  assert.equal(Object.hasOwn(launchBody, 'model_id'), false)
  assert.equal(Object.hasOwn(launchBody, 'model_config_hash'), false)
  assert.deepEqual(workbench.notice.value, { type: 'success', message: '评测已启动。' })
}))

test('evaluation workbench loads benchmark batch detail games and diagnostics', () => withWindow(async () => {
  const requests = []
  const batch = {
    kind: 'benchmark_batch',
    batch_id: 'bench-detail',
    roles: ['seer'],
    status: 'completed',
    started_at: '2026-06-07T10:00:00',
    benchmark: {
      id: 'role-baseline-quick-v1',
      version: 1,
      target_type: 'role_version',
      evaluation_set_id: 'role-baseline-quick-v1@v1',
      seed_set_id: 'role-baseline-quick-202606',
      config_hash: 'sha256:front'
    }
  }
  const apiFetch = async (path) => {
    requests.push({ path })
    if (path === '/benchmarks') return { items: [] }
    if (path === '/roles') return { roles: ['seer'] }
    if (path === '/roles/seer/leaderboard') return { entries: [] }
    if (path === '/roles/seer/versions') return { versions: [] }
    if (path === '/evolution-runs') return { runs: [], batches: [batch] }
    if (path === '/benchmark/batch/bench-detail') {
      return {
        kind: 'benchmark_batch_detail',
        batch_id: 'bench-detail',
        status: 'completed',
        benchmark: batch.benchmark,
        target_type: 'role_version',
        roles: ['seer'],
        result_count: 1,
        results: [{
          result_batch_id: 'bench-detail_seer',
          target_role: 'seer',
          config: { target_role: 'seer', target_version_id: 'seer_candidate_v2' },
          completed: 1,
          errored: 1,
          attempted_game_count: 2,
          rankable: false,
          rankable_reason: 'completed_games 1 < required 2',
          score_summary: {
            avg_role_score: 0.62,
            target_side_win_rate: 0.5,
            decision_judge_aggregate: { status: 'degraded', metrics: { judged: 1 } }
          }
        }],
        game_summary: {
          total: 2,
          completed: 1,
          failed: 1,
          timeout: 0,
          abnormal: 0,
          by_status: { completed: 1, failed: 1 }
        },
        diagnostic_summary: {
          total: 2,
          by_kind: { rankable_failed: 1, game_failure: 1 },
          by_origin: { result: 1, game: 1 }
        }
      }
    }
    if (path === '/benchmark/batch/bench-detail/games?status=problem&limit=20&offset=0') {
      return {
        kind: 'benchmark_batch_games',
        batch_id: 'bench-detail',
        games: [{
          result_batch_id: 'bench-detail_seer',
          target_role: 'seer',
          game_id: 'bench-detail-game-002',
          status: 'failed',
          seed: 260601,
          event_count: 0,
          decision_count: 0,
          diagnostic_count: 1,
          replay_available: false
        }],
        pagination: { total: 1, offset: 0, limit: 20, returned: 1, has_more: false }
      }
    }
    if (path === '/benchmark/batch/bench-detail/games?limit=20&offset=0') {
      return {
        kind: 'benchmark_batch_games',
        batch_id: 'bench-detail',
        games: [{
          result_batch_id: 'bench-detail_seer',
          target_role: 'seer',
          game_id: 'bench-detail-game-001',
          status: 'completed',
          seed: 260600,
          event_count: 1,
          decision_count: 1,
          diagnostic_count: 0,
          replay_available: true
        }],
        pagination: { total: 2, offset: 0, limit: 20, returned: 1, has_more: true }
      }
    }
    if (path === '/benchmark/batch/bench-detail/diagnostics') {
      return {
        kind: 'benchmark_batch_diagnostics',
        batch_id: 'bench-detail',
        diagnostics: [{
          origin: 'result',
          kind: 'rankable_failed',
          level: 'warning',
          stage: 'leaderboard.rankable',
          message: 'completed_games 1 < required 2',
          target_role: 'seer',
          result_batch_id: 'bench-detail_seer'
        }],
        summary: { total: 1, by_kind: { rankable_failed: 1 }, by_origin: { result: 1 } }
      }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()
  const loaded = await workbench.loadBenchmarkBatchDetail('bench-detail')

  assert.equal(loaded, true)
  assert.equal(workbench.selectedBenchmarkBatchId.value, 'bench-detail')
  assert.equal(workbench.benchmarkBatchDetail.value.benchmarkLabel, 'role-baseline-quick-v1@v1')
  assert.equal(workbench.benchmarkBatchDetail.value.resultRows[0].rankableLabel, '未入榜')
  assert.equal(workbench.benchmarkBatchDetail.value.resultRows[0].targetVersionShort, 'seer_can')
  assert.equal(workbench.benchmarkBatchGames.value[0].game_id, 'bench-detail-game-002')
  assert.equal(workbench.benchmarkBatchGames.value[0].statusLabel, '失败')
  assert.equal(workbench.benchmarkBatchDiagnostics.value[0].kindLabel, '未入榜')
  assert.equal(
    requests.some((item) => item.path === '/benchmark/batch/bench-detail/games?status=problem&limit=20&offset=0'),
    true
  )

  workbench.setBenchmarkGameStatusFilter('all')
  await flushPromises()
  assert.equal(
    requests.some((item) => item.path === '/benchmark/batch/bench-detail/games?limit=20&offset=0'),
    true
  )
}))

test('evaluation workbench loads aggregate benchmark diagnostics without selected run', () => withWindow(async () => {
  const requests = []
  const suite = {
    id: 'role-baseline-quick-v1',
    version: 1,
    name: 'Role Baseline Quick',
    target_type: 'role_version',
    roles: ['seer'],
    game_count: 3,
    max_days: 5,
    seed_set_id: 'role-baseline-quick-202606',
    evaluation_set_id: 'role-baseline-quick-v1@v1'
  }
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/benchmarks') return { items: [suite] }
    if (path === '/roles') return { roles: ['seer'] }
    if (path === '/roles/seer/leaderboard?evaluation_set_id=role-baseline-quick-v1%40v1') return { entries: [] }
    if (path === '/roles/seer/versions') return { versions: [] }
    if (path === '/evolution-runs') return { runs: [], batches: [] }
    if (path === '/benchmark/snapshots?scope=role_version&evaluation_set_id=role-baseline-quick-v1%40v1&benchmark_id=role-baseline-quick-v1&target_role=seer&limit=50') {
      return { items: [] }
    }
    if (path === '/benchmark/diagnostics?scope=role_version&evaluation_set_id=role-baseline-quick-v1%40v1&benchmark_id=role-baseline-quick-v1&target_role=seer&limit=200&offset=0') {
      return {
        kind: 'benchmark_diagnostics',
        schema_version: 1,
        scope: 'role_version',
        evaluation_set_id: 'role-baseline-quick-v1@v1',
        benchmark_id: 'role-baseline-quick-v1',
        target_role: 'seer',
        diagnostics: [
          {
            batch_id: 'bench-a',
            origin: 'result',
            kind: 'rankable_failed',
            level: 'warning',
            stage: 'leaderboard.rankable',
            message: 'completed_games 1 < required 2',
            target_role: 'seer',
            result_batch_id: 'bench-a_seer'
          },
          {
            batch_id: 'bench-b',
            origin: 'game',
            kind: 'game_failure',
            level: 'error',
            stage: 'game.run',
            message: 'game timeout',
            target_role: 'seer',
            result_batch_id: 'bench-b_seer',
            game_id: 'bench-b-game-001',
            seed: 260600
          }
        ],
        affected_runs: [
          {
            batch_id: 'bench-a',
            status: 'completed',
            benchmark_id: 'role-baseline-quick-v1',
            evaluation_set_id: 'role-baseline-quick-v1@v1',
            target_type: 'role_version',
            roles: ['seer'],
            diagnostic_count: 1,
            diagnostic_summary: { total: 1, by_kind: { rankable_failed: 1 } }
          },
          {
            batch_id: 'bench-b',
            status: 'failed',
            benchmark_id: 'role-baseline-quick-v1',
            evaluation_set_id: 'role-baseline-quick-v1@v1',
            target_type: 'role_version',
            roles: ['seer'],
            diagnostic_count: 1,
            diagnostic_summary: { total: 1, by_kind: { game_failure: 1 } }
          }
        ],
        affected_games: [
          {
            batch_id: 'bench-b',
            result_batch_id: 'bench-b_seer',
            target_role: 'seer',
            game_id: 'bench-b-game-001',
            status: 'timeout',
            seed: 260600,
            diagnostic_count: 1,
            replay_available: true,
            history_game_id: 'bench-b-game-001'
          }
        ],
        summary: {
          total: 2,
          by_kind: { game_failure: 1, rankable_failed: 1 },
          by_level: { error: 1, warning: 1 },
          by_origin: { game: 1, result: 1 },
          affected_run_count: 2,
          affected_game_count: 1
        },
        pagination: { total: 2, offset: 0, limit: 200, returned: 2, has_more: false }
      }
    }
    if (path.startsWith('/roles/overview?')) throw new Error('overview unsupported')
    if (path.startsWith('/benchmark/plan')) return { budget: {}, estimates: {}, warnings: [] }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  assert.equal(workbench.selectedBenchmarkBatchId.value, '')
  assert.equal(workbench.benchmarkDiagnosticAggregateDiagnostics.value.length, 2)
  assert.equal(workbench.benchmarkDiagnosticAggregateDiagnostics.value[1].kindLabel, '失败局')
  assert.equal(workbench.benchmarkDiagnosticAggregateSummary.value.affected_run_count, 2)
  assert.deepEqual(workbench.benchmarkDiagnosticAggregateRuns.value.map((run) => run.id), ['bench-a', 'bench-b'])
  assert.equal(workbench.benchmarkDiagnosticAggregateGames.value[0].replayHash, '#logs?workspace=archive&game_id=bench-b-game-001')
  assert.equal(
    requests.includes('/benchmark/diagnostics?scope=role_version&evaluation_set_id=role-baseline-quick-v1%40v1&benchmark_id=role-baseline-quick-v1&target_role=seer&limit=200&offset=0'),
    true
  )
}))

test('evaluation workbench loads server leaderboard compare rows', () => withWindow(async () => {
  const requests = []
  const suite = {
    id: 'role-baseline-quick-v1',
    version: 1,
    name: 'Role Baseline Quick',
    target_type: 'role_version',
    roles: ['seer'],
    game_count: 3,
    max_days: 5,
    seed_set_id: 'role-baseline-quick-202606',
    evaluation_set_id: 'role-baseline-quick-v1@v1'
  }
  const apiFetch = async (path) => {
    requests.push(path)
    if (path === '/benchmarks') return { items: [suite] }
    if (path === '/roles') return { roles: ['seer'] }
    if (path === '/roles/seer/leaderboard?evaluation_set_id=role-baseline-quick-v1%40v1') {
      return {
        entries: [
          {
            scope: 'role_version',
            subject_id: 'seer_baseline',
            target_role: 'seer',
            target_version_id: 'seer_baseline',
            evaluation_set_id: 'role-baseline-quick-v1@v1',
            avg_role_score: 0.6,
            target_side_win_rate: 0.55,
            rankable: true,
            is_baseline: true
          }
        ]
      }
    }
    if (path === '/roles/seer/versions') return { versions: [] }
    if (path === '/evolution-runs') return { runs: [], batches: [] }
    if (path === '/leaderboards/compare?scope=role_version&evaluation_set_id=role-baseline-quick-v1%40v1&target_role=seer&limit=100') {
      return {
        kind: 'benchmark_leaderboard_compare',
        schema_version: 1,
        scope: 'role_version',
        evaluation_set_id: 'role-baseline-quick-v1@v1',
        target_role: 'seer',
        baseline_subject_id: 'seer_baseline',
        baseline: { subject_id: 'seer_baseline' },
        rows: [
          {
            scope: 'role_version',
            subject_id: 'seer_baseline',
            target_role: 'seer',
            target_version_id: 'seer_baseline',
            evaluation_set_id: 'role-baseline-quick-v1@v1',
            avg_role_score: 0.6,
            target_side_win_rate: 0.55,
            rankable: true,
            is_reference: true,
            change: 'reference',
            delta_vs_baseline: { score: 0, target_side_win_rate: 0 }
          },
          {
            scope: 'role_version',
            subject_id: 'seer_candidate',
            target_role: 'seer',
            target_version_id: 'seer_candidate',
            evaluation_set_id: 'role-baseline-quick-v1@v1',
            avg_role_score: 0.66,
            target_side_win_rate: 0.58,
            rankable: true,
            change: 'improvement',
            delta_vs_baseline: { score: 0.06, target_side_win_rate: 0.03 }
          }
        ],
        summary: { row_count: 2, improvement_count: 1, reference_count: 1 }
      }
    }
    if (path === '/benchmark/snapshots?scope=role_version&evaluation_set_id=role-baseline-quick-v1%40v1&benchmark_id=role-baseline-quick-v1&target_role=seer&limit=50') return { items: [] }
    if (path === '/benchmark/diagnostics?scope=role_version&evaluation_set_id=role-baseline-quick-v1%40v1&benchmark_id=role-baseline-quick-v1&target_role=seer&limit=200&offset=0') {
      return { diagnostics: [], affected_runs: [], affected_games: [], summary: {}, pagination: { total: 0, offset: 0, limit: 200, returned: 0, has_more: false } }
    }
    if (path.startsWith('/roles/overview?')) throw new Error('overview unsupported')
    if (path === '/benchmark/plan') return { budget: {}, estimates: {}, warnings: [] }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()

  assert.equal(workbench.benchmarkLeaderboardCompare.value.kind, 'benchmark_leaderboard_compare')
  assert.equal(workbench.benchmarkLeaderboardCompare.value.rows[1].change, 'improvement')
  assert.equal(workbench.benchmarkLeaderboardCompare.value.rows[1].delta_vs_baseline.score, 0.06)
  assert.equal(
    requests.includes('/leaderboards/compare?scope=role_version&evaluation_set_id=role-baseline-quick-v1%40v1&target_role=seer&limit=100'),
    true
  )
}))

test('evaluation workbench composes reportable benchmark run data from detail games and diagnostics', () => withWindow(async () => {
  const requests = []
  const batch = {
    kind: 'benchmark_batch',
    batch_id: 'bench-report',
    roles: ['witch'],
    status: 'completed',
    started_at: '2026-06-07T12:00:00',
    completed_at: '2026-06-07T12:08:00',
    benchmark: {
      id: 'role-baseline-standard-v1',
      version: 2,
      target_type: 'role_version',
      evaluation_set_id: 'role-baseline-standard-v1@v2',
      seed_set_id: 'role-standard-202606',
      config_hash: 'sha256:reportable'
    },
    diagnostic_count: 3,
    warning_count: 1
  }
  const detailResponse = {
    kind: 'benchmark_batch_detail',
    batch_id: 'bench-report',
    status: 'completed',
    benchmark: batch.benchmark,
    target_type: 'role_version',
    roles: ['witch'],
    result_count: 1,
    results: [{
      result_batch_id: 'bench-report_witch',
      target_role: 'witch',
      config: { target_role: 'witch', target_version_id: 'witch_candidate_v9' },
      completed: 18,
      errored: 2,
      attempted_game_count: 20,
      rankable: false,
      rankable_reason: 'leaderboard gate failed: errored games exceed threshold',
      score_summary: {
        avg_role_score: 0.54,
        target_side_win_rate: 0.45,
        decision_judge_aggregate: { avg_score: 7.3, judged_decisions: 42 }
      },
      diagnostic_count: 2,
      warning_count: 1
    }],
    game_summary: {
      total: 20,
      completed: 18,
      failed: 1,
      timeout: 1,
      abnormal: 0,
      by_status: { completed: 18, failed: 1, timeout: 1 }
    },
    diagnostic_summary: {
      total: 3,
      by_kind: { leaderboard_gate_failed: 1, game_failure: 1, timeout: 1 },
      by_origin: { result: 1, game: 2 }
    }
  }
  const problemGames = [{
    result_batch_id: 'bench-report_witch',
    target_role: 'witch',
    game_id: 'bench-report-game-019',
    status: 'failed',
    seed: 260919,
    event_count: 3,
    decision_count: 2,
    diagnostic_count: 2,
    replay_available: false
  }]
  const allGames = [{
    result_batch_id: 'bench-report_witch',
    target_role: 'witch',
    game_id: 'bench-report-game-001',
    status: 'completed',
    seed: 260901,
    event_count: 54,
    decision_count: 13,
    diagnostic_count: 0,
    replay_available: true
  }, ...problemGames]
  const diagnosticsResponse = {
    kind: 'benchmark_batch_diagnostics',
    batch_id: 'bench-report',
    diagnostics: [{
      origin: 'result',
      kind: 'leaderboard_gate_failed',
      level: 'error',
      stage: 'leaderboard.rankable',
      message: 'leaderboard gate failed: errored games exceed threshold',
      target_role: 'witch',
      result_batch_id: 'bench-report_witch'
    }, {
      origin: 'game',
      kind: 'game_failure',
      level: 'warning',
      stage: 'game.persist',
      message: 'game failed before scoring',
      target_role: 'witch',
      result_batch_id: 'bench-report_witch',
      game_id: 'bench-report-game-019',
      seed: 260919
    }],
    summary: {
      total: 2,
      by_kind: { leaderboard_gate_failed: 1, game_failure: 1 },
      by_origin: { result: 1, game: 1 },
      by_level: { error: 1, warning: 1 }
    }
  }
  const reportResponse = {
    kind: 'benchmark_run_report',
    schema_version: 1,
    generated_at: '2026-06-07T12:09:00Z',
    run_id: 'bench-report',
    batch_id: 'bench-report',
    status: 'completed',
    evaluation_set_id: 'role-baseline-standard-v1@v2',
    seed_set_id: 'role-standard-202606',
    benchmark_config_hash: 'sha256:reportable',
    suite: {
      id: 'role-baseline-standard-v1',
      version: 2,
      target_type: 'role_version',
      evaluation_set_id: 'role-baseline-standard-v1@v2',
      seed_set_id: 'role-standard-202606',
      config_hash: 'sha256:reportable'
    },
    subject: {
      type: 'role_version',
      target_role: 'witch',
      target_version_id: 'witch_candidate_v9'
    },
    summary: {
      result_count: 1,
      problem_game_count: 1,
      diagnostic_count: 2,
      game_summary: detailResponse.game_summary,
      diagnostic_summary: diagnosticsResponse.summary
    },
    results: detailResponse.results,
    gates: [{
      result_batch_id: 'bench-report_witch',
      target_role: 'witch',
      rankable: false,
      reason: 'leaderboard gate failed: errored games exceed threshold'
    }],
    problem_games: problemGames,
    diagnostics: diagnosticsResponse.diagnostics,
    tags: [],
    reproducibility: {
      run_id: 'bench-report',
      batch_id: 'bench-report',
      benchmark_id: 'role-baseline-standard-v1',
      evaluation_set_id: 'role-baseline-standard-v1@v2',
      seed_set_id: 'role-standard-202606',
      benchmark_config_hash: 'sha256:reportable',
      roles: ['witch'],
      target_type: 'role_version'
    },
    leaderboard: {
      rankable_count: 0,
      unrankable_count: 1,
      rows: [{
        result_batch_id: 'bench-report_witch',
        target_role: 'witch',
        rankable: false,
        rankable_reason: 'leaderboard gate failed: errored games exceed threshold'
      }]
    }
  }
  let reportShouldFail = false
  const apiFetch = async (path) => {
    requests.push({ path })
    if (path === '/benchmarks') return { items: [] }
    if (path === '/roles') return { roles: ['witch'] }
    if (path === '/roles/witch/leaderboard') return { entries: [] }
    if (path === '/roles/witch/versions') return { versions: [] }
    if (path === '/evolution-runs') return { runs: [], batches: [batch] }
    if (path === '/benchmark/batch/bench-report') return detailResponse
    if (path === '/benchmark/batch/bench-report/games?status=problem&limit=20&offset=0') {
      return {
        kind: 'benchmark_batch_games',
        batch_id: 'bench-report',
        games: problemGames,
        pagination: { total: 1, offset: 0, limit: 20, returned: 1, has_more: false }
      }
    }
    if (path === '/benchmark/batch/bench-report/games?limit=20&offset=0') {
      return {
        kind: 'benchmark_batch_games',
        batch_id: 'bench-report',
        games: allGames,
        pagination: { total: 20, offset: 0, limit: 20, returned: 2, has_more: false }
      }
    }
    if (path === '/benchmark/batch/bench-report/diagnostics') return diagnosticsResponse
    if (path === '/benchmark/batch/bench-report/report' || path === '/benchmark/batch/bench-report/report?format=json') {
      if (reportShouldFail) throw new Error('canonical report unavailable')
      return reportResponse
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()
  const loaded = await workbench.loadBenchmarkBatchDetail('bench-report')

  assert.equal(loaded, true)
  assert.equal(workbench.selectedBenchmarkBatchRun.value.id, 'bench-report')
  assert.equal(workbench.selectedBenchmarkBatchRun.value.benchmarkLabel, 'role-baseline-standard-v1@v2')
  assert.equal(workbench.selectedBenchmarkBatchRun.value.evaluationSetId, 'role-baseline-standard-v1@v2')
  assert.equal(requests.some((item) => item.path === '/benchmark/batch/bench-report/report'), true)
  assert.equal(workbench.benchmarkBatchReport.value.kind, 'benchmark_run_report')
  assert.equal(workbench.benchmarkBatchReport.value.run_id, 'bench-report')
  assert.equal(workbench.benchmarkBatchReport.value.evaluation_set_id, 'role-baseline-standard-v1@v2')
  assert.equal(workbench.benchmarkBatchReport.value.seed_set_id, 'role-standard-202606')
  assert.equal(workbench.benchmarkBatchReport.value.benchmark_config_hash, 'sha256:reportable')
  assert.equal(workbench.benchmarkBatchReport.value.problem_games[0].game_id, 'bench-report-game-019')
  assert.equal(workbench.benchmarkBatchReport.value.diagnostics[1].stage, 'game.persist')
  assert.deepEqual(workbench.benchmarkBatchReport.value.reproducibility, {
    run_id: 'bench-report',
    batch_id: 'bench-report',
    benchmark_id: 'role-baseline-standard-v1',
    evaluation_set_id: 'role-baseline-standard-v1@v2',
    seed_set_id: 'role-standard-202606',
    benchmark_config_hash: 'sha256:reportable',
    roles: ['witch'],
    target_type: 'role_version'
  })

  const reportData = {
    selectedRun: workbench.selectedBenchmarkBatchRun.value,
    boundary: {
      benchmark: workbench.benchmarkBatchDetail.value.benchmark.id,
      evaluation_set_id: workbench.benchmarkBatchDetail.value.benchmark.evaluation_set_id,
      seed_set_id: workbench.benchmarkBatchDetail.value.benchmark.seed_set_id,
      config_hash: workbench.benchmarkBatchDetail.value.benchmark.config_hash
    },
    results: workbench.benchmarkBatchDetail.value.resultRows.map((row) => ({
      result_batch_id: row.result_batch_id,
      rankableLabel: row.rankableLabel,
      rankableReason: row.rankableReason
    })),
    games: workbench.benchmarkBatchGames.value.map((game) => ({
      game_id: game.game_id,
      status: game.status,
      seed: game.seed,
      seedLabel: game.seedLabel,
      diagnostic_count: game.diagnostic_count
    })),
    diagnostics: workbench.benchmarkBatchDiagnostics.value.map((diagnostic) => ({
      kindLabel: diagnostic.kindLabel,
      levelLabel: diagnostic.levelLabel,
      message: diagnostic.message,
      stage: diagnostic.stage
    }))
  }

  assert.deepEqual(reportData.boundary, {
    benchmark: 'role-baseline-standard-v1',
    evaluation_set_id: 'role-baseline-standard-v1@v2',
    seed_set_id: 'role-standard-202606',
    config_hash: 'sha256:reportable'
  })
  assert.deepEqual(reportData.results, [{
    result_batch_id: 'bench-report_witch',
    rankableLabel: '未入榜',
    rankableReason: 'leaderboard gate failed: errored games exceed threshold'
  }])
  assert.deepEqual(reportData.games, [{
    game_id: 'bench-report-game-019',
    status: 'failed',
    seed: 260919,
    seedLabel: '260919',
    diagnostic_count: 2
  }])
  assert.deepEqual(reportData.diagnostics[0], {
    kindLabel: '门禁失败',
    levelLabel: '错误',
    message: 'leaderboard gate failed: errored games exceed threshold',
    stage: 'leaderboard.rankable'
  })
  assert.deepEqual(reportData.diagnostics[1], {
    kindLabel: '失败局',
    levelLabel: '警告',
    message: 'game failed before scoring',
    stage: 'game.persist'
  })

  workbench.setBenchmarkGameStatusFilter('all')
  await flushPromises()
  assert.equal(workbench.selectedBenchmarkBatchRun.value.id, 'bench-report')
  assert.equal(workbench.benchmarkBatchDetail.value.benchmark.config_hash, 'sha256:reportable')
  assert.equal(workbench.benchmarkBatchDetail.value.resultRows[0].rankableReason, 'leaderboard gate failed: errored games exceed threshold')
  assert.equal(workbench.benchmarkBatchGames.value[0].status, 'completed')
  assert.equal(workbench.benchmarkBatchGames.value[0].seedLabel, '260901')
  assert.equal(workbench.benchmarkBatchDiagnostics.value[0].message, 'leaderboard gate failed: errored games exceed threshold')

  workbench.setBenchmarkGameStatusFilter('problem')
  await flushPromises()
  assert.equal(workbench.selectedBenchmarkBatchRun.value.id, 'bench-report')
  assert.equal(workbench.benchmarkBatchDetail.value.benchmark.evaluation_set_id, 'role-baseline-standard-v1@v2')
  assert.equal(workbench.benchmarkBatchGames.value[0].status, 'failed')
  assert.equal(workbench.benchmarkBatchGames.value[0].diagnostic_count, 2)
  assert.equal(workbench.benchmarkBatchDiagnostics.value[1].stage, 'game.persist')
  assert.equal(
    requests.filter((item) => item.path === '/benchmark/batch/bench-report/games?status=problem&limit=20&offset=0').length,
    2
  )
  assert.equal(
    requests.some((item) => item.path === '/benchmark/batch/bench-report/games?limit=20&offset=0'),
    true
  )

  reportShouldFail = true
  const loadedWithReportFailure = await workbench.loadBenchmarkBatchDetail('bench-report')
  assert.equal(loadedWithReportFailure, true)
  assert.equal(Boolean(workbench.benchmarkBatchReportError.value), true)
  assert.equal(workbench.benchmarkBatchDetail.value.batch_id, 'bench-report')
  assert.equal(workbench.benchmarkBatchDetail.value.benchmark.config_hash, 'sha256:reportable')
  assert.equal(workbench.benchmarkBatchGames.value[0].status, 'failed')
  assert.equal(workbench.benchmarkBatchDiagnostics.value[0].kind, 'leaderboard_gate_failed')
}))

test('evaluation workbench loads report history and keeps canonical report selectable', () => withWindow(async () => {
  const createHarness = ({ historyShouldFail = false } = {}) => {
    const requests = []
    const suite = {
      id: 'role-baseline-standard-v1',
      version: 2,
      name: 'Role Baseline Standard',
      target_type: 'role_version',
      roles: ['seer'],
      game_count: 20,
      max_days: 5,
      evaluation_set_id: 'role-baseline-standard-v1@v2',
      seed_set_id: 'role-standard-202606',
      config_hash: 'sha256:history-suite'
    }
    const batch = {
      kind: 'benchmark_batch',
      batch_id: 'bench-history',
      roles: ['seer'],
      status: 'completed',
      started_at: '2026-06-08T10:00:00Z',
      finished_at: '2026-06-08T10:08:00Z',
      benchmark: {
        id: suite.id,
        version: suite.version,
        target_type: 'role_version',
        evaluation_set_id: suite.evaluation_set_id,
        seed_set_id: suite.seed_set_id,
        config_hash: suite.config_hash
      },
      result: {
        result_batch_id: 'bench-history_seer',
        target_role: 'seer',
        target_version_id: 'seer_candidate_history',
        completed: 19,
        errored: 1,
        rankable: true,
        score_summary: { avg_role_score: 0.63, target_side_win_rate: 0.56 }
      }
    }
    const detailResponse = {
      kind: 'benchmark_batch_detail',
      schema_version: 1,
      batch_id: 'bench-history',
      status: 'completed',
      benchmark: batch.benchmark,
      target_type: 'role_version',
      result_count: 1,
      results: [{
        result_batch_id: 'bench-history_seer',
        target_role: 'seer',
        target_version_id: 'seer_candidate_history',
        completed: 19,
        errored: 1,
        attempted_game_count: 20,
        rankable: true,
        score_summary: { avg_role_score: 0.63, target_side_win_rate: 0.56 },
        diagnostic_count: 1
      }],
      game_summary: {
        total: 20,
        completed: 19,
        failed: 1,
        timeout: 0,
        abnormal: 0,
        by_status: { completed: 19, failed: 1 }
      },
      diagnostic_summary: {
        total: 1,
        by_kind: { game_failure: 1 },
        by_level: { warning: 1 },
        by_origin: { game: 1 }
      }
    }
    const problemGames = [{
      result_batch_id: 'bench-history_seer',
      target_role: 'seer',
      game_id: 'bench-history-game-020',
      status: 'failed',
      seed: 260920,
      event_count: 8,
      decision_count: 3,
      diagnostic_count: 1,
      replay_available: true
    }]
    const diagnosticsResponse = {
      kind: 'benchmark_batch_diagnostics',
      schema_version: 1,
      batch_id: 'bench-history',
      diagnostics: [{
        origin: 'game',
        kind: 'game_failure',
        level: 'warning',
        stage: 'game.persist',
        message: 'archive persisted after retry',
        target_role: 'seer',
        result_batch_id: 'bench-history_seer',
        game_id: 'bench-history-game-020',
        seed: 260920
      }],
      summary: detailResponse.diagnostic_summary
    }
    const reportPayload = {
      kind: 'benchmark_run_report',
      schema_version: 1,
      generated_at: '2026-06-08T10:09:00Z',
      run_id: 'bench-history',
      batch_id: 'bench-history',
      status: 'completed',
      evaluation_set_id: suite.evaluation_set_id,
      seed_set_id: suite.seed_set_id,
      benchmark_config_hash: suite.config_hash,
      suite: {
        id: suite.id,
        version: suite.version,
        target_type: 'role_version',
        evaluation_set_id: suite.evaluation_set_id,
        seed_set_id: suite.seed_set_id,
        config_hash: suite.config_hash
      },
      subject: {
        type: 'role_version',
        target_role: 'seer',
        target_version_id: 'seer_candidate_history'
      },
      summary: {
        result_count: 1,
        problem_game_count: 1,
        diagnostic_count: 1,
        game_summary: detailResponse.game_summary,
        diagnostic_summary: diagnosticsResponse.summary
      },
      results: detailResponse.results,
      gates: [{
        result_batch_id: 'bench-history_seer',
        target_role: 'seer',
        rankable: true,
        reason: ''
      }],
      problem_games: problemGames,
      diagnostics: diagnosticsResponse.diagnostics,
      tags: [],
      reproducibility: {
        run_id: 'bench-history',
        batch_id: 'bench-history',
        benchmark_id: suite.id,
        evaluation_set_id: suite.evaluation_set_id,
        seed_set_id: suite.seed_set_id,
        benchmark_config_hash: suite.config_hash,
        roles: ['seer'],
        target_type: 'role_version'
      },
      leaderboard: {
        rankable_count: 1,
        unrankable_count: 0,
        rows: [{
          result_batch_id: 'bench-history_seer',
          target_role: 'seer',
          rankable: true,
          rankable_reason: ''
        }]
      }
    }
    const reportSummary = {
      kind: 'benchmark_run_report_summary',
      schema_version: 1,
      report_id: 'report-bench-history',
      run_id: 'bench-history',
      batch_id: 'bench-history',
      status: 'completed',
      suite: reportPayload.suite,
      subject: reportPayload.subject,
      summary: reportPayload.summary,
      evaluation_set_id: suite.evaluation_set_id,
      seed_set_id: suite.seed_set_id,
      benchmark_config_hash: suite.config_hash,
      problem_game_count: 1,
      diagnostic_count: 1,
      rankable_count: 1,
      unrankable_count: 0,
      generated_at: '2026-06-08T10:09:00Z'
    }
    const apiFetch = async (path) => {
      requests.push({ path })
      if (path === '/benchmarks') return { items: [suite] }
      if (path === '/roles') return { roles: ['seer'] }
      if (path === '/roles/seer/leaderboard?evaluation_set_id=role-baseline-standard-v1%40v2') return { entries: [] }
      if (path === '/roles/seer/versions') return { versions: [] }
      if (path === '/evolution-runs') return { runs: [], batches: [batch] }
      if (path === '/benchmark/plan') return { budget: {}, estimates: {}, warnings: [] }
      if (path.startsWith('/leaderboards/compare?')) {
        return { kind: 'benchmark_leaderboard_compare', schema_version: 1, rows: [], summary: { row_count: 0 } }
      }
      if (path.startsWith('/benchmark/diagnostics?')) {
        return {
          kind: 'benchmark_diagnostics',
          schema_version: 1,
          diagnostics: [],
          affected_runs: [],
          affected_games: [],
          summary: {},
          pagination: { total: 0, offset: 0, limit: 200, returned: 0, has_more: false }
        }
      }
      if (path.startsWith('/benchmark/snapshots?')) {
        return { kind: 'benchmark_snapshots', schema_version: 1, items: [], pagination: { total: 0, returned: 0 } }
      }
      if (path.startsWith('/benchmark/reports?')) {
        if (historyShouldFail) throw new Error('report history unavailable')
        return {
          kind: 'benchmark_run_reports',
          schema_version: 1,
          items: [reportSummary],
          pagination: { total: 1, offset: 0, limit: 50, returned: 1, has_more: false }
        }
      }
      if (path === '/benchmark/batch/bench-history') return detailResponse
      if (path === '/benchmark/batch/bench-history/games?status=problem&limit=20&offset=0') {
        return {
          kind: 'benchmark_batch_games',
          schema_version: 1,
          batch_id: 'bench-history',
          games: problemGames,
          pagination: { total: 1, offset: 0, limit: 20, returned: 1, has_more: false }
        }
      }
      if (path === '/benchmark/batch/bench-history/diagnostics') return diagnosticsResponse
      if (path === '/benchmark/batch/bench-history/report') return reportPayload
      throw new Error(`unexpected ${path}`)
    }

    return { workbench: useEvaluationWorkbench({ installLifecycle: false, apiFetch }), requests }
  }

  const success = createHarness()
  await success.workbench.refreshAll()
  assert.equal(typeof success.workbench.loadBenchmarkReportHistory, 'function')
  await success.workbench.loadBenchmarkReportHistory()

  const historyRequest = success.requests.find((item) => item.path.startsWith('/benchmark/reports?'))
  assert.equal(Boolean(historyRequest), true)
  const historyQuery = new URLSearchParams(historyRequest.path.split('?')[1])
  assert.equal(historyQuery.get('scope'), 'role_version')
  assert.equal(historyQuery.get('evaluation_set_id'), 'role-baseline-standard-v1@v2')
  assert.equal(historyQuery.get('benchmark_id'), 'role-baseline-standard-v1')
  assert.equal(historyQuery.get('target_role'), 'seer')
  assert.equal(historyQuery.has('limit'), true)
  assert.equal(historyQuery.get('offset'), '0')
  assert.equal(success.workbench.benchmarkReportHistory.value[0].kind, 'benchmark_run_report_summary')
  assert.equal(success.workbench.benchmarkReportHistory.value[0].report_id, 'report-bench-history')
  assert.equal(success.workbench.benchmarkReportHistory.value[0].run_id, 'bench-history')
  assert.equal(success.workbench.benchmarkReportHistory.value[0].evaluation_set_id, 'role-baseline-standard-v1@v2')
  assert.equal(success.workbench.benchmarkReportHistory.value[0].problem_game_count, 1)
  assert.equal(success.workbench.benchmarkReportHistory.value[0].diagnostic_count, 1)
  assert.equal(success.workbench.benchmarkReportHistory.value[0].rankable_count, 1)
  assert.equal(success.workbench.benchmarkReportHistoryPagination.value.total, 1)
  assert.equal(success.workbench.benchmarkReportHistoryError.value, '')
  assert.equal(success.workbench.benchmarkReportHistoryLoading.value, false)

  const loaded = await success.workbench.loadBenchmarkBatchDetail(success.workbench.benchmarkReportHistory.value[0].batch_id)
  assert.equal(loaded, true)
  assert.equal(success.workbench.selectedBenchmarkBatchRun.value.id, 'bench-history')
  assert.equal(success.requests.some((item) => item.path === '/benchmark/batch/bench-history/report'), true)
  assert.equal(success.workbench.benchmarkBatchReport.value.kind, 'benchmark_run_report')
  assert.equal(success.workbench.benchmarkBatchReport.value.run_id, 'bench-history')
  assert.equal(success.workbench.benchmarkBatchReport.value.evaluation_set_id, 'role-baseline-standard-v1@v2')

  const failure = createHarness({ historyShouldFail: true })
  await failure.workbench.refreshAll()
  assert.equal(typeof failure.workbench.loadBenchmarkReportHistory, 'function')
  await failure.workbench.loadBenchmarkReportHistory()
  assert.equal(failure.workbench.benchmarkSuites.value[0].id, 'role-baseline-standard-v1')
  assert.equal(failure.workbench.batchRunRows.value[0].id, 'bench-history')
  assert.equal(failure.workbench.benchmarkDiagnosticAggregateDiagnostics.value.length, 0)
  assert.equal(Boolean(failure.workbench.benchmarkReportHistoryError.value), true)
  assert.equal(failure.workbench.benchmarkReportHistoryLoading.value, false)
  assert.equal(failure.workbench.benchmarkReportHistory.value.length, 0)
}))

test('evaluation workbench refreshAll loads benchmark views without blocking primary data', () => withWindow(async ({ localStorage }) => {
  const createHarness = ({ viewsShouldFail = false, currentViewShouldFail = false } = {}) => {
    const requests = []
    const suite = {
      id: 'role-baseline-quick-v1',
      version: 1,
      label: 'Role Baseline Quick v1',
      name: 'Role Baseline Quick',
      target_type: 'role_version',
      roles: ['seer'],
      game_count: 3,
      max_days: 5,
      seed_set_id: 'role-baseline-quick-202606',
      evaluation_set_id: 'role-baseline-quick-v1@v1',
      config_hash: 'sha256:view-refresh'
    }
    const viewKey = 'benchmark-comparison-view:role_version:role-baseline-quick-v1:role-baseline-quick-v1@v1:seer'
    const savedView = {
      kind: 'benchmark_saved_view',
      schema_version: 1,
      view_key: `${viewKey}:release`,
      name: '发布复核视图',
      scope: 'role_version',
      benchmark_id: suite.id,
      evaluation_set_id: suite.evaluation_set_id,
      target_role: 'seer',
      view_config: { rank_filter: 'unrankable', columns: ['games'], search: 'gate' }
    }
    const currentView = {
      ...savedView,
      view_key: viewKey,
      name: '当前榜单视图',
      view_config: {
        rank_filter: 'rankable',
        columns: ['score', 'winRate'],
        search: 'seer_candidate',
        density: 'compact'
      }
    }
    const leaderboardRows = [{
      scope: 'role_version',
      subject_id: 'seer_candidate_v1',
      target_role: 'seer',
      target_version_id: 'seer_candidate_v1',
      target_role_role_weighted_score: 0.72,
      target_side_win_rate: 0.6,
      game_count: 30,
      rankable: true
    }]
    const clone = (value) => JSON.parse(JSON.stringify(value))
    const apiFetch = async (path, options = {}) => {
      const method = options.method || 'GET'
      const body = options.body ? JSON.parse(options.body) : null
      requests.push({ path, method, body })
      if (path === '/benchmarks') return { items: [suite] }
      if (path === '/roles/overview?evaluation_set_id=role-baseline-quick-v1%40v1') {
        return {
          roles: ['seer'],
          versions: { seer: [{ version_id: 'seer_candidate_v1', role: 'seer', source: 'candidate' }] },
          leaderboards: { seer: { entries: clone(leaderboardRows) } }
        }
      }
      if (path === '/benchmark/plan') {
        return {
          benchmark_id: suite.id,
          target_type: 'role_version',
          evaluation_set_id: suite.evaluation_set_id,
          seed_set_id: suite.seed_set_id,
          benchmark_config_hash: suite.config_hash,
          total_games: 3,
          budget: { estimated_units: 9, limit_units: 20, exceeded: false, status: 'ok' }
        }
      }
      if (path.startsWith('/leaderboards/compare?')) {
        return {
          kind: 'benchmark_leaderboard_compare',
          schema_version: 1,
          rows: clone(leaderboardRows),
          summary: { row_count: leaderboardRows.length }
        }
      }
      if (path.startsWith('/benchmark/views?')) {
        if (viewsShouldFail) throw new Error('saved views unavailable')
        return { items: [savedView] }
      }
      if (path === `/benchmark/views/${encodeURIComponent(viewKey)}`) {
        if (currentViewShouldFail) throw new Error('current view unavailable')
        return currentView
      }
      if (path === '/evolution-runs') {
        return {
          runs: [],
          batches: [{
            kind: 'benchmark_batch',
            batch_id: 'bench-view-refresh',
            status: 'completed',
            roles: ['seer'],
            benchmark: {
              id: suite.id,
              version: 1,
              target_type: 'role_version',
              evaluation_set_id: suite.evaluation_set_id
            }
          }]
        }
      }
      if (path.startsWith('/benchmark/reports?')) {
        return {
          kind: 'benchmark_run_reports',
          items: [],
          summary: {},
          pagination: { total: 0, offset: 0, limit: 50, returned: 0, has_more: false }
        }
      }
      if (path.startsWith('/benchmark/diagnostics?')) {
        return {
          kind: 'benchmark_diagnostics',
          diagnostics: [],
          affected_runs: [],
          affected_games: [],
          summary: {},
          pagination: { total: 0, offset: 0, limit: 200, returned: 0, has_more: false }
        }
      }
      if (path.startsWith('/benchmark/snapshots?')) {
        return {
          kind: 'benchmark_snapshots',
          schema_version: 1,
          items: [],
          pagination: { total: 0, returned: 0 }
        }
      }
      throw new Error(`unexpected ${method} ${path}`)
    }
    return { workbench: useEvaluationWorkbench({ installLifecycle: false, apiFetch }), requests, viewKey }
  }

  const success = createHarness()
  const refreshed = await success.workbench.refreshAll()
  assert.equal(refreshed, true)
  assert.equal(success.workbench.benchmarkSuites.value[0].id, 'role-baseline-quick-v1')
  assert.equal(success.workbench.roleLeaderboardRows.value[0].version_id, 'seer_candidate_v1')
  assert.equal(success.workbench.batchRunRows.value[0].id, 'bench-view-refresh')
  assert.equal(success.workbench.benchmarkSavedViews.value[0].view_key, `${success.viewKey}:release`)
  assert.equal(success.workbench.selectedBenchmarkViewKey.value, success.viewKey)
  assert.equal(success.workbench.benchmarkViewPreferences.value.name, '当前榜单视图')
  assert.equal(success.workbench.activeBenchmarkViewConfig.value.rank_filter, 'rankable')
  assert.deepEqual(success.workbench.activeBenchmarkViewConfig.value.columns, ['score', 'winRate'])
  assert.equal(success.workbench.activeBenchmarkViewConfig.value.search, 'seer_candidate')
  assert.equal(success.workbench.activeBenchmarkViewConfig.value.density, 'compact')
  assert.equal(success.workbench.benchmarkViewDirty.value, false)
  assert.equal(success.requests.some((item) => item.path.startsWith('/benchmark/views?')), true)
  assert.equal(success.requests.some((item) => item.path === `/benchmark/views/${encodeURIComponent(success.viewKey)}`), true)

  localStorage.clear()
  const failure = createHarness({ viewsShouldFail: true, currentViewShouldFail: true })
  const refreshedWithViewFailure = await failure.workbench.refreshAll()
  assert.equal(refreshedWithViewFailure, true)
  assert.equal(failure.workbench.error.value, '')
  assert.equal(failure.workbench.benchmarkSuites.value[0].id, 'role-baseline-quick-v1')
  assert.equal(failure.workbench.roleLeaderboardRows.value[0].version_id, 'seer_candidate_v1')
  assert.equal(failure.workbench.batchRunRows.value[0].id, 'bench-view-refresh')
  assert.equal(failure.workbench.benchmarkPlan.value.total_games, 3)
  assert.equal(failure.workbench.benchmarkSavedViews.value.length, 0)
  assert.equal(Boolean(failure.workbench.benchmarkSavedViewsError.value), true)
  assert.equal(failure.workbench.selectedBenchmarkViewKey.value, failure.viewKey)
  assert.equal(failure.workbench.benchmarkViewPreferences.value.name, '默认视图')
  assert.equal(failure.workbench.activeBenchmarkViewConfig.value.rank_filter, 'all')
  assert.deepEqual(failure.workbench.activeBenchmarkViewConfig.value.columns, [])
}))

test('evaluation workbench creates benchmark snapshots from frozen leaderboard rows', () => withWindow(async () => {
  const requests = []
  const suite = {
    id: 'role-baseline-quick-v1',
    version: 1,
    label: 'Role Baseline Quick v1',
    name: 'Role Baseline Quick',
    target_type: 'role_version',
    roles: ['seer'],
    game_count: 3,
    max_days: 5,
    seed_set_id: 'role-baseline-quick-202606',
    evaluation_set_id: 'role-baseline-quick-v1@v1',
    config_hash: 'sha256:snapshot-suite'
  }
  let liveLeaderboardRows = [{
    scope: 'role_version',
    subject_id: 'seer_candidate_v1',
    target_role: 'seer',
    target_version_id: 'seer_candidate_v1',
    target_role_role_weighted_score: 0.72,
    target_side_win_rate: 0.6,
    game_count: 30,
    rankable: true
  }]
  const snapshots = []
  const snapshotDetails = new Map()
  const clone = (value) => JSON.parse(JSON.stringify(value))
  const snapshotSummary = (snapshot) => {
    const { rows, ...summary } = snapshot
    return summary
  }
  const versionRows = () => liveLeaderboardRows.map((row) => ({
    version_id: row.target_version_id,
    source: 'candidate',
    is_baseline: false
  }))

  const apiFetch = async (path, options = {}) => {
    const method = options.method || 'GET'
    const body = options.body ? JSON.parse(options.body) : null
    requests.push({ path, method, body })
    if (path === '/benchmarks') return { items: [suite] }
    if (path === '/roles') return { roles: ['seer'] }
    if (path === '/roles/overview?evaluation_set_id=role-baseline-quick-v1%40v1') {
      return {
        roles: ['seer'],
        versions: { seer: versionRows() },
        leaderboards: { seer: { entries: clone(liveLeaderboardRows) } }
      }
    }
    if (path === '/roles/seer/leaderboard?evaluation_set_id=role-baseline-quick-v1%40v1') {
      return { entries: clone(liveLeaderboardRows) }
    }
    if (path === '/roles/seer/versions') return { versions: versionRows() }
    if (path === '/evolution-runs') return { runs: [], batches: [] }
    if (path === '/benchmark/plan') {
      return {
        benchmark_id: suite.id,
        target_type: 'role_version',
        evaluation_set_id: suite.evaluation_set_id,
        seed_set_id: suite.seed_set_id,
        benchmark_config_hash: suite.config_hash,
        total_games: 3,
        budget: { estimated_units: 9, limit_units: 20, exceeded: false, status: 'ok' },
        rankable: { eligible: true, gate_count: 3 }
      }
    }
    if (path.startsWith('/benchmark/snapshots?')) {
      return { items: snapshots.map(snapshotSummary) }
    }
    if (path === '/benchmark/snapshots' && method === 'POST') {
      const frozenRows = clone(liveLeaderboardRows)
      const rankableCount = frozenRows.filter((row) => row.rankable !== false).length
      const linkedRunIds = ['bench-snapshot-audit-run']
      const linkedReportIds = ['report-bench-snapshot-audit-run']
      const snapshot = {
        kind: 'benchmark_leaderboard_snapshot',
        snapshot_id: 'snap-release-1',
        title: body.title,
        release_notes: body.release_notes,
        scope: body.scope,
        benchmark_id: body.benchmark_id,
        benchmark_version: body.benchmark_version,
        evaluation_set_id: body.evaluation_set_id,
        seed_set_id: body.seed_set_id,
        benchmark_config_hash: body.benchmark_config_hash,
        target_role: body.target_role,
        source_filter: body.source_filter,
        view_config: body.view_config,
        content_hash: 'sha256:frozen-v1',
        row_count: frozenRows.length,
        rankable_count: rankableCount,
        unrankable_count: frozenRows.length - rankableCount,
        linked_run_ids: linkedRunIds,
        linked_report_ids: linkedReportIds,
        source_run_count: linkedRunIds.length,
        source_report_count: linkedReportIds.length,
        summary: {
          row_count: frozenRows.length,
          rankable_count: rankableCount,
          unrankable_count: frozenRows.length - rankableCount,
          source_run_count: linkedRunIds.length,
          source_report_count: linkedReportIds.length
        },
        rows: frozenRows,
        created_at: '2026-06-09T10:00:00Z'
      }
      snapshots.unshift(snapshotSummary(snapshot))
      snapshotDetails.set(snapshot.snapshot_id, snapshot)
      return clone(snapshot)
    }
    if (path === '/benchmark/snapshots/snap-release-1') {
      return clone(snapshotDetails.get('snap-release-1'))
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()
  await workbench.loadBenchmarkSnapshots()

  const listRequest = requests.find((item) => item.path.startsWith('/benchmark/snapshots?'))
  assert.equal(Boolean(listRequest), true)
  const listQuery = new URLSearchParams(listRequest.path.split('?')[1])
  assert.equal(listQuery.get('scope'), 'role_version')
  assert.equal(listQuery.get('benchmark_id'), 'role-baseline-quick-v1')
  assert.equal(listQuery.get('evaluation_set_id'), 'role-baseline-quick-v1@v1')
  assert.equal(listQuery.get('target_role'), 'seer')

  workbench.setBenchmarkViewPreference({
    name: '发布复核视图',
    rank_filter: 'rankable',
    columns: ['score', 'winRate', 'rankable'],
    sort: 'score_desc',
    search: 'seer_candidate',
    density: 'compact'
  })

  await workbench.createBenchmarkSnapshot({
    title: 'Release gate 2026-06-09',
    release_notes: 'candidate v1 accepted'
  })

  const createRequest = requests.find((item) => item.path === '/benchmark/snapshots' && item.method === 'POST')
  assert.equal(Boolean(createRequest), true)
  assert.equal(createRequest.body.title, 'Release gate 2026-06-09')
  assert.equal(createRequest.body.release_notes, 'candidate v1 accepted')
  assert.equal(createRequest.body.scope, 'role_version')
  assert.equal(createRequest.body.benchmark_id, 'role-baseline-quick-v1')
  assert.equal(createRequest.body.benchmark_version, 1)
  assert.equal(createRequest.body.evaluation_set_id, 'role-baseline-quick-v1@v1')
  assert.equal(createRequest.body.seed_set_id, 'role-baseline-quick-202606')
  assert.equal(createRequest.body.benchmark_config_hash, 'sha256:snapshot-suite')
  assert.equal(createRequest.body.target_role, 'seer')
  assert.equal(createRequest.body.view_config.view_key, workbench.currentBenchmarkViewKey.value)
  assert.equal(createRequest.body.view_config.view_name, '发布复核视图')
  assert.equal(createRequest.body.view_config.rank_filter, 'rankable')
  assert.equal(createRequest.body.view_config.search, 'seer_candidate')
  assert.equal(createRequest.body.view_config.density, 'compact')
  assert.deepEqual(createRequest.body.view_config.columns, ['score', 'winRate', 'rankable'])
  assert.deepEqual(createRequest.body.source_filter, {
    rankable: 'all',
    target_role: 'seer',
    evaluation_set_id: 'role-baseline-quick-v1@v1'
  })
  assert.deepEqual(workbench.benchmarkSnapshots.value[0].linked_run_ids, ['bench-snapshot-audit-run'])
  assert.deepEqual(workbench.benchmarkSnapshots.value[0].linked_report_ids, ['report-bench-snapshot-audit-run'])
  assert.equal(workbench.benchmarkSnapshots.value[0].source_run_count, 1)
  assert.equal(workbench.benchmarkSnapshots.value[0].source_report_count, 1)
  assert.equal(workbench.benchmarkSnapshots.value[0].rankable_count, 1)
  assert.equal(workbench.benchmarkSnapshots.value[0].unrankable_count, 0)
  assert.equal(workbench.benchmarkSnapshots.value[0].row_count, 1)
  assert.equal(workbench.benchmarkSnapshots.value[0].content_hash, 'sha256:frozen-v1')

  liveLeaderboardRows = [{
    scope: 'role_version',
    subject_id: 'seer_candidate_v2',
    target_role: 'seer',
    target_version_id: 'seer_candidate_v2',
    target_role_role_weighted_score: 0.81,
    target_side_win_rate: 0.67,
    game_count: 30,
    rankable: true
  }]
  await workbench.refreshAll({ silent: true })
  assert.equal(workbench.roleLeaderboardRows.value[0].version_id, 'seer_candidate_v2')

  await workbench.selectBenchmarkSnapshot('snap-release-1')
  assert.equal(workbench.selectedBenchmarkSnapshotId.value, 'snap-release-1')
  assert.equal(workbench.benchmarkSnapshotDetail.value.snapshot_id, 'snap-release-1')
  assert.equal(workbench.benchmarkSnapshotDetail.value.rows[0].target_version_id, 'seer_candidate_v1')
  assert.equal(workbench.benchmarkSnapshotDetail.value.rows[0].target_role_role_weighted_score, 0.72)
  assert.deepEqual(workbench.benchmarkSnapshotDetail.value.linked_run_ids, ['bench-snapshot-audit-run'])
  assert.deepEqual(workbench.benchmarkSnapshotDetail.value.linked_report_ids, ['report-bench-snapshot-audit-run'])
  assert.equal(workbench.benchmarkSnapshotDetail.value.source_run_count, 1)
  assert.equal(workbench.benchmarkSnapshotDetail.value.source_report_count, 1)
  assert.equal(workbench.benchmarkSnapshotDetail.value.rankable_count, 1)
  assert.equal(workbench.benchmarkSnapshotDetail.value.unrankable_count, 0)
  assert.equal(workbench.benchmarkSnapshotDetail.value.row_count, 1)
  assert.equal(workbench.benchmarkSnapshotDetail.value.content_hash, 'sha256:frozen-v1')
  assert.equal(workbench.roleLeaderboardRows.value[0].version_id, 'seer_candidate_v2')
}))

test('evaluation workbench loads canonical snapshot compare and keeps detail on compare failure', () => withWindow(async () => {
  const createHarness = ({ compareShouldFail = false } = {}) => {
    const requests = []
    const clone = (value) => JSON.parse(JSON.stringify(value))
    const suite = {
      id: 'role-baseline-quick-v1',
      version: 1,
      label: 'Role Baseline Quick v1',
      name: 'Role Baseline Quick',
      target_type: 'role_version',
      roles: ['seer'],
      game_count: 3,
      max_days: 5,
      seed_set_id: 'role-baseline-quick-202606',
      evaluation_set_id: 'role-baseline-quick-v1@v1',
      config_hash: 'sha256:snapshot-current'
    }
    const currentRows = [
      {
        scope: 'role_version',
        subject_id: 'seer_candidate_v1',
        hash: 'seer_candidate_v1',
        target_role: 'seer',
        target_version_id: 'seer_candidate_v1',
        evaluation_set_id: 'role-baseline-quick-v1@v1',
        seed_set_id: 'role-baseline-quick-202606',
        target_role_role_weighted_score: 0.74,
        target_side_win_rate: 0.62,
        game_count: 34,
        rankable: true
      },
      {
        scope: 'role_version',
        subject_id: 'seer_candidate_v2',
        hash: 'seer_candidate_v2',
        target_role: 'seer',
        target_version_id: 'seer_candidate_v2',
        evaluation_set_id: 'role-baseline-quick-v1@v1',
        seed_set_id: 'role-baseline-quick-202606',
        target_role_role_weighted_score: 0.68,
        target_side_win_rate: 0.58,
        game_count: 30,
        rankable: true
      }
    ]
    const frozenRows = [
      {
        scope: 'role_version',
        subject_id: 'seer_candidate_v1',
        hash: 'seer_candidate_v1',
        target_role: 'seer',
        target_version_id: 'seer_candidate_v1',
        evaluation_set_id: 'role-baseline-quick-v1@v1',
        seed_set_id: 'role-baseline-quick-202606',
        target_role_role_weighted_score: 0.7,
        target_side_win_rate: 0.59,
        game_count: 30,
        rankable: true
      },
      {
        scope: 'role_version',
        subject_id: 'seer_candidate_removed',
        hash: 'seer_candidate_removed',
        target_role: 'seer',
        target_version_id: 'seer_candidate_removed',
        evaluation_set_id: 'role-baseline-quick-v1@v1',
        seed_set_id: 'role-baseline-quick-202606',
        target_role_role_weighted_score: 0.57,
        target_side_win_rate: 0.5,
        game_count: 24,
        rankable: false,
        rankable_reason: 'leaderboard gate failed: low sample'
      }
    ]
    const versions = [
      { version_id: 'seer_candidate_v1', role: 'seer', source: 'candidate' },
      { version_id: 'seer_candidate_v2', role: 'seer', source: 'candidate' },
      { version_id: 'seer_candidate_removed', role: 'seer', source: 'candidate' }
    ]
    const snapshot = {
      kind: 'benchmark_leaderboard_snapshot',
      schema_version: 1,
      snapshot_id: 'snap-release',
      title: 'Release gate 2026-06-09',
      release_notes: 'frozen before candidate v2',
      scope: 'role_version',
      benchmark_id: 'role-baseline-quick-v1',
      benchmark_version: 1,
      evaluation_set_id: 'role-baseline-quick-v1@v1',
      seed_set_id: 'role-baseline-quick-202606',
      benchmark_config_hash: 'sha256:snapshot-frozen',
      target_role: 'seer',
      source_filter: {
        rankable: 'all',
        target_role: 'seer',
        evaluation_set_id: 'role-baseline-quick-v1@v1'
      },
      view_config: {},
      content_hash: 'sha256:frozen-release',
      row_count: frozenRows.length,
      summary: { row_count: frozenRows.length, rankable_count: 1, unrankable_count: 1 },
      rows: frozenRows,
      created_at: '2026-06-09T10:00:00Z'
    }
    const snapshotSummary = (() => {
      const { rows, ...summary } = snapshot
      return summary
    })()
    const canonicalCompare = {
      kind: 'benchmark_snapshot_compare',
      schema_version: 1,
      snapshot_id: 'snap-release',
      scope: 'role_version',
      benchmark_id: 'role-baseline-quick-v1',
      evaluation_set_id: 'role-baseline-quick-v1@v1',
      target_role: 'seer',
      snapshot: clone(frozenRows),
      current: clone(currentRows),
      summary: {
        snapshot_row_count: 2,
        current_row_count: 2,
        changed_count: 1,
        added_count: 1,
        removed_count: 1,
        boundary_warning_count: 1
      },
      changed: [{
        key: 'seer_candidate_v1',
        current: clone(currentRows[0]),
        snapshot: clone(frozenRows[0]),
        scoreDelta: 0.04,
        winRateDelta: 0.03,
        gamesDelta: 4,
        rankableChanged: false
      }],
      added: [clone(currentRows[1])],
      removed: [clone(frozenRows[1])],
      boundary_warnings: [{
        kind: 'benchmark_config_hash_mismatch',
        level: 'info',
        snapshot_value: 'sha256:snapshot-frozen',
        current_value: 'sha256:snapshot-current',
        message: 'Current benchmark config hash differs from the frozen snapshot.'
      }]
    }
    const apiFetch = async (path, options = {}) => {
      const method = options.method || 'GET'
      requests.push({ path, method })
      if (path === '/benchmarks') return { items: [suite] }
      if (path === '/roles') return { roles: ['seer'] }
      if (path === '/roles/overview?evaluation_set_id=role-baseline-quick-v1%40v1') {
        return {
          roles: ['seer'],
          versions: { seer: clone(versions) },
          leaderboards: { seer: { entries: clone(currentRows) } }
        }
      }
      if (path === '/roles/seer/leaderboard?evaluation_set_id=role-baseline-quick-v1%40v1') {
        return { entries: clone(currentRows) }
      }
      if (path === '/roles/seer/versions') return { versions: clone(versions) }
      if (path === '/evolution-runs') return { runs: [], batches: [] }
      if (path.startsWith('/leaderboards/compare?')) {
        return {
          kind: 'benchmark_leaderboard_compare',
          schema_version: 1,
          rows: clone(currentRows),
          summary: { row_count: currentRows.length }
        }
      }
      if (path === '/benchmark/plan') {
        return {
          benchmark_id: suite.id,
          target_type: 'role_version',
          evaluation_set_id: suite.evaluation_set_id,
          seed_set_id: suite.seed_set_id,
          benchmark_config_hash: suite.config_hash,
          total_games: 3,
          budget: { estimated_units: 9, limit_units: 20, exceeded: false, status: 'ok' },
          rankable: { eligible: true, gate_count: 3 }
        }
      }
      if (path.startsWith('/benchmark/snapshots?')) return { items: [clone(snapshotSummary)] }
      if (path === '/benchmark/snapshots/snap-release') return clone(snapshot)
      if (path.startsWith('/benchmark/snapshots/snap-release/compare?')) {
        if (compareShouldFail) throw new Error('snapshot compare unavailable')
        return clone(canonicalCompare)
      }
      if (path.startsWith('/benchmark/diagnostics?')) {
        return {
          diagnostics: [],
          affected_runs: [],
          affected_games: [],
          summary: {},
          pagination: { total: 0, offset: 0, limit: 200, returned: 0, has_more: false }
        }
      }
      throw new Error(`unexpected ${method} ${path}`)
    }
    return { workbench: useEvaluationWorkbench({ installLifecycle: false, apiFetch }), requests }
  }

  const success = createHarness()
  await success.workbench.refreshAll()
  await success.workbench.selectBenchmarkSnapshot('snap-release')

  const compareRequest = success.requests.find((item) =>
    item.path.startsWith('/benchmark/snapshots/snap-release/compare?')
  )
  assert.equal(Boolean(compareRequest), true)
  const compareQuery = new URLSearchParams(compareRequest.path.split('?')[1])
  assert.equal(compareQuery.get('limit'), '100')
  assert.equal(success.workbench.benchmarkSnapshotServerCompare.value.kind, 'benchmark_snapshot_compare')
  assert.equal(success.workbench.benchmarkSnapshotServerCompare.value.changed[0].key, 'seer_candidate_v1')
  assert.equal(success.workbench.benchmarkSnapshotServerCompare.value.added[0].target_version_id, 'seer_candidate_v2')
  assert.equal(success.workbench.benchmarkSnapshotServerCompare.value.removed[0].target_version_id, 'seer_candidate_removed')
  assert.equal(success.workbench.benchmarkSnapshotServerCompare.value.boundary_warnings[0].kind, 'benchmark_config_hash_mismatch')
  assert.equal(success.workbench.benchmarkSnapshotCompareError.value, '')
  assert.equal(success.workbench.benchmarkSnapshotCompareLoading.value, false)

  await success.workbench.loadBenchmarkSnapshotCompare('snap-release', {
    againstSnapshotId: 'snap-against',
    limit: 7
  })
  const pairCompareRequest = success.requests
    .filter((item) => item.path.startsWith('/benchmark/snapshots/snap-release/compare?'))
    .at(-1)
  const pairCompareQuery = new URLSearchParams(pairCompareRequest.path.split('?')[1])
  assert.equal(pairCompareQuery.get('against_snapshot_id'), 'snap-against')
  assert.equal(pairCompareQuery.get('limit'), '7')

  const failure = createHarness({ compareShouldFail: true })
  await failure.workbench.refreshAll()
  const loaded = await failure.workbench.selectBenchmarkSnapshot('snap-release')
  assert.equal(loaded, true)
  assert.equal(failure.workbench.benchmarkSnapshotDetail.value.snapshot_id, 'snap-release')
  assert.equal(failure.workbench.benchmarkSnapshotDetail.value.rows[0].target_version_id, 'seer_candidate_v1')
  assert.equal(Boolean(failure.workbench.benchmarkSnapshotCompareError.value), true)
  assert.equal(failure.workbench.benchmarkSnapshotCompareLoading.value, false)
  assert.notEqual(failure.workbench.benchmarkSnapshotServerCompare.value?.kind, 'benchmark_snapshot_compare')
  assert.equal((failure.workbench.benchmarkSnapshotCompare.value.changed || []).length, 1)
}))

test('evaluation workbench persists benchmark comparison saved views through API', () => withWindow(async () => {
  const requests = []
  const viewKey = 'benchmark-comparison-view:role_version:role-baseline-quick-v1:role-baseline-quick-v1@v1:seer'
  const savedView = {
    kind: 'benchmark_saved_view',
    schema_version: 1,
    view_key: viewKey,
    name: 'Release reviewer',
    scope: 'role_version',
    benchmark_id: 'role-baseline-quick-v1',
    evaluation_set_id: 'role-baseline-quick-v1@v1',
    target_role: 'seer',
    view_config: { rank_filter: 'rankable', columns: ['score', 'winRate'] },
    created_at: '2026-06-09T10:00:00Z',
    updated_at: '2026-06-09T10:00:00Z'
  }
  const apiFetch = async (path, options = {}) => {
    const method = options.method || 'GET'
    const body = options.body ? JSON.parse(options.body) : null
    requests.push({ path, method, body })
    if (path.startsWith('/benchmark/views?') && method === 'GET') return { items: [savedView] }
    if (path === '/benchmark/views' && method === 'POST') return { ...savedView, ...body }
    if (path === `/benchmark/views/${encodeURIComponent(viewKey)}` && method === 'GET') return savedView
    if (path === `/benchmark/views/${encodeURIComponent(viewKey)}` && method === 'DELETE') {
      return { kind: 'benchmark_saved_view_deleted', view_key: viewKey, deleted: true }
    }
    throw new Error(`unexpected ${method} ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  const listed = await workbench.loadBenchmarkViews()
  assert.equal(listed, true)
  assert.equal(workbench.benchmarkSavedViews.value[0].view_key, viewKey)

  workbench.setBenchmarkViewPreference({
    name: '本地复核',
    rank_filter: 'unrankable',
    columns: ['games']
  })
  assert.equal(workbench.benchmarkViewDirty.value, true)
  assert.equal(workbench.activeBenchmarkViewConfig.value.rank_filter, 'unrankable')
  assert.deepEqual(workbench.activeBenchmarkViewConfig.value.columns, ['games'])

  const currentSaved = await workbench.saveCurrentBenchmarkView({ view_key: viewKey })
  assert.equal(currentSaved.view_key, viewKey)
  assert.equal(workbench.benchmarkViewDirty.value, false)

  const created = await workbench.saveBenchmarkView({
    view_key: viewKey,
    name: 'Release reviewer',
    scope: 'role_version',
    benchmark_id: 'role-baseline-quick-v1',
    evaluation_set_id: 'role-baseline-quick-v1@v1',
    target_role: 'seer',
    view_config: { rank_filter: 'rankable', columns: ['score', 'winRate'] }
  })
  const loaded = await workbench.loadBenchmarkView(viewKey)
  const deleted = await workbench.deleteBenchmarkView(viewKey)

  assert.equal(created.view_key, viewKey)
  assert.equal(loaded.view_config.rank_filter, 'rankable')
  assert.equal(deleted.deleted, true)
  assert.equal(requests.some((item) => item.method === 'GET' && item.path.startsWith('/benchmark/views?')), true)
  const currentSaveRequest = requests.find((item) => item.method === 'POST' && item.body?.name === '本地复核')
  assert.deepEqual(currentSaveRequest.body.view_config.columns, ['games'])
  assert.equal(currentSaveRequest.body.view_config.rank_filter, 'unrankable')
  const directSaveRequest = requests.find((item) => item.method === 'POST' && item.body?.name === 'Release reviewer')
  assert.deepEqual(directSaveRequest.body.view_config.columns, ['score', 'winRate'])
  assert.equal(requests.some((item) => item.method === 'GET' && item.path === `/benchmark/views/${encodeURIComponent(viewKey)}`), true)
  assert.equal(requests.some((item) => item.method === 'DELETE' && item.path === `/benchmark/views/${encodeURIComponent(viewKey)}`), true)
}))

test('evaluation workbench shows success notice after starting a benchmark', () => withWindow(async () => {
  const requests = []
  let batches = []
  const apiFetch = async (path, options = {}) => {
    requests.push({ path, body: options.body ? JSON.parse(options.body) : null })
    if (path === '/roles') return { roles: ['seer'] }
    if (path === '/roles/seer/leaderboard') return { entries: [] }
    if (path === '/roles/seer/versions') return { versions: [] }
    if (path === '/evolution-runs') return { runs: [], batches }
    if (path === '/benchmark') {
      batches = [{
        kind: 'benchmark_batch',
        batch_id: 'bench-new',
        roles: ['seer'],
        status: 'queued',
        started_at: '2026-06-07T10:00:00'
      }]
      return { batch_id: 'bench-new' }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()
  await workbench.startEvaluation()

  assert.deepEqual(requests.find((item) => item.path === '/benchmark')?.body, {
    roles: ['seer'],
    battle_games: 10,
    max_days: 5
  })
  assert.deepEqual(workbench.notice.value, { type: 'success', message: '评测已启动。' })
  assert.equal(workbench.error.value, '')
  assert.equal(workbench.batchRunRows.value[0].id, 'bench-new')
}))

test('evaluation workbench warns when a started benchmark cannot refresh the list', () => withWindow(async () => {
  let benchmarkStarted = false
  const apiFetch = async (path) => {
    if (path === '/roles') return { roles: ['seer'] }
    if (path === '/roles/seer/leaderboard') return { entries: [] }
    if (path === '/roles/seer/versions') return { versions: [] }
    if (path === '/evolution-runs') {
      if (benchmarkStarted) throw new Error('benchmark failed')
      return { runs: [], batches: [] }
    }
    if (path === '/benchmark') {
      benchmarkStarted = true
      return { batch_id: 'bench-refresh-failed' }
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()
  await workbench.startEvaluation()

  assert.deepEqual(workbench.notice.value, {
    type: 'warning',
    message: '评测已启动，但列表刷新失败，请手动刷新。'
  })
  assert.equal(workbench.error.value, '评测执行失败，请查看评测记录。')
}))

test('evaluation workbench maps missing benchmark batch stop failures to warning notice', () => withWindow(async () => {
  let batches = [{
    kind: 'benchmark_batch',
    batch_id: 'bench-missing',
    roles: ['seer'],
    status: 'running',
    started_at: '2026-06-07T10:00:00'
  }]
  const apiFetch = async (path) => {
    if (path === '/roles') return { roles: ['seer'] }
    if (path === '/roles/seer/leaderboard') return { entries: [] }
    if (path === '/roles/seer/versions') return { versions: [] }
    if (path === '/evolution-runs') return { runs: [], batches }
    if (path === '/benchmark/batch/bench-missing/stop') {
      batches = []
      throw new Error('batch not found')
    }
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll()
  await workbench.stopBatch('bench-missing')

  assert.deepEqual(workbench.notice.value, {
    type: 'warning',
    message: '评测批次不存在，已刷新列表。'
  })
  assert.equal(workbench.error.value, '')
  assert.deepEqual(workbench.batchRunRows.value, [])
}))

test('evaluation workbench surfaces manual refresh failures as local notice', () => withWindow(async () => {
  const apiFetch = async (path) => {
    if (path === '/roles') return { roles: ['seer'] }
    if (path === '/roles/seer/leaderboard') return { entries: [] }
    if (path === '/roles/seer/versions') return { versions: [] }
    if (path === '/evolution-runs') throw new Error('invalid config')
    throw new Error(`unexpected ${path}`)
  }

  const workbench = useEvaluationWorkbench({ installLifecycle: false, apiFetch })
  await workbench.refreshAll({ notify: true })

  assert.deepEqual(workbench.notice.value, {
    type: 'warning',
    message: '评测配置无效，请检查局数和天数。'
  })
  assert.equal(workbench.error.value, '评测配置无效，请检查局数和天数。')
}))

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
