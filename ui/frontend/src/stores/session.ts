import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { ActiveGameSession } from '../types/game'
import type { AppView } from '../types/ui'

export const useSessionStore = defineStore('session', () => {
  const currentView = ref<AppView>('lobby')
  const backendMode = ref('mock')
  const activeSession = ref<ActiveGameSession>({ gameId: null, mode: '', running: false, sseConnected: false })
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

  function hydrateFromRuntime(runtime: {
    currentView?: AppView | string
    backendMode?: string
    activeSession?: ActiveGameSession
    returnToMatchAvailable?: boolean
  }): void {
    if (runtime.currentView) currentView.value = runtime.currentView as AppView
    backendMode.value = runtime.backendMode || 'mock'
    activeSession.value = runtime.activeSession || { gameId: null, mode: '', running: false, sseConnected: false }
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
