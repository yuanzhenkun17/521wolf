import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { Game } from '../types/game'

type LooseRecord = Record<string, unknown>

export interface GameRuntimeHydration {
  liveGame?: Game | null
  game?: Game | null
  loading?: boolean | null
  error?: string | null
  watchRunning?: boolean | null
  roleAssignmentComplete?: boolean | null
  judgeBoardStarted?: boolean | null
  judgeBoardStarting?: boolean | null
  promptText?: string | null
  judgeStripMessage?: LooseRecord[] | null
  playerIdentityList?: LooseRecord[] | null
  matchRecordLogs?: LooseRecord[] | null
  livingPlayers?: LooseRecord[] | null
  speakerCarousel?: LooseRecord[] | null
  speakerMessage?: string | null
  sceneVoteTally?: LooseRecord[] | null
  sceneEffects?: LooseRecord[] | null
}

export const useGameStore = defineStore('game', () => {
  const liveGame = ref<Game | null>(null)
  const loading = ref(false)
  const error = ref('')
  const watchRunning = ref(false)
  const roleAssignmentComplete = ref(false)
  const judgeBoardStarted = ref(false)
  const judgeBoardStarting = ref(false)
  const promptText = ref('')
  const judgeStripMessage = ref<LooseRecord[]>([])
  const playerIdentityList = ref<LooseRecord[]>([])
  const matchRecordLogs = ref<LooseRecord[]>([])
  const livingPlayers = ref<LooseRecord[]>([])
  const speakerCarousel = ref<LooseRecord[]>([])
  const speakerMessage = ref('')
  const sceneVoteTally = ref<LooseRecord[]>([])
  const sceneEffects = ref<LooseRecord[]>([])

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
    promptText.value = ''
    judgeStripMessage.value = []
    playerIdentityList.value = []
    matchRecordLogs.value = []
    livingPlayers.value = []
    speakerCarousel.value = []
    speakerMessage.value = ''
    sceneVoteTally.value = []
    sceneEffects.value = []
  }

  function hydrateFromRuntime(runtime: GameRuntimeHydration): void {
    liveGame.value = runtime.liveGame ?? runtime.game ?? null
    loading.value = Boolean(runtime.loading)
    error.value = runtime.error ?? ''
    watchRunning.value = Boolean(runtime.watchRunning)
    roleAssignmentComplete.value = Boolean(runtime.roleAssignmentComplete)
    judgeBoardStarted.value = Boolean(runtime.judgeBoardStarted)
    judgeBoardStarting.value = Boolean(runtime.judgeBoardStarting)
    promptText.value = runtime.promptText ?? ''
    judgeStripMessage.value = runtime.judgeStripMessage ?? []
    playerIdentityList.value = runtime.playerIdentityList ?? []
    matchRecordLogs.value = runtime.matchRecordLogs ?? []
    livingPlayers.value = runtime.livingPlayers ?? []
    speakerCarousel.value = runtime.speakerCarousel ?? []
    speakerMessage.value = runtime.speakerMessage ?? ''
    sceneVoteTally.value = runtime.sceneVoteTally ?? []
    sceneEffects.value = runtime.sceneEffects ?? []
  }

  return {
    liveGame,
    loading,
    error,
    watchRunning,
    roleAssignmentComplete,
    judgeBoardStarted,
    judgeBoardStarting,
    promptText,
    judgeStripMessage,
    playerIdentityList,
    matchRecordLogs,
    livingPlayers,
    speakerCarousel,
    speakerMessage,
    sceneVoteTally,
    sceneEffects,
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
