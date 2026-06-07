<script setup>
import { computed, ref } from 'vue'
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
  facets: { type: Object, default: () => ({}) }
})

const emit = defineEmits(['select-game', 'replay-game', 'change-source', 'load-more'])
const historyFilter = ref('')

const SOURCE_OPTIONS = [
  { key: 'all', label: '全部' },
  { key: 'normal', label: '人机/玩家' },
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
  return `对局${index + 1}`
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

function modeLabel(game) {
  return game?.mode === 'watch' ? '人机局' : '玩家局'
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

const sourceFilteredGames = computed(() => {
  const query = historyFilter.value.trim().toLowerCase()
  if (!query) return props.games
  return props.games.filter((game) =>
    [
      game.game_id,
      game.log_name,
      game.mode,
      game.status,
      game.winner,
      game.phase,
      game.day,
      game.seed,
      game.max_days,
      game.skill_dir,
      sourceKey(game),
      sourceLabel(game),
      sourceDetail(game),
      gameConfig(game).seed,
      gameConfig(game).max_days,
      gameConfig(game).skill_dir
    ].some((value) => String(value || '').toLowerCase().includes(query))
  )
})
const shownTotal = computed(() => props.games.length)
const backendTotal = computed(() => Number(props.pagination?.total ?? sourceCounts.value[props.sourceFilter] ?? props.games.length))
const remainingCount = computed(() => Math.max(0, backendTotal.value - shownTotal.value))

function selectSource(source) {
  if (source === props.sourceFilter || props.loading) return
  emit('change-source', source)
}
</script>

<template>
  <aside class="history-games-panel">
    <header>
      <span>历史对局</span>
      <strong>{{ backendTotal }}</strong>
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
    <div class="history-list-tools">
      <input v-model="historyFilter" type="search" placeholder="筛选 game / 阶段 / 胜负" />
      <span>{{ sourceFilteredGames.length }} / {{ shownTotal }}</span>
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
              <small :class="[sourceKey(item) === 'normal' ? 'history-mode-tag' : 'history-source-tag', sourceKey(item) === 'normal' ? modeClass(item) : sourceKey(item)]">
                {{ sourceLabel(item) }}
              </small>
            </span>
            <span class="history-game-subline">
              <span>{{ outcomeLabel(item) }}</span>
              <small>{{ sourceDetail(item) }}</small>
            </span>
          </span>
          <div class="history-game-meta">
            <small class="history-game-date">{{ gameDate(item) }}</small>
            <small>种子 {{ gameSeed(item) }}</small>
            <small>{{ gameMaxDays(item) }} 天</small>
          </div>
        </button>
        <button class="history-game-replay" title="事件回放" aria-label="事件回放" @click="emit('replay-game', item)">▶</button>
      </div>
      <div v-if="hasMore" class="history-list-more">
        <span>已显示 {{ shownTotal }} / {{ backendTotal }}，还有 {{ remainingCount }} 条</span>
        <button type="button" class="history-load-more" :disabled="loadingMore || loading" @click="emit('load-more')">
          {{ loadingMore ? '加载中' : '加载更多' }}
        </button>
      </div>
    </div>
    <p v-if="!sourceFilteredGames.length && !loading" class="empty-log">暂无历史对局</p>
  </aside>
</template>
