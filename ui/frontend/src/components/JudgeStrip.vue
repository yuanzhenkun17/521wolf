<script setup lang="ts">
import { ref } from 'vue'

interface JudgeStripMessage {
  message: string
}

withDefaults(defineProps<{
  messages?: JudgeStripMessage[]
  judgeBoardStarted?: boolean
  judgeBoardStarting?: boolean
}>(), {
  messages: () => [],
  judgeBoardStarted: false,
  judgeBoardStarting: false
})

const emit = defineEmits<{
  (event: 'start'): void
}>()
const judgeStripRef = ref<HTMLDivElement | null>(null)

defineExpose<{
  judgeStripRef: typeof judgeStripRef
}>({ judgeStripRef })
</script>

<template>
  <div class="strip-judge-log" aria-label="对局提示">
    <img class="strip-judge-avatar" src="/livehall-assets/props/optimized/judge-avatar-160.webp" alt="法官" />
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
