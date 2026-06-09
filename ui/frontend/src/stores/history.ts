import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { HistoryGame, HistoryWorkspaceTab } from '../types/history'
import type { NoticeState } from '../types/ui'

export interface HistoryRuntimeHydration {
  gameHistory?: HistoryGame[] | null
  selectedHistoryGameId?: string | number | null
  selectedHistoryGame?: HistoryGame | null
  historyWorkspaceTab?: HistoryWorkspaceTab | null
  historyLoading?: boolean | null
  historyNotice?: Pick<NoticeState, 'message'> | null
}

export const useHistoryStore = defineStore('history', () => {
  const games = ref<HistoryGame[]>([])
  const selectedHistoryGameId = ref<string | number | null>(null)
  const selectedHistoryGame = ref<HistoryGame | null>(null)
  const historyWorkspaceTab = ref<HistoryWorkspaceTab>('phase')
  const loading = ref(false)
  const error = ref('')

  const hasSelection = computed(() => Boolean(selectedHistoryGame.value || selectedHistoryGameId.value))

  function setGames(nextGames: HistoryGame[]): void {
    games.value = nextGames
  }

  function selectGame(game: HistoryGame | null): void {
    selectedHistoryGame.value = game
    selectedHistoryGameId.value = game?.game_id || null
  }

  function hydrateFromRuntime(runtime: HistoryRuntimeHydration): void {
    games.value = runtime.gameHistory ?? []
    selectedHistoryGameId.value = runtime.selectedHistoryGameId ?? null
    selectedHistoryGame.value = runtime.selectedHistoryGame ?? null
    historyWorkspaceTab.value = runtime.historyWorkspaceTab ?? 'phase'
    loading.value = Boolean(runtime.historyLoading)
    error.value = runtime.historyNotice?.message ?? ''
  }

  return {
    games,
    selectedHistoryGameId,
    selectedHistoryGame,
    historyWorkspaceTab,
    loading,
    error,
    hasSelection,
    setGames,
    selectGame,
    hydrateFromRuntime
  }
})
