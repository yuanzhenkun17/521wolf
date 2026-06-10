<script setup lang="ts">
import { computed, getCurrentInstance, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useGameStore, useReplayStore, useSessionStore, useUiStore } from '../stores'
import { isReturnableGame } from '../composables/gameSession.ts'
import { appViewFromRouteSource } from '../router/appViews'
import type { ActiveGameSession } from '../types/game'
import type { AppView } from '../types/ui'

type TopNavVariant = 'lobby' | 'match' | 'section'
type NavItemKey = Exclude<AppView, 'match'>
type NavWorkLine = 'play' | 'lab'
type NavItemEmit = 'go-lobby' | 'open-logs' | 'open-benchmark' | 'open-evolution' | 'open-tasks'
type TopNavEmit = NavItemEmit | 'back-to-match' | 'toggle-audio' | 'toggle-tts' | 'exit-game'
type StreamBadgeStatus = 'idle' | 'stopped' | 'polling' | 'reconnecting' | 'live' | 'background'

interface StreamAwareActiveSession {
  gameId?: ActiveGameSession['gameId']
  game_id?: string | null
  mode?: ActiveGameSession['mode']
  running?: unknown
  sseConnected?: unknown
  sse_connected?: unknown
  connected?: unknown
  streamStatus?: unknown
  stream_status?: unknown
  sseStatus?: unknown
  sse_status?: unknown
  connectionStatus?: unknown
  connection_status?: unknown
  polling?: unknown
  pollingFallback?: unknown
  polling_fallback?: unknown
  streamPolling?: unknown
  streamDegraded?: unknown
  stream_degraded?: unknown
  reconnecting?: unknown
  sseReconnecting?: unknown
  sse_reconnecting?: unknown
  streamReconnecting?: unknown
  stream_reconnecting?: unknown
  backgroundRunning?: unknown
  background_running?: unknown
  detached?: unknown
  lastRecoveredAt?: unknown
  last_recovered_at?: unknown
  recoveredAt?: unknown
  recovered_at?: unknown
  lastConnectedAt?: unknown
  last_connected_at?: unknown
}

interface TopNavProps {
  brand?: string
  variant?: TopNavVariant
  activeView?: AppView | string
  activeSession?: StreamAwareActiveSession | null
  hasActiveGame?: boolean
  audioEnabled?: boolean
  ttsEnabled?: boolean
  ttsAvailable?: boolean
  showExitGame?: boolean
  exitDisabled?: boolean
}

interface NavItem {
  key: NavItemKey
  label: string
  line: NavWorkLine
  lineLabel: 'Play' | 'Lab'
  event: NavItemEmit
}

interface StreamStatusBadge {
  status: StreamBadgeStatus
  label: string
  title: string
  ariaLabel: string
}

const props = withDefaults(defineProps<TopNavProps>(), {
  brand: 'NightCouncil',
  variant: 'lobby',
  activeView: 'lobby',
  activeSession: () => ({}),
  hasActiveGame: false,
  showExitGame: false,
  exitDisabled: false
})

const emit = defineEmits(['go-lobby', 'open-logs', 'open-benchmark', 'open-evolution', 'open-tasks', 'back-to-match', 'toggle-audio', 'toggle-tts', 'exit-game'])
const instance = getCurrentInstance()
const route = useRoute()
const sessionStore = useSessionStore()
const gameStore = useGameStore()
const replayStore = useReplayStore()
const uiStore = useUiStore()
const exitConfirming = ref(false)
const topbarCharactersWebp = '/optimized/topbar-characters-320.webp'
const topbarCharactersPng = '/topbar-characters.png'
const judgeAvatarUrl = '/livehall-assets/props/judge-avatar.png'

const navItems = [
  { key: 'lobby', label: '大厅', line: 'play', lineLabel: 'Play', event: 'go-lobby' },
  { key: 'logs', label: '日志', line: 'play', lineLabel: 'Play', event: 'open-logs' },
  { key: 'benchmark', label: '评测', line: 'lab', lineLabel: 'Lab', event: 'open-benchmark' },
  { key: 'evolution', label: '自进化', line: 'lab', lineLabel: 'Lab', event: 'open-evolution' },
  { key: 'tasks', label: '任务', line: 'lab', lineLabel: 'Lab', event: 'open-tasks' }
] as const satisfies readonly NavItem[]

const RECONNECTING_STREAM_STATUSES: ReadonlySet<string> = new Set(['connecting', 'reconnect', 'reconnecting', 'retrying'])
const POLLING_STREAM_STATUSES: ReadonlySet<string> = new Set(['degraded', 'fallback', 'polling', 'polling_fallback', 'long_polling'])
const BACKGROUND_STREAM_STATUSES: ReadonlySet<string> = new Set(['background', 'background_running', 'detached'])
const STOPPED_STREAM_STATUSES: ReadonlySet<string> = new Set(['closed', 'done', 'stopped', 'terminal'])
const TOP_NAV_PROP_ALIASES = {
  activeView: ['activeView', 'active-view'],
  activeSession: ['activeSession', 'active-session'],
  hasActiveGame: ['hasActiveGame', 'has-active-game'],
  showExitGame: ['showExitGame', 'show-exit-game'],
  exitDisabled: ['exitDisabled', 'exit-disabled']
} as const
const UI_PROP_ALIASES = {
  audioEnabled: ['audioEnabled', 'audio-enabled'],
  ttsEnabled: ['ttsEnabled', 'tts-enabled'],
  ttsAvailable: ['ttsAvailable', 'tts-available']
} as const

function hasExplicitAliasProp(aliases: readonly string[]): boolean {
  const rawProps = instance?.vnode.props || {}
  return aliases.some((key) => Object.prototype.hasOwnProperty.call(rawProps, key))
}

function hasExplicitTopNavProp(propName: keyof typeof TOP_NAV_PROP_ALIASES): boolean {
  return hasExplicitAliasProp(TOP_NAV_PROP_ALIASES[propName])
}

function hasExplicitUiProp(propName: keyof typeof UI_PROP_ALIASES): boolean {
  return hasExplicitAliasProp(UI_PROP_ALIASES[propName])
}

function truthy(value: unknown): boolean {
  return value === true || value === 1 || value === '1' || value === 'true'
}

function anyTruthy(...values: unknown[]): boolean {
  return values.some((value) => truthy(value))
}

function normalizedStatus(value: unknown): string {
  return String(value || '').trim().toLowerCase().replace(/[\s-]+/g, '_')
}

function firstValue(...values: unknown[]): unknown {
  return values.find((value) => value !== undefined && value !== null && value !== '')
}

function formatStreamTime(value: unknown): string {
  const raw = firstValue(value)
  if (!raw) return ''
  const date = raw instanceof Date ? raw : new Date(raw as string | number)
  if (Number.isNaN(date.getTime())) return String(raw)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

function navItemAriaLabel(item): string {
  const label = `${item.lineLabel} 工作线：${item.label}`
  return activeNavView.value === item.key ? `${label}，当前页面` : label
}

const routeActiveView = computed(() => appViewFromRouteSource(route))

const storeActiveView = computed(() => sessionStore.currentView || '')
const explicitActiveView = computed(() => hasExplicitTopNavProp('activeView') ? props.activeView : '')
const activeNavView = computed(() => {
  if (routeActiveView.value) return routeActiveView.value
  return explicitActiveView.value || storeActiveView.value || 'lobby'
})

const storeActiveSession = computed<StreamAwareActiveSession>(() => sessionStore.activeSession || {})
const propActiveSession = computed<StreamAwareActiveSession>(() => hasExplicitTopNavProp('activeSession') ? props.activeSession || {} : {})
function hasSessionSignal(session: StreamAwareActiveSession): boolean {
  return Boolean(session?.gameId || session?.game_id || session?.running || session?.mode)
}

const effectiveActiveSession = computed(() => {
  const session = storeActiveSession.value
  if (hasSessionSignal(session)) return session
  return propActiveSession.value
})

const storeHasActiveGame = computed(() => {
  if (replayStore.isReplayMode) return false
  if (props.variant === 'match' || activeNavView.value === 'match') return false
  return sessionStore.returnToMatchAvailable || isReturnableGame(gameStore.liveGame)
})

const propHasActiveGame = computed(() => hasExplicitTopNavProp('hasActiveGame') && Boolean(props.hasActiveGame))
const effectiveHasActiveGame = computed(() => !replayStore.isReplayMode && (propHasActiveGame.value || storeHasActiveGame.value))
const propShowExitGame = computed(() => hasExplicitTopNavProp('showExitGame') && Boolean(props.showExitGame))
const storeShowExitGame = computed(() => activeNavView.value === 'match' && Boolean(gameStore.liveGame))
const effectiveShowExitGame = computed(() => !replayStore.isReplayMode && (propShowExitGame.value || storeShowExitGame.value))
const effectiveExitDisabled = computed(() => hasExplicitTopNavProp('exitDisabled') ? Boolean(props.exitDisabled) : false)

const effectiveAudioEnabled = computed(() => hasExplicitUiProp('audioEnabled') ? props.audioEnabled : uiStore.audioEnabled)
const effectiveTtsEnabled = computed(() => hasExplicitUiProp('ttsEnabled') ? props.ttsEnabled : uiStore.ttsEnabled)
const effectiveTtsAvailable = computed(() => hasExplicitUiProp('ttsAvailable') ? props.ttsAvailable : uiStore.ttsAvailable)

const streamStatusBadge = computed(() => {
  const session = effectiveActiveSession.value
  const running = Boolean(session.running)
  const connected = anyTruthy(session.sseConnected, session.sse_connected, session.connected)
  const explicitStatus = normalizedStatus(firstValue(
    session.streamStatus,
    session.stream_status,
    session.sseStatus,
    session.sse_status,
    session.connectionStatus,
    session.connection_status
  ))
  const polling = POLLING_STREAM_STATUSES.has(explicitStatus)
    || anyTruthy(session.polling, session.pollingFallback, session.polling_fallback, session.streamPolling, session.streamDegraded, session.stream_degraded)
  const reconnecting = RECONNECTING_STREAM_STATUSES.has(explicitStatus)
    || anyTruthy(session.reconnecting, session.sseReconnecting, session.sse_reconnecting, session.streamReconnecting, session.stream_reconnecting)
  const background = BACKGROUND_STREAM_STATUSES.has(explicitStatus)
    || anyTruthy(session.backgroundRunning, session.background_running, session.detached)
  const stopped = STOPPED_STREAM_STATUSES.has(explicitStatus) || !running
  const recoveredAt = formatStreamTime(firstValue(
    session.lastRecoveredAt,
    session.last_recovered_at,
    session.recoveredAt,
    session.recovered_at,
    session.lastConnectedAt,
    session.last_connected_at
  ))

  let status = 'stopped' as StreamBadgeStatus
  let label = '已停止'
  let detail = '实时流已停止'

  if (polling) {
    status = 'polling'
    label = '轮询降级'
    detail = 'SSE 不可用，正在使用轮询降级'
  } else if (reconnecting || (running && !connected && !background)) {
    status = 'reconnecting'
    label = '重连中'
    detail = '实时流中断，正在尝试重连；对局仍在后台运行'
  } else if (connected) {
    status = 'live'
    label = '实时流'
    detail = recoveredAt ? `实时流已连接，最近恢复 ${recoveredAt}` : '实时流已连接'
  } else if (background || running) {
    status = 'background'
    label = '后台运行'
    detail = '未连接实时流，对局仍在后台运行'
  } else if (!session.gameId && !session.game_id) {
    status = 'idle'
    label = '可查看'
    detail = '没有正在运行的实时流'
  }

  return {
    status,
    label,
    title: detail,
    ariaLabel: `返回对局：${label}。${detail}`
  }
})

function clearExitConfirm() {
  exitConfirming.value = false
}

function requestExitGame() {
  if (effectiveExitDisabled.value) return
  exitConfirming.value = true
}

function confirmExitGame() {
  if (effectiveExitDisabled.value) return
  clearExitConfirm()
  emit('exit-game')
}

watch(() => [explicitActiveView.value, props.variant, effectiveShowExitGame.value, effectiveExitDisabled.value, activeNavView.value], clearExitConfirm)
onBeforeUnmount(clearExitConfirm)
</script>

<template>
  <header :class="['topbar', 'topbar--' + variant]">
    <div class="brand">
      <picture class="brand-mark">
        <source type="image/webp" :srcset="topbarCharactersWebp" />
        <img :src="topbarCharactersPng" :alt="brand" decoding="async" />
      </picture>
      <strong>NightCouncil</strong>
    </div>
    <nav v-if="variant !== 'match'" class="primary-nav" aria-label="主导航">
      <button
        v-for="item in navItems"
        :key="item.key"
        type="button"
        class="nav-button"
        :class="{ active: activeNavView === item.key }"
        :data-work-line="item.line"
        :aria-current="activeNavView === item.key ? 'page' : undefined"
        :aria-label="navItemAriaLabel(item)"
        @click="emit(item.event)"
      >
        <span class="nav-line">{{ item.lineLabel }}</span>
        <span class="nav-label">{{ item.label }}</span>
        <span v-if="activeNavView === item.key" class="nav-state">当前</span>
      </button>
    </nav>
    <div v-if="variant === 'match'" class="topbar-actions">
      <button
        class="audio-toggle"
        :class="{ muted: !effectiveAudioEnabled }"
        type="button"
        :title="effectiveAudioEnabled ? '关闭音乐' : '开启音乐'"
        :aria-label="effectiveAudioEnabled ? '关闭音乐' : '开启音乐'"
        @click="emit('toggle-audio')"
      >
        <span class="audio-icon" aria-hidden="true">
          <svg v-if="effectiveAudioEnabled" viewBox="0 0 24 24" role="img">
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
        :class="{ muted: !effectiveTtsEnabled, disabled: !effectiveTtsAvailable }"
        type="button"
        :disabled="!effectiveTtsAvailable"
        :title="!effectiveTtsAvailable ? '发言朗读未配置' : (effectiveTtsEnabled ? '关闭发言朗读' : '开启发言朗读')"
        :aria-label="!effectiveTtsAvailable ? '发言朗读未配置' : (effectiveTtsEnabled ? '关闭发言朗读' : '开启发言朗读')"
        @click="emit('toggle-tts')"
      >
        <span class="audio-icon" aria-hidden="true">
          <svg v-if="effectiveTtsEnabled" viewBox="0 0 24 24" role="img">
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
        v-if="effectiveHasActiveGame"
        class="active-session-pill"
        type="button"
        :title="streamStatusBadge.title"
        :aria-label="streamStatusBadge.ariaLabel"
        @click="emit('back-to-match')"
      >
        <span class="session-dot" :data-stream-status="streamStatusBadge.status"></span>
        <span class="session-copy">
          <b>{{ effectiveActiveSession?.running ? '对局进行中' : '返回对局' }}</b>
          <small
            class="stream-status-badge"
            :data-stream-status="streamStatusBadge.status"
            :title="streamStatusBadge.title"
            :aria-label="streamStatusBadge.ariaLabel"
          >
            {{ streamStatusBadge.label }}
          </small>
        </span>
      </button>
      <button
        v-if="effectiveShowExitGame"
        class="topbar-exit-game"
        type="button"
        :disabled="effectiveExitDisabled"
        title="退出游戏"
        aria-label="退出游戏"
        @click="requestExitGame"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M5 3h9v2H7v14h7v2H5zM15.5 7.5 20 12l-4.5 4.5-1.4-1.4 2.1-2.1H10v-2h6.2l-2.1-2.1z" />
        </svg>
      </button>
    </div>
  </header>

  <Teleport to="body">
    <div
      v-if="exitConfirming"
      class="exit-confirm-backdrop"
      role="presentation"
      @click.self="clearExitConfirm"
    >
      <section
        class="exit-confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="exit-confirm-title"
      >
        <span class="exit-confirm-mark" aria-hidden="true">
          <img :src="judgeAvatarUrl" alt="" />
        </span>
        <div class="exit-confirm-copy">
          <h2 id="exit-confirm-title">是否要退出对局？</h2>
          <p>退出后会停止当前对局并返回大厅。</p>
        </div>
        <div class="exit-confirm-actions">
          <button type="button" class="exit-confirm-secondary" @click="clearExitConfirm">取消</button>
          <button type="button" class="exit-confirm-primary" @click="confirmExitGame">退出</button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.topbar {
  --nav-accent: #ffb4a8;
  --nav-accent-soft: rgba(255, 180, 168, 0.15);
  --nav-fg: #ffe1dc;
  --nav-muted: rgba(255, 225, 220, 0.58);
  --nav-border: rgba(255, 180, 168, 0.16);
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
  font-family: Anton, "Microsoft YaHei", Arial, sans-serif;
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
  font-size: 24px;
  font-style: normal;
  font-weight: 100;
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
  --nav-button-accent: var(--nav-accent);
  position: relative;
  display: inline-grid;
  grid-template-rows: 1fr;
  align-items: center;
  align-content: center;
  justify-content: center;
  gap: 1px;
  min-width: 86px;
  height: 32px;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--nav-muted);
  box-shadow: none;
  font-family: "Microsoft YaHei", Arial, sans-serif;
  font-size: 17px;
  font-weight: 800;
  letter-spacing: 0;
  white-space: nowrap;
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease, transform 0.16s ease;
}

.topbar .primary-nav button[data-work-line="play"] {
  --nav-button-accent: var(--nav-accent);
}

.topbar .primary-nav button[data-work-line="lab"] {
  --nav-button-accent: var(--nav-accent);
}

.topbar .primary-nav button:hover {
  border-color: rgba(255, 240, 185, 0.12);
  background: rgba(255, 255, 255, 0.04);
  color: var(--nav-fg);
  transform: none;
}

.topbar .primary-nav button.active {
  border-color: color-mix(in srgb, var(--nav-button-accent) 36%, transparent);
  background: color-mix(in srgb, var(--nav-button-accent) 16%, transparent);
  color: color-mix(in srgb, var(--nav-button-accent) 84%, #fff 16%);
}

.nav-line,
.nav-label {
  display: block;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-align: center;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-line {
  display: none;
}

.nav-label {
  color: inherit;
  font-size: inherit;
  font-weight: 800;
  line-height: 1;
}

.nav-state {
  display: none;
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
  width: 350px;
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
  position: relative;
  flex: 1 1 0;
  width: 56px;
  min-width: 56px;
  height: 48px;
  padding: 0 8px;
  border: 0;
  border-radius: 0;
  color: var(--nav-accent);
  background: transparent;
  box-shadow: none;
  font-family: "Microsoft YaHei", Arial, sans-serif;
  font-size: 17px;
  font-weight: 800;
  text-shadow: 0 0 12px rgba(255, 180, 168, 0.14);
}

.topbar--lobby .primary-nav button[data-work-line="lab"] {
  color: var(--nav-accent);
  text-shadow: 0 0 12px rgba(255, 180, 168, 0.14);
}

.topbar--lobby .primary-nav button:hover {
  border: 0;
  color: var(--nav-accent);
  background: rgba(255, 180, 168, 0.08);
  box-shadow: none;
  transform: none;
}

.topbar--lobby .primary-nav button[data-work-line="lab"]:hover {
  color: var(--nav-accent);
  background: rgba(255, 180, 168, 0.08);
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
  color: var(--nav-accent);
  text-shadow: 0 0 14px rgba(242, 202, 80, 0.18);
}

.topbar--section .primary-nav button:hover {
  border: 0;
  color: var(--nav-accent);
  background: rgba(242, 202, 80, 0.08);
  box-shadow: none;
  transform: none;
}

.topbar--lobby .primary-nav button.active:hover {
  background: rgba(255, 180, 168, 0.08);
}

.topbar--lobby .primary-nav button[data-work-line="lab"].active:hover {
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

.exit-confirm-backdrop {
  position: fixed;
  inset: 0;
  z-index: 120;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(circle at 50% 44%, rgba(214, 154, 78, 0.18), transparent 32%),
    radial-gradient(circle at 50% 62%, rgba(76, 38, 18, 0.26), transparent 42%),
    rgba(18, 10, 4, 0.58);
  backdrop-filter: blur(5px);
}

.exit-confirm-dialog {
  --exit-wood-bg:
    radial-gradient(ellipse at 22% 18%, rgba(255, 252, 229, 0.72), transparent 38%) padding-box,
    radial-gradient(ellipse at 78% 88%, rgba(181, 116, 48, 0.1), transparent 44%) padding-box,
    linear-gradient(180deg, rgba(246, 222, 166, 0.98), rgba(233, 197, 128, 0.96) 52%, rgba(218, 174, 102, 0.96)) padding-box,
    repeating-linear-gradient(95deg, #5a3319 0 7px, #8a5428 7px 13px, #3f220f 13px 20px) border-box;
  position: relative;
  display: grid;
  grid-template-columns: 78px minmax(0, 1fr);
  gap: 14px 18px;
  width: min(470px, calc(100vw - 40px));
  padding: 22px 26px 22px 22px;
  border: 5px solid transparent;
  border-radius: 0;
  background: var(--exit-wood-bg);
  color: #3f2714;
  box-shadow:
    0 18px 42px rgba(0, 0, 0, 0.46),
    inset 0 0 0 1px rgba(255, 239, 183, 0.54),
    inset 0 0 28px rgba(88, 42, 14, 0.2);
  backdrop-filter: none;
}

.exit-confirm-dialog::before {
  content: "";
  position: absolute;
  inset: 9px 10px;
  z-index: 0;
  display: block;
  border: 1px solid rgba(77, 38, 16, 0.34);
  border-radius: 0;
  pointer-events: none;
  background:
    linear-gradient(90deg, rgba(72, 37, 15, 0.08), transparent 12% 88%, rgba(72, 37, 15, 0.1)),
    repeating-linear-gradient(0deg, rgba(92, 48, 18, 0.035) 0 1px, transparent 1px 7px);
  box-shadow:
    inset 0 0 0 1px rgba(255, 241, 194, 0.42),
    inset 0 0 24px rgba(87, 43, 15, 0.18);
}

.exit-confirm-dialog::after {
  display: none;
}

.exit-confirm-mark {
  position: relative;
  z-index: 1;
  display: grid;
  width: 72px;
  height: 72px;
  place-items: center;
  align-self: center;
  border: 1px solid rgba(77, 38, 16, 0.38);
  border-radius: 0;
  background:
    radial-gradient(ellipse at 28% 18%, rgba(255, 248, 213, 0.58), transparent 42%),
    linear-gradient(180deg, rgba(255, 241, 194, 0.56), rgba(170, 101, 40, 0.18));
  box-shadow:
    inset 0 0 0 1px rgba(255, 241, 194, 0.42),
    inset 0 0 18px rgba(87, 43, 15, 0.16);
  overflow: hidden;
}

.exit-confirm-mark img {
  width: 66px;
  height: 66px;
  object-fit: cover;
  object-position: center 26%;
  border-radius: 0;
  filter: saturate(0.95) contrast(1.04) drop-shadow(0 2px 2px rgba(45, 21, 6, 0.35));
}

.exit-confirm-copy {
  position: relative;
  z-index: 1;
  min-width: 0;
  align-self: center;
}

.exit-confirm-copy h2 {
  margin: 0;
  color: #4b250d;
  font-family: Anton, "Microsoft YaHei", Arial, sans-serif;
  font-size: 28px;
  font-weight: 950;
  line-height: 1.1;
  letter-spacing: 0;
  text-shadow: 0 1px 0 rgba(255, 236, 183, 0.62);
}

.exit-confirm-copy p {
  margin: 9px 0 0;
  color: rgba(75, 37, 13, 0.76);
  font-family: "Microsoft YaHei", Arial, sans-serif;
  font-size: 14px;
  font-weight: 900;
  line-height: 1.55;
}

.exit-confirm-actions {
  position: relative;
  z-index: 1;
  grid-column: 1 / -1;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 4px;
}

.exit-confirm-actions button {
  height: 40px;
  min-width: 92px;
  padding: 0 18px;
  border-radius: 5px;
  font-family: "Microsoft YaHei", Arial, sans-serif;
  font-size: 14px;
  font-weight: 900;
  cursor: pointer;
  transition: border-color 0.16s ease, background 0.16s ease, color 0.16s ease, transform 0.16s ease;
}

.exit-confirm-actions button:hover {
  transform: translateY(-1px);
}

.exit-confirm-secondary {
  border: 1px solid rgba(93, 48, 17, 0.38);
  color: #5b2b10;
  background:
    linear-gradient(180deg, rgba(255, 241, 194, 0.72), rgba(188, 123, 46, 0.22)),
    rgba(233, 197, 128, 0.58);
  box-shadow: inset 0 1px 0 rgba(255, 252, 224, 0.62);
}

.exit-confirm-secondary:hover {
  border-color: rgba(91, 47, 18, 0.62);
  background:
    linear-gradient(180deg, rgba(255, 246, 213, 0.86), rgba(200, 142, 66, 0.28)),
    rgba(233, 197, 128, 0.7);
}

.exit-confirm-primary {
  border: 1px solid #7c321f;
  color: #fff2d0;
  background:
    linear-gradient(180deg, #b75b33, #8f3a23 54%, #6f2918);
  box-shadow:
    0 10px 22px rgba(115, 43, 18, 0.28),
    inset 0 1px 0 rgba(255, 215, 148, 0.38);
  text-shadow: 0 1px 1px rgba(38, 13, 4, 0.48);
}

.exit-confirm-primary:hover {
  border-color: #9d4328;
  background:
    linear-gradient(180deg, #cf7044, #a84429 54%, #78301d);
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

.session-dot[data-stream-status="live"] {
  background: #52d273;
  box-shadow: 0 0 0 3px rgba(82, 210, 115, 0.18), 0 0 14px rgba(82, 210, 115, 0.55);
}

.session-dot[data-stream-status="reconnecting"] {
  background: #f2ca50;
  box-shadow: 0 0 0 3px rgba(242, 202, 80, 0.2), 0 0 14px rgba(242, 202, 80, 0.48);
}

.session-dot[data-stream-status="polling"] {
  background: #62b6cb;
  box-shadow: 0 0 0 3px rgba(98, 182, 203, 0.18), 0 0 14px rgba(98, 182, 203, 0.42);
}

.session-dot[data-stream-status="background"] {
  background: #b89762;
  box-shadow: 0 0 0 3px rgba(184, 151, 98, 0.18);
}

.session-dot[data-stream-status="stopped"],
.session-dot[data-stream-status="idle"] {
  background: #8c7d5b;
  box-shadow: 0 0 0 3px rgba(140, 125, 91, 0.16);
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

.stream-status-badge {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  max-width: 100%;
  min-width: 0;
  overflow: hidden;
  color: inherit;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stream-status-badge[data-stream-status="polling"] {
  color: #9edfeb;
}

.stream-status-badge[data-stream-status="reconnecting"] {
  color: #f5d77a;
}

.stream-status-badge[data-stream-status="background"] {
  color: #d8bd87;
}

.stream-status-badge[data-stream-status="stopped"],
.stream-status-badge[data-stream-status="idle"] {
  color: var(--nav-muted);
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

  .nav-state {
    min-width: 20px;
    padding: 0 4px;
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
    position: relative;
    grid-template-rows: 9px 14px;
    width: auto;
    height: 30px;
    padding: 0 5px;
    font-size: 11px;
  }

  .nav-line {
    font-size: 8px;
  }

  .nav-label {
    font-size: 11px;
  }

  .nav-state {
    top: 4px;
    right: 4px;
    width: 6px;
    min-width: 6px;
    height: 6px;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: var(--nav-button-accent);
    color: transparent;
    font-size: 0;
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
