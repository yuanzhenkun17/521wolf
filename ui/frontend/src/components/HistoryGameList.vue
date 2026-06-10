<script setup lang="ts">
import { computed, getCurrentInstance, type PropType } from 'vue'
import { useHistoryStore } from '../stores'
import { displayWinnerLabel } from './history/historyDisplay.ts'

type GameId = string | number
type DateValue = string | number | Date
type SourceOptionKey = 'all' | 'normal' | 'benchmark' | 'evolution'
type CountMap = Record<string, number | string | null | undefined>

type HistoryGameConfig = {
  seed?: unknown
  max_days?: unknown
  log_time?: DateValue
  finished_at?: DateValue
  started_at?: DateValue
  log_source?: string
  log_source_label?: string
  source_phase_label?: string
  [key: string]: unknown
}

type HistoryGame = {
  game_id: GameId
  config?: HistoryGameConfig | null
  seed?: unknown
  max_days?: unknown
  log_time?: DateValue
  finished_at?: DateValue
  started_at?: DateValue
  log_source?: string
  log_source_label?: string
  source_phase_label?: string
  mode?: string
  winner?: unknown
  status?: string
  [key: string]: unknown
}

type HistoryPagination = {
  total?: number | string | null
  limit?: number | string | null
  offset?: number | string | null
  returned?: number | string | null
  [key: string]: unknown
}

type HistoryFacets = {
  source?: CountMap
  [key: string]: unknown
}

type HistoryNotice = {
  message?: unknown
  type?: unknown
  [key: string]: unknown
}

const props = defineProps({
  games: { type: Array as PropType<HistoryGame[]>, default: () => [] },
  selectedGameId: { type: [String, Number, null] as unknown as PropType<GameId | null>, default: null },
  loading: Boolean,
  loadingMore: Boolean,
  hasMore: Boolean,
  sourceFilter: { type: String, default: 'all' },
  pagination: { type: Object as PropType<HistoryPagination>, default: () => ({}) },
  counts: { type: Object as PropType<CountMap>, default: () => ({}) },
  facets: { type: Object as PropType<HistoryFacets>, default: () => ({}) },
  notice: { type: Object as PropType<HistoryNotice>, default: () => ({}) }
})

const emit = defineEmits<{
  'select-game': [gameId: GameId]
  'replay-game': [game: HistoryGame]
  'delete-game': [game: HistoryGame]
  'change-source': [source: string]
  'change-page': [page: number]
  'load-more': []
}>()
const historyStore = useHistoryStore()
const instance = getCurrentInstance()

const PROP_ALIASES: Record<string, string[]> = {
  games: ['games'],
  selectedGameId: ['selectedGameId', 'selected-game-id'],
  loading: ['loading'],
  loadingMore: ['loadingMore', 'loading-more'],
  sourceFilter: ['sourceFilter', 'source-filter'],
  pagination: ['pagination'],
  counts: ['counts'],
  facets: ['facets'],
  notice: ['notice']
}

function hasExplicitProp(propName: keyof typeof PROP_ALIASES) {
  const rawProps = instance?.vnode.props || {}
  return PROP_ALIASES[propName].some((key) => Object.prototype.hasOwnProperty.call(rawProps, key))
}

const resolvedGames = computed<HistoryGame[]>(() => hasExplicitProp('games') ? props.games : historyStore.games)
const resolvedSelectedGameId = computed<GameId | null>(() =>
  hasExplicitProp('selectedGameId') ? props.selectedGameId : historyStore.selectedHistoryGameId
)
const resolvedLoading = computed(() => hasExplicitProp('loading') ? props.loading : historyStore.loading)
const resolvedLoadingMore = computed(() => hasExplicitProp('loadingMore') ? props.loadingMore : historyStore.loadingMore)
const resolvedSourceFilter = computed(() => hasExplicitProp('sourceFilter') ? props.sourceFilter : historyStore.sourceFilter)
const resolvedPagination = computed<HistoryPagination>(() =>
  hasExplicitProp('pagination') ? props.pagination : historyStore.pagination as HistoryPagination
)
const resolvedCounts = computed<CountMap>(() => hasExplicitProp('counts') ? props.counts : historyStore.counts as CountMap)
const resolvedFacets = computed<HistoryFacets>(() =>
  hasExplicitProp('facets') ? props.facets : historyStore.facets as HistoryFacets
)
const resolvedNotice = computed<HistoryNotice>(() => {
  if (hasExplicitProp('notice')) return props.notice
  return historyStore.notice || (historyStore.error ? { type: 'error', message: historyStore.error } : {})
})

const SOURCE_OPTIONS: Array<{ key: SourceOptionKey, label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'normal', label: '观战/玩家' },
  { key: 'benchmark', label: '批量评测' },
  { key: 'evolution', label: '自进化' }
]

function gameConfig(game: HistoryGame | null | undefined): HistoryGameConfig {
  return game?.config && typeof game.config === 'object' ? game.config : {}
}

function gameSeed(game: HistoryGame) {
  const config = gameConfig(game)
  const seed = game?.seed ?? config.seed
  return seed == null || seed === '' ? '随机' : seed
}

function gameMaxDays(game: HistoryGame) {
  const config = gameConfig(game)
  return game?.max_days ?? config.max_days ?? 20
}

function gameTimeValue(game: HistoryGame): DateValue | '' {
  const config = gameConfig(game)
  return game?.log_time || game?.finished_at || game?.started_at || config.log_time || config.finished_at || config.started_at || ''
}

function gameDate(game: HistoryGame) {
  const value = gameTimeValue(game)
  if (!value) return '时间未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间未知'
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const startOfDate = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const dayDiff = Math.round((startOfToday.getTime() - startOfDate.getTime()) / 86400000)
  const time = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  if (dayDiff === 0) return `今天 ${time}`
  if (dayDiff === 1) return `昨天 ${time}`
  if (date.getFullYear() === now.getFullYear()) {
    return `${date.getMonth() + 1}月${date.getDate()}日 ${time}`
  }
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`
}

function winnerLabel(winner: unknown) {
  return displayWinnerLabel(winner)
}

function gameTitle(index: number) {
  return `对局${pageStartIndex.value + index}`
}

function sourceKey(game: HistoryGame) {
  return game?.log_source || gameConfig(game).log_source || 'normal'
}

function sourceLabel(game: HistoryGame) {
  if (sourceKey(game) === 'normal') return modeLabel(game)
  return game?.log_source_label || gameConfig(game).log_source_label || SOURCE_OPTIONS.find((item) => item.key === sourceKey(game))?.label || '对局'
}

function sourceDetail(game: HistoryGame) {
  if (sourceKey(game) === 'normal') return '历史记录'
  return game?.source_phase_label || gameConfig(game).source_phase_label || sourceLabel(game)
}

function isEvidenceGame(game: HistoryGame) {
  return sourceKey(game) !== 'normal'
}

function deleteTitle(game: HistoryGame) {
  if (!isEvidenceGame(game)) return '删除对局'
  return `${sourceLabel(game)}会作为证据资产保留，普通删除不可用`
}

function modeLabel(game: HistoryGame) {
  return game?.mode === 'watch' ? '观战局' : '玩家局'
}

function modeClass(game: HistoryGame) {
  return game?.mode === 'watch' ? 'watch' : 'play'
}

function outcomeLabel(game: HistoryGame) {
  if (game?.winner) return `${winnerLabel(game.winner)}获胜`
  if (game?.status === 'running') return '进行中'
  return '未结束'
}

const sourceCounts = computed(() => {
  const backendCounts = resolvedFacets.value?.source || resolvedCounts.value || {}
  if (Object.keys(backendCounts).length) {
    return {
      all: Number(backendCounts.all || 0),
      normal: Number(backendCounts.normal || 0),
      benchmark: Number(backendCounts.benchmark || 0),
      evolution: Number(backendCounts.evolution || 0)
    }
  }
  const counts = { all: resolvedGames.value.length, normal: 0, benchmark: 0, evolution: 0 }
  resolvedGames.value.forEach((game) => {
    const key = sourceKey(game)
    counts[key] = (counts[key] || 0) + 1
  })
  return counts
})

const sourceTabs = computed(() =>
  SOURCE_OPTIONS.map((item) => ({
    ...item,
    count: sourceCounts.value[item.key] || 0
  }))
)

const sourceFilteredGames = computed(() => resolvedGames.value)
const shownTotal = computed(() => resolvedGames.value.length)
const backendTotal = computed(() => Number(resolvedPagination.value?.total ?? sourceCounts.value[resolvedSourceFilter.value] ?? resolvedGames.value.length))
const pageLimit = computed(() => Math.max(1, Number(resolvedPagination.value?.limit || shownTotal.value || 1)))
const pageOffset = computed(() => Math.max(0, Number(resolvedPagination.value?.offset || 0)))
const pageReturned = computed(() => Math.max(0, Number(resolvedPagination.value?.returned ?? shownTotal.value)))
const currentPage = computed(() => Math.max(1, Math.floor(pageOffset.value / pageLimit.value) + 1))
const totalPages = computed(() => Math.max(1, Math.ceil(Math.max(0, backendTotal.value) / pageLimit.value)))
const pageStartIndex = computed(() => backendTotal.value > 0 ? pageOffset.value + 1 : 0)
const pageEndIndex = computed(() => Math.min(backendTotal.value, pageOffset.value + pageReturned.value))
const pageWindow = computed(() => {
  const total = totalPages.value
  const current = currentPage.value
  const maxButtons = 5
  if (total <= maxButtons) return Array.from({ length: total }, (_, index) => index + 1)
  let start = Math.max(1, current - 2)
  let end = Math.min(total, start + maxButtons - 1)
  start = Math.max(1, end - maxButtons + 1)
  return Array.from({ length: end - start + 1 }, (_, index) => start + index)
})
const pageSummary = computed(() => {
  if (!backendTotal.value) return '暂无记录'
  return `${pageStartIndex.value}-${pageEndIndex.value} / ${backendTotal.value} 局`
})
const pageIndexSummary = computed(() => `第 ${currentPage.value} / ${totalPages.value} 页`)
const noticeMessage = computed(() => String(resolvedNotice.value?.message || '').trim())
const noticeType = computed(() => {
  const type = String(resolvedNotice.value?.type || '').trim()
  return ['success', 'warning', 'error'].includes(type) ? type : 'info'
})

function changePage(page: number) {
  if (resolvedLoading.value || resolvedLoadingMore.value) return
  const target = Math.max(1, Math.min(Number(page) || 1, totalPages.value))
  if (target === currentPage.value) return
  emit('change-page', target)
}

function selectSource(source: string) {
  if (source === resolvedSourceFilter.value || resolvedLoading.value) return
  emit('change-source', source)
}
</script>

<template>
  <aside class="history-games-panel">
    <header>
      <span>历史对局</span>
    </header>
    <div class="history-source-tabs" aria-label="对局分类">
      <button
        v-for="item in sourceTabs"
        :key="item.key"
        type="button"
        :class="{ active: resolvedSourceFilter === item.key }"
        @click="selectSource(item.key)"
      >
        <span>{{ item.label }}</span>
        <small>{{ item.count }}</small>
      </button>
    </div>
    <div v-if="noticeMessage" :class="['history-notice', noticeType]" role="status" aria-live="polite">
      <span>{{ noticeMessage }}</span>
    </div>
    <div class="history-games-list">
      <div
        v-for="(item, index) in sourceFilteredGames"
        :key="item.game_id"
        :class="{ active: item.game_id === resolvedSelectedGameId }"
        class="history-game-item"
      >
        <button class="history-game-select" @click="emit('select-game', item.game_id)">
          <span class="history-game-main">
            <span class="history-game-title">
              <b>{{ gameTitle(index) }}</b>
              <span class="history-game-support">
                <small :class="[sourceKey(item) === 'normal' ? 'history-mode-tag' : 'history-source-tag', sourceKey(item) === 'normal' ? modeClass(item) : sourceKey(item)]">
                  {{ sourceLabel(item) }}
                </small>
                <time>{{ gameDate(item) }}</time>
              </span>
            </span>
          </span>
        </button>
        <span class="history-game-actions">
          <button
            class="history-game-delete"
            type="button"
            :class="{ protected: isEvidenceGame(item) }"
            :disabled="isEvidenceGame(item)"
            :title="deleteTitle(item)"
            :aria-label="deleteTitle(item)"
            @click.stop="emit('delete-game', item)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M9 3h6l1 2h4v2H4V5h4l1-2Zm-3 6h12l-1 12H7L6 9Zm4 2v7h2v-7h-2Zm4 0v7h2v-7h-2Z" />
            </svg>
          </button>
          <button class="history-game-replay" title="事件回放" aria-label="事件回放" @click="emit('replay-game', item)">回放</button>
        </span>
      </div>
    </div>
    <p v-if="!sourceFilteredGames.length && !resolvedLoading" class="empty-log">暂无历史对局</p>
    <footer class="history-pagination" aria-label="历史对局分页">
      <div class="history-page-meta">
        <span>{{ pageSummary }}</span>
        <small>{{ pageIndexSummary }}</small>
      </div>
      <div class="history-page-controls">
        <button
          type="button"
          class="history-page-step"
          :disabled="resolvedLoading || resolvedLoadingMore || currentPage <= 1"
          aria-label="上一页"
          @click="changePage(currentPage - 1)"
        >
          ‹
        </button>
        <button
          v-for="page in pageWindow"
          :key="page"
          type="button"
          class="history-page-number"
          :class="{ active: page === currentPage }"
          :disabled="resolvedLoading || resolvedLoadingMore || page === currentPage"
          :aria-current="page === currentPage ? 'page' : undefined"
          @click="changePage(page)"
        >
          {{ page }}
        </button>
        <button
          type="button"
          class="history-page-step"
          :disabled="resolvedLoading || resolvedLoadingMore || currentPage >= totalPages"
          aria-label="下一页"
          @click="changePage(currentPage + 1)"
        >
          ›
        </button>
      </div>
    </footer>
  </aside>
</template>
