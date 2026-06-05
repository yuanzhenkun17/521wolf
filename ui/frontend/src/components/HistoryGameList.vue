<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  games: { type: Array, default: () => [] },
  selectedGameId: [String, Number, null],
  loading: Boolean
})

const emit = defineEmits(['select-game', 'replay-game'])
const historyFilter = ref('')

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

const filteredGames = computed(() => {
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
      gameConfig(game).seed,
      gameConfig(game).max_days,
      gameConfig(game).skill_dir
    ].some((value) => String(value || '').toLowerCase().includes(query))
  )
})
const visibleGames = computed(() => filteredGames.value.slice(0, 160))
</script>

<template>
  <aside class="history-games-panel">
    <header>
      <span>历史对局</span>
      <strong>{{ props.games.length }}</strong>
    </header>
    <div class="history-list-tools">
      <input v-model="historyFilter" type="search" placeholder="筛选 game / 阶段 / 胜负" />
      <span>{{ visibleGames.length }} / {{ filteredGames.length }}</span>
    </div>
    <div class="history-games-list">
      <div
        v-for="(item, index) in visibleGames"
        :key="item.game_id"
        :class="{ active: item.game_id === selectedGameId }"
        class="history-game-item"
      >
        <button class="history-game-select" @click="emit('select-game', item.game_id)">
          <span>对局{{ index + 1 }}</span>
          <div class="history-game-tags">
            <small :class="['history-mode-tag', item.mode === 'watch' ? 'watch' : 'play']">
              {{ item.mode === 'watch' ? '观战局' : '玩家局' }}
            </small>
            <small>Seed {{ gameSeed(item) }}</small>
            <small>{{ gameMaxDays(item) }} 天</small>
          </div>
        </button>
        <button class="history-game-replay" @click="emit('replay-game', item)">复盘</button>
      </div>
      <div v-if="filteredGames.length > visibleGames.length" class="history-list-more">
        继续筛选可查看其余 {{ filteredGames.length - visibleGames.length }} 条
      </div>
    </div>
    <p v-if="!filteredGames.length && !loading" class="empty-log">暂无历史对局</p>
  </aside>
</template>
