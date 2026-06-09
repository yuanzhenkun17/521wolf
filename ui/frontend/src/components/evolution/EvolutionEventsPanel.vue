<script setup>
import { computed } from 'vue'
import { sourceText, statusText } from '../../composables/workbenchShared.js'

const props = defineProps({
  evo: { type: Object, required: true }
})

const eventRows = computed(() => (props.evo.eventLog.value || []).map(normalizeEventRow))

function eventTypeLabel(event) {
  return statusText(event?.type) || '事件'
}

function eventProgressParts(payload = {}) {
  const completed = payload.completed_games ?? payload.completed_roles ?? payload.completed ?? payload.overall_completed
  const target = payload.target_games ?? payload.total_roles ?? payload.total ?? payload.overall_total
  const percent = payload.overall_percent ?? payload.percent ?? payload.progress?.overall_percent ?? payload.progress?.percent
  return { completed, target, percent }
}

function eventStageLabel(event) {
  const payload = event?.payload || {}
  const value = payload.stage || payload.status || payload.phase || payload.type || ''
  return value ? (statusText(value) || sourceText(value)) : '—'
}

function eventTargetLabel(event) {
  const payload = event?.payload || {}
  return payload.run_id || payload.batch_id || payload.id || '当前运行'
}

function eventCompletionLabel(payload = {}) {
  const { completed, target } = eventProgressParts(payload)
  if (completed == null && target == null) return '—'
  return `${Number(completed) || 0} / ${Number(target) || 0}`
}

function eventProgressPercent(payload = {}) {
  const { completed, target, percent } = eventProgressParts(payload)
  const explicit = Number(percent)
  if (Number.isFinite(explicit)) return Math.max(0, Math.min(100, Math.round(explicit <= 1 ? explicit * 100 : explicit)))
  const done = Number(completed)
  const total = Number(target)
  if (Number.isFinite(done) && Number.isFinite(total) && total > 0) {
    return Math.max(0, Math.min(100, Math.round((done / total) * 100)))
  }
  return 0
}

function eventProgressLabel(payload = {}) {
  const percent = eventProgressPercent(payload)
  return percent ? `${percent}%` : '—'
}

function eventTimeLabel(event) {
  const raw = event?.payload?.time || event?.payload?.timestamp || event?.payload?.created_at || event?.timestamp || ''
  return raw ? String(raw).replace('T', ' ').slice(0, 19) : '—'
}

function eventSummary(event) {
  const payload = event?.payload || {}
  return payload.message || payload.reason || payload.error || payload.detail || payload.stage || payload.status || event?.type || '进度'
}

function normalizeEventRow(event) {
  const payload = event?.payload || {}
  return {
    id: event?.id || `${event?.type || 'event'}-${eventTargetLabel(event)}-${eventTimeLabel(event)}`,
    type: eventTypeLabel(event),
    target: eventTargetLabel(event),
    stage: eventStageLabel(event),
    completed: eventCompletionLabel(payload),
    progress: eventProgressLabel(payload),
    progressPercent: eventProgressPercent(payload),
    summary: eventSummary(event),
    time: eventTimeLabel(event)
  }
}
</script>

<template>
  <div class="evo-tab-panel">
    <article class="evo-card evo-events-card">
      <header>
        <h2>事件</h2>
        <b>{{ eventRows.length }}</b>
      </header>
      <div v-if="!eventRows.length" class="evo-empty">暂无实时事件</div>
      <div v-else class="evo-event-table" role="table" aria-label="运行事件排障">
        <div class="evo-event-head" role="row">
          <span role="columnheader">事件类型</span>
          <span role="columnheader">目标运行或批次</span>
          <span role="columnheader">当前阶段</span>
          <span role="columnheader">完成数</span>
          <span role="columnheader">进度</span>
          <span role="columnheader">摘要</span>
        </div>
        <ol class="evo-event-list">
          <li v-for="event in eventRows" :key="event.id" role="row">
            <strong role="cell">{{ event.type }}</strong>
            <code role="cell">{{ event.target }}</code>
            <span role="cell">{{ event.stage }}</span>
            <span role="cell">{{ event.completed }}</span>
            <span class="evo-event-progress" role="cell">
              <b>{{ event.progress }}</b>
              <i aria-hidden="true"><em :style="{ width: `${event.progressPercent}%` }"></em></i>
            </span>
            <span role="cell" :title="event.summary">{{ event.summary }}</span>
          </li>
        </ol>
      </div>
    </article>
  </div>
</template>

<style scoped>
.evo-events-card {
  display: grid;
  gap: 10px;
}

.evo-event-table {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.evo-event-head,
.evo-event-list li {
  display: grid;
  grid-template-columns: minmax(72px, 0.7fr) minmax(120px, 1fr) minmax(82px, 0.8fr) minmax(62px, 0.55fr) minmax(72px, 0.7fr) minmax(120px, 1.2fr);
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.evo-event-head {
  padding: 0 10px;
}

.evo-event-head span {
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-weight: 850;
}

.evo-event-list {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.evo-event-list li {
  padding: 8px 10px;
  border: 1px solid var(--evo-border);
  border-radius: 7px;
  background: var(--evo-input-bg);
}

.evo-event-list strong,
.evo-event-list code,
.evo-event-list span {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text);
  font-size: 12px;
  font-weight: 750;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-event-list strong {
  color: var(--evo-accent-strong);
}

.evo-event-progress {
  display: grid;
  gap: 3px;
}

.evo-event-progress b {
  color: var(--evo-text);
}

.evo-event-progress i {
  display: block;
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.1);
}

.evo-event-progress em {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--evo-accent);
}

@media (max-width: 900px) {
  .evo-event-head {
    display: none;
  }

  .evo-event-list li {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
