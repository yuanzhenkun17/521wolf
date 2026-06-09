<script setup lang="ts">
// @ts-nocheck
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useEvaluationWorkbench } from '../composables/useEvaluationWorkbench.ts'
import ApiErrorPanel from '../components/ApiErrorPanel.vue'
import LabWorkbenchShell from '../components/lab/LabWorkbenchShell.vue'
import BenchmarkBatchRunsTable from '../components/benchmark/BenchmarkBatchRunsTable.vue'
import BenchmarkComparisonView from '../components/benchmark/BenchmarkComparisonView.vue'
import BenchmarkDiagnosticsExplorer from '../components/benchmark/BenchmarkDiagnosticsExplorer.vue'
import BenchmarkRunReportPanel from '../components/benchmark/BenchmarkRunReportPanel.vue'
import BenchmarkSnapshotReleasePanel from '../components/benchmark/BenchmarkSnapshotReleasePanel.vue'
import BenchmarkSuiteRail from '../components/benchmark/BenchmarkSuiteRail.vue'
import BenchmarkTargetSelector from '../components/benchmark/BenchmarkTargetSelector.vue'
import { inlineNoticeForDisplay, noticeErrorForPanel } from '../composables/apiErrorDisplay.ts'
import { benchmarkBatchIdFromHash, benchmarkBatchIdFromRoute } from '../router/workbenchDeepLinks.ts'

defineOptions({
  inheritAttrs: false
})

defineProps({
  returnToMatchAvailable: Boolean
})

const route = useRoute()
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
const planConcurrencyPolicy = computed(() => plan.value?.concurrency_policy || {})
const planWarnings = computed(() => Array.isArray(plan.value?.warnings) ? plan.value.warnings : [])
const planBudgetExceeded = computed(() => {
  const exceeded = planBudget.value?.exceeded
  if (exceeded && typeof exceeded === 'object' && !Array.isArray(exceeded)) {
    return {
      ...exceeded,
      value: Boolean(exceeded.value),
      reasons: Array.isArray(exceeded.reasons) ? exceeded.reasons : [],
      evidence: Array.isArray(exceeded.evidence) ? exceeded.evidence : []
    }
  }
  return { value: Boolean(exceeded), reasons: [], evidence: [] }
})
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
const launchStatusLabel = computed(() =>
  benchmark.selectedBenchmarkCanLaunch.value ? '可启动' : '不可启动'
)
const launchDisabledReason = computed(() =>
  benchmark.selectedBenchmarkSuiteLaunchDisabledReason.value ||
  benchmark.selectedRoleTargetVersionBlockedReason.value ||
  (benchmark.benchmarkPlanBudgetExceeded.value ? '评测预算超过上限，请提高预算或选择更小的套件。' : '')
)
const estimatedUnitsLabel = computed(() => {
  const value = planBudget.value.estimated_units ?? planEstimates.value.estimated_llm_call_units
  return formatNumber(value)
})
const estimatedUnits = computed(() =>
  numberOrNull(planBudget.value.estimated_units ?? planEstimates.value.estimated_llm_call_units)
)
const planCurrency = computed(() => String(planBudget.value.currency || planEstimates.value.currency || plan.value?.currency || '').trim())
const estimatedCost = computed(() =>
  numberOrNull(planBudget.value.estimated_cost ?? planEstimates.value.estimated_cost ?? plan.value?.estimated_cost)
)
const estimatedCostLabel = computed(() => formatCost(estimatedCost.value, planCurrency.value))
const budgetLimitUnits = computed(() => numberOrNull(planBudget.value.limit_units))
const budgetLimitCost = computed(() => numberOrNull(planBudget.value.limit_cost))
const budgetLimitCostLabel = computed(() => formatCost(budgetLimitCost.value, planCurrency.value, '未设置'))
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
const judgeUnitValue = computed(() =>
  planEstimates.value.judge_decision_units ?? planJudge.value.estimated_decisions ?? plan.value?.judge_decisions
)
const judgeDecisionLabel = computed(() => formatNumber(judgeUnitValue.value))
const totalGamesLabel = computed(() => formatNumber(plan.value?.total_games))
const suiteCostTier = computed(() => String(plan.value?.cost_tier || selectedSuite.value?.cost_tier || 'ad_hoc').toLowerCase())
const suiteCostTierDisplayLabel = computed(() => costTierDisplayLabel(suiteCostTier.value))
const requiresLaunchConfirmation = computed(() =>
  ['standard', 'release'].includes(suiteCostTier.value)
)
const currentScopeLabel = computed(() => {
  const scope = benchmark.benchmarkSnapshotScope.value || (benchmark.selectedBenchmarkIsModelSuite.value ? 'model' : 'role_version')
  const normalized = String(scope || '').replace(/^scope=/, '').trim()
  if (normalized === 'model') return '模型范围'
  if (normalized === 'role_version') return '角色版本范围'
  return normalized || '模型范围'
})
const expectedDurationLabel = computed(() => {
  const explicitSeconds = numberOrNull(
    planConcurrencyPolicy.value.expected_duration_seconds ??
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
  const roleConcurrency = numberOrNull(planConcurrencyPolicy.value.role_batch_concurrency)
  const gameConcurrency = numberOrNull(planConcurrencyPolicy.value.game_concurrency)
  const judgeConcurrency = numberOrNull(planConcurrencyPolicy.value.judge_concurrency ?? planJudge.value.concurrency ?? plan.value?.concurrency)
  const parts = []
  if (roleConcurrency != null && roleConcurrency > 0) parts.push(`批次 ${formatNumber(roleConcurrency)}`)
  if (gameConcurrency != null && gameConcurrency > 0) parts.push(`对局 ${formatNumber(gameConcurrency)}`)
  if (judgeConcurrency != null && judgeConcurrency > 0) parts.push(`Judge ${formatNumber(judgeConcurrency)}`)
  return parts.length ? parts.join(' / ') : '后端默认'
})
const dryRunBlocked = computed(() =>
  Boolean(plan.value && (benchmark.benchmarkPlanBudgetExceeded.value || plan.value.launchable === false || launchDisabledReason.value))
)
const dryRunCaption = computed(() => {
  if (!plan.value) return '等待计划接口'
  if (benchmark.benchmarkPlanBudgetExceeded.value) return '预算门禁已拦截'
  if (launchDisabledReason.value) return launchDisabledReason.value
  return plan.value.dry_run === false ? '后端返回正式启动计划' : '只做预算预检'
})
const planSummaryRows = computed(() => [
  {
    key: 'cost',
    label: '预计成本',
    value: estimatedCostLabel.value,
    caption: planCurrency.value ? planCurrency.value : '成本模型'
  },
  {
    key: 'units',
    label: '调用单位',
    value: estimatedUnitsLabel.value,
    caption: budgetDeltaUnits.value == null ? '未设上限' : budgetDeltaCaption.value,
    danger: budgetDeltaUnits.value != null && budgetDeltaUnits.value < 0
  },
  {
    key: 'duration',
    label: '预计耗时',
    value: expectedDurationLabel.value,
    caption: concurrencyLabel.value
  },
  {
    key: 'gate',
    label: '启动门禁',
    value: launchDisabledReason.value ? '不可启动' : (requiresLaunchConfirmation.value ? '需要确认' : '可直接启动'),
    caption: launchDisabledReason.value || dryRunCaption.value,
    danger: Boolean(launchDisabledReason.value || dryRunBlocked.value)
  }
])
const budgetReasonRows = computed(() => {
  const rows = []
  const reasons = Array.isArray(planBudgetExceeded.value.reasons) ? planBudgetExceeded.value.reasons : []
  const evidence = Array.isArray(planBudgetExceeded.value.evidence) ? planBudgetExceeded.value.evidence : []
  reasons.forEach((reason) => {
    rows.push({
      key: `reason:${reason}`,
      label: '超预算原因',
      value: displayPlanBudgetReason(reason),
      caption: '后端预算门禁'
    })
  })
  evidence.forEach((item, index) => {
    const row = budgetEvidenceRow(item, index)
    if (row) rows.push(row)
  })
  if (!rows.length && benchmark.benchmarkPlanBudgetExceeded.value) {
    rows.push({
      key: 'budget:fallback',
      label: '超预算原因',
      value: '预计调用单位超过预算上限',
      caption: `预计 ${estimatedUnitsLabel.value} / 上限 ${budgetLimitUnits.value == null ? '未设置' : formatNumber(budgetLimitUnits.value)}`
    })
  }
  if (planBudget.value.stop_after_predicted) {
    rows.push({
      key: 'stop_after_budget_units',
      label: '预算停止线',
      value: `${formatNumber(planBudget.value.stop_after_budget_units)} 单位`,
      caption: '达到该线后应停止继续消耗'
    })
  }
  return rows
})
const planWarningRows = computed(() =>
  planWarnings.value.map((warning, index) => ({
    key: warning.kind || warning.message || `warning-${index}`,
    label: displayPlanWarningKind(warning.kind),
    message: displayPlanWarningMessage(warning)
  }))
)
const launchSubjectLabel = computed(() => {
  if (benchmark.selectedBenchmarkIsModelSuite.value) {
    return benchmark.form.value.model_config_hash || benchmark.form.value.model_id || '当前后端模型'
  }
  return `${benchmark.selectedRoleLabel.value} / ${benchmark.form.value.target_version_id || '基线'}`
})
const benchmarkCommandMetaRows = computed(() => [
  { key: 'mode', label: '模式', value: selectedModeLabel.value },
  { key: 'subject', label: '被测对象', value: launchSubjectLabel.value },
  { key: 'games', label: '总局数', value: totalGamesLabel.value },
  { key: 'units', label: '调用单位', value: estimatedUnitsLabel.value },
  {
    key: 'budget',
    label: '预算',
    value: budgetStatusLabel.value,
    tone: benchmark.benchmarkPlanBudgetExceeded.value ? 'danger' : 'neutral'
  },
  {
    key: 'launch',
    label: '启动',
    value: launchStatusLabel.value,
    tone: benchmark.selectedBenchmarkCanLaunch.value ? 'neutral' : 'danger'
  }
])
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
const benchmarkMetricLabels = {
  avg_role_score: '角色均分',
  strength_score: '模型强度',
  target_side_win_rate: '目标阵营胜率',
  villagers_win_rate: '好人胜率',
  werewolves_win_rate: '狼人胜率',
  fallback_rate: '回退率',
  llm_error_rate: 'LLM 错误率',
  policy_adjusted_rate: '策略修正率',
  decision_judge_avg_score: '裁判均分'
}
const seedTierLabels = {
  smoke: '冒烟',
  quick: '快速',
  standard: '标准',
  release: '发布',
  audit: '审计'
}
const seedUsageBoundaryLabels = {
  smoke: '冒烟验证',
  quick_check: '快速验证',
  formal_benchmark: '正式评测',
  leaderboard: '榜单口径',
  release_gate: '发布门禁',
  audit: '审计回放'
}
const viewDensityLabels = {
  compact: '紧凑',
  comfortable: '舒展',
  default: '默认'
}
const planWarningLabels = {
  budget_exceeded: '预算超限',
  stop_after_budget_will_trigger: '停止线将触发',
  ad_hoc_benchmark: '临时评测',
  missing_seed_set: '缺少种子集',
  small_sample: '样本偏少',
  no_judge: '裁判未启用',
  warning: '警告'
}
const planWarningMessages = {
  budget_exceeded: '预计评测成本超过预算上限',
  stop_after_budget_will_trigger: '预计调用单位会触发预算停止阈值',
  ad_hoc_benchmark: '临时评测不绑定版本化套件，结果不会进入正式隔离证据。'
}
const planBudgetReasonLabels = {
  estimated_units_exceed_limit_units: '预计调用单位超限',
  estimated_cost_exceed_limit_cost: '预计成本超限',
  stop_after_budget_units: '达到预算停止线',
  estimated_units: '预计调用单位超限',
  estimated_cost: '预计成本超限',
  estimated_tokens: '预计调用单位'
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
  { key: 'scope', label: '比较边界', value: currentScopeLabel.value },
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
const selectedSuiteSeedSet = computed(() => objectOrEmpty(selectedSuite.value?.seed_set))
const contextSuiteDetailRows = computed(() => {
  const suite = selectedSuite.value
  if (!suite) return []
  return [
    {
      key: 'status',
      label: '生命周期',
      value: suite.statusLabel || displayMappedLabel(suite.status, {
        enabled: '启用',
        active: '启用',
        draft: '草稿',
        deprecated: '废弃',
        disabled: '停用',
        archived: '归档'
      }, '未标记')
    },
    { key: 'cost', label: '成本等级', value: costTierDisplayLabel(suite.cost_tier) },
    { key: 'games', label: '局数', value: suite.game_count == null ? '未设置' : `${formatNumber(suite.game_count)} 局` },
    { key: 'days', label: '最大天数', value: suite.max_days == null ? '未设置' : `${formatNumber(suite.max_days)} 天` },
    { key: 'roles', label: '覆盖角色', value: suiteRoleScopeLabel(suite) },
    { key: 'description', label: '说明', value: String(suite.description || '').trim() || '未填写', wide: true }
  ]
})
const contextSuiteSeedRows = computed(() => {
  const suite = selectedSuite.value
  if (!suite) return []
  const seed = selectedSuiteSeedSet.value
  const seedPreview = Array.isArray(suite.seed_preview) ? suite.seed_preview : []
  const warnings = Array.isArray(seed.overlap_warnings) ? seed.overlap_warnings : []
  return [
    { key: 'version', label: '种子版本', value: formatVersion(seed.version) || '未标记' },
    { key: 'tier', label: '种子层级', value: displayMappedLabel(seed.tier, seedTierLabels, '未标记') },
    { key: 'target-type', label: '对象类型', value: benchmarkTargetTypeLabel(seed.target_type || suite.target_type) },
    { key: 'created-at', label: '创建时间', value: formatDateTime(seed.created_at) || '未上报' },
    { key: 'usage', label: '使用边界', value: displayMappedLabel(seed.usage_boundary, seedUsageBoundaryLabels, '未标记') },
    { key: 'non-overlap', label: '非重叠组', value: seed.non_overlap_group || '未标记' },
    { key: 'immutable', label: '不可变', value: seed.immutable === false ? '否' : '是' },
    { key: 'seed-hash', label: 'Seed Hash', value: shortValue(seed.config_hash), wide: true },
    { key: 'count', label: '种子数', value: suite.seed_count == null ? '未上报' : `${formatNumber(suite.seed_count)} 个` },
    { key: 'preview', label: '种子预览', value: seedPreview.length ? seedPreview.join('、') : '未上报', wide: true },
    { key: 'warning', label: '重叠警告', value: warnings.length ? `${warnings.length} 条` : '无' }
  ]
})
const contextSuiteMetricRows = computed(() => {
  const suite = selectedSuite.value
  if (!suite) return []
  const metrics = objectOrEmpty(suite.metrics)
  const secondary = Array.isArray(metrics.secondary)
    ? metrics.secondary.map(displayBenchmarkMetric).filter(Boolean)
    : []
  return [
    { key: 'primary', label: '主指标', value: displayBenchmarkMetric(metrics.primary) || '未设置' },
    { key: 'secondary', label: '辅助指标', value: secondary.length ? secondary.join('、') : '未设置', wide: true }
  ]
})
const contextSuiteJudgeRows = computed(() => {
  const suite = selectedSuite.value
  if (!suite) return []
  const judge = objectOrEmpty(suite.judge)
  const enabled = Boolean(judge.enable_decision_judge)
  return [
    { key: 'enabled', label: '裁判判定', value: enabled ? '启用' : '未启用' },
    { key: 'max', label: '每局上限', value: enabled && judge.judge_max_decisions != null ? `${formatNumber(judge.judge_max_decisions)} 次` : '无' },
    { key: 'concurrency', label: '并发', value: enabled && judge.judge_concurrency != null ? `${formatNumber(judge.judge_concurrency)} 个任务` : '后端默认' },
    { key: 'timeout', label: '超时', value: enabled && judge.judge_timeout_seconds != null ? `${formatNumber(judge.judge_timeout_seconds)} 秒` : '后端默认' },
    { key: 'paired', label: '配对种子', value: suite.paired_seed ? '启用' : '未启用' }
  ]
})
const contextGateRows = computed(() => {
  const gates = selectedSuite.value?.gates || plan.value?.gates || {}
  const rows = [
    ['min_completed_games', '最少完成局'],
    ['min_valid_game_rate', '有效局率'],
    ['max_fallback_rate', '最大回退率'],
    ['max_llm_error_rate', '最大 LLM 错误率'],
    ['max_policy_adjusted_rate', '最大策略修正率']
  ].map(([key, label]) => ({ key, label, value: formatBenchmarkGateValue(key, gates[key]) }))
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

function objectOrEmpty(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function formatNumber(value, fallback = '--') {
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN') : fallback
}

function formatVersion(value) {
  if (value == null || value === '') return ''
  const text = String(value).trim()
  return text.startsWith('v') ? text : `v${text}`
}

function formatCost(value, currency = '', fallback = '--') {
  const number = Number(value)
  if (!Number.isFinite(number)) return fallback
  const suffix = currency ? ` ${currency}` : ''
  return `${number.toLocaleString('zh-CN', { maximumFractionDigits: 6 })}${suffix}`
}

function formatDateTime(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  const date = new Date(text)
  if (!Number.isFinite(date.getTime())) return text
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hour = String(date.getHours()).padStart(2, '0')
  const minute = String(date.getMinutes()).padStart(2, '0')
  return `${month}-${day} ${hour}:${minute}`
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

function displayBenchmarkMetric(value) {
  return displayMappedLabel(value, benchmarkMetricLabels, '')
}

function benchmarkTargetTypeLabel(value) {
  const type = String(value || '').trim().toLowerCase()
  if (type === 'model') return '模型评测'
  if (type === 'role_version') return '角色版本'
  return type || '未上报'
}

function formatBenchmarkGateValue(key, value) {
  if (value == null || value === '') return value
  const number = Number(value)
  if (Number.isFinite(number) && String(key || '').includes('rate')) {
    return `${Math.round(number * 100)}%`
  }
  return String(value)
}

function suiteRoleScopeLabel(suite = {}) {
  if (suite.target_type === 'model') return '全角色覆盖'
  const roles = Array.isArray(suite.roles) ? suite.roles.filter(Boolean) : []
  if (!roles.length) return '全角色'
  return roles.length > 4 ? `${roles.length} 个角色` : roles.join('、')
}

function densityDisplayLabel(value) {
  return displayMappedLabel(value, viewDensityLabels, '默认')
}

function displayPlanWarningKind(value) {
  return displayMappedLabel(value, planWarningLabels, '警告')
}

function displayPlanBudgetReason(value) {
  return displayMappedLabel(value, planBudgetReasonLabels, '预算原因')
}

function displayPlanWarningMessage(warning) {
  const message = String(warning?.message || '').trim()
  if (message && /[\u4e00-\u9fff]/.test(message)) return message
  const kind = String(warning?.kind || '').trim().toLowerCase()
  if (planWarningMessages[kind]) return planWarningMessages[kind]
  return message || '计划警告'
}

function formatBudgetMetricValue(value, metric) {
  return String(metric || '').includes('cost')
    ? formatCost(value, planCurrency.value)
    : formatNumber(value)
}

function budgetEvidenceCaption(item = {}) {
  const metric = String(item.metric || '').trim()
  const delta = item.delta == null ? '' : `超出 ${formatBudgetMetricValue(item.delta, metric)}`
  const unit = item.unit ? `单位 ${item.unit}` : '预算证据'
  return [delta, unit].filter(Boolean).join(' · ')
}

function budgetEvidenceRow(item, index) {
  if (!item || typeof item !== 'object') return null
  const metric = String(item.metric || '').trim()
  const estimated = formatBudgetMetricValue(item.estimated, metric)
  const limit = formatBudgetMetricValue(item.limit, metric)
  const delta = item.delta == null ? '' : `，超出 ${formatBudgetMetricValue(item.delta, metric)}`
  return {
    key: `evidence:${metric || index}`,
    label: '预算证据',
    value: displayPlanBudgetReason(metric),
    caption: `预计 ${estimated} / 上限 ${limit}${delta}`
  }
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

function benchmarkDeepLinkBatchId(source = route) {
  return typeof source === 'string'
    ? benchmarkBatchIdFromHash(source)
    : benchmarkBatchIdFromRoute(source)
}

function applyBenchmarkDeepLink(source = route) {
  const batchId = benchmarkDeepLinkBatchId(source)
  if (!batchId) return false
  activeView.value = 'runs'
  if (benchmark.selectedBenchmarkBatchId.value !== batchId) {
    benchmark.selectBenchmarkBatch(batchId)
  }
  return true
}

function handleBenchmarkHashChange(event) {
  applyBenchmarkDeepLink(event?.newURL || window.location.hash)
}

watch(
  () => route.fullPath,
  () => {
    applyBenchmarkDeepLink(route)
  }
)

onMounted(() => {
  if (typeof window !== 'undefined') window.addEventListener('hashchange', handleBenchmarkHashChange)
  void benchmark.refreshAll().finally(() => {
    applyBenchmarkDeepLink(route)
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
      :meta="benchmarkCommandMetaRows"
      action-label="刷新"
      action-busy-label="刷新中"
      :action-busy="Boolean(benchmark.loading.value)"
      :action-disabled="Boolean(benchmark.loading.value)"
      tabs-label="评测工作台视图"
      rail-label="评测套件栏"
      context-label="评测上下文"
      @action="refresh"
    >
      <template #rail>
        <BenchmarkSuiteRail :benchmark="benchmark" />
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
        <div v-else-if="benchmark.selectedBenchmarkUsingLegacyRuns.value" class="bench-alert bench-alert--warning">
          当前套件暂无匹配批次，已展示未绑定评测套件/评测集的历史评测批次。
        </div>
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
                <h2 :title="benchmark.selectedBenchmarkSuiteLabel.value">{{ benchmark.selectedBenchmarkSuiteLabel.value }}</h2>
              </div>
              <b>{{ benchmark.selectedBenchmarkId.value ? '正式' : '临时' }}</b>
            </header>
            <div v-if="contextSuiteDetailRows.length" class="bench-context-detail">
              <div class="bench-context-subtitle">
                <span>套件详情</span>
                <small>{{ launchStatusLabel }}</small>
              </div>
              <span
                v-for="item in contextSuiteDetailRows"
                :key="item.key"
                :class="{ wide: item.wide }"
              >
                <small>{{ item.label }}</small>
                <b :title="String(item.value || '')">{{ item.value }}</b>
              </span>
            </div>
            <div v-if="contextSuiteSeedRows.length" class="bench-context-detail">
              <div class="bench-context-subtitle">
                <span>种子集</span>
                <small>{{ selectedSuiteSeedSet.enabled === false ? '停用' : '固定边界' }}</small>
              </div>
              <span
                v-for="item in contextSuiteSeedRows"
                :key="item.key"
                :class="{ wide: item.wide }"
              >
                <small>{{ item.label }}</small>
                <b :title="String(item.value || '')">{{ item.value }}</b>
              </span>
            </div>
            <div v-if="contextSuiteMetricRows.length" class="bench-context-detail">
              <div class="bench-context-subtitle">
                <span>指标</span>
                <small>{{ suiteCostTierDisplayLabel }}</small>
              </div>
              <span
                v-for="item in contextSuiteMetricRows"
                :key="item.key"
                :class="{ wide: item.wide }"
              >
                <small>{{ item.label }}</small>
                <b :title="String(item.value || '')">{{ item.value }}</b>
              </span>
            </div>
            <div v-if="contextSuiteJudgeRows.length" class="bench-context-detail">
              <div class="bench-context-subtitle">
                <span>裁判配置</span>
                <small>{{ selectedSuite?.paired_seed ? 'paired seed' : '非配对' }}</small>
              </div>
              <span v-for="item in contextSuiteJudgeRows" :key="item.key">
                <small>{{ item.label }}</small>
                <b :title="String(item.value || '')">{{ item.value }}</b>
              </span>
            </div>
          </article>

          <article class="bench-context-section bench-context-section--boundary">
            <header>
              <div>
                <small>评测边界</small>
                <h2>复现口径</h2>
              </div>
            </header>
            <div class="bench-context-boundary">
              <span v-for="item in contextBoundaryRows" :key="item.key">
                <small>{{ item.label }}</small>
                <b :title="String(item.value || '')">{{ item.value }}</b>
              </span>
            </div>
          </article>

          <article class="bench-context-section bench-context-section--gate">
            <header>
              <div>
                <small>入榜门禁</small>
                <h2>正式排名约束</h2>
              </div>
              <b>{{ launchStatusLabel }}</b>
            </header>
            <div class="bench-context-gates">
              <div class="bench-context-subtitle">
                <span>门禁规则</span>
                <small>{{ budgetStatusLabel }}</small>
              </div>
              <span v-for="item in contextGateRows" :key="item.key">
                <small>{{ item.label }}</small>
                <b :title="String(item.value || '')">{{ item.value }}</b>
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
              <strong :title="contextRun.benchmarkLabel">{{ contextRun.benchmarkLabel }}</strong>
              <span :title="`${contextRun.displayRole} / ${contextRun.statusLabel}`">{{ contextRun.displayRole }} / {{ contextRun.statusLabel }}</span>
              <em :title="contextRunProgressLabel">{{ contextRunProgressLabel }}</em>
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
                  <b :title="run.benchmarkLabel">{{ run.benchmarkLabel }}</b>
                  <small :title="`${run.displayRole} / ${run.statusLabel}`">{{ run.displayRole }} / {{ run.statusLabel }}</small>
                </span>
                <em :title="run.judgeScoreLabel || '--'">{{ run.judgeScoreLabel || '--' }}</em>
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
                <b :title="String(item.value || '')">{{ item.value }}</b>
                <em :title="String(item.caption || '')">{{ item.caption }}</em>
              </span>
            </div>
            <div v-else class="bench-context-empty">当前套件边界暂无诊断。</div>
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
                <b :title="String(item.value || '')">{{ item.value }}</b>
                <em :title="String(item.caption || '')">{{ item.caption }}</em>
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
                <b>{{ launchStatusLabel }}</b>
              </header>
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
                  <span>单位预算上限</span>
                  <input
                    v-model.number="benchmark.form.value.budget_limit_units"
                    type="number"
                    min="0"
                    max="1000000"
                  />
                </label>
                <label>
                  <span>费用预算上限</span>
                  <input
                    v-model.number="benchmark.form.value.budget_limit_cost"
                    type="number"
                    min="0"
                    max="1000000"
                    step="0.0001"
                  />
                </label>
                <label>
                  <span>达到预算停止线</span>
                  <input
                    v-model.number="benchmark.form.value.stop_after_budget_units"
                    type="number"
                    min="0"
                    max="1000000"
                  />
                </label>
              </div>
              <div class="bench-plan-summary" aria-label="启动计划摘要">
                <span
                  v-for="item in planSummaryRows"
                  :key="item.key"
                  :class="{ danger: item.danger }"
                >
                  <small>{{ item.label }}</small>
                  <b>{{ item.value }}</b>
                  <em>{{ item.caption }}</em>
                </span>
              </div>
              <div v-if="planWarnings.length" class="bench-plan-warnings">
                <span v-for="warning in planWarnings" :key="warning.kind || warning.message">
                  <b>{{ displayPlanWarningKind(warning.kind) }}</b>
                  <em>{{ displayPlanWarningMessage(warning) }}</em>
                </span>
              </div>
              <div v-if="benchmark.benchmarkPlanBudgetExceeded.value && budgetReasonRows.length" class="bench-budget-reasons" aria-label="预算超限提示">
                <strong>超预算原因</strong>
                <span v-for="item in budgetReasonRows" :key="item.key">
                  <b>{{ item.label }}</b>
                  <em>{{ item.value }}</em>
                  <small>{{ item.caption }}</small>
                </span>
              </div>
              <div v-if="benchmark.benchmarkPlanError.value" class="bench-inline-warning">
                {{ benchmark.benchmarkPlanError.value }}
              </div>
              <footer class="bench-launch-strip">
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
  --logbook-bg: var(--workbench-logbook-bg, #f2dfae);
  --logbook-bg-texture: var(
    --workbench-logbook-bg-texture,
    repeating-linear-gradient(90deg, rgba(118, 71, 27, 0.024) 0 1px, transparent 1px 34px),
    var(--logbook-bg)
  );
  --logbook-surface: var(--workbench-logbook-surface, rgba(255, 252, 245, 0.7));
  --logbook-panel: var(--workbench-logbook-panel, rgba(255, 252, 245, 0.86));
  --logbook-panel-solid: var(--workbench-logbook-panel-solid, rgba(255, 250, 240, 0.92));
  --logbook-panel-soft: var(--workbench-logbook-panel-soft, rgba(255, 242, 210, 0.58));
  --logbook-border: var(--workbench-logbook-border, rgba(139, 94, 52, 0.15));
  --logbook-border-strong: var(--workbench-logbook-border-strong, rgba(90, 51, 25, 0.34));
  --logbook-text: var(--workbench-logbook-text, #3a2a18);
  --logbook-muted: var(--workbench-logbook-muted, #8b6b4a);
  --logbook-accent: var(--workbench-logbook-accent, #8b5e34);
  --logbook-accent-strong: var(--workbench-logbook-accent-strong, #5a3319);
  --logbook-input-bg: var(--workbench-logbook-input-bg, rgba(255, 255, 250, 0.8));
  --logbook-input-border: var(--workbench-logbook-input-border, rgba(139, 94, 52, 0.2));
  --logbook-hover: var(--workbench-logbook-hover, rgba(139, 94, 52, 0.06));
  --logbook-active-bg: var(--workbench-logbook-active-bg, rgba(139, 94, 52, 0.1));
  --logbook-danger: var(--workbench-logbook-danger, #993026);
  --logbook-warning: var(--workbench-logbook-warning-benchmark, #8b5e34);
  --log-bg: var(--logbook-bg, var(--workbench-logbook-bg, #f2dfae));
  --log-surface: var(--logbook-surface, var(--workbench-logbook-surface, rgba(255, 252, 245, 0.7)));
  --log-border: var(--logbook-border, var(--workbench-logbook-border, rgba(139, 94, 52, 0.15)));
  --log-text: var(--logbook-text, var(--workbench-logbook-text, #3a2a18));
  --log-text-secondary: var(--logbook-muted, var(--workbench-logbook-muted, #8b6b4a));
  --log-accent: var(--logbook-accent, var(--workbench-logbook-accent, #8b5e34));
  --log-accent-strong: var(--logbook-accent-strong, var(--workbench-logbook-accent-strong, #5a3319));
  --log-input-bg: var(--logbook-input-bg, var(--workbench-logbook-input-bg, rgba(255, 255, 250, 0.8)));
  --log-input-border: var(--logbook-input-border, var(--workbench-logbook-input-border, rgba(139, 94, 52, 0.2)));
  --log-hover: var(--logbook-hover, var(--workbench-logbook-hover, rgba(139, 94, 52, 0.06)));
  --log-active-bg: var(--logbook-active-bg, var(--workbench-logbook-active-bg, rgba(139, 94, 52, 0.1)));
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
  --lab-rail-width: 300px;
  --lab-context-width: 300px;
  display: grid;
  grid-template-columns: var(--lab-rail-width) minmax(0, 1fr) var(--lab-context-width);
  gap: 12px;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  padding: 12px;
  overflow: hidden;
}

.bench-workbench-shell :deep(.lab-workbench-main) {
  gap: 8px;
}

.bench-workbench-shell :deep(.lab-workbench-action-bar) {
  grid-template-columns: minmax(190px, 0.58fr) minmax(0, 2fr) auto;
  min-height: 0;
  padding: 10px 12px;
  border-color: rgba(139, 94, 52, 0.18);
  background: rgba(255, 249, 232, 0.76);
  box-shadow: inset 0 -1px 0 rgba(92, 54, 20, 0.08);
}

.bench-workbench-shell :deep(.lab-workbench-title h1) {
  font-size: 22px;
}

.bench-workbench-shell :deep(.lab-workbench-meta) {
  grid-template-columns: repeat(6, minmax(78px, 1fr));
  gap: 7px;
}

.bench-workbench-shell :deep(.lab-workbench-meta span) {
  min-height: 38px;
  padding: 6px 8px;
  background: rgba(255, 248, 226, 0.48);
}

.bench-workbench-shell :deep(.lab-workbench-meta small),
.bench-panel header small,
.bench-plan-summary small,
.bench-plan-controls span {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
}

.bench-workbench-shell :deep(.lab-workbench-meta b),
.bench-panel header b {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

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

.bench-launch-button:hover {
  background: var(--bench-accent);
}

.bench-launch-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.bench-workbench-shell :deep(.lab-workbench-tabs) {
  background: rgba(255, 252, 245, 0.9);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.54);
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
  align-content: start;
  align-self: start;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
  min-width: 0;
  min-height: 0;
  overflow: visible;
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
  overflow: visible;
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
  align-items: start;
  grid-auto-rows: max-content;
  gap: 10px;
  height: 100%;
  min-width: 0;
  min-height: 0;
  max-height: 100%;
  overflow-y: auto;
  padding-right: 2px;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
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
.bench-context-detail small,
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
  display: -webkit-box;
  overflow: hidden;
  margin: 2px 0 0;
  color: var(--bench-text);
  font-size: 13px;
  font-weight: 950;
  line-height: 1.16;
  overflow-wrap: anywhere;
  white-space: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
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

.bench-context-gates,
.bench-context-detail,
.bench-context-diagnostics,
.bench-context-boundary,
.bench-context-artifacts {
  display: grid;
  gap: 7px;
  min-width: 0;
  padding: 0 10px 10px;
}

.bench-context-boundary,
.bench-context-artifacts {
  padding-top: 10px;
}

.bench-context-gates span,
.bench-context-detail span,
.bench-context-diagnostics span,
.bench-context-boundary span,
.bench-context-artifacts span {
  display: grid;
  align-content: start;
  gap: 3px;
  min-width: 0;
  padding: 7px 8px;
  border: 1px solid rgba(139, 94, 52, 0.13);
  border-radius: 7px;
  background: rgba(255, 250, 240, 0.68);
}

.bench-context-gates b,
.bench-context-detail b,
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

.bench-context-gates b,
.bench-context-detail b,
.bench-context-diagnostics b,
.bench-context-boundary b,
.bench-context-artifacts b {
  color: var(--bench-text);
  font-size: 12px;
  font-weight: 900;
}

.bench-context-detail {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.bench-context-detail .bench-context-subtitle,
.bench-context-detail span.wide {
  grid-column: 1 / -1;
}

.bench-context-boundary span.danger {
  border-color: var(--bench-danger-border);
  background: var(--bench-danger-bg);
}

.bench-context-boundary span.danger b {
  color: var(--bench-danger);
}

.bench-context-diagnostics em,
.bench-context-artifacts em {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
  line-height: 1.25;
}

.bench-context-diagnostics em,
.bench-context-detail b,
.bench-context-boundary b,
.bench-context-artifacts em {
  display: -webkit-box;
  overflow-wrap: anywhere;
  white-space: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
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

.bench-diagnostic-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  padding: 12px;
}

.bench-diagnostic-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

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

.bench-diagnostic-grid b {
  color: var(--bench-text);
  font-size: 17px;
  font-weight: 950;
  line-height: 1;
}

.bench-plan-controls {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
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

.bench-plan-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  padding: 0 12px 12px;
}

.bench-plan-summary span {
  display: grid;
  gap: 3px;
  min-width: 0;
  min-height: 52px;
  padding: 9px 10px;
  border: 1px solid var(--bench-border);
  border-radius: 7px;
  background: rgba(255, 250, 240, 0.72);
}

.bench-plan-summary span.danger {
  border-color: var(--bench-danger-border);
  background: var(--bench-danger-bg);
}

.bench-plan-summary small,
.bench-plan-summary em {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-plan-summary b {
  min-width: 0;
  overflow: hidden;
  color: var(--bench-text);
  font-size: 14px;
  font-weight: 950;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-plan-summary span.danger b,
.bench-plan-summary span.danger em {
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

.bench-budget-reasons {
  display: grid;
  grid-template-columns: 140px repeat(2, minmax(0, 1fr));
  gap: 7px;
  align-items: stretch;
  margin: 0 12px 12px;
  padding: 9px 10px;
  border: 1px solid var(--bench-danger-border);
  border-radius: 7px;
  background: var(--bench-danger-bg);
}

.bench-budget-reasons strong,
.bench-budget-reasons span {
  min-width: 0;
}

.bench-budget-reasons strong {
  display: flex;
  align-items: center;
  color: var(--bench-danger);
  font-size: 12px;
  font-weight: 950;
}

.bench-budget-reasons span {
  display: grid;
  gap: 3px;
  padding: 7px 8px;
  border: 1px solid rgba(153, 48, 38, 0.18);
  border-radius: 6px;
  background: rgba(255, 250, 240, 0.56);
}

.bench-budget-reasons b,
.bench-budget-reasons em,
.bench-budget-reasons small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bench-budget-reasons b {
  color: var(--bench-danger);
  font-size: 12px;
  font-weight: 950;
}

.bench-budget-reasons em,
.bench-budget-reasons small {
  color: var(--bench-text-secondary);
  font-size: 11px;
  font-style: normal;
  font-weight: 850;
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
  display: flex;
  justify-content: flex-end;
  margin: 0 12px 12px;
  padding: 10px;
  border: 1px solid var(--bench-border);
  border-radius: 7px;
  background: rgba(255, 242, 210, 0.5);
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
  align-self: start;
  overflow: visible;
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
