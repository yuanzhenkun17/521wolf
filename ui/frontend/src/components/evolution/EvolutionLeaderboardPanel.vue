<script setup lang="ts">
// @ts-nocheck
import { computed } from 'vue'

const props = defineProps({
  evo: { type: Object, required: true }
})

const rows = computed(() => props.evo.selectedRoleLeaderboard.value || [])
const baselineRow = computed(() => rows.value.find((item) => item.is_baseline) || null)
const leadingCandidate = computed(() => rows.value.find((item) => !item.is_baseline) || rows.value[0] || null)
const summaryRows = computed(() => [
  { key: 'role', label: '角色', value: props.evo.selectedRoleLabel.value || '—' },
  { key: 'baseline', label: '基线', value: versionLabel(baselineRow.value), code: true },
  { key: 'candidate', label: '候选', value: leadingCandidate.value?.is_baseline ? '—' : versionLabel(leadingCandidate.value), code: true },
  { key: 'recommendation', label: '推荐结论', value: leadingCandidate.value?.recommendationLabel || '未标记' }
])

function leaderboardKey(item, index) {
  return item.hash || item.target_version_id || item.version_id || item.subject_id || index
}

function versionLabel(item) {
  if (!item) return '—'
  return item.short || item.target_version_id || item.version_id || item.subject_id || item.hash || '—'
}

function sourceRunId(item) {
  return item?.source_run_id || item?.sourceRunId || item?.run_id || item?.runId || item?.provenance?.source_run_id || ''
}

function sourceRunHref(item) {
  const runId = sourceRunId(item)
  return runId ? `#evolution?run_id=${encodeURIComponent(runId)}` : ''
}

function rowRoleLabel(item) {
  return item?.target_role_label || item?.roleLabel || props.evo.selectedRoleLabel.value || '—'
}

function rowTypeLabel(item) {
  if (item?.is_baseline) return '基线'
  return item?.releaseStageLabel || item?.release_stage_label || item?.sourceLabel || '候选'
}

function scoreLabel(item) {
  const value = Number(item?.scorePct)
  return Number.isFinite(value) ? `${Math.round(value)}%` : '—'
}

function winRateLabel(item) {
  const value = Number(item?.winRatePct)
  return Number.isFinite(value) ? `${Math.round(value)}%` : '—'
}

function deltaLabel(item) {
  const value = Number(item?.deltaScore)
  if (!Number.isFinite(value) || value === 0) return '—'
  const percent = Math.abs(value) <= 1 ? value * 100 : value
  return `${percent > 0 ? '+' : ''}${Math.round(percent)}%`
}
</script>

<template>
  <div class="evo-tab-panel">
    <article class="evo-card evo-leaderboard-card">
      <header>
        <h2>验证榜单</h2>
        <b>{{ evo.selectedRoleLabel.value }}</b>
      </header>

      <div class="evo-leaderboard-summary" aria-label="自进化验证摘要">
        <span v-for="item in summaryRows" :key="item.key">
          <small>{{ item.label }}</small>
          <code v-if="item.code">{{ item.value }}</code>
          <b v-else>{{ item.value }}</b>
        </span>
      </div>

      <div v-if="!rows.length" class="evo-empty">暂无对战数据</div>
      <div v-else class="evo-leaderboard-table" role="table" aria-label="自进化验证结果">
        <div class="evo-leaderboard-head" role="row">
          <span role="columnheader">角色</span>
          <span role="columnheader">基线</span>
          <span role="columnheader">候选</span>
          <span role="columnheader">推荐结论</span>
          <span role="columnheader">胜率 / 得分</span>
          <span role="columnheader">来源运行</span>
        </div>
        <div
          v-for="(item, index) in rows"
          :key="leaderboardKey(item, index)"
          class="evo-leaderboard-row"
          role="row"
        >
          <span class="evo-leaderboard-label" role="cell">
            <b>{{ rowRoleLabel(item) }}</b>
            <small>{{ rowTypeLabel(item) }}</small>
          </span>
          <code role="cell">{{ item.is_baseline ? versionLabel(item) : versionLabel(baselineRow) }}</code>
          <code role="cell">{{ item.is_baseline ? '—' : versionLabel(item) }}</code>
          <span role="cell">{{ item.is_baseline ? '基线' : (item.recommendationLabel || '未标记') }}</span>
          <span class="evo-leaderboard-score" role="cell">
            <b>{{ winRateLabel(item) }}</b>
            <small>{{ scoreLabel(item) }} · 差值 {{ deltaLabel(item) }}</small>
            <i aria-hidden="true">
              <em
                :class="{ 'is-baseline': item.is_baseline }"
                :style="{ width: scoreLabel(item) === '—' ? '0%' : scoreLabel(item) }"
              ></em>
            </i>
          </span>
          <a v-if="sourceRunHref(item)" role="cell" :href="sourceRunHref(item)">
            {{ sourceRunId(item) }}
          </a>
          <span v-else role="cell">—</span>
        </div>
      </div>
    </article>
  </div>
</template>

<style scoped>
.evo-leaderboard-card {
  display: grid;
  gap: 12px;
}

.evo-leaderboard-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.evo-leaderboard-summary span {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 8px 9px;
  border: 1px solid var(--evo-border);
  border-radius: 7px;
  background: var(--evo-input-bg);
}

.evo-leaderboard-summary small,
.evo-leaderboard-head span,
.evo-leaderboard-score small {
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0;
}

.evo-leaderboard-summary b,
.evo-leaderboard-summary code {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text);
  font-size: 12px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-leaderboard-table {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.evo-leaderboard-head,
.evo-leaderboard-row {
  display: grid;
  grid-template-columns: minmax(90px, 0.8fr) minmax(84px, 0.8fr) minmax(84px, 0.8fr) minmax(90px, 0.8fr) minmax(110px, 1fr) minmax(100px, 0.9fr);
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.evo-leaderboard-head {
  padding: 0 10px;
}

.evo-leaderboard-row {
  padding: 9px 10px;
  border: 1px solid var(--evo-border);
  border-radius: 7px;
  background: var(--evo-input-bg);
}

.evo-leaderboard-row > span,
.evo-leaderboard-row > code,
.evo-leaderboard-row > a {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text);
  font-size: 12px;
  font-weight: 750;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-leaderboard-row > a {
  color: var(--evo-accent-strong);
  text-decoration: none;
}

.evo-leaderboard-label {
  display: grid;
  gap: 2px;
}

.evo-leaderboard-label small {
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-weight: 750;
}

.evo-leaderboard-score {
  display: grid;
  gap: 3px;
}

.evo-leaderboard-score b {
  color: var(--evo-text);
}

.evo-leaderboard-score i {
  display: block;
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.1);
}

.evo-leaderboard-score em {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--evo-accent);
}

.evo-leaderboard-score em.is-baseline {
  background: var(--evo-accent-strong);
}

@media (max-width: 960px) {
  .evo-leaderboard-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .evo-leaderboard-head {
    display: none;
  }

  .evo-leaderboard-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
