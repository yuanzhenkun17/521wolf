<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, type PropType } from 'vue'
import { displayPhaseLabel } from './history/historyDisplay.ts'

type ChatLogEntry = {
  id?: string | number
  index?: string | number
  sequence?: string | number
  day?: string | number
  phase?: string
  event_phase?: string
  stage?: string
  type?: string
  event_type?: string
  speaker?: string
  message?: string
  _speaker?: string
  _message?: string
  _kindLabel?: string
  _seat?: string | number
  _chatKind?: string
  _speaking?: boolean
  _roleIcon?: string
}

type PhaseOption = {
  key: string
  label: string
  count: number
}

const props = defineProps({
  logs: { type: Array as PropType<ChatLogEntry[]>, default: () => [] },
  expanded: Boolean,
  activeSeat: { type: [String, Number], default: '' },
  logSpeaker: Function as PropType<(log: ChatLogEntry) => string>,
  logMessage: Function as PropType<(log: ChatLogEntry) => string>
})

const emit = defineEmits<{
  'toggle-expand': []
  'update:expanded': [value: boolean]
  'compact-height': [height: number]
}>()
const panelRef = ref<HTMLElement | null>(null)
const chatListRef = ref<HTMLElement | null>(null)
const selectedPhaseKey = ref('latest')
const phaseMenuOpen = ref(false)
let compactResizeObserver: ResizeObserver | null = null
const phaseFallbackLabel: Record<string, string> = {
  day_speech: '白天发言',
  night_result: '黑夜结果',
  exile_vote: '放逐投票',
  pk_vote: '对决投票',
  pk_speak: '对决发言',
  last_word: '遗言'
}

function phaseKey(log: ChatLogEntry) {
  const day = log?.day ?? 0
  const phase = String(log?.phase || log?.event_phase || log?.stage || 'unknown')
  return `${day}-${phase}`
}

function phaseText(log: ChatLogEntry) {
  const day = log?.day ? `第${log.day}天` : '阶段'
  const phase = String(log?.phase || log?.event_phase || log?.stage || 'unknown')
  return `${day} ${phaseFallbackLabel[phase] || displayPhaseLabel(phase)}`
}

const phaseOptions = computed(() => {
  const options = [{ key: 'latest', label: '最新', count: props.logs.length }]
  const byPhase = new Map<string, PhaseOption>()
  props.logs.forEach((log) => {
    const key = phaseKey(log)
    if (!byPhase.has(key)) {
      byPhase.set(key, { key, label: phaseText(log), count: 0 })
    }
    const option = byPhase.get(key)
    if (option) option.count += 1
  })
  return [...options, ...byPhase.values()]
})
const selectedPhaseOption = computed(() =>
  phaseOptions.value.find((option) => option.key === selectedPhaseKey.value) || phaseOptions.value[0]
)
const filteredLogs = computed(() => {
  if (selectedPhaseKey.value === 'latest') return props.logs
  return props.logs.filter((log) => phaseKey(log) === selectedPhaseKey.value)
})

const visibleLogs = computed(() => {
  if (props.expanded) return filteredLogs.value
  return filteredLogs.value.slice(-2)
})
function speaker(log: ChatLogEntry) {
  return log?._speaker || (props.logSpeaker ? props.logSpeaker(log) : (log?.speaker || ''))
}

function message(log: ChatLogEntry) {
  return log?._message || (props.logMessage ? props.logMessage(log) : (log?.message || ''))
}

function kindLabel(log: ChatLogEntry) {
  return log?._kindLabel || '记录'
}

function isLinkedSeat(log: ChatLogEntry) {
  return Boolean(props.activeSeat) && String(log?._seat ?? '') === String(props.activeSeat)
}

function isLatestVisible(index: number) {
  return index === visibleLogs.value.length - 1
}

function logKey(log: ChatLogEntry, index: number) {
  return log?.sequence || log?.index || log?.id || `${log?.day || 0}-${log?.phase || 'phase'}-${log?.type || log?.event_type || 'log'}-${index}`
}

function toggleExpanded() {
  emit('update:expanded', !props.expanded)
  emit('toggle-expand')
}

function selectPhase(key: string) {
  selectedPhaseKey.value = key
  phaseMenuOpen.value = false
}

function selectPhaseFromEvent(event: Event) {
  selectPhase((event.target as HTMLSelectElement | null)?.value || 'latest')
}

async function scrollToLatest() {
  await nextTick()
  if (!chatListRef.value) return
  chatListRef.value.scrollTop = chatListRef.value.scrollHeight
  reportCompactHeight()
}

async function reportCompactHeight() {
  if (props.expanded) return
  await nextTick()
  const height = Math.ceil(panelRef.value?.getBoundingClientRect?.().height || 0)
  if (height > 0) emit('compact-height', height)
}

watch(() => phaseOptions.value.map((option) => option.key).join('|'), (keys) => {
  if (!keys.split('|').includes(selectedPhaseKey.value)) {
    selectedPhaseKey.value = 'latest'
  }
})

watch(() => [props.logs.length, props.expanded, selectedPhaseKey.value, filteredLogs.value.length], scrollToLatest, { flush: 'post' })

onMounted(() => {
  compactResizeObserver = new ResizeObserver(reportCompactHeight)
  if (panelRef.value) compactResizeObserver.observe(panelRef.value)
  reportCompactHeight()
})

onBeforeUnmount(() => compactResizeObserver?.disconnect())

defineExpose({ chatListRef });
</script>

<template>
  <aside ref="panelRef" class="chat-log-panel" :class="{ expanded }" aria-label="聊天记录">
    <div class="chat-log-top">
      <div class="chat-log-heading">
        <span>对局记录</span>
      </div>
      <div class="chat-log-actions">
        <div class="chat-log-phase-picker">
          <button
            class="chat-log-phase-button"
            type="button"
            :aria-expanded="phaseMenuOpen"
            aria-label="选择记录阶段"
            @click="phaseMenuOpen = !phaseMenuOpen"
          >
            <span>{{ selectedPhaseOption.label }} · {{ selectedPhaseOption.count }}</span>
            <svg viewBox="0 0 24 24"><path d="M7 10l5 5 5-5z" /></svg>
          </button>
          <div v-if="phaseMenuOpen" class="chat-log-phase-menu" role="menu">
            <button
              v-for="option in phaseOptions"
              :key="option.key"
              type="button"
              class="chat-log-phase-option"
              :class="{ active: option.key === selectedPhaseKey }"
              @click="selectPhase(option.key)"
            >
              <span>{{ option.label }}</span>
              <small>{{ option.count }}</small>
            </button>
          </div>
        </div>
        <label class="chat-log-phase-filter" title="选择记录阶段">
          <select
            class="chat-log-phase-select"
            :value="selectedPhaseKey"
            aria-label="选择记录阶段"
            @change="selectPhaseFromEvent"
          >
            <option v-for="option in phaseOptions" :key="option.key" :value="option.key">
              {{ option.label }} · {{ option.count }}
            </option>
          </select>
        </label>
        <button class="chat-log-toggle" :title="expanded ? '收起' : '展开'" @click="toggleExpanded">
          <svg viewBox="0 0 24 24">
            <path v-if="!expanded" d="M7 10l5 5 5-5z" />
            <path v-else d="M7 14l5-5 5 5z" />
          </svg>
        </button>
      </div>
    </div>
    <div class="chat-log-body">
      <div ref="chatListRef" class="chat-log-scroll">
        <article
          v-for="(log, index) in visibleLogs"
          :key="logKey(log, index)"
          class="chat-log-line"
          :class="[`kind-${log?._chatKind || 'action'}`, { speaking: log?._speaking, linked: isLinkedSeat(log), latest: isLatestVisible(index) }]"
        >
          <img
            class="chat-log-avatar"
            :class="{ judge: String(log?._roleIcon || '').includes('judge-avatar') }"
            :src="log?._roleIcon || '/role-icons/optimized/未知.webp'"
            alt=""
          />
          <div class="chat-log-content">
            <div class="chat-log-meta">
              <b>{{ speaker(log) }}</b>
              <em>{{ kindLabel(log) }}</em>
            </div>
            <p>{{ message(log) }}</p>
          </div>
        </article>
      </div>
    </div>
  </aside>
</template>
