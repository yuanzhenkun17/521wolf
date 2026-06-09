<script setup lang="ts">
// @ts-nocheck
import { computed } from 'vue'

const props = defineProps({
  isReplayMode: Boolean,
  cursor: { type: Number, default: 0 },
  total: { type: Number, default: 0 },
  playing: Boolean,
  speed: { type: Number, default: 1 },
  eventLabel: { type: String, default: '' },
  compact: Boolean
})

const emit = defineEmits(['return-to-history', 'exit-replay', 'play', 'pause', 'step', 'seek', 'speed'])

const speeds = [0.5, 1, 2, 4]
const progressStyle = computed(() => {
  const total = Math.max(Number(props.total) || 0, 0)
  const cursor = Math.min(Math.max(Number(props.cursor) || 0, 0), total)
  const progress = total > 0 ? (cursor / total) * 100 : 0
  return { '--replay-progress': `${progress}%` }
})
</script>

<template>
  <section v-if="isReplayMode" :class="['replay-controls', { compact }]" :style="progressStyle" aria-label="回放控制">
    <div class="replay-topline">
      <div class="replay-meta">
        <strong>事件 {{ cursor }} / {{ total }}</strong>
        <span :title="eventLabel">{{ eventLabel || '准备回放' }}</span>
      </div>

      <div class="replay-transport">
        <button class="replay-icon" title="上一事件" :disabled="cursor <= 0" @click="emit('step', -1)">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 6v12L3 12l8-6Zm2 0h2v12h-2zM17 6h2v12h-2z" /></svg>
        </button>
        <button class="replay-icon primary" :title="playing ? '暂停' : '播放'" :disabled="total <= 0" @click="playing ? emit('pause') : emit('play')">
          <svg v-if="playing" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h4v14H7zM13 5h4v14h-4z" /></svg>
          <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z" /></svg>
        </button>
        <button class="replay-icon" title="下一事件" :disabled="cursor >= total" @click="emit('step', 1)">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 6v12l8-6-8-6Zm10 0h2v12h-2zM19 6h2v12h-2z" /></svg>
        </button>
      </div>

      <div class="replay-actions">
        <button class="replay-action" title="返回日志" @click="emit('return-to-history')">返回日志</button>
        <button class="replay-icon close" title="退出回放" @click="emit('exit-replay')">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.4 5 5 6.4l5.6 5.6L5 17.6 6.4 19l5.6-5.6 5.6 5.6 1.4-1.4-5.6-5.6L19 6.4 17.6 5 12 10.6z" /></svg>
        </button>
      </div>
    </div>

    <div class="replay-timeline">
      <input
        class="replay-range"
        type="range"
        min="0"
        :max="Math.max(total, 0)"
        :value="cursor"
        :disabled="total <= 0"
        @input="emit('seek', Number($event.target.value))"
      />

      <div class="replay-speed" aria-label="倍速">
        <button
          v-for="item in speeds"
          :key="item"
          type="button"
          :class="{ active: Number(speed) === item }"
          @click="emit('speed', item)"
        >
          {{ item }}x
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.replay-controls {
  --replay-ink: #321807;
  --replay-muted: rgba(75, 37, 13, 0.68);
  --replay-line: rgba(77, 38, 16, 0.34);
  --replay-accent: #6b3518;
  --replay-track: rgba(91, 47, 18, 0.18);
  --replay-wood-bg:
    radial-gradient(ellipse at 22% 18%, rgba(255, 252, 229, 0.72), transparent 38%) padding-box,
    radial-gradient(ellipse at 78% 88%, rgba(181, 116, 48, 0.1), transparent 44%) padding-box,
    linear-gradient(180deg, rgba(246, 222, 166, 0.98), rgba(233, 197, 128, 0.96) 52%, rgba(218, 174, 102, 0.96)) padding-box,
    repeating-linear-gradient(95deg, #5a3319 0 7px, #8a5428 7px 13px, #3f220f 13px 20px) border-box;
  position: relative;
  display: grid;
  grid-template-rows: auto auto;
  gap: 10px;
  min-width: 0;
  padding: 15px 18px 16px;
  border: 5px solid transparent;
  border-radius: 0;
  background: var(--replay-wood-bg);
  box-shadow:
    0 14px 30px rgba(0, 0, 0, 0.42),
    inset 0 0 0 1px rgba(255, 239, 183, 0.54),
    inset 0 0 28px rgba(88, 42, 14, 0.2);
  color: var(--replay-ink);
  font-family: "Microsoft YaHei", Arial, sans-serif;
}

.replay-controls::before {
  content: "";
  position: absolute;
  inset: 9px 10px;
  z-index: 0;
  border: 1px solid var(--replay-line);
  background:
    linear-gradient(90deg, rgba(72, 37, 15, 0.08), transparent 12% 88%, rgba(72, 37, 15, 0.1)),
    repeating-linear-gradient(0deg, rgba(92, 48, 18, 0.035) 0 1px, transparent 1px 7px);
  box-shadow:
    inset 0 0 0 1px rgba(255, 241, 194, 0.42),
    inset 0 0 24px rgba(87, 43, 15, 0.18);
  pointer-events: none;
}

.replay-controls.compact {
  position: fixed;
  right: 22px;
  bottom: 22px;
  z-index: 30;
  width: min(680px, calc(100vw - 44px));
  box-shadow:
    0 22px 56px rgba(0, 0, 0, 0.38),
    inset 0 0 0 1px rgba(255, 239, 183, 0.54),
    inset 0 0 28px rgba(88, 42, 14, 0.2);
}

.replay-topline,
.replay-timeline {
  position: relative;
  z-index: 1;
  display: grid;
  align-items: center;
  min-width: 0;
}

.replay-topline {
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 14px;
}

.replay-timeline {
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
}

.replay-meta {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.replay-meta strong {
  font-size: 12px;
  font-weight: 1000;
  line-height: 1;
  color: #5b2f12;
  white-space: nowrap;
}

.replay-meta span {
  overflow: hidden;
  color: var(--replay-ink);
  font-size: 13px;
  font-weight: 800;
  line-height: 1.28;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.replay-transport,
.replay-actions,
.replay-speed {
  display: flex;
  align-items: center;
  gap: 6px;
}

.replay-transport {
  padding: 2px;
  border: 1px solid rgba(93, 48, 17, 0.24);
  border-radius: 6px;
  background: rgba(255, 239, 194, 0.42);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.46);
}

.replay-actions {
  justify-content: flex-end;
}

.replay-icon,
.replay-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 32px;
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-radius: 6px;
  color: #4b250d;
  background: rgba(255, 239, 194, 0.36);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.58);
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease, box-shadow 0.15s ease;
}

.replay-icon {
  width: 32px;
  padding: 0;
}

.replay-icon.primary {
  color: #fff4d9;
  border-color: rgba(74, 37, 13, 0.82);
  background: linear-gradient(180deg, #7c431c, #4b250d);
  box-shadow: 0 2px 6px rgba(74, 37, 13, 0.22), inset 0 1px 0 rgba(255, 226, 164, 0.24);
}

.replay-icon.close {
  color: rgba(74, 44, 18, 0.74);
}

.replay-action {
  min-width: 76px;
  padding: 0 11px;
  border-color: var(--replay-line);
  background: rgba(255, 239, 194, 0.42);
  font-size: 12px;
  font-weight: 900;
  white-space: nowrap;
}

.replay-icon:hover:not(:disabled),
.replay-action:hover:not(:disabled) {
  border-color: rgba(93, 48, 17, 0.34);
  background: rgba(255, 245, 214, 0.7);
  color: #4b250d;
}

.replay-icon.primary:hover:not(:disabled) {
  color: #fff8e8;
  background: linear-gradient(180deg, #8c4c20, #552a0f);
}

.replay-icon svg {
  width: 19px;
  height: 19px;
  fill: currentColor;
}

.replay-range {
  appearance: none;
  width: 100%;
  height: 18px;
  min-width: 120px;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.replay-range::-webkit-slider-runnable-track {
  height: 6px;
  border-radius: 999px;
  background:
    linear-gradient(90deg, #6b3518 var(--replay-progress), transparent var(--replay-progress)),
    var(--replay-track);
}

.replay-range::-webkit-slider-thumb {
  appearance: none;
  width: 16px;
  height: 16px;
  margin-top: -5px;
  border: 2px solid #fff5dc;
  border-radius: 50%;
  background: #6b3518;
  box-shadow: 0 2px 8px rgba(47, 27, 12, 0.24);
}

.replay-range::-moz-range-track {
  height: 6px;
  border-radius: 999px;
  background: var(--replay-track);
}

.replay-range::-moz-range-progress {
  height: 6px;
  border-radius: 999px;
  background: var(--replay-accent);
}

.replay-range::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border: 2px solid #fff5dc;
  border-radius: 50%;
  background: var(--replay-accent);
  box-shadow: 0 2px 8px rgba(47, 27, 12, 0.24);
}

.replay-speed button {
  height: 30px;
  min-width: 36px;
  padding: 0 8px;
  border: 1px solid rgba(93, 48, 17, 0.22);
  border-radius: 6px;
  background: rgba(255, 239, 194, 0.42);
  color: #4b250d;
  font-size: 11px;
  font-weight: 900;
  cursor: pointer;
  white-space: nowrap;
}

.replay-speed button.active {
  border-color: #4b250d;
  background: #4b250d;
  color: #fff4d9;
}

button:disabled {
  cursor: default;
  opacity: 0.38;
}

@media (max-width: 900px) {
  .replay-controls,
  .replay-controls.compact {
    width: auto;
  }

  .replay-topline {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .replay-actions {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }
}

@media (max-width: 640px) {
  .replay-controls {
    gap: 8px;
    padding: 10px;
  }

  .replay-timeline {
    grid-template-columns: 1fr;
  }

  .replay-topline {
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 8px;
  }

  .replay-transport {
    justify-content: flex-end;
  }

  .replay-speed {
    justify-content: center;
  }

  .replay-actions {
    grid-column: 1 / -1;
    justify-content: center;
  }

  .replay-icon,
  .replay-action {
    height: 30px;
  }

  .replay-icon {
    width: 30px;
  }

  .replay-action {
    min-width: 86px;
  }
}
</style>
