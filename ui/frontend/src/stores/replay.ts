import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { ReplaySnapshot } from '../types/history'

export interface ReplayRuntimeHydration {
  replayGame?: ReplaySnapshot | null
  isReplayMode?: boolean | null
  replayCursor?: number | null
  replayPlaying?: boolean | null
  replaySpeed?: number | null
}

export const useReplayStore = defineStore('replay', () => {
  const replayGame = ref<ReplaySnapshot | null>(null)
  const isReplayMode = ref(false)
  const replayCursor = ref(0)
  const replayPlaying = ref(false)
  const replaySpeed = ref(1)

  const hasReplay = computed(() => Boolean(replayGame.value))

  function enterReplay(game: ReplaySnapshot): void {
    replayGame.value = game
    isReplayMode.value = true
    replayCursor.value = Number(game.cursor || 0)
  }

  function exitReplay(): void {
    replayPlaying.value = false
    isReplayMode.value = false
    replayGame.value = null
  }

  function hydrateFromRuntime(runtime: ReplayRuntimeHydration): void {
    replayGame.value = runtime.replayGame ?? null
    isReplayMode.value = Boolean(runtime.isReplayMode)
    replayCursor.value = Number(runtime.replayCursor ?? 0)
    replayPlaying.value = Boolean(runtime.replayPlaying)
    replaySpeed.value = Number(runtime.replaySpeed ?? 1)
  }

  return {
    replayGame,
    isReplayMode,
    replayCursor,
    replayPlaying,
    replaySpeed,
    hasReplay,
    enterReplay,
    exitReplay,
    hydrateFromRuntime
  }
})
