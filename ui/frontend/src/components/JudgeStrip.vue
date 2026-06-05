<script setup>
import { ref } from 'vue'

defineProps({
  messages: { type: Array, default: () => [] },
  judgeBoardStarted: Boolean,
  judgeBoardStarting: Boolean
})

const emit = defineEmits(['start'])
const judgeStripRef = ref(null)

defineExpose({ judgeStripRef });
</script>

<template>
  <div class="strip-judge-log" aria-label="法官日志">
    <img class="strip-judge-avatar" src="/livehall-assets/props/judge-avatar.png" alt="法官" />
    <div class="strip-judge-copy" :class="{ 'has-start': !judgeBoardStarted }">
      <div ref="judgeStripRef" class="strip-judge-scroll">
        <p v-for="(line, index) in messages" :key="'judge-strip-' + index">
          {{ line.message }}
        </p>
      </div>
      <button
        v-if="!judgeBoardStarted"
        class="strip-judge-start"
        :class="{ fading: judgeBoardStarting }"
        :disabled="judgeBoardStarting"
        @click="emit('start')"
      >
        开始对局
      </button>
    </div>
  </div>
</template>
