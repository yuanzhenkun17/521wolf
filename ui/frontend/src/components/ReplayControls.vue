<script setup>
defineProps({
  isReplayMode: Boolean
})

const emit = defineEmits(['return-to-history', 'exit-replay'])
</script>

<template>
  <section v-if="isReplayMode" class="replay-controls" aria-label="复盘控制">
    <button class="icon-button primary" title="返回日志" @click="emit('return-to-history')">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 5.5 9 12l6.5 6.5V5.5z" /></svg>
    </button>
    <button class="icon-button" title="退出复盘" @click="emit('exit-replay')">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.4 5 5 6.4l5.6 5.6L5 17.6 6.4 19l5.6-5.6 5.6 5.6 1.4-1.4-5.6-5.6L19 6.4 17.6 5 12 10.6z" /></svg>
    </button>
  </section>
</template>
