import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { HistoryGame, HistoryWorkspaceTab } from '../types/history'
import type { NoticeState } from '../types/ui'

type LooseRecord = Record<string, unknown>
type HistoryNotice = Partial<NoticeState> & { message?: string }

export interface HistoryRuntimeHydration {
  gameHistory?: HistoryGame[] | null
  selectedHistoryGameId?: string | number | null
  selectedHistoryGame?: HistoryGame | null
  historyWorkspaceTab?: HistoryWorkspaceTab | null
  historyLoading?: boolean | null
  historyPagination?: LooseRecord | null
  historyLoadingMore?: boolean | null
  historySourceFilter?: string | null
  historyCounts?: LooseRecord | null
  historyFacets?: LooseRecord | null
  historyNotice?: HistoryNotice | null
  historyHasMore?: boolean | null
  historyCurrentPage?: number | null
  historyTotalPages?: number | null
  historyPages?: LooseRecord[] | null
}

export const useHistoryStore = defineStore('history', () => {
  const games = ref<HistoryGame[]>([])
  const selectedHistoryGameId = ref<string | number | null>(null)
  const selectedHistoryGame = ref<HistoryGame | null>(null)
  const historyWorkspaceTab = ref<HistoryWorkspaceTab>('phase')
  const loading = ref(false)
  const pagination = ref<LooseRecord>({})
  const loadingMore = ref(false)
  const sourceFilter = ref('all')
  const counts = ref<LooseRecord>({})
  const facets = ref<LooseRecord>({})
  const notice = ref<HistoryNotice | null>(null)
  const hasMore = ref(false)
  const currentPage = ref(1)
  const totalPages = ref(1)
  const pages = ref<LooseRecord[]>([])
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
    pagination.value = runtime.historyPagination ?? {}
    loadingMore.value = Boolean(runtime.historyLoadingMore)
    sourceFilter.value = runtime.historySourceFilter || 'all'
    counts.value = runtime.historyCounts ?? {}
    facets.value = runtime.historyFacets ?? {}
    notice.value = runtime.historyNotice ?? null
    hasMore.value = Boolean(runtime.historyHasMore)
    currentPage.value = Number(runtime.historyCurrentPage ?? 1) || 1
    totalPages.value = Number(runtime.historyTotalPages ?? 1) || 1
    pages.value = runtime.historyPages ?? []
    error.value = runtime.historyNotice?.message ?? ''
  }

  return {
    games,
    selectedHistoryGameId,
    selectedHistoryGame,
    historyWorkspaceTab,
    loading,
    pagination,
    loadingMore,
    sourceFilter,
    counts,
    facets,
    notice,
    hasMore,
    currentPage,
    totalPages,
    pages,
    error,
    hasSelection,
    setGames,
    selectGame,
    hydrateFromRuntime
  }
})
