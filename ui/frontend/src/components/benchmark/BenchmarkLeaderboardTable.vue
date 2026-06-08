<script setup>
import { computed } from 'vue'

const props = defineProps({
  kind: {
    type: String,
    required: true,
    validator: value => ['model', 'role'].includes(value)
  },
  title: {
    type: String,
    required: true
  },
  meta: {
    type: String,
    required: true
  },
  rows: {
    type: Array,
    required: true
  }
})

const rankedRows = computed(() =>
  [...props.rows].sort((a, b) => Number(b.scorePct || 0) - Number(a.scorePct || 0))
)
const topRow = computed(() => rankedRows.value[0] || null)
const baselineRow = computed(() => props.rows.find((item) => item.is_baseline) || null)
const averageScore = computed(() => {
  if (!props.rows.length) return '--'
  const total = props.rows.reduce((sum, item) => sum + Number(item.scorePct || 0), 0)
  return Math.round(total / props.rows.length) + '%'
})
const averageWinRate = computed(() => {
  if (!props.rows.length) return '--'
  const total = props.rows.reduce((sum, item) => sum + Number(item.winRatePct || 0), 0)
  return Math.round(total / props.rows.length) + '%'
})
const scoreBands = computed(() => {
  const bands = [
    { label: '六十分以上', floor: 60, ceiling: 101, count: 0 },
    { label: '五十分段', floor: 50, ceiling: 60, count: 0 },
    { label: '五十分以下', floor: -1, ceiling: 50, count: 0 }
  ]
  for (const item of props.rows) {
    const score = Number(item.scorePct || 0)
    const band = bands.find((entry) => score >= entry.floor && score < entry.ceiling)
    if (band) band.count += 1
  }
  return bands.map((band) => ({
    ...band,
    width: props.rows.length ? Math.max(8, Math.round((band.count / props.rows.length) * 100)) : 0
  }))
})
const coverageRows = computed(() => {
  const groups = new Map()
  for (const item of props.rows) {
    const label = props.kind === 'role'
      ? sourceLabel(item.source || 'version')
      : (item.is_baseline ? '基线模型' : '候选模型')
    groups.set(label, (groups.get(label) || 0) + 1)
  }
  return [...groups.entries()].map(([label, count]) => ({
    label,
    count,
    width: props.rows.length ? Math.max(8, Math.round((count / props.rows.length) * 100)) : 0
  }))
})
const spreadRows = computed(() => {
  const baselineScore = Number(baselineRow.value?.scorePct ?? rankedRows.value[0]?.scorePct ?? 0)
  return rankedRows.value.slice(0, 6).map((item) => {
    const delta = Number(item.scorePct || 0) - baselineScore
    return {
      ...item,
      deltaPct: Math.round(delta),
      width: Math.max(8, Number(item.scorePct || 0))
    }
  })
})
const hasMeaningfulResult = computed(() =>
  props.rows.some((item) =>
    Number(item.scorePct || 0) > 0 ||
    Number(item.winRatePct || 0) > 0 ||
    Math.abs(Number(item.deltaScore || 0)) > 0
  )
)
const showAnalysis = computed(() => props.rows.length > 1 || hasMeaningfulResult.value)
const showRankSummary = computed(() => showAnalysis.value && rankedRows.value.length >= 3)

function sourceLabel(source) {
  const labels = {
    baseline: '基线',
    evolution: '演化',
    version: '版本',
    candidate: '候选'
  }
  return labels[source] || '其他'
}

function candidateNumber(item) {
  const currentKey = rowKey(item)
  const candidates = props.rows.filter((row) => !row.is_baseline)
  const index = candidates.findIndex((row) => row === item || rowKey(row) === currentKey)
  if (index >= 0) return index + 1
  const fallbackIndex = props.rows.findIndex((row) => row === item || rowKey(row) === currentKey)
  return fallbackIndex >= 0 ? fallbackIndex + 1 : 1
}

function rowKey(item) {
  if (!item) return ''
  return props.kind === 'model'
    ? String(item.hash || item.target_version_id || item.short || '')
    : String(item.version_id || item.short || '')
}

function rowLabel(item) {
  if (!item) return '暂无'
  if (props.kind === 'model') {
    return item.is_baseline ? '基线模型' : `候选模型${candidateNumber(item)}`
  }
  return item.is_baseline ? '基线版本' : `候选版本${candidateNumber(item)}`
}
</script>

<template>
  <div class="bench-tab-panel">
    <section v-if="showAnalysis" class="bench-board-stats">
      <span>
        <small>最优</small>
        <b>{{ topRow ? rowLabel(topRow) : '--' }}</b>
        <em>{{ topRow ? topRow.scorePct + '%' : '暂无' }}</em>
      </span>
      <span>
        <small>基线</small>
        <b>{{ baselineRow ? rowLabel(baselineRow) : '--' }}</b>
        <em>{{ baselineRow ? baselineRow.scorePct + '%' : '未标记' }}</em>
      </span>
      <span>
        <small>平均得分</small>
        <b>{{ averageScore }}</b>
      </span>
      <span>
        <small>平均胜率</small>
        <b>{{ averageWinRate }}</b>
      </span>
    </section>
    <section v-else class="bench-result-empty">
      <strong>暂无有效评测结果</strong>
      <span>启动评测后展示胜率、差异和排名摘要。</span>
    </section>

    <div :class="['bench-board-layout', { 'bench-board-layout--solo': !showRankSummary }]">
    <div class="bench-board-main">
      <article class="bench-card bench-leaderboard-card">
        <header>
          <div>
            <h2>{{ title }}</h2>
          </div>
          <b>{{ meta }}</b>
        </header>
        <div v-if="!rows.length" class="bench-empty">暂无数据</div>
        <div v-else class="bench-table">
          <div :class="['bench-row', 'bench-header', 'bench-row--' + kind]">
            <template v-if="kind === 'model'">
              <span>模型</span>
              <span>得分</span>
              <span>胜率</span>
              <span>差异</span>
            </template>
            <template v-else>
              <span>版本</span>
              <span>来源</span>
              <span>得分</span>
              <span>胜率</span>
            </template>
          </div>
          <div
            v-for="item in rows"
            :key="kind === 'model' ? item.hash : item.version_id"
            :class="['bench-row', 'bench-row--' + kind]"
          >
            <template v-if="kind === 'model'">
              <span>{{ rowLabel(item) }}</span>
              <span>{{ item.scorePct }}%</span>
              <span>{{ item.winRatePct }}%</span>
              <span :class="item.deltaScore >= 0 ? 'positive' : 'negative'">
                {{ item.deltaScore >= 0 ? '+' : '' }}{{ Math.round(item.deltaScore * 100) }}%
              </span>
            </template>
            <template v-else>
              <span>{{ rowLabel(item) }}</span>
              <span>{{ sourceLabel(item.source) }}</span>
              <span>{{ item.scorePct }}%</span>
              <span>{{ item.winRatePct }}%</span>
            </template>
          </div>
        </div>
        <section v-if="showAnalysis && spreadRows.length" class="bench-inline-spread" aria-label="相对基线">
          <div class="bench-inline-spread-head">
            <span>相对基线</span>
            <small>{{ baselineRow ? rowLabel(baselineRow) : '榜首' }}</small>
          </div>
          <div class="bench-spread-list">
            <div v-for="item in spreadRows" :key="'spread-' + (kind === 'model' ? item.hash : item.version_id)" class="bench-spread-row">
              <strong>{{ rowLabel(item) }}</strong>
              <i aria-hidden="true"><b :style="{ width: item.width + '%' }"></b></i>
              <span :class="item.deltaPct >= 0 ? 'positive' : 'negative'">
                {{ item.deltaPct >= 0 ? '+' : '' }}{{ item.deltaPct }}%
              </span>
            </div>
          </div>
        </section>
      </article>
    </div>

    <aside v-if="showRankSummary" class="bench-card bench-rank-card">
      <header>
        <div>
          <h2>排名摘要</h2>
        </div>
        <b>{{ rankedRows.length }}</b>
      </header>
      <div v-if="!rankedRows.length" class="bench-empty">暂无排名数据</div>
      <div v-else class="bench-rank-list">
        <div v-for="(item, index) in rankedRows" :key="'rank-' + (kind === 'model' ? item.hash : item.version_id)" class="bench-rank-row">
          <div class="bench-rank-copy">
            <strong>第{{ index + 1 }}名 {{ rowLabel(item) }}</strong>
            <span>胜率 {{ item.winRatePct }}%<template v-if="kind === 'role'"> · {{ sourceLabel(item.source) }}</template></span>
          </div>
          <div class="bench-rank-meter" aria-hidden="true">
            <i :style="{ width: item.scorePct + '%' }"></i>
          </div>
          <b>{{ item.scorePct }}%</b>
        </div>
      </div>
      <div v-if="rankedRows.length" class="bench-rank-block">
        <div class="bench-side-title">
          <span>分数区间</span>
          <small>{{ rows.length }} 条</small>
        </div>
        <div class="bench-band-list">
          <div v-for="band in scoreBands" :key="band.label" class="bench-band-row">
            <span>{{ band.label }}</span>
            <i aria-hidden="true"><b :style="{ width: band.width + '%' }"></b></i>
            <em>{{ band.count }}</em>
          </div>
        </div>
      </div>
      <div v-if="coverageRows.length" class="bench-rank-block">
        <div class="bench-side-title">
          <span>{{ kind === 'role' ? '来源覆盖' : '模型类型' }}</span>
          <small>{{ coverageRows.length }} 组</small>
        </div>
        <div class="bench-band-list">
          <div v-for="item in coverageRows" :key="item.label" class="bench-band-row">
            <span>{{ item.label }}</span>
            <i aria-hidden="true"><b :style="{ width: item.width + '%' }"></b></i>
            <em>{{ item.count }}</em>
          </div>
        </div>
      </div>
    </aside>
    </div>
  </div>
</template>

<style scoped>
.bench-tab-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
}

.bench-board-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.bench-board-stats span {
  display: grid;
  gap: 5px;
  min-height: 70px;
  padding: 10px 12px;
  border: 1px solid var(--bench-border);
  border-radius: 8px;
  background: var(--bench-surface);
  box-shadow: 0 1px 3px rgba(91, 47, 18, 0.04);
}

.bench-board-stats small {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
}

.bench-board-stats b {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text);
  font-size: 18px;
  font-weight: 800;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-board-stats em {
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
}

.bench-board-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 340px);
  gap: 14px;
  align-items: start;
}

.bench-board-layout--solo {
  grid-template-columns: minmax(0, 1fr);
}

.bench-board-main {
  display: grid;
  min-width: 0;
}

.bench-card {
  display: grid;
  grid-template-rows: auto auto;
  background: var(--bench-surface);
  border: 1px solid var(--bench-border);
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(91, 47, 18, 0.04);
  overflow: hidden;
}

.bench-card header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 58px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--bench-border);
  background: rgba(255, 252, 245, 0.42);
}

.bench-card header div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.bench-card header small {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1;
}

.bench-card header h2 {
  margin: 0;
  color: var(--bench-text);
  font-size: 16px;
  font-weight: 800;
}

.bench-card header b {
  max-width: 240px;
  overflow: hidden;
  padding: 2px 8px;
  border-radius: 5px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--bench-accent);
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-empty {
  padding: 32px 20px;
  color: var(--bench-text-secondary);
  font-size: 14px;
  font-weight: 600;
  text-align: center;
}

.bench-result-empty {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 0 12px;
  border: 1px solid var(--bench-border);
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.48);
}

.bench-result-empty strong {
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 800;
  white-space: nowrap;
}

.bench-result-empty span {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-table {
  display: flex;
  flex-direction: column;
  padding: 6px 8px 8px;
  overflow-x: auto;
  min-height: 0;
}

.bench-row {
  display: grid;
  grid-template-columns: minmax(112px, 0.9fr) minmax(100px, 1fr) minmax(86px, 0.7fr) minmax(90px, 0.7fr);
  gap: 10px;
  align-items: center;
  min-width: 580px;
  padding: 9px 10px;
  border-radius: 6px;
  border-bottom: 1px solid rgba(139, 94, 52, 0.08);
  color: var(--bench-text);
  font-size: 13px;
  transition: background 0.15s ease;
}

.bench-row:last-child {
  border-bottom: none;
}

.bench-row:not(.bench-header):hover {
  background: var(--bench-hover);
}

.bench-row.bench-header {
  min-height: 30px;
  border-bottom-color: var(--bench-border);
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
}

.bench-row span {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-row small {
  display: inline-flex;
  margin-left: 6px;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--bench-active-bg);
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
}

.positive {
  color: #3a7a3a !important;
  font-weight: 800 !important;
}

.negative {
  color: #9a3a3a !important;
  font-weight: 800 !important;
}

.bench-rank-list {
  display: grid;
  gap: 8px;
  align-content: start;
  padding: 12px;
}

.bench-rank-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 42px;
  gap: 8px;
  align-items: center;
  min-height: 52px;
  padding: 8px 10px;
  border: 1px solid rgba(139, 94, 52, 0.11);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.42);
}

.bench-rank-copy {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.bench-rank-copy strong,
.bench-rank-copy span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-rank-copy strong {
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 800;
}

.bench-rank-copy span {
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-weight: 800;
}

.bench-rank-meter {
  grid-column: 1 / -1;
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.12);
}

.bench-rank-meter i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--bench-accent-strong);
}

.bench-rank-row > b {
  grid-row: 1;
  grid-column: 2;
  color: var(--bench-accent-strong);
  font-size: 13px;
  font-weight: 800;
  text-align: right;
}

.bench-rank-card {
  grid-template-rows: auto auto auto auto;
  align-content: start;
}

.bench-rank-block {
  display: grid;
  gap: 8px;
  padding: 0 12px 12px;
}

.bench-side-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--bench-border);
}

.bench-side-title span {
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 800;
}

.bench-side-title small {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
}

.bench-band-list {
  display: grid;
  gap: 7px;
}

.bench-band-row,
.bench-spread-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(72px, 0.7fr) 36px;
  align-items: center;
  gap: 8px;
  min-height: 30px;
}

.bench-band-row span,
.bench-spread-row strong {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-band-row i,
.bench-spread-row i {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.12);
}

.bench-band-row i b,
.bench-spread-row i b {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--bench-accent-strong);
}

.bench-band-row em,
.bench-spread-row span {
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
  text-align: right;
}

.bench-inline-spread {
  display: grid;
  gap: 8px;
  padding: 10px 12px 12px;
  border-top: 1px solid var(--bench-border);
  background: rgba(255, 252, 245, 0.28);
}

.bench-inline-spread-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.bench-inline-spread-head span {
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 800;
}

.bench-inline-spread-head small {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-spread-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 7px 14px;
  align-content: start;
}

@media (max-width: 960px) {
  .bench-tab-panel {
    flex: initial;
    min-height: 0;
  }

  .bench-board-layout {
    grid-template-columns: 1fr;
    align-items: start;
    flex: initial;
    min-height: 0;
  }

  .bench-board-main {
    grid-template-rows: auto auto;
    min-height: 0;
  }

  .bench-card {
    grid-template-rows: auto auto;
  }

  .bench-rank-card {
    grid-column: auto;
    grid-template-rows: auto auto auto auto;
    align-content: start;
  }

}

@media (max-width: 640px) {
  .bench-board-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .bench-board-stats span {
    min-height: 60px;
    padding: 8px 10px;
  }

  .bench-board-stats b {
    font-size: 16px;
  }

  .bench-card header {
    grid-template-columns: minmax(0, 1fr);
  }

  .bench-card header b {
    justify-self: start;
    max-width: 100%;
  }
}
</style>
