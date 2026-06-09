import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { ActiveGameSession } from '../types/game'
import type { AppView } from '../types/ui'

export interface SessionRuntimeHydration {
  currentView?: AppView | string | null
  backendMode?: string | null
  activeSession?: ActiveGameSession | null
  returnToMatchAvailable?: boolean | null
}

export function defaultActiveSession(): ActiveGameSession {
  return { gameId: null, mode: '', running: false, sseConnected: false }
}

const appViews = new Set<AppView>(['lobby', 'match', 'logs', 'benchmark', 'evolution'])

function asAppView(view: AppView | string | null | undefined): AppView | null {
  return typeof view === 'string' && appViews.has(view as AppView) ? (view as AppView) : null
}

export const useSessionStore = defineStore('session', () => {
  const currentView = ref<AppView>('lobby')
  const backendMode = ref('mock')
  const activeSession = ref<ActiveGameSession>(defaultActiveSession())
  const returnToMatchAvailable = ref(false)

  const inLobby = computed(() => currentView.value === 'lobby')
  const inMatch = computed(() => currentView.value === 'match')
  const inLogs = computed(() => currentView.value === 'logs')
  const inBenchmark = computed(() => currentView.value === 'benchmark')
  const inEvolution = computed(() => currentView.value === 'evolution')

  function setView(view: AppView): void {
    currentView.value = view
  }

  function setActiveSession(session: ActiveGameSession): void {
    activeSession.value = session
  }

  function hydrateFromRuntime(runtime: SessionRuntimeHydration): void {
    const nextView = asAppView(runtime.currentView)
    if (nextView) currentView.value = nextView
    backendMode.value = runtime.backendMode || 'mock'
    activeSession.value = runtime.activeSession ?? defaultActiveSession()
    returnToMatchAvailable.value = Boolean(runtime.returnToMatchAvailable)
  }

  return {
    currentView,
    backendMode,
    activeSession,
    returnToMatchAvailable,
    inLobby,
    inMatch,
    inLogs,
    inBenchmark,
    inEvolution,
    setView,
    setActiveSession,
    hydrateFromRuntime
  }
})
