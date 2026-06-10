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
  selectedHistoryPageKey?: string | null
  selectedHistoryPage?: LooseRecord | null
  phaseLoadingByKey?: LooseRecord | null
  historyLogs?: LooseRecord[] | null
  pageNightActions?: LooseRecord[] | null
  pageSpeechDecisions?: LooseRecord[] | null
  sheriffVotes?: LooseRecord[] | null
  voteDecisions?: LooseRecord[] | null
  currentVoteTally?: LooseRecord[] | null
  sheriffVoteTally?: LooseRecord[] | null
  pageLastWords?: LooseRecord[] | null
  nightResult?: string | null
  sheriffResult?: LooseRecord | null
  playerAssessmentScores?: LooseRecord[] | null
  activeAssessScores?: LooseRecord[] | null
  playerAliveAtPage?: LooseRecord | null
  archiveByGameId?: LooseRecord | null
  reviewByGameId?: LooseRecord | null
  flowDataByGameId?: LooseRecord | null
  flowLoadingByGameId?: LooseRecord | null
  archiveLoading?: boolean | null
  reviewLoading?: boolean | null
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
  const selectedHistoryPageKey = ref('')
  const selectedHistoryPage = ref<LooseRecord | null>(null)
  const phaseLoadingByKey = ref<LooseRecord>({})
  const historyLogs = ref<LooseRecord[]>([])
  const pageNightActions = ref<LooseRecord[]>([])
  const pageSpeechDecisions = ref<LooseRecord[]>([])
  const sheriffVotes = ref<LooseRecord[]>([])
  const voteDecisions = ref<LooseRecord[]>([])
  const currentVoteTally = ref<LooseRecord[]>([])
  const sheriffVoteTally = ref<LooseRecord[]>([])
  const pageLastWords = ref<LooseRecord[]>([])
  const nightResult = ref('')
  const sheriffResult = ref<LooseRecord | null>(null)
  const playerAssessmentScores = ref<LooseRecord[]>([])
  const activeAssessScores = ref<LooseRecord[]>([])
  const playerAliveAtPage = ref<LooseRecord>({})
  const archiveByGameId = ref<LooseRecord>({})
  const reviewByGameId = ref<LooseRecord>({})
  const flowDataByGameId = ref<LooseRecord>({})
  const flowLoadingByGameId = ref<LooseRecord>({})
  const archiveLoading = ref(false)
  const reviewLoading = ref(false)
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
    selectedHistoryPageKey.value = runtime.selectedHistoryPageKey ?? ''
    selectedHistoryPage.value = runtime.selectedHistoryPage ?? null
    phaseLoadingByKey.value = runtime.phaseLoadingByKey ?? {}
    historyLogs.value = runtime.historyLogs ?? []
    pageNightActions.value = runtime.pageNightActions ?? []
    pageSpeechDecisions.value = runtime.pageSpeechDecisions ?? []
    sheriffVotes.value = runtime.sheriffVotes ?? []
    voteDecisions.value = runtime.voteDecisions ?? []
    currentVoteTally.value = runtime.currentVoteTally ?? []
    sheriffVoteTally.value = runtime.sheriffVoteTally ?? []
    pageLastWords.value = runtime.pageLastWords ?? []
    nightResult.value = runtime.nightResult ?? ''
    sheriffResult.value = runtime.sheriffResult ?? null
    playerAssessmentScores.value = runtime.playerAssessmentScores ?? []
    activeAssessScores.value = runtime.activeAssessScores ?? []
    playerAliveAtPage.value = runtime.playerAliveAtPage ?? {}
    archiveByGameId.value = runtime.archiveByGameId ?? {}
    reviewByGameId.value = runtime.reviewByGameId ?? {}
    flowDataByGameId.value = runtime.flowDataByGameId ?? {}
    flowLoadingByGameId.value = runtime.flowLoadingByGameId ?? {}
    archiveLoading.value = Boolean(runtime.archiveLoading)
    reviewLoading.value = Boolean(runtime.reviewLoading)
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
    selectedHistoryPageKey,
    selectedHistoryPage,
    phaseLoadingByKey,
    historyLogs,
    pageNightActions,
    pageSpeechDecisions,
    sheriffVotes,
    voteDecisions,
    currentVoteTally,
    sheriffVoteTally,
    pageLastWords,
    nightResult,
    sheriffResult,
    playerAssessmentScores,
    activeAssessScores,
    playerAliveAtPage,
    archiveByGameId,
    reviewByGameId,
    flowDataByGameId,
    flowLoadingByGameId,
    archiveLoading,
    reviewLoading,
    error,
    hasSelection,
    setGames,
    selectGame,
    hydrateFromRuntime
  }
})
