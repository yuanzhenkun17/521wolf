<script setup>
import { sourceText, statusText } from '../../composables/workbenchShared.js'

defineProps({
  evo: { type: Object, required: true }
})

function eventTypeLabel(event) {
  return statusText(event?.type) || '事件'
}

function eventPayloadLabel(event) {
  const payload = event?.payload || {}
  const completed = payload.completed_games ?? payload.completed_roles ?? payload.completed ?? payload.overall_completed
  const target = payload.target_games ?? payload.total_roles ?? payload.total ?? payload.overall_total
  const percent = payload.overall_percent ?? payload.percent ?? payload.progress?.overall_percent ?? payload.progress?.percent
  const value = payload.stage || payload.status || payload.phase || payload.type || ''
  const parts = []
  if (value) parts.push(statusText(value) || sourceText(value))
  if (completed != null || target != null) parts.push(`${Number(completed) || 0} / ${Number(target) || 0}`)
  if (percent != null) {
    const number = Number(percent)
    if (Number.isFinite(number)) parts.push(`${Math.round(number <= 1 ? number * 100 : number)}%`)
  }
  if (parts.length) return parts.join(' · ')
  if (payload.run_id) return `运行 ${payload.run_id}`
  if (payload.batch_id) return `批次 ${payload.batch_id}`
  return '进度'
}

function eventTargetLabel(event) {
  const payload = event?.payload || {}
  return payload.run_id || payload.batch_id || payload.id || '当前运行'
}
</script>

<template>
  <div class="evo-tab-panel">
    <article class="evo-card">
      <header>
        <h2>事件</h2>
        <b>{{ evo.eventLog.value.length }}</b>
      </header>
      <div v-if="!evo.eventLog.value.length" class="evo-empty">暂无实时事件</div>
      <ol v-else class="evo-event-list">
        <li v-for="event in evo.eventLog.value" :key="event.id">
          <strong>{{ eventTypeLabel(event) }}</strong>
          <span>{{ eventTargetLabel(event) }} · {{ eventPayloadLabel(event) }}</span>
        </li>
      </ol>
    </article>
  </div>
</template>
