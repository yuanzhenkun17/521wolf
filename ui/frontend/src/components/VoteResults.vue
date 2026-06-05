<script setup>
import { computed } from 'vue'

const props = defineProps({
  tally: { type: Array, default: () => [] }
})

const colors = ['#8b5425', '#c0392b', '#2980b9', '#27ae60', '#8e44ad', '#d35400', '#16a085']
const maxCount = computed(() => Math.max(...props.tally.map((item) => item.count), 1))

function barStyle(item, index) {
  return {
    width: `${(item.count / maxCount.value) * 100}%`,
    background: colors[index % colors.length]
  }
}
</script>

<template>
  <div v-if="tally.length" class="sheriff-bar-chart">
    <div v-for="(item, index) in tally" :key="item.target" class="sheriff-bar-row">
      <span class="sheriff-bar-label">{{ item.target }}</span>
      <div class="sheriff-bar-track">
        <div class="sheriff-bar-fill" :style="barStyle(item, index)"></div>
      </div>
      <span class="sheriff-bar-val">{{ item.count }} 票</span>
    </div>
  </div>
</template>
