<script setup>
import { computed, onMounted, ref } from 'vue'
import { useEvaluationWorkbench } from '../composables/useEvaluationWorkbench.js'
import ApiErrorPanel from '../components/ApiErrorPanel.vue'
import BenchmarkBatchRunsTable from '../components/benchmark/BenchmarkBatchRunsTable.vue'
import BenchmarkBoundaryBar from '../components/benchmark/BenchmarkBoundaryBar.vue'
import BenchmarkComparisonView from '../components/benchmark/BenchmarkComparisonView.vue'
import BenchmarkDiagnosticsExplorer from '../components/benchmark/BenchmarkDiagnosticsExplorer.vue'
import BenchmarkRunReportPanel from '../components/benchmark/BenchmarkRunReportPanel.vue'
import BenchmarkSnapshotReleasePanel from '../components/benchmark/BenchmarkSnapshotReleasePanel.vue'
import BenchmarkSuiteRail from '../components/benchmark/BenchmarkSuiteRail.vue'
import BenchmarkTargetSelector from '../components/benchmark/BenchmarkTargetSelector.vue'
import { inlineNoticeForDisplay, noticeErrorForPanel } from '../composables/apiErrorDisplay.js'

defineOptions({
  inheritAttrs: false
})

defineProps({
  returnToMatchAvailable: Boolean
})

const benchmark = useEvaluationWorkbench()
const activeView = ref('overview')
const launchConfirmationOpen = ref(false)

const navTabs = [
  { key: 'overview', label: 'Overview' },
  { key: 'leaderboards', label: 'Leaderboards' },
  { key: 'runs', label: 'Runs' },
  { key: 'diagnostics', label: 'Diagnostics' },
  { key: 'reports', label: 'Reports' }
]

const benchNotice = computed(() => {
  if (benchmark.notice.value?.message) return benchmark.notice.value
  if (benchmark.error.value) return { type: 'error', message: benchmark.error.value }
  return null
})
const benchInlineNotice = computed(() => inlineNoticeForDisplay(benchNotice.value))
const benchErrorNotice = computed(() => noticeErrorForPanel(benchNotice.value))
const plan = computed(() => benchmark.benchmarkPlan.value || null)
const planBudget = computed(() => plan.value?.budget || {})
const planEstimates = computed(() => plan.value?.estimates || {})
const planJudge = computed(() => plan.value?.judge || {})
const planWarnings = computed(() => Array.isArray(plan.value?.warnings) ? plan.value.warnings : [])
const activeRuns = computed(() => benchmark.filteredBatchRunRows.value.filter((run) => run.isActive).slice(0, 4))
const recentRuns = computed(() => benchmark.visibleBatchRunRows.value.slice(0, 5))
const selectedSuite = computed(() => benchmark.selectedBenchmarkSuite.value || null)
const selectedModeLabel = computed(() =>
  benchmark.selectedBenchmarkIsModelSuite.value ? 'Model Benchmark' : 'Role-Version Benchmark'
)
const budgetStatusLabel = computed(() => {
  if (!plan.value) return 'Plan pending'
  return benchmark.benchmarkPlanBudgetExceeded.value ? 'Budget exceeded' : 'Budget ok'
})
const estimatedUnitsLabel = computed(() => {
  const value = planBudget.value.estimated_units ?? planEstimates.value.estimated_llm_call_units
  return formatNumber(value)
})
const estimatedUnits = computed(() =>
  numberOrNull(planBudget.value.estimated_units ?? planEstimates.value.estimated_llm_call_units)
)
const budgetLimitUnits = computed(() => numberOrNull(planBudget.value.limit_units))
const budgetDeltaUnits = computed(() => {
  if (estimatedUnits.value == null || budgetLimitUnits.value == null) return null
  return budgetLimitUnits.value - estimatedUnits.value
})
const budgetDeltaLabel = computed(() => {
  if (budgetDeltaUnits.value == null) return 'No launch limit'
  const prefix = budgetDeltaUnits.value >= 0 ? '+' : '-'
  return `${prefix}${formatNumber(Math.abs(budgetDeltaUnits.value))} units`
})
const budgetDeltaCaption = computed(() =>
  budgetDeltaUnits.value == null
    ? 'set a limit to enforce stop-before-launch'
    : (budgetDeltaUnits.value >= 0 ? 'remaining before launch' : 'over limit; launch blocked')
)
const gameDecisionUnitsLabel = computed(() => formatNumber(planEstimates.value.game_decision_units))
const judgeUnitValue = computed(() =>
  planEstimates.value.judge_decision_units ?? planJudge.value.estimated_decisions ?? plan.value?.judge_decisions
)
const judgeDecisionLabel = computed(() => formatNumber(judgeUnitValue.value))
const totalGamesLabel = computed(() => formatNumber(plan.value?.total_games))
const evalBatchLabel = computed(() => formatNumber(plan.value?.eval_batch_count))
const suiteCostTier = computed(() => String(plan.value?.cost_tier || selectedSuite.value?.cost_tier || 'ad_hoc').toLowerCase())
const requiresLaunchConfirmation = computed(() =>
  ['standard', 'release'].includes(suiteCostTier.value)
)
const formalLaunchLabel = computed(() =>
  benchmark.selectedBenchmarkId.value ? `${suiteCostTier.value || 'suite'} / official boundary` : 'ad-hoc / not official'
)
const expectedDurationLabel = computed(() => {
  const explicitSeconds = numberOrNull(
    planEstimates.value.expected_duration_seconds ??
    planEstimates.value.duration_seconds ??
    plan.value?.expected_duration_seconds
  )
  if (explicitSeconds != null) return formatDuration(explicitSeconds)
  const totalGames = numberOrNull(plan.value?.total_games)
  const maxDays = numberOrNull(plan.value?.max_days)
  if (totalGames != null && maxDays != null) return `${formatNumber(totalGames * maxDays)} game-days`
  return 'Plan pending'
})
const concurrencyLabel = computed(() => {
  const value = numberOrNull(planJudge.value.concurrency ?? plan.value?.concurrency)
  return value == null ? 'Backend default' : `${formatNumber(value)} judge workers`
})
const planCostRows = computed(() => [
  {
    key: 'game',
    label: 'Game Units',
    value: gameDecisionUnitsLabel.value,
    caption: `${formatNumber(planEstimates.value.player_count || 12)} players x days x games`
  },
  {
    key: 'judge',
    label: 'Judge Units',
    value: judgeDecisionLabel.value,
    caption: planJudge.value.enabled ? `${formatNumber(planJudge.value.max_decisions_per_game)} max decisions/game` : 'decision judge disabled'
  },
  {
    key: 'limit',
    label: 'Budget Limit',
    value: budgetLimitUnits.value == null ? 'No limit' : `${formatNumber(budgetLimitUnits.value)} units`,
    caption: 'checked before launch'
  },
  {
    key: 'remaining',
    label: budgetDeltaUnits.value == null || budgetDeltaUnits.value >= 0 ? 'Remaining' : 'Over Limit',
    value: budgetDeltaLabel.value,
    caption: budgetDeltaCaption.value,
    danger: budgetDeltaUnits.value != null && budgetDeltaUnits.value < 0
  }
])
const planPolicyRows = computed(() => [
  {
    key: 'duration',
    label: 'Expected Duration',
    value: expectedDurationLabel.value,
    caption: 'workload band before launch'
  },
  {
    key: 'concurrency',
    label: 'Concurrency',
    value: concurrencyLabel.value,
    caption: planJudge.value.timeout_seconds ? `${formatNumber(planJudge.value.timeout_seconds)}s judge timeout` : 'runtime policy'
  },
  {
    key: 'formality',
    label: 'Formality',
    value: formalLaunchLabel.value,
    caption: benchmark.selectedBenchmarkId.value ? 'eligible for isolated leaderboard' : 'ad-hoc runs do not freeze official evidence'
  },
  {
    key: 'confirmation',
    label: 'Launch Gate',
    value: requiresLaunchConfirmation.value ? 'Confirm required' : 'Direct launch',
    caption: requiresLaunchConfirmation.value ? 'standard/release guardrail' : 'quick suite or ad-hoc'
  }
])
const launchSubjectLabel = computed(() => {
  if (benchmark.selectedBenchmarkIsModelSuite.value) {
    return benchmark.form.value.model_config_hash || benchmark.form.value.model_id || 'current backend model'
  }
  return `${benchmark.selectedRoleLabel.value} / ${benchmark.form.value.target_version_id || 'baseline'}`
})

function numberOrNull(value) {
  if (value == null || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function formatNumber(value, fallback = '--') {
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN') : fallback
}

function refresh() {
  benchmark.refreshAll({ notify: true })
}

function selectRun(run) {
  if (!run?.id) return
  benchmark.selectBenchmarkBatch(run.id)
  activeView.value = 'runs'
}

function formatDuration(seconds) {
  const value = Number(seconds)
  if (!Number.isFinite(value) || value < 0) return 'Plan pending'
  if (value < 90) return `${Math.round(value)}s`
  const minutes = Math.round(value / 60)
  if (minutes < 90) return `${minutes}m`
  const hours = Math.round(minutes / 60)
  return `${hours}h`
}

async function launchBenchmark() {
  launchConfirmationOpen.value = false
  await benchmark.startEvaluation()
}

function requestLaunch() {
  if (requiresLaunchConfirmation.value && !launchConfirmationOpen.value) {
    launchConfirmationOpen.value = true
    return
  }
  void launchBenchmark()
}

function cancelLaunchConfirmation() {
  launchConfirmationOpen.value = false
}

onMounted(() => benchmark.refreshAll())
</script>

<template>
  <section class="bench-page" aria-label="Benchmark Workbench">
    <div class="bench-workbench-shell">
      <BenchmarkSuiteRail :benchmark="benchmark" />

      <main class="bench-workbench-main">
        <header class="bench-workbench-header">
          <div class="bench-title-block">
            <small>Evaluation Console</small>
            <h1>Benchmark Workbench</h1>
          </div>
          <div class="bench-header-meta">
            <span>
              <small>Mode</small>
              <b>{{ selectedModeLabel }}</b>
            </span>
            <span>
              <small>Suite</small>
              <b>{{ benchmark.selectedBenchmarkSuiteLabel.value }}</b>
            </span>
            <span :class="{ danger: benchmark.benchmarkPlanBudgetExceeded.value }">
              <small>Budget</small>
              <b>{{ budgetStatusLabel }}</b>
            </span>
          </div>
          <button type="button" class="bench-refresh-button" @click="refresh">
            Refresh
          </button>
        </header>

        <BenchmarkBoundaryBar :benchmark="benchmark" />

        <nav class="bench-view-tabs" aria-label="Benchmark workbench views">
          <button
            v-for="tab in navTabs"
            :key="tab.key"
            type="button"
            :class="{ active: activeView === tab.key }"
            @click="activeView = tab.key"
          >
            {{ tab.label }}
          </button>
        </nav>

        <ApiErrorPanel
          v-if="benchErrorNotice"
          :error="benchErrorNotice"
          title="评测操作失败"
          compact
        />
        <div
          v-else-if="benchInlineNotice"
          :class="['bench-alert', `bench-alert--${benchInlineNotice.type}`]"
        >
          {{ benchInlineNotice.message }}
        </div>

        <section v-if="activeView === 'overview'" class="bench-overview">
          <div class="bench-overview-primary">
            <BenchmarkTargetSelector :benchmark="benchmark" />

            <article class="bench-panel bench-planner-panel">
              <header>
                <div>
                  <small>Run Planner</small>
                  <h2>Launch Plan</h2>
                </div>
                <b>{{ budgetStatusLabel }}</b>
              </header>
              <div class="bench-plan-grid">
                <span>
                  <small>Total Games</small>
                  <b>{{ totalGamesLabel }}</b>
                </span>
                <span>
                  <small>Eval Batches</small>
                  <b>{{ evalBatchLabel }}</b>
                </span>
                <span>
                  <small>Judge Decisions</small>
                  <b>{{ judgeDecisionLabel }}</b>
                </span>
                <span :class="{ danger: benchmark.benchmarkPlanBudgetExceeded.value }">
                  <small>Estimated Units</small>
                  <b>{{ estimatedUnitsLabel }}</b>
                </span>
              </div>
              <div class="bench-plan-controls">
                <label>
                  <span>Games</span>
                  <input
                    v-model.number="benchmark.form.value.battle_games"
                    type="number"
                    min="1"
                    max="200"
                    :disabled="Boolean(benchmark.selectedBenchmarkId.value)"
                  />
                </label>
                <label>
                  <span>Max Days</span>
                  <input
                    v-model.number="benchmark.form.value.max_days"
                    type="number"
                    min="1"
                    max="100"
                    :disabled="Boolean(benchmark.selectedBenchmarkId.value)"
                  />
                </label>
                <label>
                  <span>Budget Limit</span>
                  <input
                    v-model.number="benchmark.form.value.budget_limit_units"
                    type="number"
                    min="0"
                    max="1000000"
                  />
                </label>
              </div>
              <div class="bench-cost-breakdown" aria-label="Benchmark cost breakdown">
                <span
                  v-for="item in planCostRows"
                  :key="item.key"
                  :class="{ danger: item.danger }"
                >
                  <small>{{ item.label }}</small>
                  <b>{{ item.value }}</b>
                  <em>{{ item.caption }}</em>
                </span>
              </div>
              <div class="bench-policy-breakdown" aria-label="Benchmark execution policy">
                <span v-for="item in planPolicyRows" :key="item.key">
                  <small>{{ item.label }}</small>
                  <b>{{ item.value }}</b>
                  <em>{{ item.caption }}</em>
                </span>
              </div>
              <div v-if="planWarnings.length" class="bench-plan-warnings">
                <span v-for="warning in planWarnings" :key="warning.kind || warning.message">
                  <b>{{ warning.kind || 'warning' }}</b>
                  <em>{{ warning.message || 'Plan warning' }}</em>
                </span>
              </div>
              <div v-if="benchmark.benchmarkPlanError.value" class="bench-inline-warning">
                {{ benchmark.benchmarkPlanError.value }}
              </div>
              <footer class="bench-launch-strip">
                <span>
                  <small>Subject</small>
                  <b>{{ launchSubjectLabel }}</b>
                  <em>{{ selectedSuite?.evaluation_set_id || 'ad-hoc evaluation' }}</em>
                </span>
                <button
                  type="button"
                  class="bench-launch-button"
                  :disabled="Boolean(benchmark.actionLoading.value) || !benchmark.selectedBenchmarkCanLaunch.value"
                  @click="requestLaunch"
                >
                  <template v-if="requiresLaunchConfirmation && !launchConfirmationOpen">Review Launch</template>
                  <template v-else>{{ benchmark.selectedBenchmarkIsModelSuite.value ? 'Run Model Benchmark' : 'Run Role Benchmark' }}</template>
                </button>
              </footer>
              <section v-if="launchConfirmationOpen" class="bench-launch-confirmation" aria-label="Benchmark launch confirmation">
                <div>
                  <small>{{ suiteCostTier }} suite confirmation</small>
                  <b>Confirm launch boundary and budget before execution.</b>
                </div>
                <dl>
                  <div>
                    <dt>Games</dt>
                    <dd>{{ totalGamesLabel }}</dd>
                  </div>
                  <div>
                    <dt>Judge Decisions</dt>
                    <dd>{{ judgeDecisionLabel }}</dd>
                  </div>
                  <div>
                    <dt>Estimated Units</dt>
                    <dd>{{ estimatedUnitsLabel }}</dd>
                  </div>
                  <div>
                    <dt>Concurrency</dt>
                    <dd>{{ concurrencyLabel }}</dd>
                  </div>
                  <div>
                    <dt>Evaluation Set</dt>
                    <dd>{{ selectedSuite?.evaluation_set_id || 'ad-hoc' }}</dd>
                  </div>
                  <div>
                    <dt>Seed Set</dt>
                    <dd>{{ selectedSuite?.seed_set_id || plan?.seed_set_id || 'ad-hoc' }}</dd>
                  </div>
                </dl>
                <footer>
                  <button type="button" class="bench-confirm-secondary" @click="cancelLaunchConfirmation">
                    Cancel
                  </button>
                  <button
                    type="button"
                    class="bench-confirm-primary"
                    :disabled="Boolean(benchmark.actionLoading.value) || !benchmark.selectedBenchmarkCanLaunch.value"
                    @click="launchBenchmark"
                  >
                    Confirm Launch
                  </button>
                </footer>
              </section>
              <span v-if="benchmark.loading.value || benchmark.actionLoading.value" class="bench-loading">
                {{ benchmark.actionLoading.value === 'start' ? 'Launching benchmark' : 'Loading benchmark data' }}
              </span>
            </article>
          </div>

          <aside class="bench-overview-side">
            <article class="bench-panel">
              <header>
                <div>
                  <small>Active Runs</small>
                  <h2>Execution</h2>
                </div>
                <b>{{ activeRuns.length }}</b>
              </header>
              <div v-if="activeRuns.length" class="bench-run-stack">
                <button
                  v-for="run in activeRuns"
                  :key="run.id"
                  type="button"
                  class="bench-run-card"
                  @click="selectRun(run)"
                >
                  <strong>{{ run.benchmarkLabel }}</strong>
                  <span>{{ run.statusLabel }} / {{ run.progress?.percent ? Math.round(run.progress.percent * 100) + '%' : 'progress pending' }}</span>
                </button>
              </div>
              <div v-else class="bench-empty-compact">No active benchmark runs.</div>
            </article>

            <article class="bench-panel">
              <header>
                <div>
                  <small>Recent Runs</small>
                  <h2>Latest Evidence</h2>
                </div>
                <b>{{ recentRuns.length }}</b>
              </header>
              <div v-if="recentRuns.length" class="bench-run-stack">
                <button
                  v-for="run in recentRuns"
                  :key="run.id"
                  type="button"
                  class="bench-run-card"
                  @click="selectRun(run)"
                >
                  <strong>{{ run.benchmarkLabel }}</strong>
                  <span>{{ run.displayRole }} / {{ run.statusLabel }} / {{ run.rankableLabel }}</span>
                </button>
              </div>
              <div v-else class="bench-empty-compact">No benchmark runs yet.</div>
            </article>
          </aside>
        </section>

        <BenchmarkComparisonView
          v-if="activeView === 'leaderboards'"
          :benchmark="benchmark"
        />

        <BenchmarkBatchRunsTable
          v-if="activeView === 'runs'"
          :benchmark="benchmark"
        />

        <BenchmarkDiagnosticsExplorer
          v-if="activeView === 'diagnostics'"
          :benchmark="benchmark"
        />

        <section
          v-if="activeView === 'reports'"
          class="bench-reports-view"
        >
          <BenchmarkSnapshotReleasePanel :benchmark="benchmark" />
          <BenchmarkRunReportPanel :benchmark="benchmark" />
        </section>
      </main>
    </div>
  </section>
</template>

<style scoped>
.bench-page {
  --bench-surface: #ffffff;
  --bench-border: #d8dedb;
  --bench-text: #1f2a27;
  --bench-text-secondary: #66736d;
  --bench-accent: #256b8f;
  --bench-accent-strong: #1f6f54;
  --bench-input-bg: #ffffff;
  --bench-input-border: #cbd5d0;
  --bench-hover: #f2f5f3;
  --bench-active-bg: #e6f2ee;
  --bench-danger: #a13d36;
  --bench-warning: #8b641f;
  --bench-font: "Segoe UI", "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif;
  --status-danger: var(--bench-danger);
  --text-main: var(--bench-text);
  --text-muted: var(--bench-text-secondary);
  position: fixed;
  z-index: 11;
  top: 72px;
  right: 0;
  bottom: 0;
  left: 0;
  overflow: hidden;
  background: #eef2f0;
  color: var(--bench-text);
  font-family: var(--bench-font);
}

.bench-page *:not(svg):not(svg *) {
  box-sizing: border-box;
  font-family: var(--bench-font);
}

.bench-workbench-shell {
  display: grid;
  grid-template-columns: 316px minmax(0, 1fr);
  gap: 14px;
  height: 100%;
  min-height: 0;
  padding: 14px;
}

.bench-workbench-main {
  display: grid;
  grid-template-rows: auto auto auto auto minmax(0, 1fr);
  gap: 10px;
  min-width: 0;
  min-height: 0;
}

.bench-workbench-header {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(420px, 1.3fr) auto;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--bench-border);
  border-radius: 8px;
  background: #ffffff;
}

.bench-title-block {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.bench-title-block small,
.bench-header-meta small,
.bench-panel header small,
.bench-plan-grid small,
.bench-plan-controls span,
.bench-launch-strip small,
.bench-run-card span {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
}

.bench-title-block h1 {
  min-width: 0;
  overflow: hidden;
  margin: 0;
  color: var(--bench-text);
  font-size: 22px;
  font-weight: 950;
  line-height: 1.05;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-header-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  min-width: 0;
}

.bench-header-meta span {
  display: grid;
  gap: 3px;
  min-width: 0;
  min-height: 42px;
  padding: 7px 9px;
  border: 1px solid var(--bench-border);
  border-radius: 6px;
  background: #f7f8f8;
}

.bench-header-meta span.danger {
  border-color: rgba(161, 61, 54, 0.32);
  background: #fff6f5;
}

.bench-header-meta b,
.bench-panel header b,
.bench-plan-grid b,
.bench-launch-strip b,
.bench-launch-strip em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-header-meta b {
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 900;
}

.bench-refresh-button,
.bench-launch-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 36px;
  padding: 0 14px;
  border: 1px solid #1a5944;
  border-radius: 6px;
  background: #1f6f54;
  color: #ffffff;
  font-size: 13px;
  font-weight: 900;
  cursor: pointer;
}

.bench-refresh-button:hover,
.bench-launch-button:hover {
  background: #185a43;
}

.bench-launch-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.bench-view-tabs {
  display: flex;
  gap: 6px;
  min-width: 0;
  padding: 4px;
  border: 1px solid var(--bench-border);
  border-radius: 8px;
  background: #ffffff;
}

.bench-view-tabs button {
  height: 32px;
  padding: 0 14px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
}

.bench-view-tabs button.active {
  border-color: #1f6f54;
  background: #e6f2ee;
  color: #153f31;
}

.bench-alert {
  padding: 9px 12px;
  border: 1px solid rgba(161, 61, 54, 0.26);
  border-radius: 8px;
  background: rgba(161, 61, 54, 0.06);
  color: var(--bench-danger);
  font-size: 12px;
  font-weight: 800;
}

.bench-alert--success {
  border-color: rgba(31, 111, 84, 0.28);
  background: rgba(31, 111, 84, 0.08);
  color: #1f6f54;
}

.bench-alert--warning {
  border-color: rgba(139, 100, 31, 0.3);
  background: rgba(139, 100, 31, 0.08);
  color: var(--bench-warning);
}

.bench-overview,
.bench-diagnostics-view {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(300px, 360px);
  gap: 12px;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.bench-overview-primary,
.bench-overview-side,
.bench-leaderboard-stack,
.bench-diagnostics-view {
  min-width: 0;
  min-height: 0;
}

.bench-overview-primary,
.bench-overview-side,
.bench-leaderboard-stack {
  display: grid;
  align-content: start;
  gap: 12px;
  overflow-y: auto;
  padding-right: 2px;
}

.bench-panel {
  display: grid;
  grid-template-rows: auto auto;
  align-content: start;
  min-width: 0;
  border: 1px solid var(--bench-border);
  border-radius: 8px;
  background: #ffffff;
  overflow: hidden;
}

.bench-panel header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 52px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--bench-border);
  background: #ffffff;
}

.bench-panel header h2,
.bench-panel header small {
  margin: 0;
}

.bench-panel header h2 {
  margin-top: 2px;
  color: var(--bench-text);
  font-size: 15px;
  font-weight: 950;
}

.bench-panel header b {
  max-width: 180px;
  padding: 3px 8px;
  border: 1px solid var(--bench-border);
  border-radius: 6px;
  background: #f7f8f8;
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 900;
}

.bench-plan-grid,
.bench-diagnostic-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  padding: 12px;
}

.bench-diagnostic-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.bench-plan-grid span,
.bench-diagnostic-grid span {
  display: grid;
  gap: 4px;
  min-width: 0;
  min-height: 56px;
  padding: 9px 10px;
  border: 1px solid var(--bench-border);
  border-radius: 7px;
  background: #f7f8f8;
}

.bench-plan-grid span.danger {
  border-color: rgba(161, 61, 54, 0.3);
  background: #fff6f5;
}

.bench-plan-grid b,
.bench-diagnostic-grid b {
  color: var(--bench-text);
  font-size: 17px;
  font-weight: 950;
  line-height: 1;
}

.bench-plan-controls {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  padding: 0 12px 12px;
}

.bench-plan-controls label {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.bench-plan-controls input {
  width: 100%;
  height: 34px;
  padding: 0 10px;
  border: 1px solid var(--bench-input-border);
  border-radius: 6px;
  background: var(--bench-input-bg);
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 900;
}

.bench-plan-controls input:disabled {
  opacity: 0.68;
}

.bench-cost-breakdown {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  padding: 0 12px 12px;
}

.bench-policy-breakdown {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  padding: 0 12px 12px;
}

.bench-cost-breakdown span,
.bench-policy-breakdown span {
  display: grid;
  gap: 3px;
  min-width: 0;
  min-height: 62px;
  padding: 9px 10px;
  border: 1px solid #d6dfda;
  border-radius: 7px;
  background: #fbfcfb;
}

.bench-cost-breakdown span.danger {
  border-color: rgba(161, 61, 54, 0.32);
  background: #fff6f5;
}

.bench-cost-breakdown small,
.bench-cost-breakdown em,
.bench-policy-breakdown small,
.bench-policy-breakdown em {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-cost-breakdown b,
.bench-policy-breakdown b {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text);
  font-size: 14px;
  font-weight: 950;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-cost-breakdown span.danger b,
.bench-cost-breakdown span.danger em {
  color: var(--bench-danger);
}

.bench-plan-warnings {
  display: grid;
  gap: 6px;
  margin: 0 12px 12px;
}

.bench-plan-warnings span {
  display: grid;
  grid-template-columns: 160px minmax(0, 1fr);
  gap: 10px;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid rgba(139, 100, 31, 0.28);
  border-radius: 6px;
  background: rgba(139, 100, 31, 0.08);
}

.bench-plan-warnings b,
.bench-plan-warnings em {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-warning);
  font-size: 12px;
  font-style: normal;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-inline-warning {
  margin: 0 12px 12px;
  padding: 8px 10px;
  border: 1px solid rgba(139, 100, 31, 0.28);
  border-radius: 6px;
  background: rgba(139, 100, 31, 0.08);
  color: var(--bench-warning);
  font-size: 12px;
  font-weight: 800;
}

.bench-launch-strip {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  margin: 0 12px 12px;
  padding: 10px;
  border: 1px solid var(--bench-border);
  border-radius: 7px;
  background: #f7f8f8;
}

.bench-launch-strip span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.bench-launch-strip b {
  color: var(--bench-text);
  font-size: 14px;
  font-weight: 950;
}

.bench-launch-strip em {
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
}

.bench-launch-confirmation {
  display: grid;
  gap: 10px;
  margin: 0 12px 12px;
  padding: 12px;
  border: 1px solid rgba(139, 100, 31, 0.34);
  border-radius: 8px;
  background: #fffaf0;
}

.bench-launch-confirmation small,
.bench-launch-confirmation dt {
  color: var(--bench-text-secondary);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.bench-launch-confirmation b {
  display: block;
  margin-top: 2px;
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 950;
}

.bench-launch-confirmation dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.bench-launch-confirmation dl div {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 8px 9px;
  border: 1px solid rgba(139, 100, 31, 0.18);
  border-radius: 7px;
  background: #ffffff;
}

.bench-launch-confirmation dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-launch-confirmation footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.bench-confirm-primary,
.bench-confirm-secondary {
  height: 32px;
  padding: 0 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 950;
  cursor: pointer;
}

.bench-confirm-primary {
  border: 1px solid #1a5944;
  background: #1f6f54;
  color: #ffffff;
}

.bench-confirm-secondary {
  border: 1px solid var(--bench-border);
  background: #ffffff;
  color: var(--bench-text);
}

.bench-confirm-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.bench-loading {
  padding: 0 12px 12px;
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-weight: 800;
}

.bench-run-stack {
  display: grid;
  gap: 7px;
  padding: 12px;
}

.bench-run-card {
  display: grid;
  gap: 4px;
  width: 100%;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--bench-border);
  border-left: 4px solid #256b8f;
  border-radius: 7px;
  background: #f7f8f8;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.bench-run-card:hover {
  border-color: #9cadb5;
}

.bench-run-card strong,
.bench-run-card span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-run-card strong {
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 950;
}

.bench-empty,
.bench-empty-compact {
  padding: 22px 14px;
  color: var(--bench-text-secondary);
  font-size: 13px;
  font-weight: 800;
  text-align: center;
}

.bench-empty-compact {
  padding: 16px 12px;
}

.bench-leaderboard-stack,
.bench-diagnostics-view,
.bench-reports-view {
  overflow-y: auto;
}

.bench-reports-view {
  display: grid;
  align-content: start;
  gap: 12px;
  min-width: 0;
  min-height: 0;
  padding-right: 2px;
}

.bench-model-isolation p {
  margin: 0;
  padding: 14px;
  color: var(--bench-text-secondary);
  font-size: 13px;
  font-weight: 800;
}
</style>
