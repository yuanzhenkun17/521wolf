<script setup>
import { ref } from 'vue'

const props = defineProps({
  logs: { type: Array, default: () => [] },
  expanded: Boolean,
  logSpeaker: Function,
  logMessage: Function
})

const emit = defineEmits(['toggle-expand', 'update:expanded'])
const chatListRef = ref(null)

function speaker(log) {
  return props.logSpeaker ? props.logSpeaker(log) : (log?.speaker || '')
}

function message(log) {
  return props.logMessage ? props.logMessage(log) : (log?.message || '')
}

function toggleExpanded() {
  emit('update:expanded', !props.expanded)
  emit('toggle-expand')
}

defineExpose({ chatListRef });
</script>

<template>
  <aside class="chat-log-panel" :class="{ expanded }" aria-label="聊天记录">
    <div class="chat-log-top">
      <span>聊天记录</span>
      <button class="chat-log-toggle" :title="expanded ? '收起' : '展开'" @click="toggleExpanded">
        <svg viewBox="0 0 24 24">
          <path v-if="!expanded" d="M7 10l5 5 5-5z" />
          <path v-else d="M7 14l5-5 5 5z" />
        </svg>
      </button>
    </div>
    <div class="chat-log-body">
      <div ref="chatListRef" class="chat-log-scroll">
        <p v-for="(log, index) in logs" :key="index" class="chat-log-line">
          <b>{{ speaker(log) }}</b>：{{ message(log) }}
        </p>
      </div>
    </div>
  </aside>
</template>
