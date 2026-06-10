<script setup>
import { computed } from 'vue'
import { displayWinnerLabel } from './history/historyDisplay.js'

const props = defineProps({
  games: { type: Array, default: () => [] },
  selectedGameId: [String, Number, null],
  loading: Boolean,
  loadingMore: Boolean,
  hasMore: Boolean,
  sourceFilter: { type: String, default: 'all' },
  pagination: { type: Object, default: () => ({}) },
  counts: { type: Object, default: () => ({}) },
  facets: { type: Object, default: () => ({}) },
  notice: { type: Object, default: () => ({}) }
})

const emit = defineEmits(['select-game', 'replay-game', 'delete-game', 'change-source', 'change-page', 'load-more'])
const SOURCE_OPTIONS = [
  { key: 'all', label: '全部' },
  { key: 'normal', label: '观战/玩家' },
  { key: 'benchmark', label: '批量评测' },
  { key: 'evolution', label: '自进化' }
]

function gameConfig(game) {
  return game?.config && typeof game.config === 'object' ? game.config : {}
}

function gameSeed(game) {
  const config = gameConfig(game)
  const seed = game?.seed ?? config.seed
  return seed == null || seed === '' ? '随机' : seed
}

function gameMaxDays(game) {
  const config = gameConfig(game)
  return game?.max_days ?? config.max_days ?? 20
}

function gameTimeValue(game) {
  const config = gameConfig(game)
  return game?.log_time || game?.finished_at || game?.started_at || config.log_time || config.finished_at || config.started_at || ''
}

function gameDate(game) {
  const value = gameTimeValue(game)
  if (!value) return '时间未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间未知'
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const startOfDate = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const dayDiff = Math.round((startOfToday - startOfDate) / 86400000)
  const time = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  if (dayDiff === 0) return `今天 ${time}`
  if (dayDiff === 1) return `昨天 ${time}`
  if (date.getFullYear() === now.getFullYear()) {
    return `${date.getMonth() + 1}月${date.getDate()}日 ${time}`
  }
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`
}

function winnerLabel(winner) {
  return displayWinnerLabel(winner)
}

function gameTitle(index) {
  return `对局${pageStartIndex.value + index}`
}

function sourceKey(game) {
  return game?.log_source || gameConfig(game).log_source || 'normal'
}

function sourceLabel(game) {
  if (sourceKey(game) === 'normal') return modeLabel(game)
  return game?.log_source_label || gameConfig(game).log_source_label || SOURCE_OPTIONS.find((item) => item.key === sourceKey(game))?.label || '对局'
}

function sourceDetail(game) {
  if (sourceKey(game) === 'normal') return '历史记录'
  return game?.source_phase_label || gameConfig(game).source_phase_label || sourceLabel(game)
}

function isEvidenceGame(game) {
  return sourceKey(game) !== 'normal'
}

function deleteTitle(game) {
  if (!isEvidenceGame(game)) return '删除对局'
  return `${sourceLabel(game)}会作为证据资产保留，普通删除不可用`
}

function modeLabel(game) {
  return game?.mode === 'watch' ? '观战局' : '玩家局'
}

function modeClass(game) {
  return game?.mode === 'watch' ? 'watch' : 'play'
}

function outcomeLabel(game) {
  if (game?.winner) return `${winnerLabel(game.winner)}获胜`
  if (game?.status === 'running') return '进行中'
  return '未结束'
}

const sourceCounts = computed(() => {
  const backendCounts = props.facets?.source || props.counts || {}
  if (Object.keys(backendCounts).length) {
    return {
      all: Number(backendCounts.all || 0),
      normal: Number(backendCounts.normal || 0),
      benchmark: Number(backendCounts.benchmark || 0),
      evolution: Number(backendCounts.evolution || 0)
    }
  }
  const counts = { all: props.games.length, normal: 0, benchmark: 0, evolution: 0 }
  props.games.forEach((game) => {
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

const sourceFilteredGames = computed(() => props.games)
const shownTotal = computed(() => props.games.length)
const backendTotal = computed(() => Number(props.pagination?.total ?? sourceCounts.value[props.sourceFilter] ?? props.games.length))
const pageLimit = computed(() => Math.max(1, Number(props.pagination?.limit || shownTotal.value || 1)))
const pageOffset = computed(() => Math.max(0, Number(props.pagination?.offset || 0)))
const pageReturned = computed(() => Math.max(0, Number(props.pagination?.returned ?? shownTotal.value)))
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
const noticeMessage = computed(() => String(props.notice?.message || '').trim())
const noticeType = computed(() => {
  const type = String(props.notice?.type || '').trim()
  return ['success', 'warning', 'error'].includes(type) ? type : 'info'
})

function changePage(page) {
  if (props.loading || props.loadingMore) return
  const target = Math.max(1, Math.min(Number(page) || 1, totalPages.value))
  if (target === currentPage.value) return
  emit('change-page', target)
}

function selectSource(source) {
  if (source === props.sourceFilter || props.loading) return
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
        :class="{ active: sourceFilter === item.key }"
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
        :class="{ active: item.game_id === selectedGameId }"
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
    <p v-if="!sourceFilteredGames.length && !loading" class="empty-log">暂无历史对局</p>
  </aside>
</template>
