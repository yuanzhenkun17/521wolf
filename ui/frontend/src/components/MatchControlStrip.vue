<script setup>
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
  historyPhaseName: Function
})

const emit = defineEmits(['toggle-watch', 'reset-game', 'step-game', 'start-from-judge-board'])

const stepTitle = computed(() => props.backendMode === 'mock' ? '单步推进' : '刷新状态')
const dayText = computed(() => `第${props.game?.day ?? '-'}天`)

function phaseName(phase) {
  return props.historyPhaseName ? props.historyPhaseName(phase) : (phase || '')
}
</script>

<template>
  <section class="match-control-strip">
    <div class="strip-top-row">
      <div class="strip-status">
        <strong>{{ dayText }}</strong>
        <span class="phase-icon" :title="phaseName(game.phase)">{{ isNight ? '☾' : '☀' }}</span>
        <Transition name="strip-text" mode="out-in">
          <em :key="promptText">
            {{ promptText }}
          </em>
        </Transition>
      </div>
      <div class="strip-controls" aria-label="观战控制">
        <button class="icon-button primary" :disabled="!watchRunning && game.winner" :title="watchRunning ? '暂停' : '开始'" @click="emit('toggle-watch')">
          <svg v-if="watchRunning" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h4v14H7zM13 5h4v14h-4z" /></svg>
          <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z" /></svg>
        </button>
        <button class="icon-button" :disabled="loading" title="重开" @click="emit('reset-game')">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.7 6.3A8 8 0 1 0 20 12h-2.2a5.8 5.8 0 1 1-1.7-4.1L13 11h8V3z" /></svg>
        </button>
        <button class="icon-button" :disabled="loading || watchRunning || game.winner" :title="stepTitle" @click="emit('step-game')">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5v14l8-7zM13 5v14l8-7z" /></svg>
        </button>
      </div>
    </div>
    <JudgeStrip
      :messages="judgeStripMessage"
      :judge-board-started="judgeBoardStarted"
      :judge-board-starting="judgeBoardStarting"
      @start="emit('start-from-judge-board')"
    />
  </section>
</template>

<style scoped>
.strip-controls {
  width: auto;
  min-width: 132px;
  flex: 0 0 auto;
}

@media (max-width: 760px) {
  .strip-controls {
    min-width: 132px;
  }
}
</style>
