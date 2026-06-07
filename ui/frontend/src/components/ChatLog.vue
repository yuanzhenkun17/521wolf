<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { displayPhaseLabel } from './history/historyDisplay.js'

const props = defineProps({
  logs: { type: Array, default: () => [] },
  expanded: Boolean,
  activeSeat: { type: [String, Number], default: '' },
  logSpeaker: Function,
  logMessage: Function
})

const emit = defineEmits(['toggle-expand', 'update:expanded'])
const chatListRef = ref(null)
const selectedPhaseKey = ref('latest')
const phaseFallbackLabel = {
  day_speech: '白天发言',
  night_result: '黑夜结果',
  exile_vote: '放逐投票',
  pk_vote: '对决投票',
  pk_speak: '对决发言',
  last_word: '遗言'
}

function phaseKey(log) {
  const day = log?.day ?? 0
  const phase = String(log?.phase || log?.event_phase || log?.stage || 'unknown')
  return `${day}-${phase}`
}

function phaseText(log) {
  const day = log?.day ? `第${log.day}天` : '阶段'
  const phase = String(log?.phase || log?.event_phase || log?.stage || 'unknown')
  return `${day} ${phaseFallbackLabel[phase] || displayPhaseLabel(phase)}`
}

const phaseOptions = computed(() => {
  const options = [{ key: 'latest', label: '最新', count: props.logs.length }]
  const byPhase = new Map()
  props.logs.forEach((log) => {
    const key = phaseKey(log)
    if (!byPhase.has(key)) {
      byPhase.set(key, { key, label: phaseText(log), count: 0 })
    }
    byPhase.get(key).count += 1
  })
  return [...options, ...byPhase.values()]
})
const filteredLogs = computed(() => {
  if (selectedPhaseKey.value === 'latest') return props.logs
  return props.logs.filter((log) => phaseKey(log) === selectedPhaseKey.value)
})

const visibleLogs = computed(() => filteredLogs.value)
const logCountText = computed(() => {
  return `${filteredLogs.value.length} 条`
})

function speaker(log) {
  return log?._speaker || (props.logSpeaker ? props.logSpeaker(log) : (log?.speaker || ''))
}

function message(log) {
  return log?._message || (props.logMessage ? props.logMessage(log) : (log?.message || ''))
}

function seatLabel(log) {
  return log?._seat ? `${log._seat}` : '?'
}

function kindLabel(log) {
  return log?._kindLabel || '记录'
}

function isLinkedSeat(log) {
  return Boolean(props.activeSeat) && String(log?._seat ?? '') === String(props.activeSeat)
}

function isLatestVisible(index) {
  return index === visibleLogs.value.length - 1
}

function logKey(log, index) {
  return log?.sequence || log?.index || log?.id || `${log?.day || 0}-${log?.phase || 'phase'}-${log?.type || log?.event_type || 'log'}-${index}`
}

function toggleExpanded() {
  emit('update:expanded', !props.expanded)
  emit('toggle-expand')
}

function selectPhase(key) {
  selectedPhaseKey.value = key
}

async function scrollToLatest() {
  await nextTick()
  if (!chatListRef.value) return
  chatListRef.value.scrollTop = chatListRef.value.scrollHeight
}

watch(() => phaseOptions.value.map((option) => option.key).join('|'), (keys) => {
  if (!keys.split('|').includes(selectedPhaseKey.value)) {
    selectedPhaseKey.value = 'latest'
  }
})

watch(() => [props.logs.length, props.expanded, selectedPhaseKey.value, filteredLogs.value.length], scrollToLatest, { flush: 'post' })

defineExpose({ chatListRef });
</script>

<template>
  <aside class="chat-log-panel" :class="{ expanded }" aria-label="聊天记录">
    <div class="chat-log-top">
      <div class="chat-log-heading">
        <span>对局记录</span>
        <small>{{ logCountText }}</small>
      </div>
      <div class="chat-log-actions">
        <label class="chat-log-phase-filter" title="选择记录阶段">
          <select
            class="chat-log-phase-select"
            :value="selectedPhaseKey"
            aria-label="选择记录阶段"
            @change="selectPhase($event.target.value)"
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
          <span class="chat-log-seat">{{ seatLabel(log) }}</span>
          <img class="chat-log-avatar" :src="log?._roleIcon || '/role-icons/未知.png'" alt="" />
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
