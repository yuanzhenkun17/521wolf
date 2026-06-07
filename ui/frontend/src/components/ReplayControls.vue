<script setup>
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
  --replay-bg: rgba(255, 246, 220, 0.94);
  --replay-ink: #2f1b0c;
  --replay-muted: rgba(47, 27, 12, 0.62);
  --replay-line: rgba(74, 44, 18, 0.18);
  --replay-accent: #6b3518;
  --replay-track: rgba(74, 44, 18, 0.16);
  display: grid;
  grid-template-rows: auto auto;
  gap: 10px;
  min-width: 0;
  padding: 12px 14px 13px;
  border: 1px solid var(--replay-line);
  border-radius: 8px;
  background:
    radial-gradient(ellipse at 18% 0%, rgba(255, 255, 255, 0.42), transparent 54%),
    var(--replay-bg);
  box-shadow: 0 12px 28px rgba(22, 14, 6, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.38);
  color: var(--replay-ink);
  font-family: "Microsoft YaHei", Arial, sans-serif;
}

.replay-controls.compact {
  position: fixed;
  right: 22px;
  bottom: 22px;
  z-index: 30;
  width: min(680px, calc(100vw - 44px));
  border-color: rgba(92, 51, 18, 0.28);
  box-shadow: 0 22px 56px rgba(0, 0, 0, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.38);
}

.replay-topline,
.replay-timeline {
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
  color: var(--replay-accent);
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
  border: 1px solid var(--replay-line);
  border-radius: 7px;
  background: rgba(255, 255, 250, 0.38);
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
  border: 1px solid transparent;
  border-radius: 6px;
  color: var(--replay-accent);
  background: transparent;
  box-shadow: none;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.replay-icon {
  width: 32px;
  padding: 0;
}

.replay-icon.primary {
  color: #fff4d9;
  background: linear-gradient(180deg, #7c431c, #4b250d);
}

.replay-icon.close {
  color: rgba(74, 44, 18, 0.74);
}

.replay-action {
  min-width: 76px;
  padding: 0 11px;
  border-color: var(--replay-line);
  background: rgba(255, 255, 250, 0.42);
  font-size: 12px;
  font-weight: 900;
  white-space: nowrap;
}

.replay-icon:hover:not(:disabled),
.replay-action:hover:not(:disabled) {
  border-color: rgba(74, 44, 18, 0.26);
  background: rgba(255, 255, 250, 0.6);
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
    linear-gradient(90deg, var(--replay-accent) var(--replay-progress), transparent var(--replay-progress)),
    var(--replay-track);
}

.replay-range::-webkit-slider-thumb {
  appearance: none;
  width: 16px;
  height: 16px;
  margin-top: -5px;
  border: 2px solid #fff5dc;
  border-radius: 50%;
  background: var(--replay-accent);
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
  border: 1px solid var(--replay-line);
  border-radius: 6px;
  background: rgba(255, 255, 250, 0.46);
  color: var(--replay-accent);
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
