// @vitest-environment jsdom

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent } from 'vue'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'

import { useSessionStore } from '../../src/stores'

const mockRuntimeState = vi.hoisted(() => {
  const runtimeRef = <T,>(value: T) => ({ __v_isRef: true, value })

  return {
    currentView: runtimeRef('match'),
    backendMode: runtimeRef('mock'),
    activeSession: runtimeRef(null),
    returnToMatchAvailable: runtimeRef(false),
    liveGame: runtimeRef(null),
    game: runtimeRef(null),
    loading: runtimeRef(false),
    error: runtimeRef(''),
    watchRunning: runtimeRef(false),
    roleAssignmentComplete: runtimeRef(false),
    judgeBoardStarted: runtimeRef(false),
    judgeBoardStarting: runtimeRef(false),
    promptText: runtimeRef(''),
    judgeStripMessage: runtimeRef([]),
    playerIdentityList: runtimeRef([]),
    matchRecordLogs: runtimeRef([]),
    livingPlayers: runtimeRef([]),
    speakerCarousel: runtimeRef([]),
    speakerMessage: runtimeRef(''),
    sceneVoteTally: runtimeRef([]),
    sceneEffects: runtimeRef([]),
    skipIntroGameId: runtimeRef(null),
    speechRemaining: runtimeRef(180),
    gameHistory: runtimeRef([]),
    selectedHistoryGameId: runtimeRef(null),
    selectedHistoryGame: runtimeRef(null),
    historyWorkspaceTab: runtimeRef('phase'),
    historyLoading: runtimeRef(false),
    historyPagination: runtimeRef({}),
    historyLoadingMore: runtimeRef(false),
    historySourceFilter: runtimeRef('all'),
    historyCounts: runtimeRef({}),
    historyFacets: runtimeRef({}),
    historyNotice: runtimeRef(null),
    historyHasMore: runtimeRef(false),
    historyCurrentPage: runtimeRef(1),
    historyTotalPages: runtimeRef(1),
    historyPages: runtimeRef([]),
    replayGame: runtimeRef(null),
    isReplayMode: runtimeRef(false),
    replayCursor: runtimeRef(0),
    replayPlaying: runtimeRef(false),
    replaySpeed: runtimeRef(1),
    replayTotal: runtimeRef(0),
    replayEventLabel: runtimeRef(''),
    audioEnabled: runtimeRef(false),
    ttsEnabled: runtimeRef(false),
    ttsAvailable: runtimeRef(true),
    matchNotice: runtimeRef(null),
    setGameStateUtils: vi.fn(),
  }
})

vi.mock('../../src/components/TopNav.vue', () => ({
  __esModule: true,
  default: {
    name: 'TopNav',
    props: ['variant'],
    template: '<nav data-test="top-nav" :data-variant="variant" />',
  },
}))

vi.mock('../../src/pages/LogsPage.vue', () => ({
  __esModule: true,
  default: {
    name: 'LogsPage',
    template: '<section data-test="logs-page" />',
  },
}))

vi.mock('../../src/pages/EvolutionPage.vue', () => ({
  __esModule: true,
  default: {
    name: 'EvolutionPage',
    template: '<section data-test="evolution-page" />',
  },
}))

vi.mock('../../src/pages/BenchmarkPage.vue', () => ({
  __esModule: true,
  default: {
    name: 'BenchmarkPage',
    template: '<section data-test="benchmark-page" />',
  },
}))

vi.mock('../../src/pages/LobbyPage.vue', () => ({
  __esModule: true,
  default: {
    name: 'LobbyPage',
    template: '<section data-test="lobby-page" />',
  },
}))

vi.mock('../../src/pages/MatchPage.vue', () => ({
  __esModule: true,
  default: {
    name: 'MatchPage',
    template: '<section data-test="match-page" />',
  },
}))

vi.mock('../../src/composables/useGameState.ts', () => ({
  useGameState: () => mockRuntimeState,
}))

vi.mock('../../src/composables/useMatchUtils.ts', () => ({
  useMatchUtils: () => ({}),
}))

vi.mock('../../src/composables/useGameActions.ts', () => ({
  useGameActions: () => ({
    setHistoryApi: vi.fn(),
    setSceneApi: vi.fn(),
  }),
}))

vi.mock('../../src/composables/useGameHistory.ts', () => ({
  useGameHistory: () => ({
    setActionApi: vi.fn(),
    setSceneApi: vi.fn(),
  }),
}))

vi.mock('../../src/composables/useGameAudio.ts', () => ({
  useGameAudio: () => ({}),
}))

vi.mock('../../src/composables/appRuntimeProps', () => ({
  useAppRuntimeProps: () => ({
    logsProps: {},
    lobbyProps: {},
    matchProps: {},
  }),
}))

const EmptyRoute = defineComponent({ template: '<div />' })

async function createTestRouter(path: string): Promise<Router> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'lobby', component: EmptyRoute },
      { path: '/match', name: 'match', component: EmptyRoute },
      { path: '/logs', name: 'logs', component: EmptyRoute },
      { path: '/benchmark', name: 'benchmark', component: EmptyRoute },
      { path: '/evolution', name: 'evolution', component: EmptyRoute },
    ],
  })
  await router.push(path)
  await router.isReady()
  return router
}

async function mountAppAt(path: string) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = await createTestRouter(path)
  const App = (await import('../../src/App.vue')).default

  const wrapper = mount(App, {
    global: {
      plugins: [pinia, router],
    },
  })
  await flushPromises()

  return { wrapper, sessionStore: useSessionStore() }
}

describe('App router and Pinia takeover', () => {
  it('renders the router-owned page even when the hydrated Pinia view is stale', async () => {
    mockRuntimeState.currentView.value = 'match'

    const { wrapper, sessionStore } = await mountAppAt('/logs')

    expect(sessionStore.currentView).toBe('match')
    expect(wrapper.find('[data-test="logs-page"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="match-page"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="top-nav"]').attributes('data-variant')).toBe('section')
  })

  it('keeps legacy hash deep links router-owned during the migration window', async () => {
    mockRuntimeState.currentView.value = 'logs'

    const { wrapper, sessionStore } = await mountAppAt('/#evolution?run_id=run-1')

    expect(sessionStore.currentView).toBe('logs')
    expect(wrapper.find('[data-test="evolution-page"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="logs-page"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="top-nav"]').attributes('data-variant')).toBe('section')
  })
})
