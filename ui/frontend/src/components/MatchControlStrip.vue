<script setup lang="ts">
// @ts-nocheck
import { computed } from 'vue'
import JudgeStrip from './JudgeStrip.vue'

const props = defineProps({
  game: Object,
  loading: Boolean,
  backendMode: { type: String, default: 'mock' },
  isNight: Boolean,
  watchRunning: Boolean,
  promptText: { type: String, default: '' },
  judgeStripMessage: { type: Array, default: () => [] },
  judgeBoardStarted: Boolean,
  judgeBoardStarting: Boolean,
  isReplayMode: Boolean,
  historyPhaseName: Function
})

const emit = defineEmits(['toggle-watch', 'reset-game', 'start-from-judge-board'])
const dayText = computed(() => props.isReplayMode ? '回放' : `第    ${props.game?.day ?? '-'}    天`)

function phaseName(phase) {
  return props.historyPhaseName ? props.historyPhaseName(phase) : (phase || '')
}
</script>

<template>
  <section :class="['match-control-strip', { 'is-replay-mode': isReplayMode }]">
    <div class="strip-status">
      <strong>{{ dayText }}</strong>
      <span :class="['phase-icon', isNight ? 'is-night' : 'is-day']" :title="phaseName(game.phase)">
        <svg v-if="isNight" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="8" />
          <circle class="moon-cutout" cx="15.5" cy="8.5" r="6.5" />
        </svg>
        <svg v-else viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="4.5" />
          <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1" />
        </svg>
      </span>
      <Transition name="strip-text" mode="out-in">
        <em :key="promptText">{{ promptText }}</em>
      </Transition>
    </div>
    <JudgeStrip
      :messages="judgeStripMessage"
      :judge-board-started="judgeBoardStarted"
      :judge-board-starting="judgeBoardStarting"
      @start="emit('start-from-judge-board')"
    />
    <div v-if="!isReplayMode" class="strip-controls" aria-label="观战控制">
      <button class="icon-button primary" :disabled="!watchRunning && game.winner" :title="watchRunning ? '暂停' : '开始'" @click="emit('toggle-watch')">
        <svg v-if="watchRunning" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h4v14H7zM13 5h4v14h-4z" /></svg>
        <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z" /></svg>
      </button>
      <button class="icon-button" :disabled="loading" title="重开" @click="emit('reset-game')">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.7 6.3A8 8 0 1 0 20 12h-2.2a5.8 5.8 0 1 1-1.7-4.1L13 11h8V3z" /></svg>
      </button>
    </div>
  </section>
</template>

<style scoped>
.match-control-strip.is-replay-mode {
  grid-template-columns: minmax(210px, 0.8fr) minmax(280px, 1.4fr) minmax(210px, 0.8fr);
}

.match-control-strip.is-replay-mode :deep(.strip-judge-log) {
  justify-self: center;
  transform: none;
}

.strip-controls {
  width: auto;
  min-width: 88px;
  flex: 0 0 auto;
}

@media (max-width: 760px) {
  .strip-controls {
    min-width: 88px;
  }
}
</style>
