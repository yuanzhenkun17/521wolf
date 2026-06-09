<script setup>
import { computed, ref, watch } from 'vue'
import JudgeEvidencePanel from '../history/JudgeEvidencePanel.vue'

const props = defineProps({
  benchmark: {
    type: Object,
    required: true
  }
})

const copyState = ref('')
const exportState = ref('')
const selectedReportExportArtifact = ref(null)

const STATUS_LABELS = {
  ok: '正常',
  pass: '通过',
  passed: '通过',
  accepted: '通过',
  rejected: '拒绝',
  running: '运行中',
  pending: '排队中',
  queued: '排队中',
  completed: '已完成',
  failed: '失败',
  fail: '失败',
  timeout: '超时',
  abnormal: '异常',
  cancelled: '已取消',
  interrupted: '已中断',
  skipped: '已跳过',
  disabled: '已关闭',
  degraded: '降级',
  warning: '警告',
  warn: '警告',
  error: '错误',
  bad: '低分',
  good: '良好',
  unknown: '未知',
  info: '信息'
}

const DISPLAY_LABELS = {
  'Benchmark ID': '评测 ID',
  benchmark_id: '评测 ID',
  run_id: '运行 ID',
  batch_id: '运行 ID',
  suite: '套件',
  status: '状态',
  target_type: '对象类型',
  subject: '评测对象',
  evaluation_set_id: '评测集',
  seed_set_id: '种子集',
  benchmark_config_hash: '配置 Hash',
  config_hash: '配置 Hash',
  content_hash: '内容摘要',
  reproducibility_manifest_hash: '复现清单 Hash',
  manifest_hash: 'Manifest Hash',
  artifacts: '产物',
  model_id: '模型 ID',
  model_config_hash: '模型配置 Hash',
  target_role: '目标角色',
  target_version_id: '目标版本',
  Decision: '决策',
  'Decision Judge': '决策 Judge',
  decision_judge: '决策 Judge',
  diagnostic: '诊断',
  diagnostics: '诊断',
  warning: '警告',
  warnings: '警告',
  error: '错误',
  errors: '错误',
  failed: '失败',
  completed: '已完成',
  judged: '已判定',
  bad: '低分',
  bad_rate: '低分率',
  quality: '质量',
  action_type: '行动类型',
  evidence_ref: '证据引用',
  evidence_refs: '证据引用',
  counterfactual: '反事实',
  counterfactuals: '反事实',
  rubric_miss: '评分规则未命中',
  rubric_misses: '评分规则未命中',
  mistake_tag: '错误标签',
  mistake_tags: '错误标签',
  degraded_reason: '降级原因',
  degraded_reasons: '降级原因',
  failure_reason: '失败原因',
  accepted: '通过',
  rejected: '拒绝',
  unknown: '未知',
  result: '结果批次',
  run: '运行',
  report: '正式报告'
}

const selectedRun = computed(() => props.benchmark.selectedBenchmarkBatchRun.value || null)
const selectedBatchId = computed(() => props.benchmark.selectedBenchmarkBatchId.value || '')
const detail = computed(() => props.benchmark.benchmarkBatchDetail.value || null)
const rawCanonicalReport = computed(() => props.benchmark.benchmarkBatchReport?.value || null)
const reportLoading = computed(() => Boolean(props.benchmark.benchmarkBatchReportLoading?.value))
const reportError = computed(() => String(props.benchmark.benchmarkBatchReportError?.value || ''))
const canonicalReport = computed(() => {
  const report = objectOrEmpty(rawCanonicalReport.value)
  if (report.kind !== 'benchmark_run_report') return null
  const selectedId = String(selectedBatchId.value || detail.value?.batch_id || selectedRun.value?.id || '')
  const reportIds = [report.batch_id, report.run_id].map((value) => String(value || '')).filter(Boolean)
  if (selectedId && reportIds.length && !reportIds.includes(selectedId)) return null
  return report
})
const reportSuite = computed(() => objectOrEmpty(canonicalReport.value?.suite))
const reportSubject = computed(() => objectOrEmpty(canonicalReport.value?.subject))
const reportSummary = computed(() => objectOrEmpty(canonicalReport.value?.summary))
const reportLeaderboard = computed(() => objectOrEmpty(canonicalReport.value?.leaderboard))
const reportSourceLabel = computed(() => {
  if (canonicalReport.value) return '正式报告'
  if (reportLoading.value) return '正在加载报告'
  if (reportError.value) return '本地回退报告'
  return '本地报告'
})
const results = computed(() => {
  const reportRows = asArray(canonicalReport.value?.results)
  return reportRows.length ? reportRows : asArray(detail.value?.resultRows)
})
const games = computed(() => asArray(props.benchmark.benchmarkBatchGames.value))
const diagnostics = computed(() => asArray(props.benchmark.benchmarkBatchDiagnostics.value))
const recentRuns = computed(() => asArray(props.benchmark.filteredBatchRunRows.value).slice(0, 8))
const reportHistory = computed(() => asArray(props.benchmark.benchmarkReportHistory?.value).slice(0, 8))
const reportHistoryError = computed(() => String(props.benchmark.benchmarkReportHistoryError?.value || ''))
const reportHistoryLoading = computed(() => Boolean(props.benchmark.benchmarkReportHistoryLoading?.value))
const isModelSuite = computed(() => Boolean(props.benchmark.selectedBenchmarkIsModelSuite.value))
const leaderboardRows = computed(() =>
  isModelSuite.value
    ? asArray(props.benchmark.modelLeaderboardRows.value)
    : asArray(props.benchmark.roleLeaderboardRows.value)
)

const benchmarkMeta = computed(() =>
  detail.value?.benchmark ||
  selectedRun.value?.benchmark ||
  selectedRun.value?.config?.benchmark ||
  props.benchmark.selectedBenchmarkSuite.value ||
  {}
)

const selectedResult = computed(() => results.value[0] || null)
const selectedConfig = computed(() => selectedRun.value?.config || detail.value?.config || {})

const headerRows = computed(() => [
  { label: '运行 ID', value: selectedRunId.value },
  { label: '套件', value: suiteLabel.value },
  { label: '状态', value: statusLabel.value },
  { label: '对象类型', value: targetTypeLabel.value },
  { label: '评测集', value: evaluationSetId.value },
  { label: '种子集', value: seedSetId.value },
  { label: '评测对象', value: subjectLabel.value }
])

const selectedRunId = computed(() =>
  String(canonicalReport.value?.run_id || canonicalReport.value?.batch_id || detail.value?.batch_id || selectedRun.value?.id || selectedBatchId.value || '')
)
const suiteLabel = computed(() =>
  reportSuite.value.label ||
  detail.value?.benchmarkLabel ||
  selectedRun.value?.benchmarkLabel ||
  props.benchmark.selectedBenchmarkSuiteLabel.value ||
  '临时评测'
)
const statusLabel = computed(() =>
  valueOrDash(canonicalReport.value?.status) !== '--' ? statusDisplayLabel(canonicalReport.value?.status) :
  statusDisplayLabel(
    detail.value?.statusLabel ||
    selectedRun.value?.statusLabel ||
    valueOrDash(selectedRun.value?.status)
  )
)
const targetType = computed(() =>
  reportSuite.value.target_type ||
  detail.value?.target_type ||
  selectedRun.value?.benchmarkTargetType ||
  benchmarkMeta.value?.target_type ||
  (isModelSuite.value ? 'model' : 'role_version')
)
const targetTypeLabel = computed(() =>
  detail.value?.targetTypeLabel ||
  selectedRun.value?.benchmarkTargetTypeLabel ||
  (targetType.value === 'model' ? '模型评测' : '角色版本')
)
const evaluationSetId = computed(() =>
  reportSuite.value.evaluation_set_id ||
  benchmarkMeta.value?.evaluation_set_id ||
  detail.value?.evaluation_set_id ||
  selectedRun.value?.evaluationSetId ||
  props.benchmark.selectedBenchmarkEvaluationSetId.value ||
  'ad-hoc'
)
const seedSetId = computed(() =>
  reportSuite.value.seed_set_id ||
  benchmarkMeta.value?.seed_set_id ||
  detail.value?.seed_set_id ||
  selectedConfig.value?.seed_set_id ||
  'ad-hoc'
)
const configHash = computed(() =>
  reportSuite.value.benchmark_config_hash ||
  benchmarkMeta.value?.config_hash ||
  benchmarkMeta.value?.benchmark_config_hash ||
  selectedConfig.value?.benchmark_config_hash ||
  selectedConfig.value?.config_hash ||
  ''
)

const modelId = computed(() =>
  reportSubject.value.model_id ||
  selectedConfig.value?.model_id ||
  selectedResult.value?.model_id ||
  selectedRun.value?.model_id ||
  props.benchmark.form.value?.model_id ||
  ''
)
const modelConfigHash = computed(() =>
  reportSubject.value.model_config_hash ||
  selectedConfig.value?.model_config_hash ||
  selectedResult.value?.model_config_hash ||
  selectedRun.value?.model_config_hash ||
  props.benchmark.form.value?.model_config_hash ||
  ''
)
const targetRole = computed(() =>
  reportSubject.value.target_role ||
  selectedResult.value?.target_role ||
  selectedConfig.value?.target_role ||
  asArray(selectedRun.value?.roleKeys)[0] ||
  props.benchmark.selectedRole.value ||
  ''
)
const targetRoleLabel = computed(() =>
  selectedResult.value?.targetRoleLabel ||
  selectedRun.value?.displayRole ||
  props.benchmark.selectedRoleLabel.value ||
  valueOrDash(targetRole.value)
)
const targetVersionId = computed(() =>
  reportSubject.value.target_version_id ||
  selectedResult.value?.target_version_id ||
  selectedConfig.value?.target_version_id ||
  selectedConfig.value?.target_versions?.[targetRole.value] ||
  props.benchmark.form.value?.target_version_id ||
  ''
)
const subjectLabel = computed(() => {
  if (reportSubject.value.label) return reportSubject.value.label
  if (targetType.value === 'model') {
    return compactJoin([modelId.value, modelConfigHash.value], ' / ') || '当前后端模型'
  }
  return compactJoin([targetRoleLabel.value, targetVersionId.value || '基线版本'], ' / ')
})

const gameSummary = computed(() => {
  const summary = objectOrEmpty(reportSummary.value.game_summary)
  if (Object.keys(summary).length) return summary
  return detail.value?.gameSummary || detail.value?.game_summary || {}
})
const diagnosticSummary = computed(() => {
  const summary = objectOrEmpty(reportSummary.value.diagnostic_summary)
  if (Object.keys(summary).length) return summary
  return detail.value?.diagnosticSummary ||
    detail.value?.diagnostic_summary ||
    props.benchmark.benchmarkBatchDiagnosticSummary.value ||
    {}
})

const gameTotal = computed(() =>
  numberOrZero(
    gameSummary.value.total ??
    props.benchmark.benchmarkBatchGamePagination.value?.total ??
    games.value.length
  )
)
const diagnosticTotal = computed(() =>
  numberOrZero(diagnosticSummary.value.total ?? diagnostics.value.length)
)
const resultCount = computed(() =>
  numberOrZero(reportSummary.value.result_count ?? detail.value?.result_count ?? results.value.length)
)
const rankableRows = computed(() => results.value.filter((row) => row?.rankable !== false))
const unrankableRows = computed(() => results.value.filter((row) => row?.rankable === false))
const rankableLabel = computed(() => {
  if (canonicalReport.value) {
    const total = numberOrZero(reportSummary.value.result_count ?? results.value.length)
    if (!total) return '暂无结果行'
    const rankable = numberOrZero(reportSummary.value.rankable_count ?? rankableRows.value.length)
    const unrankable = numberOrZero(reportSummary.value.unrankable_count ?? Math.max(total - rankable, 0))
    return unrankable ? `${rankable}/${total} 可排名` : '全部可排名'
  }
  if (!results.value.length) return '暂无结果行'
  if (unrankableRows.value.length) return `${rankableRows.value.length}/${results.value.length} 可排名`
  return '全部可排名'
})

const summaryRows = computed(() => [
  { key: 'rankable', label: '可排名', value: rankableLabel.value, caption: gateCaption.value },
  { key: 'results', label: '结果', value: resultCount.value, caption: '结果批次' },
  { key: 'games', label: '对局', value: gameTotal.value, caption: problemGameCaption.value },
  { key: 'diagnostics', label: '诊断', value: diagnosticTotal.value, caption: topDiagnosticCaption.value },
  { key: 'leaderboard', label: '排行榜', value: leaderboardRows.value.length, caption: '当前榜单行' }
])

const gateRows = computed(() => {
  const reportRows = asArray(canonicalReport.value?.gates)
  if (reportRows.length) {
    return reportRows.map((row, index) => ({
      key: row?.key || `report-gate-${index}`,
      title: displayPhrase(row?.title || `门禁 ${index + 1}`),
      status: statusDisplayLabel(row?.status || ''),
      reason: displayPhrase(row?.reason || '未返回门禁原因'),
      meta: displayPhrase(row?.meta || '门禁'),
      blocked: Boolean(row?.blocked)
    })).slice(0, 16)
  }
  const rows = results.value.map((result, index) => ({
    key: result?.result_batch_id || result?.batch_id || `result-${index}`,
    title: result?.targetRoleLabel || result?.model_id || result?.result_batch_id || `结果 ${index + 1}`,
    status: statusDisplayLabel(result?.rankableLabel || (result?.rankable === false ? '不可排名' : '可排名')),
    reason: displayPhrase(result?.rankableReason || result?.rankable_reason || '未返回门禁原因'),
    meta: compactJoin([
      result?.targetVersionShort || result?.target_version_id,
      result?.completed == null ? '' : `${result.completed} 完成`,
      result?.game_count == null ? '' : `${result.game_count} 局`
    ], ' / '),
    blocked: result?.rankable === false
  }))
  for (const kind of detailDiagnosticKindRows.value) {
    rows.push({
      key: `kind-${kind.name}`,
      title: diagnosticDisplayLabel(kind.label || kind.name),
      status: `${kind.count} 条诊断`,
      reason: '所选运行返回的诊断类型',
      meta: '诊断类型',
      blocked: false
    })
  }
  return rows.slice(0, 10)
})

const detailDiagnosticKindRows = computed(() => {
  const rows = asArray(detail.value?.diagnosticKindRows)
  if (rows.length) return rows
  return countRows(diagnosticSummary.value.by_kind)
})

const problemGames = computed(() =>
  (asArray(canonicalReport.value?.problem_games).length
    ? asArray(canonicalReport.value?.problem_games)
    : games.value)
    .map((game) => ({
      ...game,
      id: String(game?.game_id || game?.id || ''),
      statusWeight: problemStatusWeight(game?.status),
      statusLabel: statusDisplayLabel(game?.status_label || game?.statusLabel || game?.status),
      diagnostics: numberOrZero(game?.diagnostic_count),
      seed: game?.seedLabel || valueOrDash(game?.seed),
      target: game?.targetRoleLabel || valueOrDash(game?.target_role),
      replayHash: archiveReplayHash(game),
      replayUnavailableReason: displayPhrase(game?.replay_unavailable_reason || '')
    }))
    .filter((game) => game.id)
    .sort((a, b) =>
      b.statusWeight - a.statusWeight ||
      b.diagnostics - a.diagnostics ||
      String(a.id).localeCompare(String(b.id))
    )
    .slice(0, 8)
)

const diagnosticGroups = computed(() => {
  const reportGroups = asArray(canonicalReport.value?.diagnostics)
  if (reportGroups.length) {
    return reportGroups.map((group, index) => ({
      ...group,
      key: group?.kind || group?.label || `diagnostic-${index}`,
      kind: group?.kind || group?.label || 'diagnostic',
      kindLabel: diagnosticDisplayLabel(group?.label || group?.kind || 'diagnostic'),
      total: numberOrZero(group?.total),
      levelLabel: levelDisplayLabel(group?.level || '无等级'),
      gameCount: numberOrZero(group?.game_count),
      stageCount: numberOrZero(group?.stage_count)
    })).slice(0, 8)
  }
  const groups = new Map()
  for (const item of diagnostics.value) {
    const key = String(item?.kind || 'diagnostic')
    const level = String(item?.level || 'info').toLowerCase()
    const current = groups.get(key) || {
      key,
      kind: key,
      kindLabel: diagnosticDisplayLabel(item?.kindLabel || key),
      total: 0,
      levels: new Map(),
      games: new Set(),
      stages: new Set()
    }
    current.total += 1
    current.levels.set(level, (current.levels.get(level) || 0) + 1)
    if (item?.game_id) current.games.add(String(item.game_id))
    if (item?.stage) current.stages.add(String(item.stage))
    groups.set(key, current)
  }
  return [...groups.values()]
    .map((group) => ({
      ...group,
      levelLabel: topMapEntry(group.levels),
      gameCount: group.games.size,
      stageCount: group.stages.size
    }))
    .sort((a, b) => b.total - a.total || a.kindLabel.localeCompare(b.kindLabel))
    .slice(0, 8)
})

const benchmarkJudgeDiagnostics = computed(() =>
  uniqueRows([
    ...diagnostics.value,
    ...asArray(canonicalReport.value?.decision_judge_diagnostics),
    ...asArray(canonicalReport.value?.judge_diagnostics)
  ].filter(isBenchmarkJudgeDiagnostic))
)

const benchmarkJudgeAggregateSources = computed(() => {
  const sources = []
  for (const result of results.value) {
    const aggregate = benchmarkResultJudgeAggregate(result)
    if (!hasObjectData(aggregate)) continue
    const resultId = String(result?.result_batch_id || result?.batch_id || `result-${sources.length}`)
    sources.push({
      type: 'result',
      key: `result-${resultId}`,
      title: result?.targetRoleLabel || result?.model_id || result?.target_role || resultId,
      result,
      aggregate
    })
  }
  if (!sources.length) {
    const runAggregate = objectOrEmpty(
      selectedRun.value?.judgeAggregate ||
      selectedRun.value?.scoreSummary?.decision_judge_aggregate ||
      selectedRun.value?.decision_judge_aggregate
    )
    if (hasObjectData(runAggregate)) {
      sources.push({
        type: 'run',
        key: `run-${selectedRunId.value || 'selected'}`,
        title: subjectLabel.value,
        result: null,
        aggregate: runAggregate
      })
    }
  }
  const reportAggregate = objectOrEmpty(canonicalReport.value?.decision_judge_aggregate || canonicalReport.value?.judge_aggregate)
  if (hasObjectData(reportAggregate) && !sources.some((source) => rowIdentity(source.aggregate) === rowIdentity(reportAggregate))) {
    sources.push({
      type: 'report',
      key: `report-${selectedRunId.value || 'canonical'}`,
      title: subjectLabel.value,
      result: null,
      aggregate: reportAggregate
    })
  }
  return sources
})

const benchmarkJudgeEvidenceRows = computed(() => {
  const rows = []
  for (const source of benchmarkJudgeAggregateSources.value) {
    const scopedDiagnostics = benchmarkJudgeDiagnostics.value
      .filter((row) => diagnosticMatchesBenchmarkJudgeSource(row, source))
    const aggregateEvidence = buildBenchmarkAggregateEvidence(source.aggregate, scopedDiagnostics)
    if (aggregateEvidence.hasAny) {
      rows.push({
        key: `${source.key}-aggregate`,
        title: source.title,
        status: judgeAggregateStatus(source.aggregate),
        meta: judgeAggregateMeta(source),
        evidence: aggregateEvidence
      })
    }
    asArray(source.aggregate?.lowest_decisions).forEach((decision, index) => {
      const decisionDiagnostics = scopedDiagnostics.filter((row) => diagnosticMatchesJudgeDecision(row, decision))
      const decisionEvidence = buildBenchmarkDecisionEvidence(decision, decisionDiagnostics)
      if (!decisionEvidence.hasAny) return
      rows.push({
        key: `${source.key}-decision-${judgeDecisionId(decision) || index}`,
        title: judgeDecisionTitle(decision, index),
        status: judgeDecisionStatus(decision),
        meta: compactJoin([source.title, decision?.game_id ? `对局 ${decision.game_id}` : '最低分决策'], ' / '),
        evidence: decisionEvidence
      })
    })
  }
  if (!rows.length && benchmarkJudgeDiagnostics.value.length) {
    const fallbackEvidence = buildBenchmarkAggregateEvidence({}, benchmarkJudgeDiagnostics.value)
    rows.push({
      key: 'benchmark-judge-diagnostics',
      title: '决策 Judge 诊断',
      status: `${benchmarkJudgeDiagnostics.value.length} 条`,
      meta: '评测诊断',
      evidence: fallbackEvidence
    })
  }
  return rows.filter((row) => row.evidence?.hasAny).slice(0, 12)
})

const diagnosticEvidenceGroupCount = computed(() =>
  (diagnosticGroups.value.length || topTags.value.length) + benchmarkJudgeEvidenceRows.value.length
)

const topTags = computed(() => {
  const reportTags = asArray(canonicalReport.value?.tags)
  if (reportTags.length) {
    return reportTags
      .map((tag) => ({ label: diagnosticDisplayLabel(tag?.label || tag?.tag), count: numberOrZero(tag?.count) }))
      .filter((tag) => tag.label)
      .slice(0, 8)
  }
  const tagCounts = new Map()
  for (const tag of asArray(selectedRun.value?.judgeTags)) {
    const label = diagnosticDisplayLabel(tag?.tag)
    if (!label) continue
    tagCounts.set(label, (tagCounts.get(label) || 0) + numberOrZero(tag?.count))
  }
  for (const item of diagnostics.value) {
    const label = diagnosticDisplayLabel(item?.kindLabel || item?.kind)
    if (!label) continue
    tagCounts.set(label, (tagCounts.get(label) || 0) + 1)
  }
  return [...tagCounts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
    .slice(0, 8)
})

const reproducibilityRows = computed(() => {
  const reproducibility = objectOrEmpty(canonicalReport.value?.reproducibility)
  const rows = Object.entries(reproducibility).map(([label, value]) => ({ label: reproducibilityLabel(label), value }))
  if (rows.length) return rows
  return [
    { label: '套件', value: suiteLabel.value },
    { label: '评测 ID', value: benchmarkMeta.value?.id || selectedRun.value?.benchmarkId || 'ad-hoc' },
    { label: '评测集', value: evaluationSetId.value },
    { label: '种子集', value: seedSetId.value },
    { label: '配置 Hash', value: configHash.value || '未返回' },
    { label: '模型 ID', value: modelId.value || '未返回' },
    { label: '模型配置 Hash', value: modelConfigHash.value || '未返回' },
    { label: '目标角色', value: targetRole.value || targetRoleLabel.value || '未返回' },
    { label: '目标版本', value: targetVersionId.value || '基线版本' }
  ]
})
const reportArtifacts = computed(() => objectOrEmpty(canonicalReport.value?.artifacts))
const reportManifest = computed(() => objectOrEmpty(canonicalReport.value?.reproducibility_manifest))
const reportManifestArtifactHashes = computed(() => objectOrEmpty(reportManifest.value.artifact_hashes))
const reportContentHash = computed(() =>
  String(
    canonicalReport.value?.content_hash ||
    reportArtifacts.value.content_hash ||
    reportManifest.value.content_hash ||
    reportManifestArtifactHashes.value.content_hash ||
    ''
  ).trim()
)
const reportManifestHash = computed(() =>
  String(
    canonicalReport.value?.reproducibility_manifest_hash ||
    reportArtifacts.value.reproducibility_manifest_hash ||
    reportManifest.value.manifest_hash ||
    ''
  ).trim()
)
const reportManifestContentHash = computed(() =>
  String(
    reportManifest.value.content_hash ||
    reportManifestArtifactHashes.value.content_hash ||
    ''
  ).trim()
)
const selectedReportExportHash = computed(() =>
  String(
    selectedReportExportArtifact.value?.export_content_hash ||
    selectedReportExportArtifact.value?.artifact_hash ||
    selectedReportExportArtifact.value?.reproducibility_manifest?.artifact_hashes?.export_content_hash ||
    ''
  ).trim()
)
const reportManifestStatus = computed(() => {
  if (!reportManifestHash.value && !reportContentHash.value) {
    return { label: '未上报', tone: 'unknown', caption: '报告未返回复现清单' }
  }
  const checks = []
  if (reportManifestHash.value && reportManifest.value.manifest_hash) {
    checks.push(reportManifestHash.value === String(reportManifest.value.manifest_hash))
  }
  if (reportContentHash.value && reportManifestContentHash.value) {
    checks.push(reportContentHash.value === reportManifestContentHash.value)
  }
  const artifactContentHash = String(reportManifestArtifactHashes.value.content_hash || '').trim()
  if (reportContentHash.value && artifactContentHash) {
    checks.push(reportContentHash.value === artifactContentHash)
  }
  if (!checks.length) {
    return { label: '待校验', tone: 'unknown', caption: '缺少可比对 hash 字段' }
  }
  if (checks.every(Boolean)) {
    return { label: '已校验', tone: 'ready', caption: 'manifest_hash 与 content_hash 一致' }
  }
  return { label: '不一致', tone: 'blocked', caption: 'manifest 与报告 hash 不一致' }
})
const reportAuditRows = computed(() => [
  {
    key: 'content-hash',
    label: '内容 Hash',
    value: reportContentHash.value ? shortHash(reportContentHash.value) : '未上报',
    caption: reportContentHash.value || 'content_hash 未上报'
  },
  {
    key: 'manifest-hash',
    label: '复现清单 Hash',
    value: reportManifestHash.value ? shortHash(reportManifestHash.value) : '未上报',
    caption: reportManifestHash.value ? `Manifest Hash: ${reportManifestHash.value}` : 'reproducibility_manifest_hash 未上报'
  },
  {
    key: 'manifest-status',
    label: '校验状态',
    value: reportManifestStatus.value.label,
    caption: reportManifestStatus.value.caption,
    tone: reportManifestStatus.value.tone
  },
  {
    key: 'manifest-content',
    label: 'Manifest 内容',
    value: reportManifestContentHash.value ? shortHash(reportManifestContentHash.value) : '未上报',
    caption: reportManifestContentHash.value || 'manifest.content_hash 未上报'
  },
  {
    key: 'export-hash',
    label: '导出 Hash',
    value: selectedReportExportHash.value ? shortHash(selectedReportExportHash.value) : '未导出',
    caption: selectedReportExportHash.value || '导出后显示 export_content_hash'
  }
])

const leaderboardScopeValue = computed(() =>
  reportLeaderboard.value.scope || targetType.value
)
const leaderboardBoundaryLabel = computed(() =>
  compactJoin([
    leaderboardScopeValue.value === 'model' ? '模型范围' : '角色版本范围',
    reportLeaderboard.value.evaluation_set_id || evaluationSetId.value,
    reportLeaderboard.value.target_role || (leaderboardScopeValue.value === 'role_version' ? targetRoleLabel.value : '')
  ], ' / ')
)
const gateCaption = computed(() => {
  if (canonicalReport.value) {
    const blocked = gateRows.value.find((row) => row.blocked)
    return blocked ? (blocked.reason || '门禁未通过') : '门禁通过'
  }
  if (!results.value.length) return '详情待加载'
  if (!unrankableRows.value.length) return '门禁通过'
  return displayPhrase(unrankableRows.value[0]?.rankableReason || unrankableRows.value[0]?.rankable_reason || '门禁未通过')
})
const problemGameCaption = computed(() => {
  if (canonicalReport.value) {
    const count = numberOrZero(reportSummary.value.problem_game_count ?? problemGames.value.length)
    return count ? `${count} 个问题样本` : '无问题样本'
  }
  const count = problemGames.value.filter((game) => game.statusWeight > 0 || game.diagnostics > 0).length
  return count ? `已加载 ${count} 个问题样本` : '未加载问题样本'
})
const topDiagnosticCaption = computed(() =>
  diagnosticGroups.value[0]
    ? `${diagnosticGroups.value[0].kindLabel}: ${diagnosticGroups.value[0].total}`
    : '未加载'
)

watch(selectedRunId, () => {
  selectedReportExportArtifact.value = null
  exportState.value = ''
})

const markdownReport = computed(() => {
  if (!selectedRun.value) return ''
  const lines = [
    `# 评测运行报告：${selectedRunId.value}`,
    '',
    '## 报告头',
    ...headerRows.value.map((row) => `- ${row.label}: ${markdownValue(row.value)}`),
    '',
    '## 摘要',
    ...summaryRows.value.map((row) => `- ${row.label}: ${markdownValue(row.value)} (${markdownValue(row.caption)})`),
    '',
    '## 门禁摘要',
    ...markdownGateRows.value,
    '',
    '## 问题对局',
    ...markdownGameRows.value,
    '',
    '## 诊断与标签',
    ...markdownDiagnosticRows.value,
    '',
    '## 审计证据',
    ...reportAuditRows.value.map((row) => `- ${row.label}: ${markdownValue(row.value)} (${markdownValue(row.caption)})`),
    '',
    '## 追溯数据',
    ...reproducibilityRows.value.map((row) => `- ${row.label}: ${markdownValue(row.value)}`)
  ]
  return lines.join('\n')
})

const jsonReport = computed(() =>
  selectedRun.value ? JSON.stringify(canonicalReport.value || reportPayload(), null, 2) : ''
)

const csvReport = computed(() =>
  selectedRun.value
    ? toCsv([
        ['区段', '标签', '值', '详情'],
        ...headerRows.value.map((row) => ['报告头', row.label, row.value, '']),
        ...summaryRows.value.map((row) => ['摘要', row.label, row.value, row.caption]),
        ...gateRows.value.map((row) => ['门禁', row.title, row.status, compactJoin([row.reason, row.meta], ' / ')]),
        ...problemGames.value.map((game) => [
          '对局',
          game.id,
          game.statusLabel || game.status || '',
          compactJoin([
            `种子 ${game.seed}`,
            game.target,
            `${game.diagnostics} 条诊断`,
            game.history_game_id ? `日志 ${game.history_game_id}` : '',
            game.replayHash ? `回放 ${game.replayHash}` : '无回放'
          ], ' / ')
        ]),
        ...diagnosticGroups.value.map((group) => [
          '诊断',
          group.kindLabel,
          group.total,
          compactJoin([group.levelLabel, `${group.gameCount} 局`, `${group.stageCount} 阶段`], ' / ')
        ]),
        ...topTags.value.map((tag) => ['标签', tag.label, tag.count, '']),
        ...reportAuditRows.value.map((row) => ['审计证据', row.label, row.value, row.caption]),
        ...reproducibilityRows.value.map((row) => ['追溯', row.label, row.value, ''])
      ])
    : ''
)

const markdownGateRows = computed(() =>
  gateRows.value.length
    ? gateRows.value.map((row) =>
        `- ${markdownValue(row.title)}: ${markdownValue(row.status)} - ${markdownValue(row.reason)}`
      )
    : ['- 未加载门禁行']
)
const markdownGameRows = computed(() =>
  problemGames.value.length
    ? problemGames.value.slice(0, 6).map((game) =>
        `- ${markdownValue(game.id)}: ${markdownValue(game.statusLabel || statusDisplayLabel(game.status))} / 种子 ${markdownValue(game.seed)} / 诊断 ${game.diagnostics} / 回放 ${markdownValue(game.replayHash || game.replayUnavailableReason || '不可用')}`
      )
    : ['- 未加载对局样本']
)
const markdownDiagnosticRows = computed(() => {
  if (diagnosticGroups.value.length) {
    return diagnosticGroups.value.map((group) =>
      `- ${markdownValue(group.kindLabel)}: ${group.total} (${markdownValue(group.levelLabel)})`
    )
  }
  if (topTags.value.length) {
    return topTags.value.map((tag) => `- ${markdownValue(tag.label)}: ${tag.count}`)
  }
  return ['- 未加载诊断']
})

async function copyReport() {
  copyState.value = ''
  const text = await resolveExportText('markdown')
  if (!text || typeof navigator === 'undefined' || !navigator.clipboard?.writeText) return
  try {
    await navigator.clipboard.writeText(text)
    copyState.value = '已复制'
    window.setTimeout(() => {
      copyState.value = ''
    }, 1600)
  } catch {
    copyState.value = ''
  }
}

async function copyExport(format) {
  const text = await resolveExportText(format)
  copyState.value = ''
  exportState.value = ''
  if (!text || typeof navigator === 'undefined' || !navigator.clipboard?.writeText) return
  try {
    await navigator.clipboard.writeText(text)
    exportState.value = reportExportStateLabel(format, '已复制')
    clearTransientState(exportState)
  } catch {
    exportState.value = ''
  }
}

async function downloadReport(format) {
  const text = await resolveExportText(format)
  if (!text) return
  const extension = format === 'markdown' ? 'md' : format
  const mime = format === 'json'
    ? 'application/json'
    : (format === 'csv' ? 'text/csv' : 'text/markdown')
  if (downloadText(`${safeFilename(selectedRunId.value || 'benchmark-run-report')}.${extension}`, text, mime)) {
    exportState.value = reportExportStateLabel(format, '已导出')
    clearTransientState(exportState)
  }
}

function localExportText(format) {
  if (format === 'json') return jsonReport.value
  if (format === 'csv') return csvReport.value
  return markdownReport.value
}

async function resolveExportText(format) {
  const normalized = String(format || 'markdown').toLowerCase()
  if (normalized === 'json') return jsonReport.value
  const loader = props.benchmark.loadBenchmarkBatchReportExport
  if (canonicalReport.value && typeof loader === 'function') {
    const payload = await loader(normalized, selectedRunId.value || selectedBatchId.value)
    if (payload && typeof payload === 'object') {
      if (payload.export_content_hash || payload.artifact_hash || payload.reproducibility_manifest_hash) {
        selectedReportExportArtifact.value = payload
      }
      if (typeof payload.content === 'string') return payload.content
    }
    if (typeof payload === 'string' && payload) return payload
  }
  return localExportText(normalized)
}

function reportExportStateLabel(format, action) {
  const hash = selectedReportExportHash.value
  const suffix = hash ? ` / ${shortHash(hash)}` : ''
  return `${String(format || '').toUpperCase()} ${action}${suffix}`
}

function reportPayload() {
  return {
    kind: 'benchmark_run_report',
    schema_version: 1,
    generated_at: new Date().toISOString(),
    run_id: selectedRunId.value,
    suite: {
      label: suiteLabel.value,
      benchmark_id: benchmarkMeta.value?.id || selectedRun.value?.benchmarkId || '',
      target_type: targetType.value,
      evaluation_set_id: evaluationSetId.value,
      seed_set_id: seedSetId.value,
      benchmark_config_hash: configHash.value || ''
    },
    subject: {
      label: subjectLabel.value,
      target_role: targetRole.value,
      target_version_id: targetVersionId.value,
      model_id: modelId.value,
      model_config_hash: modelConfigHash.value
    },
    header: headerRows.value,
    summary: summaryRows.value,
    gates: gateRows.value.map((row) => ({
      title: row.title,
      status: row.status,
      reason: row.reason,
      meta: row.meta,
      blocked: row.blocked
    })),
    problem_games: problemGames.value.map((game) => ({
      game_id: game.id,
      status: game.status || '',
      status_label: game.statusLabel || '',
      seed: game.seed,
      target: game.target,
      diagnostic_count: game.diagnostics,
      replay_available: game.replay_available ?? null,
      history_game_id: game.history_game_id || '',
      replay_hash: game.replayHash || ''
    })),
    diagnostics: diagnosticGroups.value.map((group) => ({
      kind: group.kind,
      label: group.kindLabel,
      total: group.total,
      level: group.levelLabel,
      game_count: group.gameCount,
      stage_count: group.stageCount
    })),
    tags: topTags.value,
    reproducibility: Object.fromEntries(reproducibilityRows.value.map((row) => [row.label, row.value])),
    leaderboard: {
      scope: leaderboardScopeValue.value,
      boundary: leaderboardBoundaryLabel.value,
      rows: leaderboardRows.value.slice(0, 20)
    }
  }
}

function selectRun(run) {
  if (!run?.id) return
  props.benchmark.selectBenchmarkBatch(run.id)
}

function selectReportHistory(row) {
  const id = String(row?.batch_id || row?.run_id || row?.id || '').trim()
  if (!id) return
  props.benchmark.selectBenchmarkBatch(id)
}

function isSelectedRecentRun(run) {
  return run?.id && run.id === selectedBatchId.value
}

function isSelectedReport(row) {
  return String(row?.batch_id || row?.run_id || row?.id || '') === selectedBatchId.value
}

function reportHistoryMeta(row) {
  return compactJoin([
    row?.subjectLabel,
    statusDisplayLabel(row?.statusLabel || row?.status)
  ], ' / ')
}

function reportHistoryCounts(row) {
  return compactJoin([
    `${numberOrZero(row?.rankable_count)}/${numberOrZero(row?.result_count)} 可排名`,
    `${numberOrZero(row?.problem_game_count)} 问题`,
    `${numberOrZero(row?.diagnostic_count)} 诊断`
  ], ' / ')
}

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function objectOrEmpty(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function hasObjectData(value) {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length)
}

function numberOrZero(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

function valueOrDash(value) {
  const text = String(value ?? '').trim()
  return text || '--'
}

function shortHash(value) {
  const text = String(value || '').trim()
  return text ? text.slice(0, 16) : ''
}

function compactJoin(values, separator) {
  return values.map((value) => String(value || '').trim()).filter(Boolean).join(separator)
}

function countRows(source) {
  if (!source || typeof source !== 'object') return []
  return Object.entries(source)
    .map(([name, count]) => ({
      name: String(name || 'unknown'),
      label: diagnosticDisplayLabel(name || '未知'),
      count: numberOrZero(count)
    }))
    .filter((row) => row.count > 0)
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
}

function topMapEntry(map) {
  const [entry] = [...map.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  return entry ? `${levelDisplayLabel(entry[0])}: ${entry[1]}` : '无等级'
}

function statusDisplayLabel(value) {
  const text = String(value ?? '').trim()
  if (!text || text === '--') return text || '--'
  const normalized = text.toLowerCase()
  return STATUS_LABELS[normalized] || displayPhrase(text)
}

function levelDisplayLabel(value) {
  const text = String(value ?? '').trim()
  if (!text) return '无等级'
  return STATUS_LABELS[text.toLowerCase()] || displayPhrase(text)
}

function diagnosticDisplayLabel(value) {
  const text = String(value ?? '').trim()
  if (!text) return ''
  return DISPLAY_LABELS[text] || DISPLAY_LABELS[text.toLowerCase()] || displayPhrase(text)
}

function reproducibilityLabel(value) {
  const text = String(value ?? '').trim()
  if (!text) return '审计字段'
  return DISPLAY_LABELS[text] || DISPLAY_LABELS[text.toLowerCase()] || displayPhrase(text)
}

function sourceTypeLabel(value) {
  const text = String(value ?? '').trim().toLowerCase()
  return DISPLAY_LABELS[text] || displayPhrase(value || '来源')
}

function displayPhrase(value) {
  const text = String(value ?? '').trim()
  if (!text) return ''
  const exact = DISPLAY_LABELS[text] || DISPLAY_LABELS[text.toLowerCase()]
  if (exact) return exact
  return text
    .replace(/\bDecision Judge\b/gi, '决策 Judge')
    .replace(/\bBenchmark ID\b/g, '评测 ID')
    .replace(/\bdiagnostics?\b/gi, '诊断')
    .replace(/\bjudged\b/gi, '已判定')
    .replace(/\bbad rate\b/gi, '低分率')
    .replace(/\bbad\b/gi, '低分')
    .replace(/\baccepted\b/gi, '通过')
    .replace(/\brejected\b/gi, '拒绝')
    .replace(/\bcompleted\b/gi, '已完成')
    .replace(/\bfailed\b/gi, '失败')
    .replace(/\btimeout\b/gi, '超时')
    .replace(/\bwarning\b/gi, '警告')
    .replace(/\berror\b/gi, '错误')
    .replace(/\bdegraded\b/gi, '降级')
    .replace(/\bunknown\b/gi, '未知')
}

function valueRows(value) {
  if (value == null || value === '') return []
  if (Array.isArray(value)) return value.flatMap(valueRows)
  if (typeof value === 'object') return Object.keys(value).length ? [value] : []
  const text = String(value).trim()
  return text ? [value] : []
}

function fieldRows(item, names) {
  if (!item || typeof item !== 'object') return []
  return uniqueRows(names.flatMap((name) => valueRows(item[name])))
}

function rowIdentity(value) {
  if (value && typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return Object.prototype.toString.call(value)
    }
  }
  return String(value)
}

function uniqueRows(rows) {
  const seen = new Set()
  return rows.filter((row) => {
    const key = rowIdentity(row)
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function benchmarkResultJudgeAggregate(result) {
  const scoreSummary = objectOrEmpty(result?.score_summary || result?.scoreSummary)
  return objectOrEmpty(
    scoreSummary.decision_judge_aggregate ||
    result?.decision_judge_aggregate ||
    result?.judgeAggregate
  )
}

function isBenchmarkJudgeDiagnostic(row) {
  if (!row || typeof row !== 'object') return false
  const haystack = [
    row.kind,
    row.stage,
    row.source,
    row.origin,
    row.message,
    row.reason
  ].map((value) => String(value || '').toLowerCase()).join(' ')
  return haystack.includes('judge') || hasJudgeEvidenceFields(row)
}

function hasJudgeEvidenceFields(row) {
  return [
    'evidence',
    'evidence_ref',
    'evidence_refs',
    'counterfactual',
    'counterfactuals',
    'rubric_miss',
    'rubric_misses',
    'degraded_reason',
    'degraded_reasons',
    'warnings',
    'diagnostics'
  ].some((field) => valueRows(row?.[field]).length)
}

function diagnosticMatchesBenchmarkJudgeSource(row, source) {
  const resultId = String(source?.result?.result_batch_id || source?.result?.batch_id || '')
  const rowResultId = String(row?.result_batch_id || '')
  if (resultId && rowResultId && resultId !== rowResultId) return false
  const role = String(source?.result?.target_role || '')
  const rowRole = String(row?.target_role || '')
  if (role && rowRole && role !== rowRole) return false
  return true
}

function diagnosticMatchesJudgeDecision(row, decision) {
  const id = judgeDecisionId(decision)
  if (!id) return false
  if (row && typeof row === 'object') {
    const rowId = row.decision_id ?? row.decisionId ?? row.id ?? row.target_id
    if (rowId != null && String(rowId) === id) return true
    return [
      row.message,
      row.reason,
      row.exception_message,
      row.detail,
      row.summary
    ].some((value) => value != null && String(value).includes(id))
  }
  return String(row).includes(id)
}

function labelCountRows(rows, fields, fallbackKind) {
  return valueRows(rows).map((row) => {
    if (!row || typeof row !== 'object') return row
    const label = fields.map((field) => row[field]).find((value) => value != null && String(value).trim())
    if (!label) return row
    const count = row.count == null ? '' : ` x${row.count}`
    return { kind: diagnosticDisplayLabel(fallbackKind), message: displayPhrase(`${label}${count}`) }
  })
}

function diagnosticReason(row) {
  if (!row || typeof row !== 'object') return ''
  return displayPhrase(row.reason || row.message || row.kind || '')
}

function displayEvidenceRow(row) {
  if (!row || typeof row !== 'object') return displayPhrase(row)
  return {
    ...row,
    kind: diagnosticDisplayLabel(row.kind),
    stage: displayPhrase(row.stage),
    reason: displayPhrase(row.reason),
    message: displayPhrase(row.message),
    exception_message: displayPhrase(row.exception_message),
    detail: displayPhrase(row.detail),
    summary: displayPhrase(row.summary)
  }
}

function displayEvidenceRows(rows) {
  return rows.map(displayEvidenceRow)
}

function isWarningDiagnostic(row) {
  return String(row?.level || '').toLowerCase() === 'warning' || String(row?.kind || '').includes('warning')
}

function aggregateStatusReason(aggregate) {
  const status = String(aggregate?.status || '').toLowerCase()
  const reason = String(aggregate?.reason || '').trim()
  if (!reason || !status || status === 'ok' || status === 'disabled') return []
  return [`${statusDisplayLabel(status)}: ${displayPhrase(reason)}`]
}

function withEvidenceMeta(details) {
  details.total = Object.values(details).reduce((sum, rows) => (
    Array.isArray(rows) ? sum + rows.length : sum
  ), 0)
  details.hasAny = details.total > 0
  return details
}

function buildBenchmarkAggregateEvidence(aggregate, diagnosticsRows) {
  const warningDiagnostics = diagnosticsRows.filter(isWarningDiagnostic)
  const degradedDiagnostics = diagnosticsRows.filter((row) => !isWarningDiagnostic(row))
  return withEvidenceMeta({
    evidenceRefs: uniqueRows(fieldRows(aggregate, ['evidence_refs', 'evidence_ref', 'evidence'])),
    counterfactuals: uniqueRows(fieldRows(aggregate, ['counterfactual', 'counterfactuals'])),
    rubricMisses: uniqueRows([
      ...fieldRows(aggregate, ['rubric_misses', 'rubric_miss', 'mistake_tags', 'mistake_tag']),
      ...labelCountRows(aggregate?.top_rubric_misses, ['miss', 'tag', 'label'], 'rubric_miss'),
      ...labelCountRows(aggregate?.top_mistake_tags, ['tag', 'miss', 'label'], 'mistake_tag')
    ]),
    diagnostics: uniqueRows(displayEvidenceRows([...fieldRows(aggregate, ['diagnostics', 'diagnostic']), ...diagnosticsRows])),
    degradedReasons: uniqueRows([
      ...aggregateStatusReason(aggregate),
      ...fieldRows(aggregate, ['degraded_reasons', 'degraded_reason', 'failure_reason', 'error']).map(displayEvidenceRow),
      ...degradedDiagnostics.map(diagnosticReason).filter(Boolean)
    ]),
    warnings: uniqueRows([
      ...fieldRows(aggregate, ['warnings', 'warning']).map(displayEvidenceRow),
      ...warningDiagnostics.map(diagnosticReason).filter(Boolean)
    ])
  })
}

function buildBenchmarkDecisionEvidence(decision, diagnosticsRows) {
  const warningDiagnostics = diagnosticsRows.filter(isWarningDiagnostic)
  const degradedDiagnostics = diagnosticsRows.filter((row) => !isWarningDiagnostic(row))
  return withEvidenceMeta({
    evidenceRefs: uniqueRows(fieldRows(decision, ['evidence_refs', 'evidence_ref', 'evidence'])),
    counterfactuals: uniqueRows(fieldRows(decision, ['counterfactual', 'counterfactuals'])),
    rubricMisses: uniqueRows([
      ...fieldRows(decision, ['rubric_misses', 'rubric_miss', 'mistake_tags', 'mistake_tag']),
      ...labelCountRows(decision?.top_rubric_misses, ['miss', 'tag', 'label'], 'rubric_miss')
    ]),
    diagnostics: uniqueRows(displayEvidenceRows([...fieldRows(decision, ['diagnostics', 'diagnostic']), ...diagnosticsRows])),
    degradedReasons: uniqueRows([
      ...fieldRows(decision, ['degraded_reasons', 'degraded_reason', 'failure_reason', 'error']).map(displayEvidenceRow),
      ...degradedDiagnostics.map(diagnosticReason).filter(Boolean)
    ]),
    warnings: uniqueRows([
      ...fieldRows(decision, ['warnings', 'warning']).map(displayEvidenceRow),
      ...warningDiagnostics.map(diagnosticReason).filter(Boolean)
    ])
  })
}

function judgeAggregateStatus(aggregate) {
  const status = String(aggregate?.status || '').toLowerCase()
  const label = {
    ok: 'Judge 已完成',
    degraded: 'Judge 部分完成',
    failed: 'Judge 失败',
    skipped: 'Judge 未启用',
    disabled: 'Judge 已关闭'
  }[status] || 'Judge 聚合'
  const score = aggregate?.avg_score ?? aggregate?.average_score
  const scoreText = Number.isFinite(Number(score)) ? ` / ${Number(score).toFixed(1)}` : ''
  return `${label}${scoreText}`
}

function judgeAggregateMeta(source) {
  const aggregate = source.aggregate || {}
  const judgedCount = aggregate.judged_decisions ?? aggregate.judged ?? aggregate.metrics?.judged
  const badRate = Number(aggregate.bad_rate)
  return compactJoin([
    sourceTypeLabel(source.type),
    judgedCount == null || judgedCount === '' ? '' : `${judgedCount} 已判定`,
    Number.isFinite(badRate) ? `低分率 ${(badRate * 100).toFixed(0)}%` : ''
  ], ' / ')
}

function judgeDecisionId(decision) {
  const id = decision?.decision_id ?? decision?.decisionId ?? decision?.id
  return id == null ? '' : String(id)
}

function judgeDecisionTitle(decision, index) {
  const id = judgeDecisionId(decision)
  return compactJoin([
    id ? `决策 ${id}` : `低分决策 ${index + 1}`,
    decision?.role,
    displayPhrase(decision?.action_type)
  ], ' / ')
}

function judgeDecisionStatus(decision) {
  const score = decision?.score
  if (Number.isFinite(Number(score))) return `Judge ${Number(score).toFixed(1)}`
  return diagnosticDisplayLabel(decision?.quality || '低分决策')
}

function problemStatusWeight(status) {
  const text = String(status || '').toLowerCase()
  if (text === 'failed') return 5
  if (text === 'timeout') return 4
  if (text === 'abnormal') return 3
  if (text === 'cancelled' || text === 'interrupted') return 2
  if (text === 'completed') return 0
  return 1
}

function archiveReplayHash(game) {
  const replayHash = String(game?.replayHash || game?.replay_hash || '').trim()
  if (replayHash) return withArchiveWorkspace(replayHash)
  const historyGameId = String(game?.history_game_id || game?.historyGameId || '').trim()
  return historyGameId ? `#logs?workspace=archive&game_id=${encodeURIComponent(historyGameId)}` : ''
}

function withArchiveWorkspace(hash) {
  const text = String(hash || '').trim()
  if (!text.startsWith('#logs?')) return text
  const params = new URLSearchParams(text.slice('#logs?'.length))
  if (!params.has('game_id')) return text
  params.set('workspace', 'archive')
  return `#logs?${params.toString()}`
}

function markdownValue(value) {
  return String(value ?? '--').replace(/\n/g, ' ').replace(/\|/g, '\\|')
}

function jsonText(value) {
  return JSON.stringify(value, null, 2)
}

function toCsv(rows) {
  return rows.map((row) => row.map(csvValue).join(',')).join('\n')
}

function csvValue(value) {
  const text = String(value ?? '')
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`
  return text
}

function safeFilename(value) {
  return String(value || 'benchmark-report')
    .trim()
    .replace(/[^a-zA-Z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 96) || 'benchmark-report'
}

function downloadText(filename, text, mime) {
  if (typeof document === 'undefined' || typeof Blob === 'undefined' || typeof URL === 'undefined') return false
  const blob = new Blob([text], { type: `${mime};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
  return true
}

function clearTransientState(stateRef) {
  if (typeof window === 'undefined' || !window.setTimeout) return
  window.setTimeout(() => {
    stateRef.value = ''
  }, 1600)
}
</script>

<template>
  <section class="benchmark-report-panel" aria-label="评测运行报告">
    <template v-if="selectedRun">
      <header class="report-header">
        <div class="report-title">
          <small>运行报告</small>
          <h2>{{ selectedRunId }}</h2>
          <p>{{ subjectLabel }} / {{ targetTypeLabel }}</p>
        </div>
        <div class="report-status">
          <span>{{ statusLabel }}</span>
          <em>{{ rankableLabel }}</em>
          <small>{{ reportSourceLabel }}</small>
        </div>
      </header>

      <section class="report-summary-grid" aria-label="报告摘要">
        <article
          v-for="row in summaryRows"
          :key="row.key"
          :class="['report-summary-card', 'summary-' + row.key]"
        >
          <small>{{ row.label }}</small>
          <b>{{ row.value }}</b>
          <em>{{ row.caption }}</em>
        </article>
      </section>

      <div class="report-workspace">
        <main class="report-main">
          <section class="report-section">
            <div class="report-section-heading">
              <span>
                <small>门禁摘要</small>
                <b>排名资格与诊断门禁</b>
              </span>
              <em>{{ gateRows.length }} 行</em>
            </div>
            <div v-if="gateRows.length" class="gate-list">
              <article
                v-for="row in gateRows"
                :key="row.key"
                :class="['gate-row', { blocked: row.blocked }]"
              >
                <span>
                  <small>{{ row.meta || '门禁' }}</small>
                  <b>{{ row.title }}</b>
                  <em>{{ row.reason }}</em>
                </span>
                <strong>{{ row.status }}</strong>
              </article>
            </div>
            <p v-else class="report-empty-inline">所选运行暂无门禁记录。</p>
          </section>

          <section class="report-section">
            <div class="report-section-heading">
              <span>
                <small>问题对局</small>
                <b>已加载样本</b>
              </span>
              <em>{{ problemGames.length }} 局</em>
            </div>
            <div v-if="problemGames.length" class="game-table">
              <div class="game-row game-row-header">
                <span>对局</span>
                <span>状态</span>
                <span>种子</span>
                <span>目标</span>
                <span>诊断</span>
                <span>回放</span>
              </div>
              <div v-for="game in problemGames" :key="game.id" class="game-row">
                <span class="mono">{{ game.id }}</span>
                <span>{{ game.statusLabel || statusDisplayLabel(game.status) || '--' }}</span>
                <span>{{ game.seed }}</span>
                <span>{{ game.target }}</span>
                <span>{{ game.diagnostics }}</span>
                <span>
                  <a v-if="game.replayHash" class="report-replay-link" :href="game.replayHash">
                    打开
                  </a>
                  <small v-else>{{ game.replayUnavailableReason || '无回放' }}</small>
                </span>
              </div>
            </div>
            <p v-else class="report-empty-inline">暂无已加载对局样本。请选择已完成运行，或把对局筛选切到问题局/全部。</p>
          </section>

          <section class="report-section">
            <div class="report-section-heading">
              <span>
                <small>诊断与标签</small>
                <b>失败信号汇总</b>
              </span>
              <em>{{ diagnosticEvidenceGroupCount }} 组</em>
            </div>
            <div v-if="diagnosticGroups.length" class="diagnostic-rollup">
              <article v-for="group in diagnosticGroups" :key="group.key" class="diagnostic-rollup-row">
                <span>
                  <b>{{ group.kindLabel }}</b>
                  <small>{{ group.levelLabel }} / {{ group.gameCount }} 局 / {{ group.stageCount }} 阶段</small>
                </span>
                <em>{{ group.total }}</em>
              </article>
            </div>
            <div v-else-if="topTags.length" class="tag-list">
              <span v-for="tag in topTags" :key="tag.label" class="tag-pill">
                <b>{{ tag.label }}</b>
                <em>{{ tag.count }}</em>
              </span>
            </div>
            <div v-if="benchmarkJudgeEvidenceRows.length" class="benchmark-judge-evidence-list" aria-label="评测 Judge 证据">
              <article
                v-for="row in benchmarkJudgeEvidenceRows"
                :key="row.key"
                class="benchmark-judge-evidence-row"
              >
                <header class="benchmark-judge-evidence-head">
                  <span>
                    <small>决策 Judge</small>
                    <b>{{ row.title }}</b>
                  </span>
                  <em>{{ row.status }}</em>
                </header>
                <p v-if="row.meta" class="benchmark-judge-evidence-meta">{{ row.meta }}</p>
                <JudgeEvidencePanel :evidence="row.evidence" :row-key="row.key" :format-json="jsonText" />
              </article>
            </div>
            <p v-if="!diagnosticGroups.length && !topTags.length && !benchmarkJudgeEvidenceRows.length" class="report-empty-inline">
              暂无诊断、Judge 标签或可展开证据。
            </p>
          </section>
        </main>

        <aside class="report-side">
          <section class="report-section report-history">
            <div class="report-section-heading">
              <span>
                <small>报告历史</small>
                <b>运行产物</b>
              </span>
              <em>{{ reportHistoryLoading ? '加载中' : reportHistory.length + ' 份报告' }}</em>
            </div>
            <div v-if="reportHistory.length" class="report-history-list">
              <button
                v-for="row in reportHistory"
                :key="row.report_id || row.batch_id"
                type="button"
                :class="['report-history-row', { active: isSelectedReport(row) }]"
                @click="selectReportHistory(row)"
              >
                <span>
                  <b>{{ row.suiteLabel }}</b>
                  <small>{{ reportHistoryMeta(row) }}</small>
                </span>
                <em>{{ reportHistoryCounts(row) }}</em>
              </button>
            </div>
            <p v-else class="report-empty-inline">
              {{ displayPhrase(reportHistoryError) || '当前套件边界暂无报告历史。' }}
            </p>
          </section>

          <section class="report-section report-export">
            <div class="report-section-heading export-heading">
              <span>
                <small>报告导出</small>
                <b>Markdown / JSON / CSV</b>
              </span>
              <div class="export-actions">
                <button type="button" class="copy-button" @click="copyReport">
                  {{ copyState || '复制 MD' }}
                </button>
                <button type="button" class="ghost-button" @click="downloadReport('markdown')">
                  MD
                </button>
                <button type="button" class="ghost-button" @click="downloadReport('json')">
                  JSON
                </button>
                <button type="button" class="ghost-button" @click="downloadReport('csv')">
                  CSV
                </button>
              </div>
            </div>
            <p v-if="reportError" class="report-export-note">{{ displayPhrase(reportError) }}</p>
            <div class="copy-row">
              <button type="button" @click="copyExport('json')">复制 JSON</button>
              <button type="button" @click="copyExport('csv')">复制 CSV</button>
              <em>{{ exportState }}</em>
            </div>
            <div class="report-audit-grid" aria-label="报告审计证据">
              <span
                v-for="row in reportAuditRows"
                :key="row.key"
                :class="['report-audit-item', row.tone ? 'is-' + row.tone : '']"
              >
                <small>{{ row.label }}</small>
                <b :title="String(row.value || '')">{{ row.value }}</b>
                <em :title="String(row.caption || '')">{{ row.caption }}</em>
              </span>
            </div>
          </section>
        </aside>
      </div>
    </template>

    <section v-else class="report-empty-state">
      <div>
        <small>运行报告</small>
        <h2>未选择运行</h2>
        <p>从运行列表选择一个评测批次，生成摘要、门禁解释、问题对局、诊断汇总和追溯数据。</p>
      </div>
      <div v-if="reportHistory.length || recentRuns.length" class="report-empty-picker">
        <div v-if="reportHistory.length" class="report-empty-history">
          <div class="report-section-heading">
            <span>
              <small>报告历史</small>
              <b>运行产物</b>
            </span>
            <em>{{ reportHistory.length }} 份报告</em>
          </div>
          <div class="report-history-list">
            <button
              v-for="row in reportHistory"
              :key="row.report_id || row.batch_id"
              type="button"
              :class="['report-history-row', { active: isSelectedReport(row) }]"
              @click="selectReportHistory(row)"
            >
              <span>
                <b>{{ row.suiteLabel }}</b>
                <small>{{ reportHistoryMeta(row) }}</small>
              </span>
              <em>{{ reportHistoryCounts(row) }}</em>
            </button>
          </div>
        </div>
        <div v-else class="recent-run-list">
          <button
            v-for="run in recentRuns"
            :key="run.id"
            type="button"
            :class="['recent-run-button', { active: isSelectedRecentRun(run) }]"
            @click="selectRun(run)"
          >
            <span>
              <b>{{ run.benchmarkLabel || run.id }}</b>
              <small>{{ run.displayRole || run.benchmarkTargetTypeLabel || '评测对象' }}</small>
            </span>
            <em>{{ statusDisplayLabel(run.statusLabel || run.status || '--') }}</em>
          </button>
        </div>
      </div>
      <p v-else class="report-empty-inline">暂无最近评测运行。</p>
    </section>
  </section>
</template>

<style scoped>
.benchmark-report-panel {
  --report-bg: var(--bench-bg, var(--logbook-bg, #f2dfae));
  --report-ink: var(--bench-text, var(--logbook-text, #3a2a18));
  --report-muted: var(--bench-text-secondary, var(--logbook-muted, #8b6b4a));
  --report-line: var(--bench-border, var(--logbook-border, rgba(139, 94, 52, 0.15)));
  --report-panel: var(--bench-surface, var(--logbook-surface, rgba(255, 252, 245, 0.7)));
  --report-soft: var(--bench-panel-soft, var(--logbook-panel-soft, rgba(255, 252, 245, 0.48)));
  --report-accent: var(--bench-accent, var(--logbook-accent, #8b5e34));
  --report-accent-strong: var(--bench-accent-strong, var(--logbook-accent-strong, #5a3319));
  --report-caution: var(--bench-warning, var(--logbook-warning, #8b5e34));
  --report-danger: var(--bench-danger, var(--logbook-danger, #5a3319));
  --log-text: var(--report-ink);
  --log-text-secondary: var(--report-muted);
  --log-accent: var(--report-accent);
  display: grid;
  gap: 12px;
  min-width: 0;
  color: var(--report-ink);
}

.report-header {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 16px;
  min-width: 0;
  padding: 14px 16px;
  border: 1px solid var(--report-line);
  border-radius: 8px;
  background:
    linear-gradient(90deg, rgba(139, 94, 52, 0.1), rgba(255, 252, 245, 0) 48%),
    var(--report-panel);
}

.report-title,
.report-title h2,
.report-title p,
.report-status,
.report-status span,
.report-status em,
.report-status small {
  min-width: 0;
}

.report-title small,
.report-summary-card small,
.report-section-heading small,
.gate-row small,
.diagnostic-rollup-row small,
.benchmark-judge-evidence-head small,
.report-audit-grid small,
.recent-run-button small,
.report-history-row small {
  color: var(--report-muted);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.report-title h2 {
  margin: 2px 0 0;
  overflow: hidden;
  color: var(--report-ink);
  font-size: 20px;
  font-weight: 900;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-title p {
  margin: 4px 0 0;
  overflow: hidden;
  color: var(--report-muted);
  font-size: 12px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-status {
  display: grid;
  justify-items: end;
  gap: 4px;
}

.report-status span {
  padding: 5px 9px;
  border: 1px solid rgba(139, 94, 52, 0.22);
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--report-accent-strong);
  font-size: 12px;
  font-weight: 900;
}

.report-status em,
.report-status small,
.report-summary-card em,
.report-section-heading em,
.gate-row em,
.benchmark-judge-evidence-head em,
.report-audit-grid em,
.tag-pill em,
.recent-run-button em,
.report-history-row em {
  color: var(--report-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
}

.report-status small {
  justify-self: end;
}

.report-summary-card,
.report-section,
.report-empty-state {
  border: 1px solid var(--report-line);
  border-radius: 8px;
  background: var(--report-panel);
}

.report-summary-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.report-summary-card {
  display: grid;
  gap: 4px;
  min-width: 0;
  min-height: 72px;
  padding: 11px 12px;
  border-left: 4px solid var(--report-accent);
}

.report-summary-card.summary-rankable {
  border-left-color: var(--report-accent);
}

.report-summary-card.summary-diagnostics {
  border-left-color: var(--report-caution);
}

.report-summary-card b {
  overflow: hidden;
  color: var(--report-ink);
  font-size: 18px;
  font-weight: 950;
  line-height: 1.05;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(360px, 0.85fr);
  gap: 12px;
  min-width: 0;
  align-items: start;
}

.report-main,
.report-side {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.report-section {
  min-width: 0;
  padding: 12px;
}

.report-section-heading {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  margin-bottom: 10px;
}

.report-section-heading span {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.report-section-heading b {
  overflow: hidden;
  color: var(--report-ink);
  font-size: 13px;
  font-weight: 950;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gate-list,
.diagnostic-rollup,
.benchmark-judge-evidence-list,
.recent-run-list,
.report-history-list {
  display: grid;
  gap: 6px;
}

.gate-row,
.diagnostic-rollup-row,
.recent-run-button,
.report-history-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid var(--report-line);
  border-radius: 7px;
  background: var(--report-soft);
}

.gate-row.blocked {
  border-color: rgba(90, 51, 25, 0.28);
  background: rgba(139, 94, 52, 0.08);
}

.gate-row span,
.diagnostic-rollup-row span,
.benchmark-judge-evidence-head span,
.recent-run-button span,
.report-history-row span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.gate-row b,
.diagnostic-rollup-row b,
.benchmark-judge-evidence-head b,
.recent-run-button b,
.report-history-row b {
  overflow: hidden;
  color: var(--report-ink);
  font-size: 12px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gate-row strong,
.diagnostic-rollup-row em {
  justify-self: end;
  color: var(--report-ink);
  font-size: 12px;
  font-weight: 950;
  white-space: nowrap;
}

.gate-row.blocked strong {
  color: var(--report-danger);
}

.game-table {
  display: grid;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--report-line);
  border-radius: 7px;
}

.game-row {
  display: grid;
  grid-template-columns: minmax(150px, 1.3fr) 0.62fr 0.6fr 0.8fr 0.62fr 62px;
  gap: 8px;
  align-items: center;
  min-width: 0;
  min-height: 34px;
  padding: 7px 9px;
  border-top: 1px solid var(--report-line);
  background: var(--report-panel);
  color: var(--report-ink);
  font-size: 12px;
  font-weight: 800;
}

.game-row:first-child {
  border-top: 0;
}

.game-row span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-replay-link {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 8px;
  border: 1px solid var(--report-accent);
  border-radius: 6px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--report-accent);
  font-size: 11px;
  font-weight: 900;
  text-decoration: none;
}

.game-row small {
  color: var(--report-muted);
  font-size: 11px;
  font-weight: 850;
}

.game-row-header {
  min-height: 30px;
  background: var(--report-soft);
  color: var(--report-muted);
  font-size: 10px;
  font-weight: 950;
  text-transform: uppercase;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  max-width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--report-line);
  border-radius: 7px;
  background: var(--report-soft);
}

.tag-pill b {
  overflow: hidden;
  color: var(--report-ink);
  font-size: 12px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.export-heading {
  align-items: center;
}

.copy-button,
.ghost-button,
.copy-row button {
  min-height: 30px;
  padding: 0 11px;
  border: 1px solid var(--report-accent);
  border-radius: 7px;
  font-size: 12px;
  font-weight: 950;
  cursor: pointer;
}

.copy-button {
  background: var(--report-accent);
  color: #f8f0e0;
}

.benchmark-judge-evidence-list {
  min-width: 0;
  margin-top: 8px;
}

.benchmark-judge-evidence-row {
  display: grid;
  gap: 7px;
  min-width: 0;
  overflow: hidden;
  padding: 9px 10px;
  border: 1px solid var(--report-line);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.58);
}

.benchmark-judge-evidence-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
  min-width: 0;
}

.benchmark-judge-evidence-head em {
  justify-self: end;
  white-space: nowrap;
}

.benchmark-judge-evidence-meta {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--report-muted);
  font-size: 11px;
  font-weight: 850;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.benchmark-judge-evidence-row :deep(.review-judge-evidence) {
  padding-top: 7px;
  border-top-color: var(--report-line);
}

.benchmark-judge-evidence-row :deep(.review-judge-evidence-block) {
  background: rgba(255, 252, 245, 0.42);
}

.report-audit-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  min-width: 0;
}

.report-audit-item {
  display: grid;
  gap: 3px;
  min-width: 0;
  min-height: 68px;
  padding: 8px 9px;
  border: 1px solid var(--report-line);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.5);
}

.report-audit-item.is-ready {
  border-color: rgba(139, 94, 52, 0.3);
  background: rgba(139, 94, 52, 0.08);
}

.report-audit-item.is-blocked {
  border-color: rgba(90, 51, 25, 0.34);
  background: rgba(90, 51, 25, 0.08);
}

.report-audit-item b {
  overflow: hidden;
  color: var(--report-ink);
  font-size: 12px;
  font-weight: 950;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-audit-item em {
  overflow: hidden;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ghost-button,
.copy-row button {
  background: var(--report-panel);
  color: var(--report-accent);
}

.export-actions,
.copy-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.copy-row {
  justify-content: flex-start;
  margin-bottom: 8px;
}

.copy-row em {
  color: var(--report-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 850;
}

.report-export-note {
  margin: -2px 0 8px;
  color: var(--report-caution);
  font-size: 11px;
  font-weight: 850;
  line-height: 1.35;
}

.report-empty-state {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(360px, 0.85fr);
  gap: 16px;
  min-width: 0;
  padding: 18px;
  background:
    linear-gradient(90deg, rgba(139, 94, 52, 0.08), rgba(255, 252, 245, 0) 50%),
    var(--report-panel);
}

.report-empty-state h2 {
  margin: 3px 0 0;
  color: var(--report-ink);
  font-size: 20px;
  font-weight: 950;
}

.report-empty-picker,
.report-empty-history {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.report-empty-state p,
.report-empty-inline {
  margin: 6px 0 0;
  color: var(--report-muted);
  font-size: 12px;
  font-weight: 750;
  line-height: 1.45;
}

.recent-run-button,
.report-history-row {
  width: 100%;
  border-color: var(--report-line);
  text-align: left;
  cursor: pointer;
}

.recent-run-button.active,
.report-history-row.active {
  border-color: var(--report-accent);
  background: rgba(139, 94, 52, 0.1);
}

@media (max-width: 720px) {
  .benchmark-judge-evidence-head {
    grid-template-columns: minmax(0, 1fr);
    gap: 4px;
  }

  .benchmark-judge-evidence-head em {
    justify-self: start;
    white-space: normal;
  }

  .benchmark-judge-evidence-meta {
    white-space: normal;
    overflow-wrap: anywhere;
  }

  .benchmark-judge-evidence-row :deep(.review-judge-evidence-grid) {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
