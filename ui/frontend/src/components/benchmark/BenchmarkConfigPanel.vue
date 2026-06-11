<script setup lang="ts">
import { computed, type PropType } from 'vue'

type ReadableRef<T> = {
  readonly value: T
}

type BenchmarkActionLoading = '' | 'start' | `stop:${string}` | string

interface BenchmarkConfigForm {
  battle_games: number | string | null
  max_days: number | string | null
  budget_limit_units: number | string | null
  model_id: string
  model_config_hash: string
  target_version_id: string
}

interface BenchmarkSuiteSummary {
  id: string
  label: string
  roles?: string[]
  cost_tier?: string
  seed_count?: number | string | null
  seed_set_id?: string
  seed_preview?: string[]
}

interface BenchmarkLeaderboardPreviewRow {
  hash?: string
  version_id?: string
  model_id?: string
  model_config_hash?: string
  is_baseline?: boolean
  scorePct?: number | string
  winRatePct?: number | string
  source?: string
}

interface BenchmarkBatchRunRow {
  id: string
  status?: string
  statusLabel?: string
  roleKeys?: string[]
}

interface BenchmarkBudgetExceededDetail {
  value?: boolean
}

interface BenchmarkPlanBudget {
  exceeded?: boolean | BenchmarkBudgetExceededDetail | null
  estimated_units?: number | string | null
  estimated_tokens?: number | string | null
  estimated_cost?: number | string | null
  currency?: string | null
}

interface BenchmarkPlanEstimates {
  estimated_llm_call_units?: number | string | null
  estimated_tokens?: number | string | null
  estimated_cost?: number | string | null
  currency?: string | null
}

interface BenchmarkPlanJudge {
  estimated_decisions?: number | string | null
}

interface BenchmarkPlan {
  budget?: BenchmarkPlanBudget | null
  estimates?: BenchmarkPlanEstimates | null
  judge?: BenchmarkPlanJudge | null
  estimated_tokens?: number | string | null
  estimated_cost?: number | string | null
  currency?: string | null
  dry_run?: boolean
  total_games?: number | string | null
  eval_batch_count?: number | string | null
}

interface BenchmarkConfigPanelBenchmark {
  modelLeaderboardRows: ReadableRef<BenchmarkLeaderboardPreviewRow[]>
  roleLeaderboardRows: ReadableRef<BenchmarkLeaderboardPreviewRow[]>
  visibleBatchRunRows: ReadableRef<BenchmarkBatchRunRow[]>
  filteredBatchRunRows: ReadableRef<BenchmarkBatchRunRow[]>
  actionLoading: ReadableRef<BenchmarkActionLoading>
  loading: ReadableRef<boolean>
  benchmarkSuites: ReadableRef<BenchmarkSuiteSummary[]>
  benchmarkSuiteError: ReadableRef<string>
  benchmarkPlan: ReadableRef<BenchmarkPlan | null>
  benchmarkPlanError: ReadableRef<string>
  benchmarkPlanBudgetExceeded: ReadableRef<boolean>
  selectedBenchmarkId: ReadableRef<string>
  selectedBenchmarkSuite: ReadableRef<BenchmarkSuiteSummary | null>
  selectedBenchmarkIsModelSuite: ReadableRef<boolean>
  selectedBenchmarkCanLaunch: ReadableRef<boolean>
  selectedBenchmarkSuiteLabel: ReadableRef<string>
  launchBattleGames: ReadableRef<number>
  launchMaxDays: ReadableRef<number>
  selectedRole: ReadableRef<string>
  selectedRoleLabel: ReadableRef<string>
  form: ReadableRef<BenchmarkConfigForm>
  roleMeta: (role: string) => { label: string }
  selectBenchmarkSuite: (benchmarkId: string) => void
  startEvaluation: () => void | Promise<void>
}

const props = defineProps({
  benchmark: {
    type: Object as PropType<BenchmarkConfigPanelBenchmark>,
    required: true
  }
})

const modelPreviewRows = computed(() => props.benchmark.modelLeaderboardRows.value.slice(0, 5))
const rolePreviewRows = computed(() => props.benchmark.roleLeaderboardRows.value.slice(0, 5))
const recentRunRows = computed(() => props.benchmark.visibleBatchRunRows.value.slice(0, 5))
const bestModelRow = computed(() =>
  modelPreviewRows.value.reduce((best, row) => {
    if (!best) return row
    return Number(row.scorePct || 0) > Number(best.scorePct || 0) ? row : best
  }, null)
)
const batchStats = computed(() => {
  const counts = { active: 0, completed: 0, failed: 0 }
  for (const run of props.benchmark.filteredBatchRunRows.value) {
    if (run.status === 'queued' || run.status === 'running') counts.active += 1
    else if (run.status === 'completed') counts.completed += 1
    else if (run.status === 'failed') counts.failed += 1
  }
  return {
    ...counts,
    total: props.benchmark.filteredBatchRunRows.value.length
  }
})

const loadingLabel = computed(() => {
  const value = props.benchmark.actionLoading.value
  if (value === 'start') return '正在启动当前评测'
  if (String(value || '').startsWith('stop:')) return '正在停止评测'
  return props.benchmark.loading.value ? '读取中' : ''
})
const suiteRoleLabels = computed(() => {
  const roles = props.benchmark.selectedBenchmarkSuite.value?.roles || []
  if (!roles.length) return '全部角色'
  return roles.map((role) => props.benchmark.roleMeta(role).label).join('、')
})
const suiteModeLabel = computed(() =>
  props.benchmark.selectedBenchmarkId.value ? '正式套件' : '临时评测'
)
const suiteTargetTypeLabel = computed(() =>
  props.benchmark.selectedBenchmarkIsModelSuite.value ? '模型评测' : '角色版本'
)
const suiteCostTierLabel = computed(() => {
  const tier = props.benchmark.selectedBenchmarkSuite.value?.cost_tier || ''
  const labels = {
    smoke: '冒烟',
    quick: 'quick 快速',
    low: '低成本',
    medium: '中等',
    standard: 'standard 标准',
    release: 'release 发布',
    high: '高成本'
  }
  return labels[tier] || (tier ? tier : '未标注')
})
const suiteSeedSummary = computed(() => {
  const suite = props.benchmark.selectedBenchmarkSuite.value
  if (!suite) return '临时'
  if (suite.seed_count != null) {
    const count = Number(suite.seed_count)
    if (Number.isFinite(count)) return `${count} 个种子`
  }
  return suite.seed_set_id || '固定种子'
})
const suiteSeedPreview = computed(() => {
  const preview = props.benchmark.selectedBenchmarkSuite.value?.seed_preview || []
  return preview.length ? preview.join(', ') : ''
})
const launchScopeLabel = computed(() =>
  props.benchmark.selectedBenchmarkIsModelSuite.value ? '模型配置' : props.benchmark.selectedRoleLabel.value
)
const launchSubjectLabel = computed(() => {
  if (props.benchmark.selectedBenchmarkIsModelSuite.value) {
    return props.benchmark.form.value.model_id || '当前后端模型'
  }
  return props.benchmark.form.value.target_version_id || '当前基线版本'
})
const boardTitle = computed(() =>
  props.benchmark.selectedBenchmarkIsModelSuite.value ? '模型评测' : '模型与版本'
)
const modelBoardTitle = computed(() =>
  props.benchmark.selectedBenchmarkIsModelSuite.value ? '模型配置榜' : '模型榜'
)
const versionBoardTitle = computed(() =>
  props.benchmark.selectedBenchmarkIsModelSuite.value ? '角色版本榜隔离' : '角色版本榜'
)
const runPlan = computed(() => props.benchmark.benchmarkPlan.value || null)
const planBudget = computed<BenchmarkPlanBudget>(() => runPlan.value?.budget || {})
const planEstimates = computed<BenchmarkPlanEstimates>(() => runPlan.value?.estimates || {})
const planJudge = computed<BenchmarkPlanJudge>(() => runPlan.value?.judge || {})
const planBudgetExceeded = computed(() => {
  const exceeded = planBudget.value.exceeded
  if (exceeded && typeof exceeded === 'object' && !Array.isArray(exceeded)) return Boolean(exceeded.value)
  return Boolean(exceeded)
})
const budgetStatusLabel = computed(() =>
  planBudgetExceeded.value ? '超出预算' : (runPlan.value ? '预算内' : '未估算')
)
const estimatedUnitsLabel = computed(() => {
  const value = Number(planBudget.value.estimated_units ?? planEstimates.value.estimated_llm_call_units)
  return Number.isFinite(value) ? value.toLocaleString('zh-CN') : '--'
})
const estimatedTokensLabel = computed(() => {
  const value = Number(runPlan.value?.estimated_tokens ?? planBudget.value.estimated_tokens ?? planEstimates.value.estimated_tokens)
  return Number.isFinite(value) ? value.toLocaleString('zh-CN') : '--'
})
const estimatedCostLabel = computed(() => {
  const value = Number(runPlan.value?.estimated_cost ?? planBudget.value.estimated_cost ?? planEstimates.value.estimated_cost)
  const currency = runPlan.value?.currency || planBudget.value.currency || planEstimates.value.currency || 'USD'
  return Number.isFinite(value) ? `${value.toLocaleString('zh-CN', { maximumFractionDigits: 6 })} ${currency}` : '--'
})
const dryRunLabel = computed(() => (runPlan.value?.dry_run ? '仅预估不启动' : (runPlan.value ? '正式启动计划' : '未估算')))
const judgeUnitsLabel = computed(() => {
  const value = Number(planJudge.value.estimated_decisions || 0)
  return Number.isFinite(value) ? value.toLocaleString('zh-CN') : '--'
})

function modelLabel(item: BenchmarkLeaderboardPreviewRow | null | undefined, index = 0) {
  if (!item) return '暂无'
  return item.model_id || item.model_config_hash || item.hash || (item.is_baseline ? '基线模型' : `候选模型${index + 1}`)
}

function versionLabel(item: BenchmarkLeaderboardPreviewRow | null | undefined, index = 0) {
  if (!item) return '暂无'
  return item.is_baseline ? '基线版本' : `候选版本${index + 1}`
}

function sourceLabel(source: string | undefined) {
  const labels = {
    baseline: '基线',
    evolution: '演化',
    version: '版本',
    candidate: '候选'
  }
  return labels[source] || '其他'
}

function formatScore(value: unknown) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '--'
  return number.toFixed(2)
}

function selectBenchmarkSuite(event: Event) {
  props.benchmark.selectBenchmarkSuite((event.target as HTMLSelectElement | null)?.value || '')
}
</script>

<template>
  <div class="bench-tab-panel bench-tab-panel--config">
    <div class="bench-config-dashboard">
      <article class="bench-card bench-card--setup">
        <header>
          <div>
            <h2>启动配置</h2>
          </div>
        </header>
        <div class="bench-setup-grid">
          <div class="bench-form bench-form--suite">
            <label>评测套件
              <select
                :value="benchmark.selectedBenchmarkId.value"
                @change="selectBenchmarkSuite"
              >
                <option value="">临时评测</option>
                <option
                  v-for="suite in benchmark.benchmarkSuites.value"
                  :key="suite.id"
                  :value="suite.id"
                >
                  {{ suite.label }}
                </option>
              </select>
            </label>
          </div>
          <div class="bench-form bench-form--control">
            <label>对战局数
              <input
                v-model.number="benchmark.form.value.battle_games"
                type="number"
                min="1"
                max="200"
                inputmode="numeric"
                :disabled="Boolean(benchmark.selectedBenchmarkId.value)"
              />
            </label>
            <label>最大天数
              <input
                v-model.number="benchmark.form.value.max_days"
                type="number"
                min="1"
                max="100"
                inputmode="numeric"
                :disabled="Boolean(benchmark.selectedBenchmarkId.value)"
              />
            </label>
            <label>预算上限
              <input
                v-model.number="benchmark.form.value.budget_limit_units"
                type="number"
                min="0"
                max="1000000"
                inputmode="numeric"
              />
            </label>
          </div>
          <div
            v-if="benchmark.selectedBenchmarkIsModelSuite.value"
            class="bench-form bench-form--identity"
          >
            <label>模型 ID
              <input
                v-model.trim="benchmark.form.value.model_id"
                type="text"
                autocomplete="off"
                placeholder="留空使用当前后端模型"
              />
            </label>
            <label>Config Hash
              <input
                v-model.trim="benchmark.form.value.model_config_hash"
                type="text"
                autocomplete="off"
                placeholder="留空由后端生成"
              />
            </label>
          </div>
          <div
            v-else
            class="bench-form bench-form--identity"
          >
            <label>目标版本
              <input
                v-model.trim="benchmark.form.value.target_version_id"
                type="text"
                autocomplete="off"
                placeholder="留空使用基线版本"
              />
            </label>
          </div>
          <section class="bench-suite-summary">
            <span>
              <small>模式</small>
              <b>{{ suiteModeLabel }}</b>
            </span>
            <span>
              <small>对象类型</small>
              <b>{{ suiteTargetTypeLabel }}</b>
            </span>
            <span>
              <small>固定配置</small>
              <b>{{ benchmark.launchBattleGames.value }} 局 / {{ benchmark.launchMaxDays.value }} 天</b>
            </span>
            <span>
              <small>种子集</small>
              <b>{{ benchmark.selectedBenchmarkSuite.value?.seed_set_id || '临时' }}</b>
              <em v-if="suiteSeedPreview">{{ suiteSeedPreview }}</em>
            </span>
            <span>
              <small>种子摘要</small>
              <b>{{ suiteSeedSummary }}</b>
            </span>
            <span>
              <small>成本等级</small>
              <b>{{ suiteCostTierLabel }}</b>
            </span>
            <span>
              <small>角色范围</small>
              <b>{{ suiteRoleLabels }}</b>
            </span>
            <span>
              <small>被测对象</small>
              <b>{{ launchSubjectLabel }}</b>
            </span>
            <span>
              <small>预计调用单位</small>
              <b>{{ estimatedUnitsLabel }}</b>
            </span>
            <span>
              <small>预计成本</small>
              <b>{{ estimatedCostLabel }}</b>
            </span>
            <span>
              <small>预计 Token</small>
              <b>{{ estimatedTokensLabel }}</b>
            </span>
            <span>
              <small>预检模式</small>
              <b>{{ dryRunLabel }}</b>
            </span>
            <span>
              <small>总局数</small>
              <b>{{ runPlan?.total_games ?? '--' }}</b>
            </span>
            <span>
              <small>评测批次</small>
              <b>{{ runPlan?.eval_batch_count ?? '--' }}</b>
            </span>
            <span>
              <small>Judge 决策</small>
              <b>{{ judgeUnitsLabel }}</b>
            </span>
            <span :class="{ 'bench-suite-summary--danger': benchmark.benchmarkPlanBudgetExceeded.value }">
              <small>预算状态</small>
              <b>{{ budgetStatusLabel }}</b>
            </span>
          </section>
          <div v-if="benchmark.benchmarkSuiteError.value" class="bench-suite-note">
            {{ benchmark.benchmarkSuiteError.value }}
          </div>
          <div v-if="benchmark.benchmarkPlanError.value" class="bench-suite-note">
            {{ benchmark.benchmarkPlanError.value }}
          </div>
          <section class="bench-launch-row">
            <span>
              <small>评测范围</small>
              <b>{{ launchScopeLabel }}</b>
              <em>{{ benchmark.selectedBenchmarkSuiteLabel.value }}</em>
            </span>
            <button
              type="button"
              class="bench-action"
              :disabled="Boolean(benchmark.actionLoading.value) || (!benchmark.selectedBenchmarkIsModelSuite.value && !benchmark.selectedRole.value) || !benchmark.selectedBenchmarkCanLaunch.value"
              @click="benchmark.startEvaluation()"
            >
              <span aria-hidden="true">&#9654;</span>
              {{ benchmark.selectedBenchmarkIsModelSuite.value ? '评测模型' : '评测当前' }}
            </button>
          </section>
          <div class="bench-setup-stat-grid">
            <span>
              <small>模型样本</small>
              <b>{{ modelPreviewRows.length }}</b>
            </span>
            <span>
              <small>版本样本</small>
              <b>{{ rolePreviewRows.length }}</b>
            </span>
            <span>
              <small>运行中</small>
              <b>{{ batchStats.active }}</b>
            </span>
            <span>
              <small>最优模型</small>
              <b>{{ modelLabel(bestModelRow) }}</b>
              <em>{{ bestModelRow ? formatScore(bestModelRow.scorePct) : '--' }}</em>
            </span>
          </div>
        </div>
        <span v-if="benchmark.loading.value || benchmark.actionLoading.value" class="bench-loading">
          {{ loadingLabel }}
        </span>
      </article>

      <article class="bench-card bench-card--board">
        <header>
          <div>
            <h2>{{ boardTitle }}</h2>
          </div>
        </header>
        <div class="bench-board-columns">
          <div class="bench-embedded-section">
            <div class="bench-section-title">
              <span>{{ modelBoardTitle }}</span>
              <small>得分 / 胜率</small>
            </div>
            <div v-if="modelPreviewRows.length" class="bench-mini-list">
              <div v-for="(item, index) in modelPreviewRows" :key="item.hash" class="bench-mini-row">
                <span>{{ modelLabel(item, index) }}</span>
                <b>{{ formatScore(item.scorePct) }}</b>
                <em>{{ item.winRatePct }}%</em>
              </div>
            </div>
            <div v-else class="bench-mini-empty">暂无模型榜数据</div>
          </div>
          <div class="bench-embedded-section">
            <div class="bench-section-title">
              <span>{{ versionBoardTitle }}</span>
              <small>{{ benchmark.selectedBenchmarkIsModelSuite.value ? '模型范围' : '版本 / 来源' }}</small>
            </div>
            <div v-if="!benchmark.selectedBenchmarkIsModelSuite.value && rolePreviewRows.length" class="bench-mini-list">
              <div v-for="(item, index) in rolePreviewRows" :key="item.version_id" class="bench-mini-row">
                <span>{{ versionLabel(item, index) }}</span>
                <b>{{ formatScore(item.scorePct) }}</b>
                <em>{{ sourceLabel(item.source) }}</em>
              </div>
            </div>
            <div v-else-if="benchmark.selectedBenchmarkIsModelSuite.value" class="bench-mini-empty">模型榜单独隔离</div>
            <div v-else class="bench-mini-empty">暂无版本榜数据</div>
          </div>
        </div>
      </article>

      <article class="bench-card bench-card--runs">
        <header>
          <div>
            <h2>评测记录</h2>
          </div>
          <b>{{ batchStats.total }} 批</b>
        </header>
        <div class="bench-summary-grid">
          <span>
            <small>运行中</small>
            <b>{{ batchStats.active }}</b>
          </span>
          <span>
            <small>最近记录</small>
            <b>{{ recentRunRows.length }}</b>
          </span>
          <span>
            <small>已完成</small>
            <b>{{ batchStats.completed }}</b>
          </span>
          <span>
            <small>失败</small>
            <b>{{ batchStats.failed }}</b>
          </span>
        </div>
        <div class="bench-embedded-section">
          <div class="bench-section-title">
            <span>最近批次</span>
            <small>{{ recentRunRows.length }} 条</small>
          </div>
          <div v-if="recentRunRows.length" class="bench-mini-list">
            <div v-for="(run, index) in recentRunRows" :key="run.id" class="bench-mini-row">
              <span>批次{{ index + 1 }}</span>
              <b>{{ benchmark.selectedRoleLabel.value }}</b>
              <em>{{ run.statusLabel }}</em>
            </div>
          </div>
          <div v-else class="bench-mini-empty">暂无评测记录</div>
        </div>
      </article>
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

.bench-config-split {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
  align-items: start;
}

.bench-config-dashboard {
  display: grid;
  grid-template-columns: minmax(280px, 0.38fr) minmax(560px, 1fr);
  grid-template-rows: auto auto;
  grid-template-areas:
    "setup board"
    "setup runs";
  gap: 12px;
  min-height: 0;
  align-items: stretch;
}

.bench-card {
  display: grid;
  grid-template-rows: auto auto;
  align-content: start;
  background: var(--bench-surface);
  border: 1px solid var(--bench-border);
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(91, 47, 18, 0.04);
  overflow: hidden;
}

.bench-card--setup {
  grid-area: setup;
  align-self: stretch;
}

.bench-card--board {
  grid-area: board;
}

.bench-card--runs {
  grid-area: runs;
}

.bench-card header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 52px;
  padding: 9px 14px;
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
  font-size: 15px;
  font-weight: 800;
}

.bench-card header b {
  padding: 2px 8px;
  border-radius: 5px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--bench-accent);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.bench-form {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 12px 16px;
  padding: 16px;
}

.bench-form--control,
.bench-form--suite {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 0;
}

.bench-form--suite {
  grid-template-columns: minmax(0, 1fr);
}

.bench-form label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-weight: 800;
}

.bench-form input,
.bench-form select {
  box-sizing: border-box;
  width: 100%;
  height: 32px;
  padding: 0 11px;
  border: 1px solid var(--bench-input-border);
  border-radius: 6px;
  background: var(--bench-input-bg);
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 800;
  transition: border-color 0.16s ease, box-shadow 0.16s ease;
}

.bench-form input:focus,
.bench-form select:focus {
  border-color: var(--bench-accent);
  outline: none;
  box-shadow: 0 0 0 2px rgba(139, 94, 52, 0.08);
}

.bench-form input:disabled {
  opacity: 0.72;
  cursor: not-allowed;
}

.bench-suite-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}

.bench-suite-summary span {
  display: grid;
  gap: 4px;
  min-height: 48px;
  padding: 8px 9px;
  border: 1px solid rgba(139, 94, 52, 0.12);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.42);
}

.bench-suite-summary span.bench-suite-summary--danger {
  border-color: var(--bench-danger-border, rgba(153, 48, 38, 0.28));
  background: var(--bench-danger-bg, rgba(153, 48, 38, 0.06));
}

.bench-suite-summary span.bench-suite-summary--danger b {
  color: var(--bench-danger, var(--logbook-danger, #993026));
}

.bench-suite-summary small {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1;
}

.bench-suite-summary b {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 800;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-suite-summary em {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-suite-note {
  padding: 8px 9px;
  border: 1px solid var(--bench-warning-border, rgba(139, 100, 31, 0.3));
  border-radius: 7px;
  background: var(--bench-warning-bg, rgba(139, 100, 31, 0.08));
  color: var(--bench-warning, var(--logbook-warning, #8b5e34));
  font-size: 12px;
  font-weight: 800;
}

.bench-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  padding: 0 16px;
  border: 1px solid rgba(90, 51, 25, 0.18);
  border-radius: 6px;
  background: var(--bench-accent-strong);
  color: #fff7dc;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  transition: background 0.16s ease, transform 0.16s ease, box-shadow 0.16s ease;
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

.bench-loading {
  display: block;
  padding: 0 16px 14px;
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-weight: 800;
}

.bench-setup-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
  padding: 10px 12px 12px;
  align-items: stretch;
  align-content: start;
  min-height: 0;
}

.bench-launch-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 0;
  padding: 9px;
  border: 1px solid rgba(139, 94, 52, 0.12);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.42);
}

.bench-launch-row span {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.bench-launch-row small {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1;
}

.bench-launch-row b {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text);
  font-size: 16px;
  font-weight: 800;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-launch-row em {
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
}

.bench-setup-stat-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}

.bench-setup-stat-grid span {
  display: grid;
  gap: 4px;
  min-height: 58px;
  padding: 8px 9px;
  border: 1px solid rgba(139, 94, 52, 0.12);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.42);
}

.bench-setup-stat-grid small {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1;
}

.bench-setup-stat-grid b {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text);
  font-size: 15px;
  font-weight: 800;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-setup-stat-grid em {
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
}

.bench-board-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-template-rows: auto;
  gap: 0;
  min-height: 0;
  height: auto;
}

.bench-board-columns .bench-embedded-section + .bench-embedded-section {
  border-left: 1px solid var(--bench-border);
  border-top: 0;
}

.bench-embedded-section {
  display: grid;
  grid-template-rows: auto auto;
  align-content: start;
  gap: 7px;
  padding: 0 14px 14px;
  min-height: 0;
}

.bench-section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 27px;
  border-top: 1px solid var(--bench-border);
  padding-top: 10px;
}

.bench-section-title span {
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 800;
}

.bench-section-title small {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
}

.bench-mini-list {
  display: grid;
  gap: 5px;
  align-content: start;
  min-height: 0;
}

.bench-mini-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 64px 70px;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  padding: 0 9px;
  border: 1px solid rgba(139, 94, 52, 0.11);
  border-radius: 6px;
  background: rgba(255, 252, 245, 0.42);
}

.bench-mini-row span,
.bench-mini-row b,
.bench-mini-row em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-mini-row span {
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 800;
}

.bench-mini-row span small {
  margin-left: 6px;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--bench-active-bg);
  color: var(--bench-text-secondary);
  font-family: inherit;
  font-size: 11px;
  font-weight: 700;
}

.bench-mini-row b {
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 800;
}

.bench-mini-row em {
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
  text-align: right;
}

.bench-mini-empty {
  min-height: 36px;
  display: grid;
  place-items: center;
  border: 1px dashed var(--bench-border);
  border-radius: 6px;
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-weight: 800;
}

.bench-summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
  padding: 12px 14px;
}

.bench-summary-grid span {
  display: grid;
  gap: 4px;
  min-height: 48px;
  padding: 8px 9px;
  border: 1px solid var(--bench-border);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.46);
}

.bench-summary-grid small {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
}

.bench-summary-grid b {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text);
  font-size: 16px;
  font-weight: 800;
  line-height: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-summary-grid em {
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
}

@media (max-width: 1220px) {
  .bench-config-dashboard {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto auto auto;
    grid-template-areas:
      "setup"
      "board"
      "runs";
    min-height: 0;
  }

  .bench-card--board,
  .bench-card--runs {
    min-height: 0;
  }

  .bench-setup-grid {
    grid-template-columns: minmax(180px, 0.75fr) minmax(240px, 1fr) minmax(260px, 1fr);
    align-items: stretch;
  }

  .bench-form--control {
    grid-template-columns: 1fr 1fr;
  }

  .bench-summary-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .bench-board-columns {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .bench-board-columns .bench-embedded-section + .bench-embedded-section {
    border-top: 0;
    border-left: 1px solid var(--bench-border);
  }
}

@media (max-width: 900px) {
  .bench-tab-panel {
    flex: initial;
    min-height: 0;
  }

  .bench-config-dashboard {
    display: flex;
    flex-direction: column;
  }

  .bench-config-dashboard,
  .bench-config-split,
  .bench-setup-grid,
  .bench-board-columns {
    grid-template-columns: 1fr;
  }

  .bench-config-dashboard {
    grid-template-rows: auto auto auto;
    flex: initial;
    align-items: start;
  }

  .bench-card--setup,
  .bench-card--board,
  .bench-card--runs {
    grid-area: auto;
  }

  .bench-card {
    grid-template-rows: auto auto;
    align-content: start;
  }

  .bench-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .bench-board-columns {
    grid-template-rows: auto auto;
    grid-template-columns: 1fr;
    height: auto;
  }

  .bench-embedded-section {
    grid-template-rows: auto auto;
  }

  .bench-board-columns .bench-embedded-section + .bench-embedded-section {
    border-left: 0;
    border-top: 1px solid var(--bench-border);
  }
}

@media (max-width: 640px) {
  .bench-card header {
    min-height: 50px;
    padding: 9px 12px;
  }

  .bench-form,
  .bench-setup-grid,
  .bench-loading,
  .bench-embedded-section {
    padding-right: 12px;
    padding-left: 12px;
  }

  .bench-form--control {
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  .bench-launch-row {
    grid-template-columns: 1fr;
    min-height: 0;
    gap: 8px;
  }

  .bench-setup-stat-grid {
    grid-template-columns: 1fr 1fr;
  }

  .bench-launch-row .bench-action {
    width: 100%;
  }

  .bench-summary-grid {
    grid-template-columns: 1fr 1fr;
    padding: 12px;
  }

  .bench-summary-grid span {
    min-height: 58px;
    padding: 8px 10px;
  }

  .bench-summary-grid b {
    font-size: 16px;
  }

  .bench-mini-row {
    grid-template-columns: minmax(0, 1fr) 48px 58px;
    padding: 0 8px;
  }
}
</style>
