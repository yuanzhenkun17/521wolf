<script setup>
import { computed } from 'vue'

const props = defineProps({
  action: { type: Object, required: true },
  selected: Boolean,
  mode: { type: String, default: 'night' },
  nightActionDetail: Function
})

const emit = defineEmits(['select'])

const roleText = computed(() => {
  if (props.mode === 'vote') return props.action.actorName
  return props.action.roleName
})

const seatText = computed(() => {
  if (props.mode === 'vote') return '投票给'
  return props.action.actorName ? `· ${props.action.actorName}` : ''
})

const actionText = computed(() => {
  if (props.mode === 'night' && props.nightActionDetail) return props.nightActionDetail(props.action)
  if (props.mode === 'vote') return props.action.targetName
  return props.action.public_summary || props.action.reason || '先过。'
})

const reasonText = computed(() => props.action.private_reasoning || props.action.reason || '')
const reasonPreview = computed(() => {
  const value = reasonText.value
  return value.length > 40 ? `${value.slice(0, 40)}…` : value
})
const confidenceText = computed(() => `${Math.round((props.action.confidence || 0) * 100)}%`)
</script>

<template>
  <div :class="['night-mini-card', { sel: selected }]" @click="emit('select', action)">
    <div class="nmc-header">
      <span class="nmc-role">{{ roleText }}</span>
      <span class="nmc-seat">{{ seatText }}</span>
    </div>
    <div class="nmc-action">{{ actionText }}</div>
    <div class="nmc-row" v-if="action.confidence != null">
      <span class="nmc-label">置信度</span>
      <span class="nmc-val">{{ confidenceText }}</span>
    </div>
    <div class="nmc-row" v-if="reasonText">
      <span class="nmc-label">理由</span>
      <span class="nmc-val nmc-reason">{{ reasonPreview }}</span>
    </div>
  </div>
</template>
