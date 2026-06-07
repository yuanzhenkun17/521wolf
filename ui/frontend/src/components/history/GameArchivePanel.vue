<script setup>
import { computed } from 'vue'
import {
  displayActionLabel,
  displayDayLabel,
  displayPhaseLabel,
  displaySkillDirLabel,
  displaySourceLabel,
  displayWinnerLabel,
  normalizeHistoryDisplayText
} from './historyDisplay.js'

const props = defineProps({
  archive: { type: Object, default: null },
  formatJson: Function
})

const archiveData = computed(() => {
  const raw = props.archive
  if (!raw || raw.error) return null
  return raw.data || raw
})
const archiveEvents = computed(() => archiveData.value?.events || archiveData.value?.logs || [])
const archiveDecisions = computed(() => archiveData.value?.decisions || [])
const archiveEventCount = computed(() => archiveData.value?.event_count ?? archiveEvents.value.length)
const archiveDecisionCount = computed(() => archiveData.value?.decision_count ?? archiveDecisions.value.length)
const archiveErrorCount = computed(() => {
  if (archiveData.value?.error_count != null) return archiveData.value.error_count
  return archiveDecisions.value.filter((d) => d.source === 'llm_error' || d.errors?.length).length
})
const archiveFallbackCount = computed(() => {
  if (archiveData.value?.fallback_count != null) return archiveData.value.fallback_count
  return archiveDecisions.value.filter((d) => sourceKind(d.source) === 'fallback').length
})
const archiveTitle = computed(() => archiveData.value?.title || archiveData.value?.game_id || '对局档案')
const archiveSummary = computed(() => {
  if (archiveData.value?.summary) return formatArchiveHighlight(archiveData.value.summary)
  const winner = displayWinnerLabel(archiveData.value?.winner)
  return `胜方 ${winner}；事件 ${archiveEventCount.value} 条；决策 ${archiveDecisionCount.value} 条。`
})
const archiveHighlights = computed(() => {
  const list = archiveData.value?.highlights
  if (Array.isArray(list) && list.length) return list.map(formatArchiveHighlight).filter(Boolean).slice(0, 5)
  return archiveEvents.value
    .map(formatArchiveHighlight)
    .filter(Boolean)
    .slice(0, 5)
})
const archiveConfigRows = computed(() => {
  const data = archiveData.value || {}
  const config = data.config && typeof data.config === 'object' ? data.config : {}
  const roleSkillDirs = config.role_skill_dirs && typeof config.role_skill_dirs === 'object'
    ? Object.values(config.role_skill_dirs).filter(Boolean).length
    : 0
  return [
    { label: '胜方', value: displayWinnerLabel(data.winner) },
    { label: '种子', value: data.seed ?? config.seed ?? '随机' },
    { label: '最大天数', value: config.max_days ?? data.max_days ?? '默认' },
    { label: '技能目录', value: displaySkillDirLabel(config.skill_dir || data.skill_dir) },
    { label: '角色覆盖', value: roleSkillDirs ? `${roleSkillDirs} 个` : '无' }
  ]
})
const archiveDecisionSources = computed(() => {
  const sources = archiveData.value?.decision_sources
  let rows = []
  if (sources && typeof sources === 'object' && !Array.isArray(sources)) {
    rows = Object.entries(sources).map(([source, count]) => ({ source, count: Number(count) || 0 }))
  } else if (Array.isArray(sources)) {
    rows = sources.map((item) => ({
      source: item.source || item.name || item.key || 'unknown',
      count: Number(item.count ?? item.value ?? 0) || 0
    }))
  } else {
    const tally = {}
    archiveDecisions.value.forEach((decision) => {
      const src = decision.source || 'unknown'
      tally[src] = (tally[src] || 0) + 1
    })
    rows = Object.entries(tally).map(([source, count]) => ({ source, count }))
  }
  return rows.filter((item) => item.count > 0).sort((a, b) => b.count - a.count)
})
const recentDecisions = computed(() =>
  archiveDecisions.value
    .slice(-8)
    .reverse()
    .map((decision, index) => ({
      key: decision.id || decision.decision_id || `${decision.actor_id || decision.player_id || 'd'}-${index}`,
      day: decision.day ?? '—',
      phase: phaseLabel(decision.phase),
      actor: playerLabel(decision.actor_id ?? decision.player_id),
      action: actionLabel(decision.action || decision.action_type),
      choice: choiceLabel(decision.selected_choice ?? decision.choice ?? decision.selected_skill),
      target: targetLabel(decision),
      source: decision.source || 'unknown',
      confidence: confidencePercent(decision.confidence),
      summary: formatArchiveHighlight(decision.public_summary || decision.reason || decision.private_reasoning || '')
    }))
)
const archiveExtraFields = computed(() => {
  const data = archiveData.value
  if (!data || typeof data !== 'object') return []
  const knownKeys = new Set([
    'kind', 'schema_version', 'game_id', 'id', 'title', 'summary', 'highlights',
    'seed', 'config', 'winner', 'events', 'logs', 'decisions', 'decision_count',
    'total_decisions', 'event_count', 'error_count', 'errors', 'fallback_count',
    'fallbacks', 'decision_sources', 'review', 'agent_name', 'name', 'data', 'error'
  ])
  return Object.entries(data)
    .filter(([key]) => !knownKeys.has(key))
    .map(([key, value]) => ({
      key,
      label: fieldLabel(key),
      value: displayValue(key, value)
    }))
    .slice(0, 12)
})

function sourceKind(source = '') {
  const key = String(source).toLowerCase()
  if (key.includes('policy')) return 'policy'
  if (key === 'tot' || key.includes('tree')) return 'reasoning'
  if (key === 'got' || key.includes('graph')) return 'reasoning'
  if (key.includes('fallback')) return 'fallback'
  if (key.includes('error')) return 'error'
  if (key.includes('human')) return 'human'
  if (key.includes('llm')) return 'llm'
  return 'other'
}

function sourceLabel(source) {
  return displaySourceLabel(source)
}

function sourceWidth(count) {
  if (!archiveDecisionCount.value) return '0%'
  return `${Math.max(4, Math.round((count / archiveDecisionCount.value) * 100))}%`
}

function sourcePercent(count) {
  if (!archiveDecisionCount.value) return '0%'
  return `${Math.round((count / archiveDecisionCount.value) * 100)}%`
}

function phaseLabel(phase) {
  return displayPhaseLabel(phase)
}

function dayLabel(day) {
  return displayDayLabel(day)
}

function actionLabel(action) {
  return displayActionLabel(action)
}

function choiceLabel(choice) {
  const key = String(choice || '').toLowerCase()
  const map = {
    save: '救人',
    poison: '毒人',
    none: '不使用',
    skip: '跳过',
    pass: '弃权',
    withdraw: '退水',
    run: '竞选'
  }
  return map[key] || ''
}

function playerLabel(value) {
  if (value == null || value === '') return '系统'
  return `${value}号`
}

function targetLabel(decision) {
  const value = decision.target_id ?? decision.selected_target ?? decision.target
  if (value == null || value === '' || value === 'none') return ''
  return playerLabel(value)
}

function confidencePercent(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return null
  return Math.round(Math.max(0, Math.min(num > 1 ? num : num * 100, 100)))
}

function fieldLabel(key) {
  const map = {
    created_at: '创建时间',
    updated_at: '更新时间',
    started_at: '开始时间',
    finished_at: '结束时间',
    run_id: '运行编号',
    source_run_id: '来源运行',
    model: '模型',
    model_name: '模型',
    player_count: '玩家数',
    mode: '模式',
    status: '状态',
    source: '来源',
    source_type: '来源类型',
    action: '动作',
    action_type: '动作',
    phase: '阶段',
    day: '天数',
    duration: '耗时',
    duration_seconds: '耗时'
  }
  return map[key] || String(key || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function displayValue(key, value) {
  if (value == null || value === '') return '—'
  if (key === 'source') return sourceLabel(value)
  if (key === 'action' || key === 'action_type') return actionLabel(value)
  if (key === 'phase') return phaseLabel(value)
  if (key === 'winner') return displayWinnerLabel(value)
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  if (typeof value === 'object') {
    const text = normalizeHistoryDisplayText(JSON.stringify(value))
    return text.length > 120 ? text.slice(0, 117) + '...' : text
  }
  const text = normalizeHistoryDisplayText(value)
  return text.length > 120 ? text.slice(0, 117) + '...' : text
}

function formatArchiveHighlight(item) {
  if (item == null) return ''
  if (typeof item === 'object') {
    const actor = item.actor_id ?? item.player_id
    const action = actionLabel(item.action || item.action_type || item.event_type || item.type)
    const source = item.source ? ` · ${sourceLabel(item.source)}` : ''
    const target = targetLabel(item)
    const prefix = actor != null ? `${playerLabel(actor)} ${action}` : action
    const message = item.message || item.summary || item.public_summary || item.reason || ''
    return `${prefix}${target ? ` → ${target}` : ''}${source}${message ? `：${formatArchiveHighlight(message)}` : ''}`
  }
  return normalizeHistoryDisplayText(item)
}

function jsonText(value) {
  if (props.formatJson) return props.formatJson(value)
  return JSON.stringify(value, null, 2)
}
</script>

<template>
  <section class="archive-review-panel">
    <header class="archive-header">
      <div>
        <h3>{{ archiveTitle }}</h3>
        <p v-if="archiveData">{{ archiveSummary }}</p>
      </div>
    </header>

    <template v-if="archiveData">
      <div class="archive-kpi-strip">
        <span class="archive-kpi-card"><small>事件</small><b>{{ archiveEventCount }}</b></span>
        <span class="archive-kpi-card"><small>决策</small><b>{{ archiveDecisionCount }}</b></span>
        <span class="archive-kpi-card">
          <small>错误</small><b :class="{ 'archive-kpi-error': archiveErrorCount > 0 }">{{ archiveErrorCount }}</b>
        </span>
        <span class="archive-kpi-card"><small>回退</small><b>{{ archiveFallbackCount }}</b></span>
      </div>

      <div class="archive-config-grid">
        <span v-for="item in archiveConfigRows" :key="item.label" class="archive-config-item">
          <small>{{ item.label }}</small>
          <b :title="String(item.value)">{{ item.value }}</b>
        </span>
      </div>

      <section v-if="archiveHighlights.length" class="archive-section">
        <h4>关键记录</h4>
        <ol class="archive-highlight-list">
          <li v-for="(item, index) in archiveHighlights" :key="'highlight-' + index">{{ item }}</li>
        </ol>
      </section>

      <section v-if="archiveDecisionSources.length" class="archive-section">
        <h4>决策来源</h4>
        <div class="archive-source-list">
          <div v-for="item in archiveDecisionSources" :key="'ds-' + item.source" class="archive-source-row">
            <span class="archive-source-label" :data-kind="sourceKind(item.source)">{{ sourceLabel(item.source) }}</span>
            <div class="archive-source-track">
              <div
                class="archive-source-fill"
                :data-kind="sourceKind(item.source)"
                :style="{ width: sourceWidth(item.count) }"
              ></div>
            </div>
            <b class="archive-source-count">{{ item.count }} <small>{{ sourcePercent(item.count) }}</small></b>
          </div>
        </div>
      </section>

      <section v-if="recentDecisions.length" class="archive-section">
        <h4>最近决策</h4>
        <div class="archive-decision-list">
          <article v-for="decision in recentDecisions" :key="decision.key" class="archive-decision-card">
            <header>
              <span>{{ dayLabel(decision.day) }} · {{ decision.phase }}</span>
              <small :data-kind="sourceKind(decision.source)">{{ sourceLabel(decision.source) }}</small>
            </header>
            <strong>
              {{ decision.actor }} {{ decision.action }}<template v-if="decision.choice"> · {{ decision.choice }}</template><template v-if="decision.target"> → {{ decision.target }}</template>
            </strong>
            <p v-if="decision.summary">{{ decision.summary }}</p>
            <em v-if="decision.confidence != null">置信度 {{ decision.confidence }}%</em>
          </article>
        </div>
      </section>

      <details v-if="archiveExtraFields.length" class="archive-extra-fields">
        <summary>附加字段</summary>
        <div>
          <span v-for="field in archiveExtraFields" :key="'ae-' + field.key" class="archive-extra-item">
            <small :title="field.key">{{ field.label }}</small><b :title="field.value">{{ field.value }}</b>
          </span>
        </div>
      </details>
    </template>
    <pre v-if="!archiveData">{{ jsonText(archive) }}</pre>
  </section>
</template>

<style scoped>
.archive-review-panel {
  display: grid;
  gap: 14px;
  margin-top: 12px;
  border: 1px solid var(--log-border);
  padding: 16px;
  background: var(--log-surface);
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(91, 47, 18, 0.06);
}

.archive-header {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--log-border);
}

.archive-header h3 {
  margin: 0;
  color: var(--log-text);
  font-size: 16px;
  font-weight: 950;
}

.archive-header p {
  margin: 7px 0 0;
  color: var(--log-text-secondary);
  font-size: 13px;
  font-weight: 700;
  line-height: 1.55;
}

.archive-review-panel h4 {
  margin: 0 0 8px;
  color: var(--log-text);
  font-size: 13px;
  font-weight: 900;
}

.archive-review-panel pre {
  max-height: 240px;
  overflow: auto;
  margin: 0;
  padding: 10px;
  border: 1px solid var(--log-border);
  border-radius: 6px;
  color: var(--log-text);
  background: rgba(255, 248, 225, 0.5);
  font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
  font-size: 12px;
  white-space: pre-wrap;
  line-height: 1.5;
}

.archive-kpi-strip,
.archive-config-grid {
  display: grid;
  gap: 8px;
}

.archive-kpi-strip {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.archive-config-grid {
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
}

.archive-kpi-card,
.archive-config-item {
  display: grid;
  gap: 4px;
  min-width: 0;
  border: 1px solid var(--log-border);
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.62);
}

.archive-kpi-card {
  min-height: 58px;
  padding: 10px 12px;
}

.archive-config-item {
  min-height: 48px;
  padding: 8px 10px;
}

.archive-kpi-card small,
.archive-config-item small,
.archive-extra-item small {
  color: var(--log-text-secondary);
  font-size: 10px;
  font-weight: 900;
  line-height: 1;
  text-transform: uppercase;
}

.archive-kpi-card b,
.archive-config-item b {
  min-width: 0;
  overflow: hidden;
  color: var(--log-text);
  font-weight: 950;
  line-height: 1.15;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.archive-kpi-card b {
  font-size: 18px;
}

.archive-config-item b {
  font-size: 13px;
}

.archive-kpi-card b.archive-kpi-error {
  color: #c0392b;
}

.archive-section {
  display: grid;
  gap: 8px;
}

.archive-highlight-list {
  display: grid;
  gap: 7px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.archive-highlight-list li {
  padding: 8px 10px 8px 12px;
  border-left: 3px solid rgba(139, 94, 52, 0.38);
  border-radius: 7px;
  color: var(--log-text);
  background: rgba(255, 252, 245, 0.46);
  font-size: 13px;
  font-weight: 700;
  line-height: 1.48;
}

.archive-source-list,
.archive-decision-list {
  display: grid;
  gap: 7px;
}

.archive-source-row {
  display: grid;
  grid-template-columns: minmax(54px, 78px) minmax(0, 1fr) 70px;
  align-items: center;
  gap: 9px;
  min-width: 0;
}

.archive-source-label {
  display: inline-flex;
  justify-content: center;
  min-width: 0;
  padding: 3px 7px;
  border-radius: 5px;
  color: var(--log-accent);
  background: var(--log-active-bg);
  font-size: 11px;
  font-weight: 900;
}

.archive-source-label[data-kind="error"] {
  color: #b42318;
  background: rgba(192, 57, 43, 0.1);
}

.archive-source-label[data-kind="human"] {
  color: #166534;
  background: rgba(39, 174, 96, 0.12);
}

.archive-source-track {
  min-width: 0;
  height: 9px;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.08);
  overflow: hidden;
}

.archive-source-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #d4af37, #a56a22);
  transition: width 0.4s cubic-bezier(0.22, 0.61, 0.36, 1);
}

.archive-source-fill[data-kind="fallback"] {
  background: linear-gradient(90deg, #8a7e6a, #b0a48e);
}

.archive-source-fill[data-kind="error"] {
  background: linear-gradient(90deg, #c0392b, #8f1f10);
}

.archive-source-fill[data-kind="human"] {
  background: linear-gradient(90deg, #27ae60, #166534);
}

.archive-source-count {
  color: var(--log-text);
  font-size: 12px;
  font-weight: 950;
  text-align: right;
}

.archive-source-count small {
  color: var(--log-text-secondary);
  font-size: 10px;
  font-weight: 800;
}

.archive-decision-card {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--log-border);
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.54);
}

.archive-decision-card header {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.archive-decision-card header span {
  min-width: 0;
  overflow: hidden;
  color: var(--log-text-secondary);
  font-size: 11px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.archive-decision-card header small {
  margin-left: auto;
  padding: 2px 7px;
  border-radius: 999px;
  color: var(--log-accent);
  background: var(--log-active-bg);
  font-size: 10px;
  font-weight: 900;
  white-space: nowrap;
}

.archive-decision-card header small[data-kind="fallback"],
.archive-decision-card header small[data-kind="error"] {
  color: #8f1f10;
  background: rgba(192, 57, 43, 0.09);
}

.archive-decision-card strong {
  color: var(--log-text);
  font-size: 13px;
  font-weight: 950;
  line-height: 1.35;
}

.archive-decision-card p {
  display: -webkit-box;
  overflow: hidden;
  margin: 0;
  color: var(--log-text-secondary);
  font-size: 12px;
  font-weight: 700;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.archive-decision-card em {
  color: var(--log-accent);
  font-size: 11px;
  font-style: normal;
  font-weight: 900;
}

.archive-extra-fields {
  border-top: 1px solid var(--log-border);
  padding-top: 10px;
}

.archive-extra-fields summary {
  color: var(--log-accent);
  cursor: pointer;
  font-size: 12px;
  font-weight: 900;
}

.archive-extra-fields div {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 6px;
  margin-top: 8px;
}

.archive-extra-item {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid var(--log-border);
  border-radius: 5px;
  background: rgba(255, 252, 245, 0.5);
}

.archive-extra-item b {
  min-width: 0;
  overflow: hidden;
  color: var(--log-text);
  font-size: 12px;
  font-weight: 800;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 720px) {
  .archive-review-panel {
    padding: 12px;
    border-radius: 8px;
  }

  .archive-kpi-strip,
  .archive-config-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .archive-source-row {
    grid-template-columns: minmax(0, 1fr) 58px;
    gap: 6px;
  }

  .archive-source-label {
    grid-column: 1 / -1;
    justify-self: start;
  }
}

@media (max-width: 420px) {
  .archive-kpi-strip,
  .archive-config-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
