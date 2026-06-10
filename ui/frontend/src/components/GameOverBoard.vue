<script setup lang="ts">
import { computed, type PropType } from 'vue'
import { displayWinnerLabel } from './history/historyDisplay.ts'

type GameOverInfo = {
  winner?: string | number | null
  day?: string | number | null
  player_count?: number | null
}

const props = defineProps({
  game: Object as PropType<GameOverInfo | null>,
  loading: Boolean,
  livingCount: { type: Number, default: 0 }
})

const emit = defineEmits<{
  'reset-game': []
  'exit-game': []
  close: []
}>()

const winnerText = computed(() => {
  const label = displayWinnerLabel(props.game?.winner)
  if (!label || label === '未记录') return '胜负未记录'
  if (/获胜|胜利|平局|结束|取消|异常/.test(label)) return label
  return `${label}获胜`
})

const tone = computed(() => {
  const raw = `${props.game?.winner || ''} ${winnerText.value}`.toLowerCase()
  if (raw.includes('wolf') || raw.includes('狼人')) return 'wolf'
  if (raw.includes('draw') || raw.includes('tie') || raw.includes('平局')) return 'draw'
  return 'good'
})

const dayText = computed(() => {
  const day = props.game?.day
  return day == null || day === '' ? '终局' : `第${day}天结束`
})

const aliveText = computed(() => {
  const total = props.game?.player_count
  if (!total) return `存活 ${props.livingCount} 人`
  return `存活 ${props.livingCount}/${total} 人`
})
</script>

<template>
  <section class="game-over-overlay" aria-live="polite">
    <div class="game-over-board" :class="`winner-${tone}`">
      <button class="game-over-close" type="button" title="关闭" aria-label="关闭终局弹窗" @click="emit('close')">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.4 5 12 10.6 17.6 5 19 6.4 13.4 12 19 17.6 17.6 19 12 13.4 6.4 19 5 17.6 10.6 12 5 6.4z" /></svg>
      </button>
      <span class="game-over-kicker">终局裁定</span>
      <h2>游戏结束</h2>
      <strong>{{ winnerText }}</strong>
      <div class="game-over-meta" aria-label="终局概况">
        <span>{{ dayText }}</span>
        <span>{{ aliveText }}</span>
      </div>
      <div class="game-over-actions">
        <button class="game-over-action primary" :disabled="loading" @click="emit('reset-game')">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.7 6.3A8 8 0 1 0 20 12h-2.2a5.8 5.8 0 1 1-1.7-4.1L13 11h8V3z" /></svg>
          <span>再开一局</span>
        </button>
        <button class="game-over-action" :disabled="loading" @click="emit('exit-game')">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 3h9v2H7v14h7v2H5zM15.5 7.5 20 12l-4.5 4.5-1.4-1.4 2.1-2.1H10v-2h6.2l-2.1-2.1z" /></svg>
          <span>返回大厅</span>
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.game-over-overlay {
  position: fixed;
  inset: 0;
  z-index: 76;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(ellipse at 50% 46%, rgba(20, 10, 4, 0.2), transparent 34%),
    linear-gradient(180deg, rgba(3, 2, 2, 0.24), rgba(3, 2, 2, 0.46));
  pointer-events: auto;
}

.game-over-board {
  position: relative;
  display: grid;
  width: min(460px, calc(100vw - 64px));
  min-height: 286px;
  place-items: center;
  align-content: center;
  gap: 12px;
  padding: 34px 38px 30px;
  border: 7px solid transparent;
  border-radius: 0;
  color: #321807;
  text-align: center;
  background:
    radial-gradient(ellipse at 24% 16%, rgba(255, 252, 229, 0.76), transparent 40%) padding-box,
    radial-gradient(ellipse at 84% 94%, rgba(181, 116, 48, 0.14), transparent 46%) padding-box,
    linear-gradient(180deg, rgba(247, 224, 169, 0.98), rgba(232, 193, 121, 0.97) 54%, rgba(210, 157, 82, 0.98)) padding-box,
    repeating-linear-gradient(95deg, #4b2812 0 8px, #8a5428 8px 15px, #321707 15px 23px) border-box;
  box-shadow:
    0 28px 58px rgba(0, 0, 0, 0.54),
    inset 0 0 0 1px rgba(255, 239, 183, 0.58),
    inset 0 0 34px rgba(88, 42, 14, 0.24);
}

.game-over-board::before {
  content: "";
  position: absolute;
  inset: 11px 12px;
  border: 1px solid rgba(77, 38, 16, 0.38);
  pointer-events: none;
  background:
    linear-gradient(90deg, rgba(72, 37, 15, 0.08), transparent 12% 88%, rgba(72, 37, 15, 0.12)),
    repeating-linear-gradient(0deg, rgba(92, 48, 18, 0.04) 0 1px, transparent 1px 7px);
  box-shadow:
    inset 0 0 0 1px rgba(255, 241, 194, 0.44),
    inset 0 0 26px rgba(87, 43, 15, 0.2);
}

.game-over-board > * {
  position: relative;
  z-index: 1;
}

.game-over-close {
  position: absolute;
  top: 12px;
  right: 13px;
  z-index: 2;
  display: grid;
  width: 30px;
  height: 30px;
  min-width: 30px;
  min-height: 30px;
  place-items: center;
  padding: 0;
  border: 1px solid rgba(77, 38, 16, 0.38);
  color: #4b250d;
  background:
    linear-gradient(180deg, rgba(255, 241, 196, 0.62), rgba(129, 72, 31, 0.14)),
    rgba(255, 239, 198, 0.34);
  box-shadow: inset 0 1px 0 rgba(255, 246, 215, 0.42);
  cursor: pointer;
}

.game-over-close:hover {
  color: #2b1206;
  filter: brightness(1.08);
}

.game-over-close svg {
  width: 15px;
  height: 15px;
  fill: currentColor;
}

.game-over-kicker {
  padding: 4px 11px;
  border: 1px solid rgba(93, 48, 17, 0.34);
  color: #5a2d14;
  background: rgba(255, 239, 198, 0.28);
  font-size: 12px;
  font-weight: 950;
}

.game-over-board h2 {
  margin: 0;
  color: #2b1206;
  font-size: 30px;
  font-weight: 1000;
  line-height: 1.05;
  letter-spacing: 0;
  text-shadow: 0 1px 0 rgba(255, 236, 183, 0.6);
}

.game-over-board strong {
  color: #5b2213;
  font-size: 21px;
  font-weight: 1000;
  line-height: 1.25;
}

.game-over-board.winner-good strong {
  color: #315728;
}

.game-over-board.winner-wolf strong {
  color: #7d1f18;
}

.game-over-board.winner-draw strong {
  color: #5a3c19;
}

.game-over-meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 2px;
}

.game-over-meta span {
  min-height: 28px;
  padding: 5px 10px;
  border: 1px solid rgba(91, 47, 18, 0.22);
  color: #4b250d;
  background: rgba(255, 239, 198, 0.28);
  font-size: 12px;
  font-weight: 900;
}

.game-over-actions {
  display: flex;
  justify-content: center;
  gap: 10px;
  margin-top: 8px;
}

.game-over-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-width: 116px;
  min-height: 36px;
  padding: 0 14px;
  border: 1px solid rgba(77, 38, 16, 0.42);
  color: #321807;
  background:
    linear-gradient(180deg, rgba(255, 241, 196, 0.54), rgba(129, 72, 31, 0.12)),
    rgba(255, 239, 198, 0.28);
  box-shadow: inset 0 1px 0 rgba(255, 246, 215, 0.42);
  font-size: 13px;
  font-weight: 950;
  cursor: pointer;
}

.game-over-action.primary {
  color: #f6deb5;
  background: linear-gradient(180deg, #7a481e, #3a1909);
}

.game-over-action:disabled {
  opacity: 0.58;
  cursor: not-allowed;
}

.game-over-action:hover:not(:disabled) {
  filter: brightness(1.08);
}

.game-over-action svg {
  width: 17px;
  height: 17px;
  fill: currentColor;
  flex: 0 0 auto;
}
</style>
