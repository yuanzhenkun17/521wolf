import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { Game } from '../types/game'

export const useGameStore = defineStore('game', () => {
  const liveGame = ref<Game | null>(null)
  const loading = ref(false)
  const error = ref('')
  const watchRunning = ref(false)

  const isNight = computed(() => liveGame.value?.phase === 'night')
  const isWatch = computed(() => liveGame.value?.mode === 'watch')

  function setGame(game: Game | null): void {
    liveGame.value = game
  }

  function clearGame(): void {
    liveGame.value = null
    watchRunning.value = false
  }

  function hydrateFromRuntime(runtime: {
    liveGame?: Game | null
    game?: Game | null
    loading?: boolean
    error?: string
    watchRunning?: boolean
  }): void {
    liveGame.value = runtime.liveGame || runtime.game || null
    loading.value = Boolean(runtime.loading)
    error.value = runtime.error || ''
    watchRunning.value = Boolean(runtime.watchRunning)
  }

  return {
    liveGame,
    loading,
    error,
    watchRunning,
    isNight,
    isWatch,
    setGame,
    clearGame,
    hydrateFromRuntime
  }
})
