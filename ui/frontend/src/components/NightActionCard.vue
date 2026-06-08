<script setup>
import { computed } from 'vue'
import {
  displayRoleLabel,
  normalizeHistoryDisplayText
} from './history/historyDisplay.js'

const props = defineProps({
  action: { type: Object, required: true },
  selected: Boolean,
  mode: { type: String, default: 'night' },
  nightActionDetail: Function,
  roleIconImage: Function
})

const emit = defineEmits(['select'])

const roleText = computed(() => {
  if (props.mode === 'vote') return props.action.actorName
  return displayRoleLabel(props.action.roleName)
})

const seatText = computed(() => {
  if (props.mode === 'vote') return '投票给'
  return props.action.actorName ? `· ${props.action.actorName}` : ''
})

const actionText = computed(() => {
  const text = props.mode === 'night' && props.nightActionDetail
    ? props.nightActionDetail(props.action)
    : props.mode === 'vote'
      ? props.action.targetName
      : props.action.public_summary || props.action.reason || '先过。'
  return normalizeHistoryDisplayText(text) || '暂无行动'
})

const confidenceValue = computed(() => {
  const value = Number(props.action.confidence || 0)
  return Math.round(Math.max(0, Math.min(value > 1 ? value : value * 100, 100)))
})
const confidenceText = computed(() => `${confidenceValue.value}%`)
const confidenceClass = computed(() => {
  if (confidenceValue.value < 50) return 'low'
  if (confidenceValue.value < 80) return 'medium'
  return 'high'
})
const iconRoleText = computed(() => displayRoleLabel(props.action.roleName))
const roleIcon = computed(() => props.roleIconImage?.({
  role: props.action.roleName,
  role_hint: iconRoleText.value
}) || '')
</script>

<template>
  <div :class="['night-mini-card', { sel: selected }]" @click="emit('select', action)">
    <div class="nmc-header">
      <img v-if="roleIcon" class="nmc-role-icon" :src="roleIcon" alt="" />
      <span class="nmc-role">{{ roleText }}</span>
      <span class="nmc-seat">{{ seatText }}</span>
      <span v-if="action.confidence != null" :class="['nmc-confidence', confidenceClass]">置信度 {{ confidenceText }}</span>
    </div>
    <div class="nmc-action">{{ actionText }}</div>
  </div>
</template>
