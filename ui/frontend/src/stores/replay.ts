import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { ReplaySnapshot } from '../types/history'

export interface ReplayRuntimeHydration {
  replayGame?: ReplaySnapshot | null
  isReplayMode?: boolean | null
  replayCursor?: number | null
  replayPlaying?: boolean | null
  replaySpeed?: number | null
  replayTotal?: number | null
  replayEventLabel?: string | null
}

export const useReplayStore = defineStore('replay', () => {
  const replayGame = ref<ReplaySnapshot | null>(null)
  const isReplayMode = ref(false)
  const replayCursor = ref(0)
  const replayPlaying = ref(false)
  const replaySpeed = ref(1)
  const replayTotal = ref(0)
  const replayEventLabel = ref('')

  const hasReplay = computed(() => Boolean(replayGame.value))

  function enterReplay(game: ReplaySnapshot): void {
    replayGame.value = game
    isReplayMode.value = true
    replayCursor.value = Number(game.cursor || 0)
    replayTotal.value = Number(game.logs?.length ?? 0) || 0
  }

  function exitReplay(): void {
    replayPlaying.value = false
    isReplayMode.value = false
    replayGame.value = null
    replayTotal.value = 0
    replayEventLabel.value = ''
  }

  function hydrateFromRuntime(runtime: ReplayRuntimeHydration): void {
    replayGame.value = runtime.replayGame ?? null
    isReplayMode.value = Boolean(runtime.isReplayMode)
    replayCursor.value = Number(runtime.replayCursor ?? 0)
    replayPlaying.value = Boolean(runtime.replayPlaying)
    replaySpeed.value = Number(runtime.replaySpeed ?? 1)
    replayTotal.value = Number(runtime.replayTotal ?? 0)
    replayEventLabel.value = runtime.replayEventLabel ?? ''
  }

  return {
    replayGame,
    isReplayMode,
    replayCursor,
    replayPlaying,
    replaySpeed,
    replayTotal,
    replayEventLabel,
    hasReplay,
    enterReplay,
    exitReplay,
    hydrateFromRuntime
  }
})
