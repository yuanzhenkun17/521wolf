<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  brand: { type: String, default: 'NightCouncil' },
  variant: { type: String, default: 'lobby' },
  activeView: { type: String, default: 'lobby' },
  activeSession: { type: Object, default: () => ({}) },
  hasActiveGame: Boolean,
  audioEnabled: Boolean,
  ttsEnabled: Boolean,
  ttsAvailable: { type: Boolean, default: true },
  showExitGame: Boolean,
  exitDisabled: Boolean
})

const emit = defineEmits(['go-lobby', 'open-logs', 'open-benchmark', 'open-evolution', 'back-to-match', 'toggle-audio', 'toggle-tts', 'exit-game'])
const exitConfirming = ref(false)
let exitConfirmTimer = 0

const navItems = [
  { key: 'lobby', label: '大厅', event: 'go-lobby' },
  { key: 'logs', label: '日志', event: 'open-logs' },
  { key: 'benchmark', label: '评测', event: 'open-benchmark' },
  { key: 'evolution', label: '自进化', event: 'open-evolution' }
]

function clearExitConfirm() {
  if (exitConfirmTimer) {
    window.clearTimeout(exitConfirmTimer)
    exitConfirmTimer = 0
  }
  exitConfirming.value = false
}

function requestExitGame() {
  if (props.exitDisabled) return
  if (exitConfirming.value) {
    clearExitConfirm()
    emit('exit-game')
    return
  }
  exitConfirming.value = true
  exitConfirmTimer = window.setTimeout(clearExitConfirm, 1800)
}

watch(() => [props.activeView, props.variant, props.showExitGame], clearExitConfirm)
onBeforeUnmount(clearExitConfirm)
</script>

<template>
  <header :class="['topbar', 'topbar--' + variant]">
    <div class="brand">
      <picture class="brand-mark">
        <source type="image/webp" srcset="/optimized/topbar-characters-320.webp" />
        <img src="/topbar-characters.png" :alt="brand" decoding="async" />
      </picture>
      <strong>NightCouncil</strong>
    </div>
    <nav v-if="variant !== 'match'" class="primary-nav" aria-label="主导航">
      <button
        v-for="item in navItems"
        :key="item.key"
        type="button"
        :class="{ active: activeView === item.key }"
        @click="emit(item.event)"
      >
        {{ item.label }}
      </button>
    </nav>
    <div v-if="variant === 'match'" class="topbar-actions">
      <button
        class="audio-toggle"
        :class="{ muted: !audioEnabled }"
        type="button"
        :title="audioEnabled ? '关闭音乐' : '开启音乐'"
        :aria-label="audioEnabled ? '关闭音乐' : '开启音乐'"
        @click="emit('toggle-audio')"
      >
        <span class="audio-icon" aria-hidden="true">
          <svg v-if="audioEnabled" viewBox="0 0 24 24" role="img">
            <path d="M4 9.5h3.7L13 5.2v13.6l-5.3-4.3H4z" />
            <path d="M16.2 8.1c1.4 1.4 1.4 5.4 0 6.8" />
            <path d="M18.7 5.8c2.9 3.1 2.9 10.3 0 12.4" />
          </svg>
          <svg v-else viewBox="0 0 24 24" role="img">
            <path d="M4 9.5h3.7L13 5.2v13.6l-5.3-4.3H4z" />
            <path d="M17 9l5 5" />
            <path d="M22 9l-5 5" />
          </svg>
        </span>
      </button>
      <button
        class="audio-toggle voice-toggle"
        :class="{ muted: !ttsEnabled, disabled: !ttsAvailable }"
        type="button"
        :disabled="!ttsAvailable"
        :title="!ttsAvailable ? '发言朗读未配置' : (ttsEnabled ? '关闭发言朗读' : '开启发言朗读')"
        :aria-label="!ttsAvailable ? '发言朗读未配置' : (ttsEnabled ? '关闭发言朗读' : '开启发言朗读')"
        @click="emit('toggle-tts')"
      >
        <span class="audio-icon" aria-hidden="true">
          <svg v-if="ttsEnabled" viewBox="0 0 24 24" role="img">
            <path d="M7 9.5a5 5 0 0 1 10 0v2a5 5 0 0 1-10 0z" />
            <path d="M12 16.5v3" />
            <path d="M9.5 20h5" />
            <path d="M5 11.5c0 4 3 6.5 7 6.5s7-2.5 7-6.5" />
          </svg>
          <svg v-else viewBox="0 0 24 24" role="img">
            <path d="M7 9.5a5 5 0 0 1 10 0v2a5 5 0 0 1-10 0z" />
            <path d="M12 16.5v3" />
            <path d="M9.5 20h5" />
            <path d="M4 4l18 18" />
          </svg>
        </span>
      </button>
      <button
        v-if="hasActiveGame"
        class="active-session-pill"
        type="button"
        @click="emit('back-to-match')"
      >
        <span class="session-dot" :class="{ live: activeSession?.sseConnected }"></span>
        <span class="session-copy">
          <b>{{ activeSession?.running ? '对局进行中' : '返回对局' }}</b>
          <small>{{ activeSession?.sseConnected ? '实时流' : (activeSession?.running ? '后台运行' : '可查看') }}</small>
        </span>
      </button>
      <button
        v-if="showExitGame"
        class="topbar-exit-game"
        :class="{ confirming: exitConfirming }"
        type="button"
        :disabled="exitDisabled"
        :title="exitConfirming ? '再次点击确认退出游戏' : '退出游戏'"
        :aria-label="exitConfirming ? '再次点击确认退出游戏' : '退出游戏'"
        @click="requestExitGame"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M5 3h9v2H7v14h7v2H5zM15.5 7.5 20 12l-4.5 4.5-1.4-1.4 2.1-2.1H10v-2h6.2l-2.1-2.1z" />
        </svg>
      </button>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  --nav-accent: #f2ca50;
  --nav-accent-soft: rgba(242, 202, 80, 0.15);
  --nav-fg: #f6ead2;
  --nav-muted: rgba(246, 234, 210, 0.58);
  --nav-border: rgba(246, 214, 142, 0.16);
  --nav-panel: rgba(12, 10, 8, 0.68);
  position: fixed;
  top: 0;
  right: 0;
  left: 0;
  z-index: 50;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  gap: 16px;
  height: 72px;
  padding: 0 clamp(16px, 2.6vw, 32px);
  border-bottom: 1px solid var(--nav-border);
  background:
    linear-gradient(90deg, rgba(0, 0, 0, 0.46), transparent 22% 78%, rgba(0, 0, 0, 0.32)),
    rgba(16, 13, 9, 0.8);
  box-shadow: 0 12px 34px rgba(0, 0, 0, 0.26), inset 0 -1px 0 rgba(255, 241, 192, 0.04);
  backdrop-filter: blur(18px);
  color: var(--nav-fg);
  font-family: "Microsoft YaHei", Arial, sans-serif;
  user-select: none;
}

.topbar .brand {
  justify-self: start;
  display: flex;
  align-items: center;
  gap: 12px;
  height: auto;
  width: max-content;
  max-width: 100%;
  min-width: 0;
  margin: 0 0 0 -16px;
}

.topbar .brand .brand-mark {
  display: block;
  height: 62px;
  line-height: 0;
}

.topbar .brand img {
  display: block;
  width: auto;
  height: 100%;
  object-fit: contain;
  border-radius: 0;
  background: transparent;
  filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.4));
  pointer-events: none;
}

.brand-copy {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 1px;
  height: 58px;
  min-width: 0;
  padding-top: 1px;
}

.topbar .brand strong {
  display: block;
  margin: 0px 0px 0px 0px;
  font-family: Anton, "Microsoft YaHei", Arial, sans-serif;
  color: var(--nav-accent);
  font-size: 26px;
  font-style: normal;
  font-weight: 400;
  line-height: 1;
  letter-spacing: 0;
  white-space: nowrap;
  text-shadow: 0 0 12px rgba(255, 180, 168, 0.14);
}

.brand-copy span {
  display: block;
  margin: 0;
  overflow: hidden;
  color: var(--nav-muted);
  font-size: 11px;
  font-weight: 700;
  line-height: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topbar .primary-nav {
  position: static;
  justify-self: center;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  min-width: 0;
  width: auto;
  height: 40px;
  padding: 3px;
  border: 1px solid var(--nav-border);
  border-radius: 8px;
  background: var(--nav-panel);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.025);
}

.topbar .primary-nav button {
  position: static;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 72px;
  height: 32px;
  padding: 0 13px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--nav-muted);
  box-shadow: none;
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0;
  white-space: nowrap;
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease, transform 0.16s ease;
}

.topbar .primary-nav button:hover {
  border-color: rgba(255, 240, 185, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: var(--nav-fg);
  transform: none;
}

.topbar .primary-nav button.active {
  border-color: color-mix(in srgb, var(--nav-accent) 36%, transparent);
  background: color-mix(in srgb, var(--nav-accent) 16%, transparent);
  color: color-mix(in srgb, var(--nav-accent) 84%, #fff 16%);
}

/* ---- lobby variant ---- */
.topbar--lobby {
  --nav-accent: var(--lobby-accent, #ffb4a8);
  --nav-accent-soft: rgba(255, 180, 168, 0.16);
  --nav-border: rgba(255, 204, 160, 0.13);
  --nav-panel: rgba(18, 13, 9, 0.56);
  grid-template-columns: minmax(0, 1fr) auto;
  background:
    linear-gradient(90deg, rgba(0, 0, 0, 0.28), transparent 24% 76%, rgba(0, 0, 0, 0.2)),
    rgba(16, 12, 7, 0.42);
}

.topbar--lobby .primary-nav,
.topbar--section .primary-nav {
  position: absolute;
  right: 8px;
  justify-self: auto;
  width: 344px;
  height: 48px;
  gap: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.topbar--lobby .primary-nav button,
.topbar--section .primary-nav button {
  flex: 1 1 0;
  width: auto;
  min-width: 0;
  height: 48px;
  padding: 0;
  border: 0;
  border-radius: 0;
  color: var(--nav-accent);
  background: transparent;
  box-shadow: none;
  text-shadow: 0 0 12px rgba(255, 180, 168, 0.14);
}

.topbar--lobby .primary-nav button:hover {
  border: 0;
  color: var(--nav-accent);
  background: rgba(255, 180, 168, 0.08);
  box-shadow: none;
  transform: none;
}

.topbar--lobby .primary-nav button.active,
.topbar--section .primary-nav button.active {
  border: 0;
  color: var(--nav-accent);
  background: transparent;
  box-shadow: none;
  transform: none;
}

.topbar--section {
  --nav-accent: #f2ca50;
  --nav-accent-soft: rgba(242, 202, 80, 0.16);
  --nav-border: rgba(242, 202, 80, 0.14);
  --nav-panel: transparent;
  grid-template-columns: minmax(0, 1fr) auto;
}

.topbar--section .primary-nav button {
  color: #f2ca50;
  text-shadow: 0 0 14px rgba(242, 202, 80, 0.18);
}

.topbar--section .primary-nav button:hover {
  border: 0;
  color: #f2ca50;
  background: rgba(242, 202, 80, 0.08);
  box-shadow: none;
  transform: none;
}

.topbar--lobby .primary-nav button.active:hover {
  background: rgba(255, 180, 168, 0.08);
}

.topbar--section .primary-nav button.active:hover {
  background: rgba(242, 202, 80, 0.08);
}

/* ---- match variant ---- */
.topbar--match {
  --nav-accent: #f2ca50;
  --nav-accent-soft: rgba(242, 202, 80, 0.16);
  --nav-fg: #f6ead2;
  --nav-muted: rgba(246, 234, 210, 0.58);
  --nav-border: rgba(246, 214, 142, 0.16);
  --nav-panel: rgba(12, 10, 8, 0.68);
}

/* ---- match variant night-mode ---- */
.topbar--match.night-mode {
  --nav-accent: #f2ca50;
  --nav-accent-soft: rgba(242, 202, 80, 0.16);
  --nav-border: rgba(246, 214, 142, 0.16);
  --nav-panel: rgba(12, 10, 8, 0.68);
  background:
    linear-gradient(90deg, rgba(0, 0, 0, 0.46), transparent 22% 78%, rgba(0, 0, 0, 0.32)),
    rgba(16, 13, 9, 0.8);
}

.topbar-actions {
  position: absolute;
  right: clamp(16px, 2.6vw, 32px);
  justify-self: end;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}

.audio-toggle {
  flex: 0 0 auto;
  display: inline-grid;
  width: 42px;
  min-width: 42px;
  height: 42px;
  place-items: center;
  padding: 0;
  border: 1px solid color-mix(in srgb, var(--nav-accent) 28%, transparent);
  border-radius: 8px;
  color: var(--nav-accent);
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--nav-accent) 11%, transparent), rgba(0, 0, 0, 0.14)),
    rgba(0, 0, 0, 0.18);
  cursor: pointer;
  transition: border-color 0.16s ease, background 0.16s ease, color 0.16s ease;
}

.audio-toggle:hover {
  border-color: color-mix(in srgb, var(--nav-accent) 50%, transparent);
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--nav-accent) 17%, transparent), rgba(0, 0, 0, 0.12)),
    rgba(0, 0, 0, 0.2);
}

.audio-toggle.muted {
  color: var(--nav-muted);
  border-color: rgba(255, 255, 255, 0.1);
  background: rgba(0, 0, 0, 0.18);
}

.audio-toggle.disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.audio-toggle.disabled:hover {
  border-color: rgba(255, 255, 255, 0.1);
  background: rgba(0, 0, 0, 0.18);
}

.topbar-actions .topbar-exit-game {
  flex: 0 0 auto;
  display: inline-grid;
  width: 42px;
  min-width: 42px;
  height: 42px;
  place-items: center;
  padding: 0;
  border: 1px solid rgba(255, 138, 108, 0.28);
  border-radius: 8px;
  color: #ff8a6c;
  background:
    linear-gradient(180deg, rgba(255, 138, 108, 0.1), rgba(0, 0, 0, 0.14)),
    rgba(0, 0, 0, 0.18);
  cursor: pointer;
  animation: none;
  filter: none;
  transform: none;
  transition: border-color 0.16s ease, background 0.16s ease, color 0.16s ease;
}

.topbar-actions .topbar-exit-game:hover:not(:disabled) {
  border-color: rgba(255, 138, 108, 0.54);
  color: #ffd0c3;
  background:
    linear-gradient(180deg, rgba(255, 138, 108, 0.16), rgba(0, 0, 0, 0.12)),
    rgba(0, 0, 0, 0.2);
  filter: none;
  transform: none;
}

.topbar-actions .topbar-exit-game.confirming {
  color: #ffd0c3;
  border-color: rgba(255, 91, 64, 0.5);
  background: rgba(255, 91, 64, 0.16);
  box-shadow: inset 0 0 0 1px rgba(255, 91, 64, 0.22);
  animation: none;
  filter: none;
  transform: none;
}

.topbar-actions .topbar-exit-game:disabled {
  cursor: not-allowed;
  opacity: 0.52;
}

.topbar-actions .topbar-exit-game svg {
  width: 20px;
  height: 20px;
  fill: currentColor;
}

.audio-icon {
  display: inline-grid;
  width: 26px;
  height: 26px;
  place-items: center;
  border-radius: 50%;
  background: color-mix(in srgb, currentColor 18%, transparent);
}

.audio-icon svg {
  width: 17px;
  height: 17px;
  overflow: visible;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2;
}

.active-session-pill {
  position: relative;
  z-index: 2;
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 9px;
  width: auto;
  min-width: 146px;
  max-width: 178px;
  height: 42px;
  padding: 0 13px;
  border: 1px solid color-mix(in srgb, var(--nav-accent) 34%, transparent);
  border-radius: 8px;
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--nav-accent) 14%, transparent), rgba(0, 0, 0, 0.14)),
    rgba(0, 0, 0, 0.22);
  color: var(--nav-accent);
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.04);
  cursor: pointer;
  overflow: hidden;
  transition: border-color 0.16s ease, background 0.16s ease, transform 0.16s ease;
}

.active-session-pill:hover {
  border-color: color-mix(in srgb, var(--nav-accent) 58%, transparent);
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--nav-accent) 20%, transparent), rgba(0, 0, 0, 0.1)),
    rgba(0, 0, 0, 0.24);
  transform: translateY(-1px);
}

.session-dot {
  flex: 0 0 auto;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #8c7d5b;
  box-shadow: 0 0 0 3px rgba(140, 125, 91, 0.18);
}

.session-dot.live {
  background: #52d273;
  box-shadow: 0 0 0 3px rgba(82, 210, 115, 0.18), 0 0 14px rgba(82, 210, 115, 0.55);
}

.session-copy {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.session-copy b,
.session-copy small {
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-copy b {
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
}

.session-copy small {
  opacity: 0.78;
  font-size: 10px;
  font-weight: 800;
  line-height: 1;
}

@media (max-width: 980px) {
  .topbar {
    grid-template-columns: auto minmax(0, 1fr) auto;
    gap: 10px;
    padding: 0 12px;
  }

  .brand-copy span {
    display: none;
  }

  .topbar .primary-nav {
    justify-self: stretch;
  }

  .topbar .primary-nav button {
    flex: 1 1 0;
    min-width: 0;
    padding: 0 8px;
  }

  .audio-toggle {
    width: 40px;
    min-width: 40px;
    height: 40px;
  }
}

@media (max-width: 760px) {
  .topbar {
    grid-template-columns: auto minmax(0, 1fr) auto;
    height: 64px;
    padding: 0 8px;
    gap: 7px;
  }

  .topbar .brand .brand-mark {
    height: 38px;
  }

  .topbar .brand strong {
    display: none;
  }

  .topbar .primary-nav {
    position: static;
    display: flex;
    width: auto;
    height: 36px;
    min-width: 0;
    gap: 2px;
    padding: 2px;
  }

  .topbar .primary-nav button {
    position: static;
    width: auto;
    height: 30px;
    padding: 0 5px;
    font-size: 11px;
  }

  .topbar-actions {
    gap: 4px;
  }

  .audio-toggle {
    width: 36px;
    min-width: 36px;
    height: 36px;
  }

  .audio-icon {
    width: 24px;
    height: 24px;
  }

  .audio-icon svg {
    width: 15px;
    height: 15px;
  }

  .active-session-pill {
    min-width: 38px;
    width: 38px;
    height: 38px;
    padding: 0;
    justify-content: center;
    gap: 0;
  }

  .session-copy {
    display: none;
  }
}
</style>
