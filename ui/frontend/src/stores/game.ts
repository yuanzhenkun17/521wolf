import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { Game } from '../types/game'

export interface GameRuntimeHydration {
  liveGame?: Game | null
  game?: Game | null
  loading?: boolean | null
  error?: string | null
  watchRunning?: boolean | null
  roleAssignmentComplete?: boolean | null
  judgeBoardStarted?: boolean | null
  judgeBoardStarting?: boolean | null
}

export const useGameStore = defineStore('game', () => {
  const liveGame = ref<Game | null>(null)
  const loading = ref(false)
  const error = ref('')
  const watchRunning = ref(false)
  const roleAssignmentComplete = ref(false)
  const judgeBoardStarted = ref(false)
  const judgeBoardStarting = ref(false)

  const isNight = computed(() => liveGame.value?.phase === 'night')
  const isWatch = computed(() => liveGame.value?.mode === 'watch')

  function setGame(game: Game | null): void {
    liveGame.value = game
  }

  function setLoading(isLoading: boolean): void {
    loading.value = isLoading
  }

  function setError(message: string | null): void {
    error.value = message ?? ''
  }

  function setWatchRunning(running: boolean): void {
    watchRunning.value = running
  }

  function clearGame(): void {
    liveGame.value = null
    watchRunning.value = false
    roleAssignmentComplete.value = false
    judgeBoardStarted.value = false
    judgeBoardStarting.value = false
  }

  function hydrateFromRuntime(runtime: GameRuntimeHydration): void {
    liveGame.value = runtime.liveGame ?? runtime.game ?? null
    loading.value = Boolean(runtime.loading)
    error.value = runtime.error ?? ''
    watchRunning.value = Boolean(runtime.watchRunning)
    roleAssignmentComplete.value = Boolean(runtime.roleAssignmentComplete)
    judgeBoardStarted.value = Boolean(runtime.judgeBoardStarted)
    judgeBoardStarting.value = Boolean(runtime.judgeBoardStarting)
  }

  return {
    liveGame,
    loading,
    error,
    watchRunning,
    roleAssignmentComplete,
    judgeBoardStarted,
    judgeBoardStarting,
    isNight,
    isWatch,
    setGame,
    setLoading,
    setError,
    setWatchRunning,
    clearGame,
    hydrateFromRuntime
  }
})
