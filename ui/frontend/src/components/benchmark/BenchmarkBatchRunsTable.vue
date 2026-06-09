<script setup>
import { computed } from 'vue'

const props = defineProps({
  benchmark: {
    type: Object,
    required: true
  }
})

const rows = computed(() => props.benchmark.filteredBatchRunRows.value)
const visibleRows = computed(() => props.benchmark.visibleBatchRunRows.value)
const selectedRun = computed(() => props.benchmark.selectedBenchmarkBatchRun.value)
const selectedDetail = computed(() => props.benchmark.benchmarkBatchDetail.value)
const detailResults = computed(() => selectedDetail.value?.resultRows || [])
const detailGames = computed(() => props.benchmark.benchmarkBatchGames.value)
const detailDiagnostics = computed(() => props.benchmark.benchmarkBatchDiagnostics.value)
const detailPagination = computed(() => props.benchmark.benchmarkBatchGamePagination.value || {})

const statusCounts = computed(() => {
  const counts = { queued: 0, running: 0, completed: 0, failed: 0, other: 0 }
  for (const run of rows.value) {
    if (run.status === 'queued') counts.queued += 1
    else if (run.status === 'running') counts.running += 1
    else if (run.status === 'completed') counts.completed += 1
    else if (run.status === 'failed') counts.failed += 1
    else counts.other += 1
  }
  return counts
})
const activeCount = computed(() => statusCounts.value.queued + statusCounts.value.running)
const roleGroups = computed(() => {
  const groups = new Map()
  for (const run of rows.value) {
    const key = run.displayRole || '未知对象'
    groups.set(key, (groups.get(key) || 0) + 1)
  }
  return [...groups.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count)
})
const judgeSummary = computed(() => {
  let judged = 0
  let scoreWeight = 0
  let scoreTotal = 0
  let badWeight = 0
  let badTotal = 0
  const tagCounts = new Map()
  for (const run of rows.value) {
    const aggregate = run.judgeAggregate
    if (!aggregate) continue
    const count = Number(aggregate.judged_decisions || 0)
    const weight = count || 1
    const score = aggregate.avg_score == null ? NaN : Number(aggregate.avg_score)
    const badRate = aggregate.bad_rate == null ? NaN : Number(aggregate.bad_rate)
    judged += count
    if (Number.isFinite(score)) {
      scoreWeight += score * weight
      scoreTotal += weight
    }
    if (Number.isFinite(badRate) && count > 0) {
      badWeight += badRate * count
      badTotal += count
    }
    for (const item of aggregate.top_mistake_tags || []) {
      const tag = String(item?.tag || '')
      if (!tag) continue
      tagCounts.set(tag, (tagCounts.get(tag) || 0) + Number(item?.count || 0))
    }
  }
  const topTags = [...tagCounts.entries()]
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag))
    .slice(0, 5)
  return {
    hasData: scoreTotal > 0 || judged > 0 || topTags.length > 0,
    judged,
    avgScoreLabel: scoreTotal ? (scoreWeight / scoreTotal).toFixed(1) : '—',
    badRatePct: badTotal ? Math.round((badWeight / badTotal) * 100) : null,
    topTags
  }
})
const statusRows = computed(() => [
  { label: '排队', count: statusCounts.value.queued },
  { label: '运行', count: statusCounts.value.running },
  { label: '完成', count: statusCounts.value.completed },
  { label: '失败', count: statusCounts.value.failed },
  { label: '其他', count: statusCounts.value.other }
].map((item) => ({
  ...item,
  width: rows.value.length ? Math.max(8, Math.round((item.count / rows.value.length) * 100)) : 0
})))
const detailStatRows = computed(() => {
  const detail = selectedDetail.value
  if (!detail) return []
  const diagnostics = detail.diagnosticSummary || {}
  const games = detail.gameSummary || {}
  return [
    { label: '结果批次', value: detail.result_count ?? detailResults.value.length },
    { label: '对局总数', value: games.total ?? 0 },
    { label: '失败/超时', value: Number(games.failed || 0) + Number(games.timeout || 0) + Number(games.abnormal || 0) },
    { label: '诊断数', value: diagnostics.total ?? detailDiagnostics.value.length },
    { label: '对象类型', value: detail.targetTypeLabel },
    { label: '状态', value: detail.statusLabel }
  ]
})
const detailBenchmarkRows = computed(() => {
  const detail = selectedDetail.value
  const benchmark = detail?.benchmark || selectedRun.value?.benchmark || {}
  return [
    { label: '套件', value: detail?.benchmarkLabel || selectedRun.value?.benchmarkLabel || '临时评测' },
    { label: '评测集', value: benchmark.evaluation_set_id || selectedRun.value?.evaluationSetId || 'ad-hoc' },
    { label: '种子集', value: benchmark.seed_set_id || 'ad-hoc' },
    { label: '配置 Hash', value: benchmark.config_hash || '—' }
  ]
})
const gameStatusOptions = [
  { value: 'problem', label: '问题局' },
  { value: 'all', label: '全部' },
  { value: 'failed', label: '失败' },
  { value: 'timeout', label: '超时' },
  { value: 'abnormal', label: '异常' },
  { value: 'completed', label: '完成' }
]

function runLabel(index) {
  return `批次${index + 1}`
}

function formatPercent(value) {
  return value == null ? '—' : `${value}%`
}

function runProblemCount(run) {
  const diagnostics = Number(run?.diagnostic_summary?.total ?? run?.diagnostic_count ?? 0)
  const errored = Number(run?.result?.errored ?? run?.errored ?? 0)
  if (Number.isFinite(diagnostics) && diagnostics > 0) return diagnostics
  return Number.isFinite(errored) ? errored : 0
}

function selectRun(run) {
  props.benchmark.selectBenchmarkBatch(run?.id)
}

function isSelectedRun(run) {
  return run?.id && props.benchmark.selectedBenchmarkBatchId.value === run.id
}
</script>

<template>
  <div class="bench-tab-panel">
    <section v-if="rows.length" class="bench-run-stats">
      <span>
        <small>总数</small>
        <b>{{ rows.length }}</b>
      </span>
      <span>
        <small>运行中</small>
        <b>{{ activeCount }}</b>
      </span>
      <span>
        <small>已完成</small>
        <b>{{ statusCounts.completed }}</b>
      </span>
      <span>
        <small>失败</small>
        <b>{{ statusCounts.failed }}</b>
      </span>
      <span>
        <small>Judge</small>
        <b>{{ judgeSummary.avgScoreLabel }}</b>
        <em>{{ judgeSummary.judged }} 条决策</em>
      </span>
    </section>
    <section v-else class="bench-run-empty">
      <strong>暂无评测批次</strong>
      <span>从配置页启动评测后，这里会显示批次状态、运行详情、对局样本和诊断。</span>
    </section>

    <div class="bench-runs-layout">
      <div class="bench-runs-main">
        <article class="bench-card">
          <header>
            <div>
              <h2>评测记录</h2>
            </div>
            <b>{{ rows.length }}</b>
          </header>
          <div v-if="!rows.length" class="bench-empty">暂无评测记录</div>
          <div v-else class="bench-table">
            <div class="bench-row bench-header">
              <span>批次</span>
              <span>套件</span>
              <span>对象</span>
              <span>状态</span>
              <span>Judge</span>
              <span>诊断</span>
              <span>操作</span>
            </div>
            <div
              v-for="(run, index) in visibleRows"
              :key="run.id"
              :class="[
                'bench-row',
                {
                  'bench-row-running': ['queued', 'running'].includes(run.status),
                  'bench-row-selected': isSelectedRun(run)
                }
              ]"
            >
              <span class="bench-id">{{ runLabel(index) }}</span>
              <span>
                <b class="bench-cell-main">{{ run.benchmarkLabel }}</b>
                <small>{{ run.evaluationSetId || 'ad-hoc' }}</small>
              </span>
              <span>
                <b class="bench-cell-main">{{ run.displayRole }}</b>
                <small>{{ run.benchmarkTargetTypeLabel }}</small>
              </span>
              <span>{{ run.statusLabel }}</span>
              <span class="bench-judge-score">
                <b>{{ run.judgeScoreLabel }}</b>
                <small>{{ run.judgeDecisionCount }} 条</small>
              </span>
              <span>
                <b class="bench-cell-main">{{ runProblemCount(run) }}</b>
                <small>{{ formatPercent(run.judgeBadRatePct) }} 坏率</small>
              </span>
              <span class="bench-row-actions">
                <button
                  type="button"
                  class="bench-action small secondary"
                  :disabled="benchmark.benchmarkDetailLoading.value && isSelectedRun(run)"
                  @click="selectRun(run)"
                >
                  详情
                </button>
                <button
                  v-if="['queued', 'running'].includes(run.status)"
                  type="button"
                  class="bench-action small"
                  :disabled="Boolean(benchmark.actionLoading.value)"
                  @click="benchmark.stopBatch(run.id)"
                >
                  停止
                </button>
              </span>
            </div>
          </div>
        </article>
      </div>

      <aside class="bench-card bench-runs-side">
        <header>
          <div>
            <h2>{{ selectedRun ? '运行详情' : '状态概览' }}</h2>
          </div>
          <b>{{ selectedRun ? selectedRun.statusLabel : rows.length + ' 批' }}</b>
        </header>

        <template v-if="!selectedRun">
          <div v-if="!rows.length" class="bench-empty bench-empty--side">暂无评测记录</div>
          <template v-else>
            <div class="bench-status-grid">
              <span><small>排队</small><b>{{ statusCounts.queued }}</b></span>
              <span><small>运行</small><b>{{ statusCounts.running }}</b></span>
              <span><small>完成</small><b>{{ statusCounts.completed }}</b></span>
              <span><small>其他</small><b>{{ statusCounts.other }}</b></span>
            </div>
            <div class="bench-role-run-list">
              <div class="bench-side-title">
                <span>对象覆盖</span>
                <small>{{ roleGroups.length }} 组</small>
              </div>
              <div class="bench-run-role-rows">
                <div v-for="item in roleGroups" :key="item.label" class="bench-run-role-row">
                  <span>{{ item.label }}</span>
                  <i aria-hidden="true"><b :style="{ width: Math.max(8, Math.round(item.count / Math.max(1, rows.length) * 100)) + '%' }"></b></i>
                  <em>{{ item.count }}</em>
                </div>
              </div>
            </div>
            <div class="bench-role-run-list">
              <div class="bench-side-title">
                <span>状态占比</span>
                <small>{{ rows.length }} 批</small>
              </div>
              <div class="bench-run-role-rows">
                <div v-for="item in statusRows" :key="item.label" class="bench-run-role-row">
                  <span>{{ item.label }}</span>
                  <i aria-hidden="true"><b :style="{ width: item.width + '%' }"></b></i>
                  <em>{{ item.count }}</em>
                </div>
              </div>
            </div>
            <div v-if="judgeSummary.hasData" class="bench-role-run-list">
              <div class="bench-side-title">
                <span>Judge 标签</span>
                <small>{{ formatPercent(judgeSummary.badRatePct) }} 坏率</small>
              </div>
              <div class="bench-run-role-rows">
                <div v-for="item in judgeSummary.topTags" :key="'judge-side-' + item.tag" class="bench-run-role-row">
                  <span>{{ item.tag }}</span>
                  <i aria-hidden="true"><b :style="{ width: Math.max(8, Math.round(item.count / Math.max(1, judgeSummary.topTags[0]?.count || 1) * 100)) + '%' }"></b></i>
                  <em>{{ item.count }}</em>
                </div>
              </div>
            </div>
          </template>
        </template>

        <template v-else>
          <div v-if="benchmark.benchmarkDetailLoading.value" class="bench-empty compact">正在读取运行详情</div>
          <div v-if="benchmark.benchmarkDetailError.value" class="bench-detail-error">
            {{ benchmark.benchmarkDetailError.value }}
          </div>
          <template v-if="selectedDetail">
            <section class="bench-detail-summary">
              <span v-for="item in detailStatRows" :key="item.label">
                <small>{{ item.label }}</small>
                <b>{{ item.value }}</b>
              </span>
            </section>

            <section class="bench-role-run-list">
              <div class="bench-side-title">
                <span>隔离边界</span>
                <small>{{ selectedDetail.targetTypeLabel }}</small>
              </div>
              <div class="bench-detail-kv-list">
                <div v-for="item in detailBenchmarkRows" :key="item.label" class="bench-detail-kv">
                  <span>{{ item.label }}</span>
                  <b>{{ item.value }}</b>
                </div>
              </div>
            </section>

            <section class="bench-role-run-list">
              <div class="bench-side-title">
                <span>结果批次</span>
                <small>{{ detailResults.length }} 条</small>
              </div>
              <div v-if="detailResults.length" class="bench-detail-result-list">
                <div v-for="item in detailResults" :key="item.result_batch_id" class="bench-detail-result">
                  <div>
                    <strong>{{ item.targetRoleLabel }}</strong>
                    <span>{{ item.targetVersionShort }}</span>
                  </div>
                  <b :class="{ warning: !item.rankable }">{{ item.rankableLabel }}</b>
                  <em>{{ item.completed }}/{{ item.attempted_game_count || item.game_count }} 局</em>
                </div>
              </div>
              <div v-else class="bench-empty compact">暂无结果批次</div>
            </section>

            <section class="bench-role-run-list">
              <div class="bench-side-title">
                <span>游戏样本</span>
                <select
                  :value="benchmark.benchmarkGameStatusFilter.value"
                  @change="benchmark.setBenchmarkGameStatusFilter($event.target.value)"
                >
                  <option v-for="item in gameStatusOptions" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </option>
                </select>
              </div>
              <div v-if="detailGames.length" class="bench-game-list">
                <div v-for="game in detailGames" :key="game.result_batch_id + '-' + game.game_id" class="bench-game-row">
                  <span>
                    <strong>{{ game.game_id }}</strong>
                    <small>{{ game.history_game_id || game.replay_unavailable_reason || '无回放 ID' }}</small>
                  </span>
                  <span>{{ game.statusLabel }} · 种子 {{ game.seedLabel }}</span>
                  <em>{{ game.decision_count }} 决策 / {{ game.diagnostic_count }} 诊断</em>
                  <a
                    v-if="game.replayHash"
                    class="bench-replay-link"
                    :href="game.replayHash"
                  >
                    回放
                  </a>
                  <small v-else class="bench-replay-missing">{{ game.replay_unavailable_reason || '无回放' }}</small>
                </div>
              </div>
              <div v-else class="bench-empty compact">当前筛选下暂无游戏样本</div>
              <div class="bench-detail-footnote">
                {{ detailPagination.returned || detailGames.length }} / {{ detailPagination.total || 0 }} 条
              </div>
            </section>

            <section class="bench-role-run-list">
              <div class="bench-side-title">
                <span>诊断</span>
                <small>{{ detailDiagnostics.length }} 条</small>
              </div>
              <div v-if="detailDiagnostics.length" class="bench-diagnostic-list">
                <div
                  v-for="item in detailDiagnostics.slice(0, 12)"
                  :key="item.id"
                  :class="['bench-diagnostic-row', 'level-' + item.level]"
                >
                  <strong>{{ item.kindLabel }}</strong>
                  <span>{{ item.message }}</span>
                  <em>{{ item.targetRoleLabel }} · {{ item.stage || item.origin }}</em>
                </div>
              </div>
              <div v-else class="bench-empty compact">暂无诊断</div>
            </section>
          </template>
        </template>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.bench-tab-panel {
  --bench-bg: #f8f0e0;
  --bench-surface: rgba(255, 252, 245, 0.7);
  --bench-border: rgba(139, 94, 52, 0.15);
  --bench-text: #3a2a18;
  --bench-text-secondary: #8b6b4a;
  --bench-accent: #8b5e34;
  --bench-accent-strong: #5a3319;
  --bench-input-bg: rgba(255, 252, 245, 0.7);
  --bench-input-border: rgba(139, 94, 52, 0.2);
  --bench-hover: rgba(139, 94, 52, 0.06);
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
  color: var(--bench-text);
}

.bench-run-stats {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.bench-run-stats span {
  display: grid;
  gap: 5px;
  min-height: 70px;
  padding: 10px 12px;
  border: 1px solid var(--bench-border);
  border-radius: 8px;
  background: var(--bench-surface);
  box-shadow: 0 1px 3px rgba(91, 47, 18, 0.04);
}

.bench-run-stats small,
.bench-run-stats em {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
}

.bench-run-stats em {
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
}

.bench-run-stats b {
  color: var(--bench-text);
  font-size: 18px;
  font-weight: 800;
  line-height: 1;
}

.bench-runs-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 390px);
  gap: 14px;
  align-items: start;
}

.bench-runs-main {
  display: grid;
  gap: 14px;
  min-width: 0;
}

.bench-run-empty {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 0 12px;
  border: 1px solid var(--bench-border);
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.48);
}

.bench-run-empty strong,
.bench-run-empty span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-run-empty strong {
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 800;
}

.bench-run-empty span {
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-weight: 700;
}

.bench-card {
  display: grid;
  grid-template-rows: auto auto;
  background: var(--bench-surface);
  border: 1px solid var(--bench-border);
  border-radius: 8px;
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

.bench-card header h2 {
  margin: 0;
  color: var(--bench-text);
  font-size: 16px;
  font-weight: 800;
}

.bench-card header b {
  max-width: 160px;
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

.bench-empty.compact {
  padding: 16px 12px;
  border-top: 1px solid var(--bench-border);
  font-size: 12px;
  font-weight: 800;
}

.bench-empty--side {
  padding: 24px 16px;
  font-size: 13px;
  font-weight: 800;
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
  grid-template-columns:
    minmax(86px, 0.5fr)
    minmax(156px, 0.95fr)
    minmax(130px, 0.8fr)
    minmax(76px, 0.45fr)
    minmax(80px, 0.5fr)
    minmax(82px, 0.48fr)
    minmax(124px, 0.62fr);
  gap: 10px;
  align-items: center;
  min-width: 880px;
  padding: 9px 10px;
  border-radius: 6px;
  border-bottom: 1px solid rgba(139, 94, 52, 0.08);
  color: var(--bench-text);
  font-size: 13px;
  transition: background 0.15s ease, box-shadow 0.15s ease;
}

.bench-row:last-child {
  border-bottom: none;
}

.bench-row:not(.bench-header):hover {
  background: var(--bench-hover);
}

.bench-row-running {
  background: rgba(255, 226, 157, 0.22);
}

.bench-row-selected {
  background: rgba(224, 184, 111, 0.24);
  box-shadow: inset 3px 0 0 var(--bench-accent-strong);
}

.bench-row.bench-header {
  min-height: 30px;
  border-bottom-color: var(--bench-border);
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
}

.bench-row span,
.bench-row small,
.bench-cell-main,
.bench-id {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-row span {
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 700;
}

.bench-cell-main {
  display: block;
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 800;
}

.bench-row small {
  display: block;
  margin-top: 3px;
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 800;
}

.bench-id {
  color: var(--bench-text-secondary) !important;
  font-size: 12px !important;
}

.bench-judge-score {
  display: inline-grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: baseline;
  gap: 6px;
}

.bench-judge-score b {
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 800;
}

.bench-row-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.bench-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 34px;
  padding: 0 18px;
  border: 1px solid rgba(90, 51, 25, 0.18);
  border-radius: 6px;
  background: var(--bench-accent-strong);
  color: #f8f0e0;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  transition: background 0.16s ease, transform 0.16s ease;
  box-shadow: 0 2px 6px rgba(91, 47, 18, 0.15);
}

.bench-action:hover {
  background: var(--bench-accent);
  transform: translateY(-1px);
}

.bench-action:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  box-shadow: none;
}

.bench-action.small {
  height: 28px;
  padding: 0 10px;
  border-radius: 5px;
  font-size: 12px;
  font-weight: 700;
}

.bench-action.secondary {
  color: var(--bench-accent-strong);
  background: rgba(255, 245, 214, 0.78);
}

.bench-status-grid,
.bench-detail-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 12px;
}

.bench-status-grid span,
.bench-detail-summary span {
  display: grid;
  gap: 4px;
  min-height: 54px;
  padding: 9px 10px;
  border: 1px solid rgba(139, 94, 52, 0.11);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.42);
}

.bench-status-grid small,
.bench-detail-summary small {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
}

.bench-status-grid b,
.bench-detail-summary b {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text);
  font-size: 16px;
  font-weight: 800;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-role-run-list {
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

.bench-side-title small,
.bench-side-title select {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
}

.bench-side-title select {
  height: 28px;
  min-width: 92px;
  border: 1px solid var(--bench-input-border);
  border-radius: 6px;
  background: var(--bench-input-bg);
}

.bench-run-role-rows,
.bench-detail-kv-list,
.bench-detail-result-list,
.bench-game-list,
.bench-diagnostic-list {
  display: grid;
  gap: 7px;
}

.bench-run-role-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 72px 24px;
  align-items: center;
  gap: 8px;
  min-height: 30px;
}

.bench-run-role-row span,
.bench-detail-kv span,
.bench-detail-kv b,
.bench-detail-result strong,
.bench-detail-result span,
.bench-game-row strong,
.bench-game-row span,
.bench-game-row small,
.bench-game-row em,
.bench-game-row a,
.bench-diagnostic-row strong,
.bench-diagnostic-row span,
.bench-diagnostic-row em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-run-role-row span {
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 800;
}

.bench-run-role-row i {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.12);
}

.bench-run-role-row i b {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--bench-accent-strong);
}

.bench-run-role-row em {
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
  text-align: right;
}

.bench-runs-side {
  grid-template-rows: auto auto;
  align-content: start;
}

.bench-detail-error {
  margin: 12px;
  padding: 9px 10px;
  border: 1px solid rgba(90, 51, 25, 0.28);
  border-radius: 7px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--bench-accent-strong);
  font-size: 12px;
  font-weight: 800;
}

.bench-detail-kv,
.bench-detail-result,
.bench-game-row,
.bench-diagnostic-row {
  display: grid;
  gap: 4px;
  min-height: 40px;
  padding: 8px 9px;
  border: 1px solid rgba(139, 94, 52, 0.11);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.42);
}

.bench-detail-kv {
  grid-template-columns: 86px minmax(0, 1fr);
  align-items: center;
}

.bench-detail-kv span {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 800;
}

.bench-detail-kv b {
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 800;
  text-align: right;
}

.bench-detail-result {
  grid-template-columns: minmax(0, 1fr) 58px 64px;
  align-items: center;
}

.bench-detail-result div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.bench-detail-result strong,
.bench-game-row strong,
.bench-diagnostic-row strong {
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 800;
}

.bench-detail-result span,
.bench-game-row span,
.bench-game-row small,
.bench-diagnostic-row span,
.bench-diagnostic-row em {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 800;
}

.bench-detail-result b {
  color: var(--bench-accent-strong);
  font-size: 12px;
  font-weight: 800;
  text-align: right;
}

.bench-detail-result b.warning {
  color: var(--bench-accent);
}

.bench-detail-result em,
.bench-game-row em {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
  text-align: right;
}

.bench-game-row {
  grid-template-columns: minmax(120px, 1fr) minmax(86px, 0.72fr) minmax(92px, 0.78fr) auto;
  align-items: center;
  gap: 8px;
}

.bench-game-row > span:first-child {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.bench-replay-link,
.bench-replay-missing {
  justify-self: end;
  font-size: 11px;
  font-weight: 900;
}

.bench-replay-link {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 8px;
  border: 1px solid var(--bench-accent-strong);
  border-radius: 6px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--bench-accent-strong);
  text-decoration: none;
}

.bench-replay-missing {
  color: var(--bench-text-secondary);
}

.bench-diagnostic-row {
  border-left: 3px solid rgba(139, 94, 52, 0.28);
}

.bench-diagnostic-row.level-error {
  border-left-color: var(--bench-accent-strong);
}

.bench-diagnostic-row.level-warning {
  border-left-color: var(--bench-accent);
}

.bench-detail-footnote {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 800;
  text-align: right;
}

@media (max-width: 960px) {
  .bench-tab-panel {
    flex: initial;
    min-height: 0;
  }

  .bench-runs-layout {
    grid-template-columns: 1fr;
    align-items: start;
    flex: initial;
    min-height: 0;
  }

  .bench-runs-main {
    grid-template-rows: auto auto;
    min-height: 0;
  }

  .bench-card {
    grid-template-rows: auto auto;
  }
}

@media (max-width: 640px) {
  .bench-run-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .bench-run-stats span {
    min-height: 60px;
    padding: 8px 10px;
  }

  .bench-card header {
    grid-template-columns: minmax(0, 1fr);
  }

  .bench-card header b {
    justify-self: start;
  }
}
</style>
