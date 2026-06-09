import assert from 'node:assert/strict'
import { afterEach, test, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'
import { useGameStore } from '../../../src/stores/game'
import { useHistoryStore } from '../../../src/stores/history'
import { useReplayStore } from '../../../src/stores/replay'
import {
  createStoreRuntimeHydration,
  hydrateStoresFromRuntime,
  runtimeHydrationKeys
} from '../../../src/stores/runtimeHydration'
import { useSessionStore } from '../../../src/stores/session'
import { useUiStore } from '../../../src/stores/ui'
import type { Game } from '../../../src/types/game'
import type { HistoryGame, ReplaySnapshot } from '../../../src/types/history'

afterEach(() => {
  vi.restoreAllMocks()
})

function gameFixture(id: string, overrides: Partial<Game> = {}): Game {
  return {
    game_id: id,
    mode: 'watch',
    status: 'running',
    phase: 'night',
    player_count: 2,
    players: [],
    logs: [],
    decisions: [],
    waiting_for: 'none',
    pending_action: null,
    skill_state: {},
    ...overrides
  }
}

function historyGameFixture(id: string, overrides: Partial<HistoryGame> = {}): HistoryGame {
  return {
    ...gameFixture(id),
    event_count: 0,
    decision_count: 0,
    phases: [],
    history_pages: [],
    ...overrides
  }
}

function replaySnapshotFixture(id: string, overrides: Partial<ReplaySnapshot> = {}): ReplaySnapshot {
  return {
    ...gameFixture(id),
    cursor: 0,
    limit: 100,
    next_cursor: null,
    has_more: false,
    ...overrides
  }
}

test('session store hydrates runtime state and updates view/session actions', () => {
  setActivePinia(createPinia())
  const store = useSessionStore()

  store.hydrateFromRuntime({
    currentView: 'match',
    backendMode: 'api',
    activeSession: { gameId: 'game-1', mode: 'watch', running: true, sseConnected: true },
    returnToMatchAvailable: true
  })

  assert.equal(store.currentView, 'match')
  assert.equal(store.backendMode, 'api')
  assert.equal(store.activeSession.gameId, 'game-1')
  assert.equal(store.activeSession.running, true)
  assert.equal(store.returnToMatchAvailable, true)
  assert.equal(store.inMatch, true)
  assert.equal(store.inLobby, false)

  store.setView('logs')
  store.setActiveSession({ gameId: 'game-2', mode: 'play', running: false, sseConnected: false })

  assert.equal(store.currentView, 'logs')
  assert.equal(store.inLogs, true)
  assert.equal(store.activeSession.gameId, 'game-2')
  assert.equal(store.activeSession.mode, 'play')

  store.hydrateFromRuntime({ currentView: 'unknown-view' })

  assert.equal(store.currentView, 'logs')
})

test('game store hydrates snapshots and clears live watch state', () => {
  setActivePinia(createPinia())
  const store = useGameStore()
  const liveGame = gameFixture('game-1', { mode: 'watch', phase: 'night' })

  store.hydrateFromRuntime({
    game: liveGame,
    loading: true,
    error: 'failed to load',
    watchRunning: true
  })

  assert.equal(store.liveGame?.game_id, 'game-1')
  assert.equal(store.loading, true)
  assert.equal(store.error, 'failed to load')
  assert.equal(store.watchRunning, true)
  assert.equal(store.isNight, true)
  assert.equal(store.isWatch, true)

  store.setGame(gameFixture('game-2', { mode: 'play', phase: 'speech' }))

  assert.equal(store.liveGame?.game_id, 'game-2')
  assert.equal(store.isNight, false)
  assert.equal(store.isWatch, false)

  store.clearGame()

  assert.equal(store.liveGame, null)
  assert.equal(store.watchRunning, false)
})

test('history store hydrates selection and derives selection state', () => {
  setActivePinia(createPinia())
  const store = useHistoryStore()
  const selectedGame = historyGameFixture('history-1')

  store.hydrateFromRuntime({
    gameHistory: [selectedGame],
    selectedHistoryGameId: 'history-1',
    selectedHistoryGame: selectedGame,
    historyWorkspaceTab: 'review',
    historyLoading: true,
    historyNotice: { message: 'history is stale' }
  })

  assert.equal(store.games.length, 1)
  assert.equal(store.games[0].game_id, 'history-1')
  assert.equal(store.selectedHistoryGameId, 'history-1')
  assert.equal(store.selectedHistoryGame?.game_id, 'history-1')
  assert.equal(store.historyWorkspaceTab, 'review')
  assert.equal(store.loading, true)
  assert.equal(store.error, 'history is stale')
  assert.equal(store.hasSelection, true)

  store.selectGame(null)

  assert.equal(store.selectedHistoryGame, null)
  assert.equal(store.selectedHistoryGameId, null)
  assert.equal(store.hasSelection, false)

  store.setGames([historyGameFixture('history-2')])

  assert.equal(store.games.length, 1)
  assert.equal(store.games[0].game_id, 'history-2')
})

test('replay store hydrates replay state and toggles replay actions', () => {
  setActivePinia(createPinia())
  const store = useReplayStore()

  store.hydrateFromRuntime({
    replayGame: replaySnapshotFixture('replay-1', { cursor: 4 }),
    isReplayMode: true,
    replayCursor: 4,
    replayPlaying: true,
    replaySpeed: 2
  })

  assert.equal(store.replayGame?.game_id, 'replay-1')
  assert.equal(store.isReplayMode, true)
  assert.equal(store.replayCursor, 4)
  assert.equal(store.replayPlaying, true)
  assert.equal(store.replaySpeed, 2)
  assert.equal(store.hasReplay, true)

  store.exitReplay()

  assert.equal(store.replayGame, null)
  assert.equal(store.isReplayMode, false)
  assert.equal(store.replayPlaying, false)
  assert.equal(store.hasReplay, false)

  store.enterReplay(replaySnapshotFixture('replay-2', { cursor: 7 }))

  assert.equal(store.replayGame?.game_id, 'replay-2')
  assert.equal(store.isReplayMode, true)
  assert.equal(store.replayCursor, 7)
  assert.equal(store.hasReplay, true)

  store.hydrateFromRuntime({
    replayCursor: 0,
    replaySpeed: 0
  })

  assert.equal(store.replayCursor, 0)
  assert.equal(store.replaySpeed, 0)
})

test('ui store hydrates notices and manages deterministic toast actions', () => {
  setActivePinia(createPinia())
  const store = useUiStore()
  const toastId = '00000000-0000-4000-8000-000000000001' as `${string}-${string}-${string}-${string}-${string}`

  vi.spyOn(Date, 'now').mockReturnValue(1710000000000)
  vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(toastId)

  store.hydrateFromRuntime({ error: 'backend failed' })

  assert.deepEqual(store.notice, { type: 'error', message: 'backend failed' })

  store.hydrateFromRuntime({
    matchNotice: { type: 'success', message: 'match ready' },
    historyNotice: { type: 'warning', message: 'history stale' }
  })

  assert.deepEqual(store.notice, { type: 'success', message: 'match ready' })

  store.setNotice({ type: 'info', message: 'manual notice' })
  const createdToastId = store.pushToast({ type: 'success', message: 'saved', timeoutMs: 5000 })

  assert.equal(createdToastId, toastId)
  assert.deepEqual(store.notice, { type: 'info', message: 'manual notice' })
  assert.deepEqual(store.toasts, [
    {
      type: 'success',
      message: 'saved',
      timeoutMs: 5000,
      id: toastId,
      createdAt: 1710000000000
    }
  ])

  store.removeToast(toastId)

  assert.deepEqual(store.toasts, [])
})

test('runtime hydration helper unwraps runtime refs and applies core store payloads', () => {
  setActivePinia(createPinia())
  const sessionStore = useSessionStore()
  const gameStore = useGameStore()
  const historyStore = useHistoryStore()
  const replayStore = useReplayStore()
  const uiStore = useUiStore()
  const liveGame = gameFixture('runtime-game', { mode: 'play', phase: 'speech' })
  const historyGame = historyGameFixture('runtime-history')
  const replayGame = replaySnapshotFixture('runtime-replay', { cursor: 3 })

  const runtime = {
    currentView: ref('match'),
    backendMode: ref('api'),
    activeSession: ref({ gameId: 'runtime-game', mode: 'play', running: true, sseConnected: false }),
    returnToMatchAvailable: ref(true),
    liveGame: ref(liveGame),
    game: ref(replayGame),
    loading: ref(false),
    error: ref(''),
    watchRunning: ref(false),
    gameHistory: ref([historyGame]),
    selectedHistoryGameId: ref('runtime-history'),
    selectedHistoryGame: ref(historyGame),
    historyWorkspaceTab: ref('archive'),
    historyLoading: ref(true),
    historyNotice: ref({ type: 'warning', message: 'history warning' }),
    replayGame: ref(replayGame),
    isReplayMode: ref(true),
    replayCursor: ref(3),
    replayPlaying: ref(false),
    replaySpeed: ref(1.5),
    matchNotice: ref({ type: 'success', message: 'match hydrated' })
  }

  const payloads = hydrateStoresFromRuntime(runtime, {
    session: sessionStore,
    game: gameStore,
    history: historyStore,
    replay: replayStore,
    ui: uiStore
  })

  assert.deepEqual(runtimeHydrationKeys.session, [
    'currentView',
    'backendMode',
    'activeSession',
    'returnToMatchAvailable'
  ])
  assert.equal(payloads.game.liveGame?.game_id, 'runtime-game')
  assert.equal(payloads.game.game?.game_id, 'runtime-replay')
  assert.equal(sessionStore.currentView, 'match')
  assert.equal(sessionStore.activeSession.gameId, 'runtime-game')
  assert.equal(gameStore.liveGame?.game_id, 'runtime-game')
  assert.equal(historyStore.games[0].game_id, 'runtime-history')
  assert.equal(historyStore.historyWorkspaceTab, 'archive')
  assert.equal(replayStore.replayGame?.game_id, 'runtime-replay')
  assert.equal(replayStore.replaySpeed, 1.5)
  assert.deepEqual(uiStore.notice, { type: 'success', message: 'match hydrated' })
})

test('runtime hydration helper creates typed payloads without mutating stores', () => {
  setActivePinia(createPinia())
  const store = useGameStore()
  const liveGame = gameFixture('payload-game')

  const payloads = createStoreRuntimeHydration({
    currentView: ref('logs'),
    liveGame: ref(liveGame),
    replayCursor: ref(0),
    replaySpeed: ref(0)
  })

  assert.equal(payloads.session.currentView, 'logs')
  assert.equal(payloads.game.liveGame?.game_id, 'payload-game')
  assert.equal(payloads.replay.replayCursor, 0)
  assert.equal(payloads.replay.replaySpeed, 0)
  assert.equal(store.liveGame, null)
})
