<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useEvaluationWorkbench } from '../composables/useEvaluationWorkbench.js'
import ApiErrorPanel from '../components/ApiErrorPanel.vue'
import LabWorkbenchShell from '../components/lab/LabWorkbenchShell.vue'
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
  { key: 'overview', label: '总览' },
  { key: 'leaderboards', label: '榜单' },
  { key: 'runs', label: '运行' },
  { key: 'diagnostics', label: '诊断' },
  { key: 'reports', label: '报告' }
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
  benchmark.selectedBenchmarkIsModelSuite.value ? '模型评测' : '角色版本评测'
)
const budgetStatusLabel = computed(() => {
  if (!plan.value) return '计划待生成'
  return benchmark.benchmarkPlanBudgetExceeded.value ? '预算超限' : '预算正常'
})
const launchDisabledReason = computed(() =>
  benchmark.selectedBenchmarkSuiteLaunchDisabledReason.value ||
  benchmark.selectedRoleTargetVersionBlockedReason.value ||
  (benchmark.benchmarkPlanBudgetExceeded.value ? '评测预算超过上限，请提高预算或选择更小的套件。' : '')
)
const labHeaderMeta = computed(() => [
  { key: 'mode', label: '模式', value: selectedModeLabel.value },
  { key: 'suite', label: '套件', value: benchmark.selectedBenchmarkSuiteLabel.value },
  {
    key: 'budget',
    label: '预算',
    value: budgetStatusLabel.value,
    tone: benchmark.benchmarkPlanBudgetExceeded.value ? 'danger' : 'neutral'
  }
])
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
  if (budgetDeltaUnits.value == null) return '未设置启动上限'
  const prefix = budgetDeltaUnits.value >= 0 ? '+' : '-'
  return `${prefix}${formatNumber(Math.abs(budgetDeltaUnits.value))} 单位`
})
const budgetDeltaCaption = computed(() =>
  budgetDeltaUnits.value == null
    ? '设置上限可在启动前拦截'
    : (budgetDeltaUnits.value >= 0 ? '启动前剩余额度' : '已超限，禁止启动')
)
const gameDecisionUnitsLabel = computed(() => formatNumber(planEstimates.value.game_decision_units))
const judgeUnitValue = computed(() =>
  planEstimates.value.judge_decision_units ?? planJudge.value.estimated_decisions ?? plan.value?.judge_decisions
)
const judgeDecisionLabel = computed(() => formatNumber(judgeUnitValue.value))
const totalGamesLabel = computed(() => formatNumber(plan.value?.total_games))
const evalBatchLabel = computed(() => formatNumber(plan.value?.eval_batch_count))
const suiteCostTier = computed(() => String(plan.value?.cost_tier || selectedSuite.value?.cost_tier || 'ad_hoc').toLowerCase())
const suiteCostTierDisplayLabel = computed(() => costTierDisplayLabel(suiteCostTier.value))
const requiresLaunchConfirmation = computed(() =>
  ['standard', 'release'].includes(suiteCostTier.value)
)
const formalLaunchLabel = computed(() =>
  benchmark.selectedBenchmarkId.value ? `${suiteCostTierDisplayLabel.value} / 正式边界` : '临时评测 / 不入正式证据'
)
const currentScopeLabel = computed(() => {
  const scope = benchmark.benchmarkSnapshotScope.value || (benchmark.selectedBenchmarkIsModelSuite.value ? 'model' : 'role_version')
  const normalized = String(scope || '').replace(/^scope=/, '').trim()
  return normalized ? `scope=${normalized}` : 'scope=model'
})
const expectedDurationLabel = computed(() => {
  const explicitSeconds = numberOrNull(
    planEstimates.value.expected_duration_seconds ??
    planEstimates.value.duration_seconds ??
    plan.value?.expected_duration_seconds
  )
  if (explicitSeconds != null) return formatDuration(explicitSeconds)
  const totalGames = numberOrNull(plan.value?.total_games)
  const maxDays = numberOrNull(plan.value?.max_days)
  if (totalGames != null && maxDays != null) return `${formatNumber(totalGames * maxDays)} 局日`
  return '计划待生成'
})
const concurrencyLabel = computed(() => {
  const value = numberOrNull(planJudge.value.concurrency ?? plan.value?.concurrency)
  return value == null ? '后端默认' : `${formatNumber(value)} 个 Judge 并发任务`
})
const planCostRows = computed(() => [
  {
    key: 'game',
    label: '对局调用单位',
    value: gameDecisionUnitsLabel.value,
    caption: `按 ${formatNumber(planEstimates.value.player_count || 12)} 人、天数、局数估算`
  },
  {
    key: 'judge',
    label: '裁判判定单位',
    value: judgeDecisionLabel.value,
    caption: planJudge.value.enabled ? `每局最多 ${formatNumber(planJudge.value.max_decisions_per_game)} 次判定` : '裁判判定未启用'
  },
  {
    key: 'limit',
    label: '预算上限',
    value: budgetLimitUnits.value == null ? '未设置' : `${formatNumber(budgetLimitUnits.value)} 单位`,
    caption: '启动前校验'
  },
  {
    key: 'remaining',
    label: budgetDeltaUnits.value == null || budgetDeltaUnits.value >= 0 ? '剩余额度' : '超出预算',
    value: budgetDeltaLabel.value,
    caption: budgetDeltaCaption.value,
    danger: budgetDeltaUnits.value != null && budgetDeltaUnits.value < 0
  }
])
const planPolicyRows = computed(() => [
  {
    key: 'duration',
    label: '预计耗时',
    value: expectedDurationLabel.value,
    caption: '启动前工作量估计'
  },
  {
    key: 'concurrency',
    label: '并发策略',
    value: concurrencyLabel.value,
    caption: planJudge.value.timeout_seconds ? `${formatNumber(planJudge.value.timeout_seconds)} 秒 Judge 超时` : '运行策略'
  },
  {
    key: 'formality',
    label: '证据边界',
    value: formalLaunchLabel.value,
    caption: benchmark.selectedBenchmarkId.value ? '可进入隔离榜单' : '临时评测不冻结正式证据'
  },
  {
    key: 'confirmation',
    label: '启动门禁',
    value: launchDisabledReason.value ? '不可启动' : (requiresLaunchConfirmation.value ? '需要确认' : '可直接启动'),
    caption: launchDisabledReason.value || (requiresLaunchConfirmation.value ? 'standard/release 正式门禁' : 'quick 快速套件或临时评测')
  }
])
const launchSubjectLabel = computed(() => {
  if (benchmark.selectedBenchmarkIsModelSuite.value) {
    return benchmark.form.value.model_config_hash || benchmark.form.value.model_id || '当前后端模型'
  }
  return `${benchmark.selectedRoleLabel.value} / ${benchmark.form.value.target_version_id || '基线'}`
})
const selectedContextRun = computed(() => benchmark.selectedBenchmarkBatchRun.value || null)
const contextRun = computed(() =>
  selectedContextRun.value || activeRuns.value[0] || recentRuns.value[0] || null
)
const contextRunProgressLabel = computed(() => {
  const progress = contextRun.value?.progress || {}
  const percent = Number(progress.percent)
  if (Number.isFinite(percent)) return `${Math.round(percent * 100)}%`
  const completed = numberOrNull(progress.completed ?? contextRun.value?.completed)
  const total = numberOrNull(progress.total ?? contextRun.value?.total_games)
  if (completed != null && total != null && total > 0) return `${formatNumber(completed)}/${formatNumber(total)}`
  return contextRun.value?.isActive ? '进度待回传' : '已结束或待详情'
})
const contextDiagnosticSummary = computed(() => benchmark.benchmarkDiagnosticAggregateSummary.value || {})
const contextDiagnosticTotal = computed(() => {
  const value = numberOrNull(contextDiagnosticSummary.value.total)
  return value == null ? benchmark.benchmarkDiagnosticAggregateDiagnostics.value.length : value
})
const diagnosticKindLabels = {
  rankable_failed: '入榜失败',
  gate_failed: '门禁失败',
  llm_error: 'LLM 错误',
  timeout: '超时',
  abnormal: '异常',
  fallback: '回退',
  diagnostic: '诊断'
}
const diagnosticLevelLabels = {
  info: '信息',
  warning: '警告',
  error: '错误'
}
const viewDensityLabels = {
  compact: '紧凑',
  comfortable: '舒展',
  default: '默认'
}
const planWarningLabels = {
  budget_exceeded: '预算超限',
  missing_seed_set: '缺少种子集',
  small_sample: '样本偏少',
  no_judge: '裁判未启用',
  warning: '警告'
}
const contextDiagnosticRows = computed(() => {
  const rows = countSummaryRows(contextDiagnosticSummary.value.by_kind, displayDiagnosticKind).slice(0, 4)
  if (rows.length) return rows
  return benchmark.benchmarkDiagnosticAggregateDiagnostics.value
    .slice(0, 4)
    .map((item) => ({
      label: displayDiagnosticKind(item.kindLabel || item.kind),
      value: displayDiagnosticLevel(item.levelLabel || item.level),
      caption: item.message || item.stage || '无详情'
    }))
})
const contextBoundaryRows = computed(() => [
  { key: 'mode', label: '模式', value: selectedModeLabel.value },
  { key: 'scope', label: '范围', value: currentScopeLabel.value },
  { key: 'evaluation', label: '评测集', value: benchmark.selectedBenchmarkEvaluationSetId.value || '临时' },
  { key: 'seed', label: '种子集', value: selectedSuite.value?.seed_set_id || plan.value?.seed_set_id || '临时' },
  {
    key: 'hash',
    label: 'Config Hash',
    value: shortValue(
      selectedSuite.value?.config_hash ||
      selectedSuite.value?.benchmark_config_hash ||
      plan.value?.benchmark?.config_hash ||
      plan.value?.benchmark_config_hash ||
      ''
    )
  },
  { key: 'subject', label: '被测对象', value: launchSubjectLabel.value }
])
const contextSuiteRows = computed(() => [
  {
    key: 'status',
    label: '生命周期',
    value: selectedSuite.value?.statusLabel || (benchmark.selectedBenchmarkId.value ? '启用' : '临时')
  },
  { key: 'cost', label: '成本等级', value: suiteCostTierDisplayLabel.value },
  { key: 'games', label: '局数', value: selectedSuite.value?.game_count ?? plan.value?.total_games ?? '未生成' },
  { key: 'days', label: '最大天数', value: selectedSuite.value?.max_days ?? plan.value?.max_days ?? '未生成' },
  { key: 'roles', label: '覆盖角色', value: suiteRoleCoverageLabel.value }
])
const suiteRoleCoverageLabel = computed(() => {
  const roles = selectedSuite.value?.roles || []
  if (!roles.length) return benchmark.selectedBenchmarkIsModelSuite.value ? '全角色模型套件' : '临时角色范围'
  return roles.length > 4 ? `${roles.length} 个角色` : roles.join('、')
})
const contextGateRows = computed(() => {
  const gates = selectedSuite.value?.gates || plan.value?.gates || {}
  const rows = [
    ['min_completed_games', '最少完成局'],
    ['min_valid_game_rate', '有效局率'],
    ['max_fallback_rate', '最大回退率'],
    ['max_llm_error_rate', '最大 LLM 错误率']
  ].map(([key, label]) => ({ key, label, value: gates[key] }))
    .filter((row) => row.value != null && row.value !== '')
  return rows.length ? rows : [{ key: 'empty', label: '门禁', value: '计划生成后显示' }]
})
const contextArtifactRows = computed(() => {
  const snapshot = benchmark.activeBenchmarkSnapshotDetail.value || benchmark.selectedBenchmarkSnapshot.value || benchmark.benchmarkSnapshots.value[0] || null
  const report = benchmark.benchmarkReportHistory.value[0] || null
  return [
    {
      key: 'snapshot',
      label: '快照',
      value: benchmark.benchmarkSnapshots.value.length ? `${benchmark.benchmarkSnapshots.value.length} 个` : '未冻结',
      caption: snapshot?.title || '冻结后可对比历史榜单'
    },
    {
      key: 'report',
      label: '报告',
      value: benchmark.benchmarkReportHistory.value.length ? `${benchmark.benchmarkReportHistory.value.length} 份` : '暂无',
      caption: report?.subjectLabel || report?.suiteLabel || '完成运行后生成'
    },
    {
      key: 'view',
      label: '视图',
      value: benchmark.benchmarkViewDirty.value ? '有未保存修改' : densityDisplayLabel(benchmark.activeBenchmarkViewConfig.value?.density),
      caption: benchmark.benchmarkViewPreferences.value?.name || '榜单列与筛选'
    }
  ]
})
const contextRecentRows = computed(() => {
  const selectedId = selectedContextRun.value?.id || ''
  const rows = activeRuns.value.length ? activeRuns.value : recentRuns.value
  return rows.slice(0, 5).map((run) => ({
    ...run,
    isSelected: selectedId && run.id === selectedId
  }))
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

function costTierDisplayLabel(value) {
  const tier = String(value || '').trim().toLowerCase()
  const labels = {
    ad_hoc: '临时',
    smoke: '冒烟',
    quick: 'quick 快速',
    low: '低成本',
    medium: '中等',
    standard: 'standard 标准',
    release: 'release 发布',
    high: '高成本'
  }
  return labels[tier] || tier || '临时'
}

function displayMappedLabel(value, labels, fallback = '未上报') {
  const text = String(value ?? '').trim()
  if (!text) return fallback
  if (/[\u4e00-\u9fff]/.test(text)) return text
  const normalized = text.toLowerCase().replace(/\s+/g, '_')
  return labels[normalized] || fallback
}

function displayDiagnosticKind(value) {
  return displayMappedLabel(value, diagnosticKindLabels, '诊断项')
}

function displayDiagnosticLevel(value) {
  return displayMappedLabel(value, diagnosticLevelLabels, '信息')
}

function densityDisplayLabel(value) {
  return displayMappedLabel(value, viewDensityLabels, '默认')
}

function displayPlanWarningKind(value) {
  return displayMappedLabel(value, planWarningLabels, '警告')
}

function countSummaryRows(source, labeler = (value) => String(value || '诊断')) {
  if (!source || typeof source !== 'object') return []
  return Object.entries(source)
    .map(([label, count]) => ({
      label: labeler(label),
      value: formatNumber(count),
      caption: '诊断类型'
    }))
    .filter((row) => row.value !== '--')
    .sort((a, b) => Number(b.value.replace(/,/g, '')) - Number(a.value.replace(/,/g, '')))
}

function shortValue(value, fallback = '未上报') {
  const text = String(value || '').trim()
  if (!text) return fallback
  return text.length > 22 ? `${text.slice(0, 22)}...` : text
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
  if (!Number.isFinite(value) || value < 0) return '计划待生成'
  if (value < 90) return `${Math.round(value)} 秒`
  const minutes = Math.round(value / 60)
  if (minutes < 90) return `${minutes} 分钟`
  const hours = Math.round(minutes / 60)
  return `${hours} 小时`
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

function benchmarkDeepLinkBatchId(hash = typeof window === 'undefined' ? '' : window.location.hash) {
  const [routeHash, queryString = ''] = String(hash || '').split('?')
  if (routeHash !== '#benchmark') return ''
  const params = new URLSearchParams(queryString)
  return String(
    params.get('batch_id') ||
    params.get('batch') ||
    params.get('run_id') ||
    params.get('run') ||
    params.get('source_run_id') ||
    ''
  ).trim()
}

function applyBenchmarkDeepLink() {
  const batchId = benchmarkDeepLinkBatchId()
  if (!batchId) return false
  activeView.value = 'runs'
  if (benchmark.selectedBenchmarkBatchId.value !== batchId) {
    benchmark.selectBenchmarkBatch(batchId)
  }
  return true
}

function handleBenchmarkHashChange() {
  applyBenchmarkDeepLink()
}

onMounted(() => {
  if (typeof window !== 'undefined') window.addEventListener('hashchange', handleBenchmarkHashChange)
  void benchmark.refreshAll().finally(() => {
    applyBenchmarkDeepLink()
  })
})

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') window.removeEventListener('hashchange', handleBenchmarkHashChange)
})
</script>

<template>
  <section class="bench-page" aria-label="评测工作台">
    <LabWorkbenchShell
      v-model:active-tab="activeView"
      class="bench-workbench-shell"
      workbench-key="benchmark"
      title="评测工作台"
      eyebrow="评测控制台"
      :tabs="navTabs"
      :meta="labHeaderMeta"
      tabs-label="评测工作台视图"
      boundary-label="评测边界"
      rail-label="评测套件栏"
      context-label="评测上下文"
      action-label="刷新"
      action-busy-label="刷新中"
      :action-busy="Boolean(benchmark.loading.value)"
      @action="refresh"
    >
      <template #rail>
        <BenchmarkSuiteRail :benchmark="benchmark" />
      </template>

      <template #boundary>
        <BenchmarkBoundaryBar :benchmark="benchmark" />
        <div v-if="benchmark.selectedBenchmarkUsingLegacyRuns.value" class="bench-inline-warning">
          当前套件暂无匹配批次，已展示未绑定评测套件/评测集的历史评测批次。
        </div>
      </template>

      <template #notice>
        <ApiErrorPanel
          v-if="benchErrorNotice"
          :error="benchErrorNotice"
          title="评测操作失败"
          retry-label="重试刷新"
          retry-busy-label="刷新中"
          :retrying="Boolean(benchmark.loading.value)"
          :retry-disabled="Boolean(benchmark.loading.value || benchmark.actionLoading.value)"
          @retry="refresh"
          compact
        />
        <div
          v-else-if="benchInlineNotice"
          :class="['bench-alert', `bench-alert--${benchInlineNotice.type}`]"
        >
          {{ benchInlineNotice.message }}
        </div>
      </template>

      <template #context>
        <section class="bench-context-panel" aria-label="评测上下文">
          <article class="bench-context-section bench-context-section--suite">
            <header>
              <div>
                <small>当前套件</small>
                <h2>{{ benchmark.selectedBenchmarkSuiteLabel.value }}</h2>
              </div>
              <b>{{ benchmark.selectedBenchmarkId.value ? '正式' : '临时' }}</b>
            </header>
            <div class="bench-context-kv-list">
              <span v-for="item in contextSuiteRows" :key="item.key">
                <small>{{ item.label }}</small>
                <b>{{ item.value }}</b>
              </span>
            </div>
            <div class="bench-context-gates">
              <div class="bench-context-subtitle">
                <span>门禁</span>
                <small>{{ budgetStatusLabel }}</small>
              </div>
              <span v-for="item in contextGateRows" :key="item.key">
                <small>{{ item.label }}</small>
                <b>{{ item.value }}</b>
              </span>
            </div>
          </article>

          <article class="bench-context-section">
            <header>
              <div>
                <small>运行上下文</small>
                <h2>{{ contextRun ? '选中运行' : '运行状态' }}</h2>
              </div>
              <b>{{ activeRuns.length }} 运行中</b>
            </header>
            <div v-if="contextRun" class="bench-context-run-detail">
              <strong>{{ contextRun.benchmarkLabel }}</strong>
              <span>{{ contextRun.displayRole }} / {{ contextRun.statusLabel }}</span>
              <em>{{ contextRunProgressLabel }}</em>
            </div>
            <div v-else class="bench-context-empty">暂无运行记录。</div>
            <div v-if="contextRecentRows.length" class="bench-context-run-list">
              <button
                v-for="run in contextRecentRows"
                :key="run.id"
                type="button"
                :class="['bench-context-run-button', { active: run.isSelected }]"
                @click="selectRun(run)"
              >
                <span>
                  <b>{{ run.benchmarkLabel }}</b>
                  <small>{{ run.displayRole }} / {{ run.statusLabel }}</small>
                </span>
                <em>{{ run.judgeScoreLabel || '--' }}</em>
              </button>
            </div>
          </article>

          <article class="bench-context-section">
            <header>
              <div>
                <small>诊断概览</small>
                <h2>失败信号</h2>
              </div>
              <b>{{ formatNumber(contextDiagnosticTotal) }}</b>
            </header>
            <div v-if="benchmark.benchmarkDiagnosticAggregateLoading.value" class="bench-context-empty">
              正在读取诊断汇总。
            </div>
            <div v-else-if="benchmark.benchmarkDiagnosticAggregateError.value" class="bench-context-warning">
              {{ benchmark.benchmarkDiagnosticAggregateError.value }}
            </div>
            <div v-else-if="contextDiagnosticRows.length" class="bench-context-diagnostics">
              <span v-for="item in contextDiagnosticRows" :key="item.label + item.caption">
                <small>{{ item.label }}</small>
                <b>{{ item.value }}</b>
                <em>{{ item.caption }}</em>
              </span>
            </div>
            <div v-else class="bench-context-empty">当前套件边界暂无诊断。</div>
          </article>

          <article class="bench-context-section">
            <header>
              <div>
                <small>审计边界</small>
                <h2>复现信息</h2>
              </div>
              <b>{{ currentScopeLabel }}</b>
            </header>
            <div class="bench-context-boundary">
              <span v-for="item in contextBoundaryRows" :key="item.key">
                <small>{{ item.label }}</small>
                <b :title="String(item.value || '')">{{ item.value }}</b>
              </span>
            </div>
          </article>

          <article class="bench-context-section">
            <header>
              <div>
                <small>产物</small>
                <h2>发布材料</h2>
              </div>
              <b>{{ benchmark.benchmarkSnapshots.value.length + benchmark.benchmarkReportHistory.value.length }}</b>
            </header>
            <div class="bench-context-artifacts">
              <span v-for="item in contextArtifactRows" :key="item.key">
                <small>{{ item.label }}</small>
                <b>{{ item.value }}</b>
                <em>{{ item.caption }}</em>
              </span>
            </div>
          </article>
        </section>
      </template>

        <section v-if="activeView === 'overview'" class="bench-overview">
          <div class="bench-overview-primary">
            <BenchmarkTargetSelector :benchmark="benchmark" />

            <article class="bench-panel bench-planner-panel">
              <header>
                <div>
                  <small>运行计划</small>
                  <h2>启动计划</h2>
                </div>
                <b>{{ budgetStatusLabel }}</b>
              </header>
              <div class="bench-plan-grid">
                <span>
                  <small>总局数</small>
                  <b>{{ totalGamesLabel }}</b>
                </span>
                <span>
                  <small>评测批次</small>
                  <b>{{ evalBatchLabel }}</b>
                </span>
                <span>
                  <small>裁判判定</small>
                  <b>{{ judgeDecisionLabel }}</b>
                </span>
                <span :class="{ danger: benchmark.benchmarkPlanBudgetExceeded.value }">
                  <small>预计调用单位</small>
                  <b>{{ estimatedUnitsLabel }}</b>
                </span>
              </div>
              <div class="bench-plan-controls">
                <label>
                  <span>局数</span>
                  <input
                    v-model.number="benchmark.form.value.battle_games"
                    type="number"
                    min="1"
                    max="200"
                    :disabled="Boolean(benchmark.selectedBenchmarkId.value)"
                  />
                </label>
                <label>
                  <span>最大天数</span>
                  <input
                    v-model.number="benchmark.form.value.max_days"
                    type="number"
                    min="1"
                    max="100"
                    :disabled="Boolean(benchmark.selectedBenchmarkId.value)"
                  />
                </label>
                <label>
                  <span>预算上限</span>
                  <input
                    v-model.number="benchmark.form.value.budget_limit_units"
                    type="number"
                    min="0"
                    max="1000000"
                  />
                </label>
              </div>
              <div class="bench-cost-breakdown" aria-label="评测成本拆分">
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
              <div class="bench-policy-breakdown" aria-label="评测执行策略">
                <span v-for="item in planPolicyRows" :key="item.key">
                  <small>{{ item.label }}</small>
                  <b>{{ item.value }}</b>
                  <em>{{ item.caption }}</em>
                </span>
              </div>
              <div v-if="planWarnings.length" class="bench-plan-warnings">
                <span v-for="warning in planWarnings" :key="warning.kind || warning.message">
                  <b>{{ displayPlanWarningKind(warning.kind) }}</b>
                  <em>{{ warning.message || '计划警告' }}</em>
                </span>
              </div>
              <div v-if="benchmark.benchmarkPlanError.value" class="bench-inline-warning">
                {{ benchmark.benchmarkPlanError.value }}
              </div>
              <footer class="bench-launch-strip">
                <span>
                  <small>被测对象</small>
                  <b>{{ launchSubjectLabel }}</b>
                  <em>{{ selectedSuite?.evaluation_set_id || '临时评测' }}</em>
                </span>
                <button
                  type="button"
                  class="bench-launch-button"
                  :disabled="Boolean(benchmark.actionLoading.value) || !benchmark.selectedBenchmarkCanLaunch.value"
                  :title="launchDisabledReason || undefined"
                  @click="requestLaunch"
                >
                  <template v-if="requiresLaunchConfirmation && !launchConfirmationOpen">检查启动</template>
                  <template v-else>{{ benchmark.selectedBenchmarkIsModelSuite.value ? '运行模型评测' : '运行角色评测' }}</template>
                </button>
              </footer>
              <div v-if="launchDisabledReason" class="bench-inline-warning">
                {{ launchDisabledReason }}
              </div>
              <section v-if="launchConfirmationOpen" class="bench-launch-confirmation" aria-label="评测启动确认">
                <div>
                  <small>{{ suiteCostTierDisplayLabel }} 套件启动确认</small>
                  <b>执行前确认边界和预算。</b>
                </div>
                <dl>
                  <div>
                    <dt>局数</dt>
                    <dd>{{ totalGamesLabel }}</dd>
                  </div>
                  <div>
                    <dt>裁判判定</dt>
                    <dd>{{ judgeDecisionLabel }}</dd>
                  </div>
                  <div>
                    <dt>预计调用单位</dt>
                    <dd>{{ estimatedUnitsLabel }}</dd>
                  </div>
                  <div>
                    <dt>并发</dt>
                    <dd>{{ concurrencyLabel }}</dd>
                  </div>
                  <div>
                    <dt>评测集</dt>
                    <dd>{{ selectedSuite?.evaluation_set_id || '临时' }}</dd>
                  </div>
                  <div>
                    <dt>种子集</dt>
                    <dd>{{ selectedSuite?.seed_set_id || plan?.seed_set_id || '临时' }}</dd>
                  </div>
                </dl>
                <footer>
                  <button type="button" class="bench-confirm-secondary" @click="cancelLaunchConfirmation">
                    取消
                  </button>
                  <button
                    type="button"
                    class="bench-confirm-primary"
                    :disabled="Boolean(benchmark.actionLoading.value) || !benchmark.selectedBenchmarkCanLaunch.value"
                    @click="launchBenchmark"
                  >
                    确认启动
                  </button>
                </footer>
              </section>
              <span v-if="benchmark.loading.value || benchmark.actionLoading.value" class="bench-loading">
                {{ benchmark.actionLoading.value === 'start' ? '正在启动评测' : '正在加载评测数据' }}
              </span>
            </article>
          </div>
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
    </LabWorkbenchShell>
  </section>
</template>

<style scoped>
.bench-page {
  --logbook-bg: #f2dfae;
  --logbook-bg-texture:
    repeating-linear-gradient(90deg, rgba(118, 71, 27, 0.024) 0 1px, transparent 1px 34px),
    var(--logbook-bg);
  --logbook-surface: rgba(255, 252, 245, 0.7);
  --logbook-panel: rgba(255, 252, 245, 0.86);
  --logbook-panel-solid: rgba(255, 250, 240, 0.92);
  --logbook-panel-soft: rgba(255, 242, 210, 0.58);
  --logbook-border: rgba(139, 94, 52, 0.15);
  --logbook-border-strong: rgba(90, 51, 25, 0.34);
  --logbook-text: #3a2a18;
  --logbook-muted: #8b6b4a;
  --logbook-accent: #8b5e34;
  --logbook-accent-strong: #5a3319;
  --logbook-input-bg: rgba(255, 255, 250, 0.8);
  --logbook-input-border: rgba(139, 94, 52, 0.2);
  --logbook-hover: rgba(139, 94, 52, 0.06);
  --logbook-active-bg: rgba(139, 94, 52, 0.1);
  --logbook-danger: #993026;
  --logbook-warning: #8b5e34;
  --log-bg: var(--logbook-bg);
  --log-surface: var(--logbook-surface);
  --log-border: var(--logbook-border);
  --log-text: var(--logbook-text);
  --log-text-secondary: var(--logbook-muted);
  --log-accent: var(--logbook-accent);
  --log-accent-strong: var(--logbook-accent-strong);
  --log-input-bg: var(--logbook-input-bg);
  --log-input-border: var(--logbook-input-border);
  --log-hover: var(--logbook-hover);
  --log-active-bg: var(--logbook-active-bg);
  --bench-bg: var(--logbook-bg);
  --bench-bg-texture: var(--logbook-bg-texture);
  --bench-surface: var(--logbook-surface);
  --bench-panel: var(--logbook-panel);
  --bench-panel-solid: var(--logbook-panel-solid);
  --bench-panel-soft: var(--logbook-panel-soft);
  --bench-border: var(--logbook-border);
  --bench-border-strong: var(--logbook-border-strong);
  --bench-text: var(--logbook-text);
  --bench-text-secondary: var(--logbook-muted);
  --bench-accent: var(--logbook-accent);
  --bench-accent-strong: var(--logbook-accent-strong);
  --bench-input-bg: var(--logbook-input-bg);
  --bench-input-border: var(--logbook-input-border);
  --bench-hover: var(--logbook-hover);
  --bench-active-bg: var(--logbook-active-bg);
  --bench-danger: var(--logbook-danger);
  --bench-danger-border: rgba(153, 48, 38, 0.28);
  --bench-danger-bg: rgba(153, 48, 38, 0.06);
  --bench-warning: var(--logbook-warning);
  --bench-warning-border: rgba(139, 100, 31, 0.3);
  --bench-warning-bg: rgba(139, 100, 31, 0.08);
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
  background: var(--bench-bg-texture);
  color: var(--bench-text);
  font-family: var(--bench-font);
}

.bench-page *:not(svg):not(svg *) {
  box-sizing: border-box;
  font-family: var(--bench-font);
}

.bench-workbench-shell {
  --lab-rail-width: 316px;
  --lab-context-width: 320px;
  display: grid;
  grid-template-columns: 316px minmax(0, 1fr) 320px;
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
  background: var(--bench-panel);
  box-shadow: 0 2px 8px rgba(91, 47, 18, 0.08);
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
.bench-launch-strip small {
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
  background: rgba(255, 248, 226, 0.58);
}

.bench-header-meta span.danger {
  border-color: var(--bench-danger-border);
  background: var(--bench-danger-bg);
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
  border: 1px solid var(--bench-accent-strong);
  border-radius: 6px;
  background: var(--bench-accent-strong);
  color: #fff7dc;
  font-size: 13px;
  font-weight: 900;
  cursor: pointer;
}

.bench-refresh-button:hover,
.bench-launch-button:hover {
  background: var(--bench-accent);
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
  background: var(--bench-panel);
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
  border-color: var(--bench-border-strong);
  background: var(--bench-active-bg);
  color: var(--bench-accent-strong);
}

.bench-alert {
  padding: 9px 12px;
  border: 1px solid var(--bench-danger-border);
  border-radius: 8px;
  background: var(--bench-danger-bg);
  color: var(--bench-danger);
  font-size: 12px;
  font-weight: 800;
}

.bench-alert--success {
  border-color: rgba(139, 94, 52, 0.28);
  background: rgba(255, 226, 157, 0.18);
  color: var(--bench-accent-strong);
}

.bench-alert--warning {
  border-color: var(--bench-warning-border);
  background: var(--bench-warning-bg);
  color: var(--bench-warning);
}

.bench-overview {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.bench-overview-primary,
.bench-leaderboard-stack {
  min-width: 0;
  min-height: 0;
}

.bench-overview-primary,
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
  background: var(--bench-panel);
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
  background: rgba(255, 252, 245, 0.9);
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
  background: rgba(255, 242, 210, 0.56);
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 900;
}

.bench-context-panel {
  display: grid;
  align-content: start;
  gap: 10px;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.bench-context-section {
  display: grid;
  gap: 10px;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--bench-border);
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.78);
}

.bench-context-section header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-width: 0;
  min-height: 48px;
  padding: 9px 10px;
  border-bottom: 1px solid var(--bench-border);
  background: rgba(255, 248, 226, 0.58);
}

.bench-context-section header div,
.bench-context-section header h2,
.bench-context-section header b {
  min-width: 0;
}

.bench-context-section header small,
.bench-context-kv-list small,
.bench-context-gates small,
.bench-context-run-button small,
.bench-context-diagnostics small,
.bench-context-boundary small,
.bench-context-artifacts small,
.bench-context-subtitle small {
  color: var(--bench-text-secondary);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0;
}

.bench-context-section header h2 {
  overflow: hidden;
  margin: 2px 0 0;
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 950;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-context-section header b {
  max-width: 96px;
  overflow: hidden;
  padding: 3px 7px;
  border: 1px solid var(--bench-border);
  border-radius: 6px;
  background: rgba(255, 242, 210, 0.6);
  color: var(--bench-accent-strong);
  font-size: 11px;
  font-weight: 950;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-context-kv-list,
.bench-context-gates,
.bench-context-diagnostics,
.bench-context-boundary,
.bench-context-artifacts {
  display: grid;
  gap: 7px;
  min-width: 0;
  padding: 0 10px 10px;
}

.bench-context-kv-list {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  padding-top: 10px;
}

.bench-context-boundary,
.bench-context-artifacts {
  padding-top: 10px;
}

.bench-context-kv-list span,
.bench-context-gates span,
.bench-context-diagnostics span,
.bench-context-boundary span,
.bench-context-artifacts span {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 8px 9px;
  border: 1px solid rgba(139, 94, 52, 0.13);
  border-radius: 7px;
  background: rgba(255, 250, 240, 0.68);
}

.bench-context-kv-list b,
.bench-context-gates b,
.bench-context-run-detail strong,
.bench-context-run-detail span,
.bench-context-run-detail em,
.bench-context-run-button b,
.bench-context-run-button small,
.bench-context-run-button em,
.bench-context-diagnostics b,
.bench-context-diagnostics em,
.bench-context-boundary b,
.bench-context-artifacts b,
.bench-context-artifacts em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-context-kv-list b,
.bench-context-gates b,
.bench-context-diagnostics b,
.bench-context-boundary b,
.bench-context-artifacts b {
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 900;
}

.bench-context-diagnostics em,
.bench-context-artifacts em {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
}

.bench-context-subtitle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  padding-top: 2px;
}

.bench-context-subtitle span {
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 950;
}

.bench-context-run-detail {
  display: grid;
  gap: 4px;
  min-width: 0;
  margin: 10px 10px 0;
  padding: 9px 10px;
  border: 1px solid var(--bench-border);
  border-left: 4px solid var(--bench-accent);
  border-radius: 7px;
  background: rgba(255, 242, 210, 0.48);
}

.bench-context-run-detail strong {
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 950;
}

.bench-context-run-detail span,
.bench-context-run-detail em {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-style: normal;
  font-weight: 850;
}

.bench-context-run-list {
  display: grid;
  gap: 7px;
  min-width: 0;
  padding: 0 10px 10px;
}

.bench-context-run-button {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  min-width: 0;
  padding: 8px 9px;
  border: 1px solid var(--bench-border);
  border-radius: 7px;
  background: rgba(255, 250, 240, 0.64);
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.bench-context-run-button:hover,
.bench-context-run-button.active {
  border-color: var(--bench-border-strong);
  background: rgba(255, 226, 157, 0.24);
}

.bench-context-run-button span {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.bench-context-run-button b {
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 950;
}

.bench-context-run-button em {
  color: var(--bench-accent-strong);
  font-size: 11px;
  font-style: normal;
  font-weight: 950;
}

.bench-context-empty,
.bench-context-warning {
  margin: 10px;
  padding: 12px 10px;
  border: 1px dashed rgba(139, 94, 52, 0.24);
  border-radius: 7px;
  background: rgba(255, 250, 240, 0.58);
  color: var(--bench-text-secondary);
  font-size: 12px;
  font-weight: 850;
  line-height: 1.45;
}

.bench-context-warning {
  border-style: solid;
  color: var(--bench-warning);
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
  background: rgba(255, 242, 210, 0.48);
}

.bench-plan-grid span.danger {
  border-color: var(--bench-danger-border);
  background: var(--bench-danger-bg);
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
  border: 1px solid var(--bench-border);
  border-radius: 7px;
  background: rgba(255, 250, 240, 0.72);
}

.bench-cost-breakdown span.danger {
  border-color: var(--bench-danger-border);
  background: var(--bench-danger-bg);
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
  border: 1px solid var(--bench-warning-border);
  border-radius: 6px;
  background: var(--bench-warning-bg);
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
  border: 1px solid var(--bench-warning-border);
  border-radius: 6px;
  background: var(--bench-warning-bg);
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
  background: rgba(255, 242, 210, 0.5);
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
  border: 1px solid var(--bench-warning-border);
  border-radius: 8px;
  background: rgba(255, 245, 221, 0.74);
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
  border: 1px solid var(--bench-warning-border);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.86);
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
  border: 1px solid var(--bench-accent-strong);
  background: var(--bench-accent-strong);
  color: #fff7dc;
}

.bench-confirm-secondary {
  border: 1px solid var(--bench-border);
  background: rgba(255, 252, 245, 0.9);
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
  border-left: 4px solid var(--bench-accent);
  border-radius: 7px;
  background: rgba(255, 242, 210, 0.46);
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.bench-run-card:hover {
  border-color: var(--bench-border-strong);
  background: rgba(255, 226, 157, 0.26);
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
