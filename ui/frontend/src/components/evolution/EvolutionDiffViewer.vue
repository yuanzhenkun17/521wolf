<script setup lang="ts">
// @ts-nocheck
import { computed } from 'vue'

const props = defineProps({
  diffData: Object,
  legacyDiff: { type: Array, default: () => [] }
})

const normalizedDiff = computed(() => {
  const raw = props.diffData
  if (raw) return raw
  const legacy = props.legacyDiff
  if (!Array.isArray(legacy) || !legacy.length) return null
  return {
    skill_changes: legacy.map((d) => ({
      file: d.filename || d.file || '',
      action: d.action || d.action_type || 'modified'
    })),
    patterns_added: [],
    patterns_removed: [],
    patterns_updated: [],
    metrics_delta: null
  }
})

function deltaLabel(value) {
  const n = Number(value || 0)
  if (!n) return '0'
  return `${n > 0 ? '+' : ''}${Math.round(n * 100)}%`
}

function diffLabel(diff) {
  const file = skillFileLabel(diff)
  const action = diff?.action || diff?.action_type || 'change'
  return `${file} · ${diffActionLabel(action)}`
}

function diffActionLabel(action) {
  return { created: '新建', modified: '修改', deleted: '删除', renamed: '重命名' }[action] || '变更'
}

function diffActionColor(action) {
  return {
    created: 'var(--evo-success)',
    modified: 'var(--evo-warning)',
    deleted: 'var(--evo-danger)',
    renamed: 'var(--evo-accent)'
  }[action] || 'var(--evo-text-secondary)'
}

function computeLineDiff(before, after) {
  const bLines = (before || '').split('\n')
  const aLines = (after || '').split('\n')
  const result = []
  const bSet = new Map()
  bLines.forEach((line, i) => {
    if (!bSet.has(line)) bSet.set(line, [])
    bSet.get(line).push(i)
  })
  const matched = new Set()
  const aMatched = new Set()
  for (let i = 0; i < aLines.length; i++) {
    const indices = bSet.get(aLines[i])
    if (indices) {
      for (const j of indices) {
        if (!matched.has(j)) {
          matched.add(j)
          aMatched.add(i)
          break
        }
      }
    }
  }
  bLines.forEach((line, i) => {
    if (!matched.has(i)) result.push({ type: 'removed', text: line })
  })
  aLines.forEach((line, i) => {
    result.push(aMatched.has(i) ? { type: 'context', text: line } : { type: 'added', text: line })
  })
  return result
}

function skillFileLabel(change) {
  const label = change?.title || change?.label || change?.display_name || ''
  if (label && !/^[a-z0-9_.:/\\-]+$/i.test(String(label))) return label
  return '技能文件'
}

function metricsDeltaEntries(delta) {
  if (!delta) return []
  const labelMap = { win_rate: '胜率', score: '得分', speech_score: '发言', vote_score: '投票', skill_score: '技能' }
  return Object.entries(delta)
    .filter(([, value]) => value != null)
    .map(([key, value]) => ({
      key,
      label: labelMap[key] || key,
      value: Number(value) || 0,
      isPositive: Number(value) >= 0
    }))
}
</script>

<template>
  <div v-if="normalizedDiff" class="evo-diff-viewer">
    <div v-if="normalizedDiff.metrics_delta && metricsDeltaEntries(normalizedDiff.metrics_delta).length" class="evo-diff-metrics-strip">
      <h3>指标变化</h3>
      <div class="evo-diff-metrics-row">
        <span
          v-for="entry in metricsDeltaEntries(normalizedDiff.metrics_delta)"
          :key="entry.key"
          :class="['evo-diff-metric-kpi', entry.isPositive ? 'positive' : 'negative']"
        >
          <small>{{ entry.label }}</small>
          <b>
            <span class="evo-diff-arrow">{{ entry.isPositive ? '▲' : '▼' }}</span>
            {{ deltaLabel(entry.value) }}
          </b>
        </span>
      </div>
    </div>

    <div v-if="normalizedDiff.skill_changes?.length" class="evo-diff-section">
      <h3>技能文件变更</h3>
      <div v-for="(change, index) in normalizedDiff.skill_changes" :key="index" class="evo-diff-file-block">
        <div class="evo-diff-file-header">
          <span class="evo-diff-filename">{{ skillFileLabel(change) }}</span>
          <span class="evo-diff-action-badge" :style="{ background: diffActionColor(change.action || change.action_type) }">
            {{ diffActionLabel(change.action || change.action_type) }}
          </span>
        </div>
        <div v-if="change.before || change.after || change.before_lines || change.after_lines" class="evo-diff-code-block">
          <div
            v-for="(line, lineIndex) in computeLineDiff(change.before || change.before_lines, change.after || change.after_lines)"
            :key="lineIndex"
            :class="['evo-diff-line', `evo-diff-line-${line.type}`]"
          >
            <span class="evo-diff-line-marker">{{ line.type === 'added' ? '+' : line.type === 'removed' ? '-' : ' ' }}</span>
            <span class="evo-diff-line-text">{{ line.text }}</span>
          </div>
        </div>
        <p v-else class="evo-diff-no-content">仅记录变更类型，无详细内容</p>
      </div>
    </div>

    <div
      v-if="(normalizedDiff.patterns_added?.length) || (normalizedDiff.patterns_removed?.length) || (normalizedDiff.patterns_updated?.length)"
      class="evo-diff-section"
    >
      <h3>策略模式变更</h3>
      <div v-if="normalizedDiff.patterns_added?.length" class="evo-diff-pattern-group">
        <small class="evo-diff-group-label added-label">新增</small>
        <div v-for="(pattern, index) in normalizedDiff.patterns_added" :key="'add-' + index" class="evo-diff-pattern-card added">
          <strong>{{ pattern.pattern_id || pattern.id || '新模式' }}</strong>
          <span>{{ pattern.recommendation || pattern.summary || pattern.situation || '—' }}</span>
        </div>
      </div>
      <div v-if="normalizedDiff.patterns_removed?.length" class="evo-diff-pattern-group">
        <small class="evo-diff-group-label removed-label">移除</small>
        <div v-for="(pattern, index) in normalizedDiff.patterns_removed" :key="'rm-' + index" class="evo-diff-pattern-card removed">
          <strong>{{ pattern.pattern_id || pattern.id || '旧模式' }}</strong>
          <span>{{ pattern.recommendation || pattern.summary || pattern.situation || '—' }}</span>
        </div>
      </div>
      <div v-if="normalizedDiff.patterns_updated?.length" class="evo-diff-pattern-group">
        <small class="evo-diff-group-label updated-label">更新</small>
        <div v-for="(pattern, index) in normalizedDiff.patterns_updated" :key="'upd-' + index" class="evo-diff-pattern-card updated">
          <strong>{{ pattern.pattern_id || pattern.id || '策略模式' }}</strong>
          <span v-if="pattern.old_confidence != null || pattern.new_confidence != null">
            置信度: {{ pattern.old_confidence != null ? Math.round(pattern.old_confidence * 100) + '%' : '—' }} 到 {{ pattern.new_confidence != null ? Math.round(pattern.new_confidence * 100) + '%' : '—' }}
          </span>
          <span v-if="pattern.old_win_rate != null || pattern.new_win_rate != null">
            胜率: {{ pattern.old_win_rate != null ? Math.round(pattern.old_win_rate * 100) + '%' : '—' }} 到 {{ pattern.new_win_rate != null ? Math.round(pattern.new_win_rate * 100) + '%' : '—' }}
          </span>
          <span v-if="pattern.recommendation || pattern.summary">{{ pattern.recommendation || pattern.summary }}</span>
        </div>
      </div>
    </div>

    <div
      v-if="!normalizedDiff.skill_changes?.length && !normalizedDiff.patterns_added?.length && !normalizedDiff.patterns_removed?.length && !normalizedDiff.patterns_updated?.length && legacyDiff.length"
      class="evo-diff-section"
    >
      <h3>差异</h3>
      <ul class="evo-diff-legacy-list">
        <li v-for="(diff, index) in legacyDiff.slice(0, 8)" :key="index">
          {{ diffLabel(diff) }}
        </li>
      </ul>
    </div>
  </div>
  <div v-else class="evo-diff-empty">
    <h3>差异</h3>
    <p>—</p>
  </div>
</template>
