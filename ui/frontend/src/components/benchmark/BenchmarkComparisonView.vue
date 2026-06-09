<script setup>
import { computed, ref, watch } from 'vue'

const MIN_CONFIDENT_GAMES = 30
const STORAGE_PREFIX = 'benchmark-comparison-view'
const RANK_FILTER_LABELS = {
  all: '全部',
  rankable: '可入榜',
  unrankable: '未入榜'
}

const props = defineProps({
  benchmark: {
    type: Object,
    required: true
  }
})

const savedViewState = ref('')
const selectedRowKey = ref('')

const mode = computed(() =>
  props.benchmark.selectedBenchmarkIsModelSuite.value ? 'model' : 'role_version'
)

const currentViewConfig = computed(() => props.benchmark.activeBenchmarkViewConfig?.value || {})
const selectedMetricColumns = computed({
  get() {
    const columns = Array.isArray(currentViewConfig.value.columns) ? currentViewConfig.value.columns : []
    return columns.length ? columns : defaultMetricColumns(mode.value).map((column) => column.key)
  },
  set(value) {
    props.benchmark.setBenchmarkViewPreference?.({
      mode: mode.value,
      columns: Array.isArray(value) ? value : []
    })
  }
})
const rankFilter = computed({
  get() {
    return ['all', 'rankable', 'unrankable'].includes(currentViewConfig.value.rank_filter)
      ? currentViewConfig.value.rank_filter
      : 'all'
  },
  set(value) {
    props.benchmark.setBenchmarkViewPreference?.({
      mode: mode.value,
      rank_filter: ['all', 'rankable', 'unrankable'].includes(value) ? value : 'all'
    })
  }
})
const savedViewName = computed({
  get() {
    return props.benchmark.benchmarkViewPreferences?.value?.name || '默认视图'
  },
  set(value) {
    props.benchmark.setBenchmarkViewPreference?.({ name: value || '默认视图' })
  }
})
const savedViewRows = computed(() => props.benchmark.benchmarkSavedViews?.value || [])
const selectedSavedViewKey = computed(() =>
  props.benchmark.selectedBenchmarkViewKey?.value || props.benchmark.currentBenchmarkViewKey?.value || ''
)
const viewDirty = computed(() => Boolean(props.benchmark.benchmarkViewDirty?.value))

const comparePayload = computed(() => {
  const compare = props.benchmark.benchmarkLeaderboardCompare?.value
  if (!compare || compare.scope !== mode.value) return null
  return compare
})
const compareLoading = computed(() => Boolean(props.benchmark.benchmarkLeaderboardCompareLoading?.value))
const compareError = computed(() => String(props.benchmark.benchmarkLeaderboardCompareError?.value || '').trim())
const compareSourceTone = computed(() => {
  if (compareLoading.value) return 'loading'
  if (comparePayload.value) return 'server'
  if (compareError.value) return 'fallback'
  return 'local'
})
const compareSourceLabel = computed(() => {
  if (compareLoading.value) return '正在加载服务端比较'
  if (comparePayload.value) return '服务端标准比较'
  if (compareError.value) return '本地兜底比较'
  return '本地当前榜单'
})
const compareSourceDetail = computed(() => {
  if (compareLoading.value) return '正在读取 /leaderboards/compare'
  if (comparePayload.value) return '正式 rows 与未入榜证据已分离'
  if (compareError.value) return compareError.value
  return '等待服务端 compare，暂按当前榜单行计算'
})

const apiCompareRows = computed(() => {
  const compare = comparePayload.value
  if (!compare || !Array.isArray(compare.rows)) return []
  return compare.rows
})

const rawRows = computed(() =>
  comparePayload.value
    ? apiCompareRows.value
    : (mode.value === 'model'
      ? props.benchmark.modelLeaderboardRows.value
      : props.benchmark.roleLeaderboardRows.value)
)

const rows = computed(() =>
  rawRows.value.map((row, index) => normalizeRow(row, index, mode.value))
)

const rankableRows = computed(() =>
  rows.value
    .filter((row) => row.rankable !== false)
    .sort((a, b) => b.scoreValue - a.scoreValue || b.winRateValue - a.winRateValue)
)

const unrankableRows = computed(() =>
  rows.value.filter((row) => row.rankable === false)
)

const backendUnrankableEvidenceRows = computed(() => {
  const compare = comparePayload.value
  return [
    ...firstArray(compare?.unrankable_evidence),
    ...firstArray(compare?.unrankableEvidence),
    ...firstArray(compare?.evidence?.unrankable)
  ].map((row, index) => normalizeUnrankableEvidence(row, index, mode.value, '后端证据'))
})

const fallbackUnrankableEvidenceRows = computed(() =>
  unrankableRows.value.map((row, index) => normalizeUnrankableEvidence(row, index, mode.value, '榜单行兜底'))
)

const unrankableEvidenceRows = computed(() =>
  backendUnrankableEvidenceRows.value.length
    ? backendUnrankableEvidenceRows.value
    : fallbackUnrankableEvidenceRows.value
)

const unrankableEvidenceSourceLabel = computed(() =>
  backendUnrankableEvidenceRows.value.length ? '后端证据' : '榜单行兜底'
)

const baselineRow = computed(() => {
  const explicit = rows.value.find((row) => row.isBaseline)
  if (explicit) return explicit
  return rankableRows.value[0] || rows.value[0] || null
})

const comparisonRows = computed(() => {
  const baseline = baselineRow.value
  const baselineScore = baseline?.scoreValue ?? 0
  const baselineWinRate = baseline?.winRateValue ?? 0
  const baselineInterval = confidenceInterval(baseline)
  return rows.value
    .map((row) => {
      const interval = confidenceInterval(row)
      const relativeWinRateDelta = row.winRateValue - baselineWinRate
      const combinedSe = Math.sqrt((interval?.se || 0) ** 2 + (baselineInterval?.se || 0) ** 2)
      const margin = combinedSe * 1.96
      const enoughSamples = Boolean(
        row.games >= MIN_CONFIDENT_GAMES &&
        (!baseline || baseline.games >= MIN_CONFIDENT_GAMES)
      )
      const isReference = Boolean(baseline && row.key === baseline.key)
      const likelyDifferent = !isReference && enoughSamples && Math.abs(relativeWinRateDelta) > margin
      return {
        ...row,
        interval,
        confidenceLabel: confidenceLabel(row, baseline, { isReference, likelyDifferent, enoughSamples }),
        confidenceTone: confidenceTone(row, { isReference, likelyDifferent, enoughSamples }),
        relativeScoreDelta: row.hasDelta ? row.deltaValue : row.scoreValue - baselineScore,
        relativeWinRateDelta,
        relativeWinRateMargin: margin
      }
    })
    .sort((a, b) => {
      if (a.rankable === false && b.rankable !== false) return 1
      if (a.rankable !== false && b.rankable === false) return -1
      return b.scoreValue - a.scoreValue || b.winRateValue - a.winRateValue
    })
})

const metricColumnDefs = computed(() => {
  const confidenceWidth = mode.value === 'model' ? '92px' : '118px'
  const rankableLabel = mode.value === 'model' ? '入榜' : '基线'
  const baseColumns = [
    { key: 'score', label: '分数', width: '70px' },
    { key: 'winRate', label: '胜率', width: '76px' },
    { key: 'delta', label: '差值', width: '70px' },
    { key: 'confidence', label: mode.value === 'model' ? '95% 置信区间' : '置信度', width: confidenceWidth },
    { key: 'rankable', label: rankableLabel, width: '96px' },
    { key: 'games', label: '局数', width: '70px' }
  ]
  if (mode.value !== 'model') return baseColumns
  return [
    ...baseColumns.slice(0, 4),
    { key: 'fallback', label: '回退率', width: '78px' },
    { key: 'llmError', label: 'LLM 错误', width: '82px' },
    { key: 'policy', label: '策略修正', width: '86px' },
    ...baseColumns.slice(4)
  ]
})

const enabledMetricColumnDefs = computed(() => {
  const selected = new Set(selectedMetricColumns.value)
  const rows = metricColumnDefs.value.filter((column) => selected.has(column.key))
  return rows.length ? rows : defaultMetricColumns(mode.value)
})

const enabledMetricColumnKeys = computed(() =>
  new Set(enabledMetricColumnDefs.value.map((column) => column.key))
)

const tableRows = computed(() => {
  if (rankFilter.value === 'rankable') return comparisonRows.value.filter((row) => row.rankable !== false)
  if (rankFilter.value === 'unrankable') return comparisonRows.value.filter((row) => row.rankable === false)
  return comparisonRows.value
})

const comparisonGridStyle = computed(() => {
  const identityColumns = mode.value === 'model'
    ? ['minmax(180px, 1.2fr)', 'minmax(180px, 1.08fr)']
    : ['minmax(190px, 1.25fr)', 'minmax(92px, 0.54fr)']
  return {
    gridTemplateColumns: [
      ...identityColumns,
      ...enabledMetricColumnDefs.value.map((column) => column.width)
    ].join(' ')
  }
})

const viewStorageKey = computed(() => {
  return props.benchmark.currentBenchmarkViewKey?.value || `${STORAGE_PREFIX}:${mode.value}`
})

const selectedLeaderboardRow = computed(() =>
  comparisonRows.value.find((row) => row.key === selectedRowKey.value) ||
  comparisonRows.value[0] ||
  null
)

const boundaryMismatchRows = computed(() => {
  const evaluationSet = props.benchmark.selectedBenchmarkEvaluationSetId.value
  if (!evaluationSet) return []
  return rows.value.filter((row) => {
    const rowEvaluationSet = String(row.raw?.evaluation_set_id || row.raw?.evaluationSetId || '').trim()
    return rowEvaluationSet && rowEvaluationSet !== evaluationSet
  })
})

const compareSummaryPayload = computed(() => {
  const summary = comparePayload.value?.summary
  return summary && typeof summary === 'object' ? summary : {}
})

const tableViewSummary = computed(() =>
  `${RANK_FILTER_LABELS[rankFilter.value] || '全部'} / ${enabledMetricColumnDefs.value.map((column) => column.label).join(', ')}`
)

const topRow = computed(() => rankableRows.value[0] || null)

const summary = computed(() => {
  const ranked = rankableRows.value
  const baseline = baselineRow.value
  const scores = ranked.map((row) => row.scoreValue).filter((value) => Number.isFinite(value))
  const winRates = ranked.map((row) => row.winRateValue).filter((value) => Number.isFinite(value))
  const topDelta = topRow.value && baseline
    ? topRow.value.scoreValue - baseline.scoreValue
    : null
  const lowSampleCount = ranked.filter((row) => row.games < MIN_CONFIDENT_GAMES).length
  return [
    {
      label: '入榜数',
      value: ranked.length.toLocaleString('zh-CN'),
      caption: `${unrankableEvidenceRows.value.length} 条未入榜证据`
    },
    {
      label: '最高分',
      value: topRow.value ? formatPct(topRow.value.scoreValue) : '--',
      caption: topRow.value ? topRow.value.primary : '暂无入榜行'
    },
    {
      label: '平均胜率',
      value: winRates.length ? formatPct(average(winRates)) : '--',
      caption: '入榜行'
    },
    {
      label: '置信度',
      value: lowSampleCount ? `${lowSampleCount} 小样本` : '置信区间正常',
      caption: topDelta == null ? '基线待定' : `${formatSignedPct(topDelta)} 最高分差`
    }
  ]
})

const compareAuditRows = computed(() => {
  const summary = compareSummaryPayload.value
  const formalCount = comparePayload.value
    ? numberFrom(summary.row_count, summary.rankable_count, apiCompareRows.value.length)
    : rankableRows.value.length
  const unrankableCount = comparePayload.value
    ? numberFrom(summary.unrankable_evidence_count, summary.unrankable_count, unrankableEvidenceRows.value.length)
    : unrankableEvidenceRows.value.length
  const boundaryCount = comparePayload.value
    ? numberFrom(summary.boundary_mismatch_count, boundaryMismatchRows.value.length)
    : boundaryMismatchRows.value.length
  const improvementCount = numberFrom(summary.improvement_count) ?? 0
  const regressionCount = numberFrom(summary.regression_count) ?? 0
  const incomparableCount = numberFrom(summary.incomparable_count, boundaryCount) ?? 0
  return [
    {
      label: '正式行',
      value: formatCount(formalCount),
      caption: comparePayload.value ? '服务端可入榜行' : '本地可见行'
    },
    {
      label: '未入榜证据',
      value: formatCount(unrankableCount),
      caption: '排除在正式排名外'
    },
    {
      label: '边界告警',
      value: formatCount(boundaryCount),
      caption: Number(boundaryCount) > 0 ? '需复核边界' : '边界一致'
    },
    {
      label: '变化分布',
      value: comparePayload.value
        ? `提升 ${formatCount(improvementCount)} / 回退 ${formatCount(regressionCount)} / 不可比 ${formatCount(incomparableCount)}`
        : '等待服务端比较',
      caption: comparePayload.value ? '相对固定基线' : '本地仅供预览'
    }
  ]
})

const boundaryRows = computed(() => {
  if (mode.value === 'model') {
    return [
      { label: '范围', value: 'scope=model' },
      { label: '套件', value: props.benchmark.selectedBenchmarkSuiteLabel.value || '--' },
      { label: '评测集', value: props.benchmark.selectedBenchmarkEvaluationSetId.value || '--' },
      { label: '排行单位', value: '模型标识 / Config Hash' }
    ]
  }
  return [
    { label: '范围', value: 'scope=role_version' },
    { label: '目标角色', value: props.benchmark.selectedRoleLabel.value || '--' },
    { label: '套件', value: props.benchmark.selectedBenchmarkSuiteLabel.value || '--' },
    { label: '评测集', value: props.benchmark.selectedBenchmarkEvaluationSetId.value || '--' }
  ]
})

const baselineDeltaRows = computed(() => {
  const baseline = baselineRow.value
  if (!baseline) return []
  return comparisonRows.value
    .filter((row) => row.key !== baseline.key)
    .slice(0, 6)
    .map((row) => ({
      ...row,
      barWidth: Math.min(100, Math.max(6, Math.abs(row.relativeScoreDelta))),
      direction: row.relativeScoreDelta >= 0 ? 'positive' : 'negative'
    }))
})

const confidenceRows = computed(() =>
  comparisonRows.value
    .filter((row) => row.key !== baselineRow.value?.key)
    .slice(0, 6)
)

const emptyTitle = computed(() =>
  mode.value === 'model' ? '暂无模型评测行' : '暂无角色版本评测行'
)

const emptyCaption = computed(() =>
  mode.value === 'model'
    ? '运行模型套件后会生成 scope=model 榜单行。'
    : '选择角色并运行角色版本套件后会生成比较数据。'
)

function normalizeRow(row, index, currentMode) {
  const score = numberFrom(
    row?.scorePct,
    percentFromFraction(row?.score),
    percentFromFraction(row?.strength_score),
    percentFromFraction(row?.avg_role_score),
    percentFromFraction(row?.target_role_role_weighted_score)
  )
  const winRate = numberFrom(
    row?.winRatePct,
    percentFromFraction(row?.winRate),
    percentFromFraction(row?.target_side_win_rate),
    percentFromFraction(row?.summary?.target_side_win_rate),
    percentFromFraction(row?.summary?.win_rate)
  )
  const delta = numberFrom(
    percentFromFraction(row?.deltaScore),
    percentFromFraction(row?.delta_score),
    percentFromFraction(row?.delta_vs_baseline?.target_role_role_weighted_score),
    row?.deltaPct
  )
  const hasDelta = delta != null
  const isModel = currentMode === 'model'
  const primary = isModel ? modelPrimary(row, index) : rolePrimary(row, index)
  const secondary = isModel ? modelSecondary(row) : roleSecondary(row)
  const rankable = row?.rankable == null ? null : row.rankable !== false
  return {
    raw: row,
    key: rowKey(row, index, currentMode),
    primary,
    secondary,
    modelId: valueOrDash(row?.model_id),
    modelConfigHash: valueOrDash(row?.model_config_hash || row?.subject_id || row?.hash),
    version: valueOrDash(row?.version_id || row?.target_version_id || row?.short),
    source: sourceLabel(row?.source),
    scoreValue: score ?? 0,
    winRateValue: winRate ?? 0,
    fallbackRateValue: numberFrom(percentFromFraction(row?.fallback_rate), percentFromFraction(row?.target_role_fallback_rate)) ?? 0,
    llmErrorRateValue: numberFrom(percentFromFraction(row?.llm_error_rate)) ?? 0,
    policyAdjustedRateValue: numberFrom(percentFromFraction(row?.policy_adjusted_rate)) ?? 0,
    deltaValue: hasDelta ? delta : 0,
    hasDelta,
    rankable,
    rankableLabel: rankable == null ? '--' : (rankable ? '可入榜' : '未入榜'),
    rankableReason: String(row?.rankable_reason || row?.reason || row?.gate_reason || '').trim(),
    isBaseline: Boolean(
      row?.is_reference ||
      row?.is_baseline ||
      row?.isBaseline ||
      String(row?.source || '').toLowerCase() === 'baseline' ||
      String(row?.recommendation || '').toLowerCase() === 'baseline'
    ),
    games: numberFrom(row?.games, row?.game_count, row?.games_played, row?.total_games, row?.completed) || 0
  }
}

function normalizeUnrankableEvidence(row, index, currentMode, source) {
  const raw = row?.raw && typeof row.raw === 'object' ? { ...row.raw, ...row } : (row || {})
  const completedGames = numberFrom(
    raw?.completed_games,
    raw?.games_played,
    raw?.completed,
    raw?.valid_games,
    raw?.game_count_completed,
    raw?.games
  )
  const totalGames = numberFrom(
    raw?.total_games,
    raw?.game_count,
    raw?.planned_games,
    raw?.games_total,
    raw?.games
  )
  const validGameRate = numberFrom(
    percentFromFraction(raw?.valid_game_rate),
    percentFromFraction(raw?.validGameRate),
    totalGames ? ((completedGames || 0) / totalGames) * 100 : null
  )
  const subject = unrankableSubjectLabel(raw, index, currentMode)
  const subjectId = valueOrDash(
    raw?.subject_id ||
    raw?.hash ||
    raw?.model_config_hash ||
    raw?.target_version_id ||
    raw?.version_id ||
    raw?.model_id
  )
  return {
    raw,
    key: String(raw?.evidence_key || raw?.key || raw?.subject_id || raw?.hash || raw?.batch_id || `${currentMode}-unrankable-${index}`),
    subject,
    subjectId,
    reason: readableReason(raw),
    status: statusLabel(raw?.status || raw?.rankable_status || raw?.gate_status || raw?.current_stage),
    gamesLabel: gamesProgressLabel(completedGames, totalGames),
    validGameRateLabel: validGameRate == null ? '--' : formatPct(validGameRate),
    batchId: valueOrDash(raw?.batch_id || raw?.result_batch_id || raw?.comparison_group_id),
    source
  }
}

function unrankableSubjectLabel(row, index, currentMode) {
  if (currentMode === 'model') {
    return String(
      row?.model_id ||
      row?.subject_label ||
      row?.label ||
      row?.model_config_hash ||
      row?.subject_id ||
      row?.hash ||
      `模型-${index + 1}`
    )
  }
  if (row?.is_baseline) return '基线版本'
  return String(
    row?.subject_label ||
    row?.label ||
    row?.short ||
    row?.version_id ||
    row?.target_version_id ||
    row?.subject_id ||
    row?.hash ||
    `版本-${index + 1}`
  )
}

function statusLabel(status) {
  const key = String(status || '').trim().toLowerCase()
  const labels = {
    insufficient_games: '样本不足',
    insufficient_data: '数据不足',
    data_sufficient: '数据充分',
    rankable: '可入榜',
    unrankable: '未入榜',
    failed: '失败',
    completed: '已完成',
    running: '运行中',
    pending: '等待中',
    blocked: '阻塞'
  }
  return labels[key] || (key ? status : '未入榜')
}

function readableReason(row) {
  const reasons = firstArray(row?.reasons).concat(firstArray(row?.rankable_reasons))
  const text = String(
    row?.rankable_reason ||
    row?.reason ||
    row?.gate_reason ||
    row?.unrankable_reason ||
    row?.message ||
    reasons.join('，')
  ).trim()
  return text || '未达到正式入榜门禁'
}

function gamesProgressLabel(completed, total) {
  const done = Number(completed)
  const planned = Number(total)
  if (Number.isFinite(done) && Number.isFinite(planned) && planned > 0) return `${done}/${planned} 局`
  if (Number.isFinite(done)) return `${done} 局`
  if (Number.isFinite(planned)) return `0/${planned} 局`
  return '--'
}

function firstArray(value) {
  return Array.isArray(value) ? value : []
}

function defaultMetricColumns(currentMode) {
  const keys = currentMode === 'model'
    ? ['score', 'winRate', 'delta', 'confidence', 'fallback', 'llmError', 'policy', 'rankable', 'games']
    : ['score', 'winRate', 'delta', 'confidence', 'rankable', 'games']
  return metricColumnDefs.value.filter((column) => keys.includes(column.key))
}

function isColumnEnabled(key) {
  return enabledMetricColumnKeys.value.has(key)
}

async function saveView() {
  const payload = {
    name: savedViewName.value || '默认视图',
    view_config: {
      mode: mode.value,
      rank_filter: rankFilter.value,
      columns: enabledMetricColumnDefs.value.map((column) => column.key)
    }
  }
  savedViewState.value = '保存中'
  try {
    if (typeof props.benchmark.saveCurrentBenchmarkView === 'function') {
      await props.benchmark.saveCurrentBenchmarkView(payload)
    }
    savedViewState.value = '已保存'
  } catch {
    savedViewState.value = '本地已保存'
  }
  clearSavedViewState()
}

async function loadSavedView() {
  if (typeof props.benchmark.loadCurrentBenchmarkView === 'function') {
    await props.benchmark.loadCurrentBenchmarkView(viewStorageKey.value)
  }
}

async function resetView() {
  savedViewState.value = '已重置'
  if (typeof props.benchmark.resetCurrentBenchmarkView === 'function') {
    await props.benchmark.resetCurrentBenchmarkView({
      mode: mode.value,
      rank_filter: 'all',
      columns: defaultMetricColumns(mode.value).map((column) => column.key)
    })
  }
  clearSavedViewState()
}

async function selectSavedView(event) {
  const key = String(event?.target?.value || '').trim()
  if (!key || key === selectedSavedViewKey.value) return
  savedViewState.value = '加载中'
  if (typeof props.benchmark.selectBenchmarkView === 'function') {
    await props.benchmark.selectBenchmarkView(key)
  }
  savedViewState.value = ''
}

function selectRow(row) {
  selectedRowKey.value = row?.key || ''
}

function clearSavedViewState() {
  if (typeof window === 'undefined' || !window.setTimeout) return
  window.setTimeout(() => {
    savedViewState.value = ''
  }, 1400)
}

function rowKey(row, index, currentMode) {
  const value = currentMode === 'model'
    ? row?.model_config_hash || row?.subject_id || row?.hash || row?.model_id
    : row?.version_id || row?.target_version_id || row?.hash || row?.short
  return String(value || `${currentMode === 'model' ? '模型' : '版本'}-${index + 1}`)
}

function modelPrimary(row, index) {
  return String(
    row?.model_id ||
    row?.model_config_hash ||
    row?.subject_id ||
    row?.hash ||
    `模型-${index + 1}`
  )
}

function modelSecondary(row) {
  const parts = [
    row?.model_config_hash || row?.subject_id || row?.hash,
    row?.provider,
    row?.runtime || row?.runtime_id
  ].map((value) => String(value || '').trim()).filter(Boolean)
  return parts.length ? parts.join(' / ') : '模型评测对象'
}

function rolePrimary(row, index) {
  if (row?.is_baseline) return '基线版本'
  return String(row?.short || row?.version_id || row?.target_version_id || `版本-${index + 1}`)
}

function roleSecondary(row) {
  return String(row?.version_id || row?.target_version_id || row?.hash || '角色版本对象')
}

function sourceLabel(source) {
  const labels = {
    baseline: '基线',
    evolution: '进化',
    version: '版本',
    candidate: '候选',
    manual: '手动',
    default_baseline: '默认'
  }
  const key = String(source || '').trim().toLowerCase()
  return labels[key] || (key ? source : '--')
}

function numberFrom(...values) {
  for (const value of values) {
    const number = Number(value)
    if (Number.isFinite(number)) return number
  }
  return null
}

function percentFromFraction(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return null
  return Math.abs(number) <= 1 ? number * 100 : number
}

function average(values) {
  if (!values.length) return 0
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function confidenceInterval(row) {
  if (!row) return null
  const games = Number(row.games)
  const winRate = Number(row.winRateValue)
  if (!Number.isFinite(games) || games <= 0 || !Number.isFinite(winRate)) return null
  const p = Math.max(0, Math.min(1, winRate / 100))
  const se = Math.sqrt((p * (1 - p)) / games) * 100
  const margin = se * 1.96
  return {
    low: Math.max(0, winRate - margin),
    high: Math.min(100, winRate + margin),
    margin,
    se
  }
}

function confidenceLabel(row, baseline, { isReference, likelyDifferent, enoughSamples }) {
  if (isReference) return '参考'
  if (!row?.games) return '无样本'
  if (row.games < MIN_CONFIDENT_GAMES || (baseline && baseline.games < MIN_CONFIDENT_GAMES)) return '小样本'
  return likelyDifferent && enoughSamples ? '差异明显' : '未定'
}

function confidenceTone(row, { isReference, likelyDifferent, enoughSamples }) {
  if (isReference) return 'reference'
  if (!row?.games || row.games < MIN_CONFIDENT_GAMES) return 'warning'
  if (likelyDifferent && enoughSamples) return 'strong'
  return 'muted'
}

function formatInterval(interval) {
  if (!interval) return '--'
  return `${formatPct(interval.low)}-${formatPct(interval.high)}`
}

function formatPct(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '--'
  return `${Math.round(number)}%`
}

function formatSignedPct(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '--'
  return `${number >= 0 ? '+' : ''}${Math.round(number)}%`
}

function formatCount(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '--'
  return Math.max(0, Math.round(number)).toLocaleString('zh-CN')
}

function valueOrDash(value) {
  const text = String(value || '').trim()
  return text || '--'
}

watch(viewStorageKey, () => {
  loadSavedView()
}, { immediate: true })

watch(tableRows, (current) => {
  if (!current.some((row) => row.key === selectedRowKey.value)) {
    selectedRowKey.value = current[0]?.key || ''
  }
})
</script>

<template>
  <section class="benchmark-comparison-view" aria-label="评测榜单比较">
    <header class="comparison-header">
      <div>
        <small>榜单比较</small>
        <h2 v-if="mode === 'model'">模型评测榜单</h2>
        <h2 v-else>{{ benchmark.selectedRoleLabel.value }} 角色版本榜单</h2>
      </div>
      <div class="comparison-header-status">
        <span :class="['mode-badge', 'mode-badge--' + mode]">
          {{ mode === 'model' ? 'scope=model' : '目标角色边界' }}
        </span>
        <span
          :class="['compare-source-chip', 'compare-source-chip--' + compareSourceTone]"
          aria-label="比较来源"
          aria-live="polite"
          :role="compareLoading ? 'status' : undefined"
        >
          <b>{{ compareSourceLabel }}</b>
          <small>{{ compareSourceDetail }}</small>
        </span>
      </div>
    </header>

    <section class="boundary-strip" aria-label="比较边界">
      <span v-for="item in boundaryRows" :key="item.label">
        <small>{{ item.label }}</small>
        <b>{{ item.value }}</b>
      </span>
    </section>

    <section class="metric-summary" aria-label="指标汇总">
      <span v-for="item in summary" :key="item.label">
        <small>{{ item.label }}</small>
        <b>{{ item.value }}</b>
        <em>{{ item.caption }}</em>
      </span>
    </section>

    <section class="compare-audit-strip" aria-label="正式比较口径">
      <span v-for="item in compareAuditRows" :key="item.label">
        <small>{{ item.label }}</small>
        <b>{{ item.value }}</b>
        <em>{{ item.caption }}</em>
      </span>
    </section>

    <section class="comparison-controls" aria-label="榜单视图控制">
      <div class="view-filter">
        <small>入榜筛选</small>
        <div class="segmented-control">
          <button type="button" :class="{ active: rankFilter === 'all' }" @click="rankFilter = 'all'">全部</button>
          <button type="button" :class="{ active: rankFilter === 'rankable' }" @click="rankFilter = 'rankable'">可入榜</button>
          <button type="button" :class="{ active: rankFilter === 'unrankable' }" @click="rankFilter = 'unrankable'">未入榜</button>
        </div>
      </div>
      <div class="metric-toggle-panel">
        <small>指标列</small>
        <div class="metric-toggle-list">
          <label v-for="column in metricColumnDefs" :key="column.key">
            <input v-model="selectedMetricColumns" type="checkbox" :value="column.key" />
            <span>{{ column.label }}</span>
          </label>
        </div>
      </div>
      <div class="saved-view-panel">
        <small>保存视图</small>
        <div>
          <select :value="selectedSavedViewKey" @change="selectSavedView">
            <option :value="viewStorageKey">当前边界</option>
            <option
              v-for="view in savedViewRows"
              :key="view.view_key"
              :value="view.view_key"
            >
              {{ view.name }}
            </option>
          </select>
          <input v-model.trim="savedViewName" type="text" autocomplete="off" />
          <button type="button" @click="saveView">保存</button>
          <button type="button" @click="resetView">重置</button>
        </div>
        <em>{{ savedViewState || (viewDirty ? '未保存 / ' : '') + tableViewSummary }}</em>
      </div>
    </section>

    <section v-if="boundaryMismatchRows.length" class="boundary-mismatch-alert" aria-label="边界不一致警告">
      <b>边界不一致</b>
      <span>{{ boundaryMismatchRows.length }} 行使用了不同 Evaluation Set，不应作为正式证据比较。</span>
    </section>

    <section v-if="compareError" class="comparison-source-alert" aria-label="比较来源提示">
      <b>服务端比较不可用</b>
      <span>{{ compareError }}</span>
    </section>

    <section v-if="confidenceRows.length" class="confidence-panel" aria-label="统计置信度">
      <div class="confidence-title">
        <span>统计置信度</span>
        <small>基于胜率和完成局数估算 95% 置信区间</small>
      </div>
      <div class="confidence-list">
        <div v-for="row in confidenceRows" :key="'confidence-' + row.key" class="confidence-row">
          <span>
            <b>{{ row.primary }}</b>
            <small>{{ row.games }} 局 / 胜率区间 {{ formatInterval(row.interval) }}</small>
          </span>
          <em :class="'confidence-chip confidence-chip--' + row.confidenceTone">
            {{ row.confidenceLabel }}
          </em>
        </div>
      </div>
    </section>

    <section v-if="baselineRow" class="baseline-panel" aria-label="基线比较">
      <div class="baseline-pin">
        <small>{{ baselineRow.isBaseline ? '固定基线' : '参考基线' }}</small>
        <strong>{{ baselineRow.primary }}</strong>
        <span>{{ baselineRow.secondary }}</span>
        <b>{{ formatPct(baselineRow.scoreValue) }} 分 / {{ formatPct(baselineRow.winRateValue) }} 胜率</b>
      </div>
      <div class="delta-panel">
        <div class="delta-panel-title">
          <span>相对差值</span>
          <small>{{ baselineDeltaRows.length ? '相对固定基线的分差' : '暂无候选差值' }}</small>
        </div>
        <div v-if="baselineDeltaRows.length" class="delta-list">
          <div v-for="row in baselineDeltaRows" :key="'delta-' + row.key" class="delta-row">
            <strong>{{ row.primary }}</strong>
            <i :class="row.direction" aria-hidden="true">
              <b :style="{ width: row.barWidth + '%' }"></b>
            </i>
            <span :class="row.direction">{{ formatSignedPct(row.relativeScoreDelta) }}</span>
          </div>
        </div>
        <div v-else class="compact-empty">至少需要两行才能比较相对差值。</div>
      </div>
    </section>

    <section v-if="tableRows.length" class="comparison-table-card">
      <div :class="['comparison-table', 'comparison-table--' + mode]">
        <div class="comparison-row comparison-row--header" :style="comparisonGridStyle">
          <template v-if="mode === 'model'">
            <span>模型</span>
            <span>配置 Hash</span>
          </template>
          <template v-else>
            <span>版本</span>
            <span>来源</span>
          </template>
          <span v-for="column in enabledMetricColumnDefs" :key="'head-' + column.key">
            {{ column.label }}
          </span>
        </div>

        <div
          v-for="row in tableRows"
          :key="row.key"
          :class="[
            'comparison-row',
            {
              'comparison-row--baseline': row.isBaseline,
              'comparison-row--unrankable': row.rankable === false,
              'comparison-row--selected': row.key === selectedLeaderboardRow?.key
            }
          ]"
          :style="comparisonGridStyle"
          role="button"
          tabindex="0"
          @click="selectRow(row)"
          @keydown.enter.prevent="selectRow(row)"
          @keydown.space.prevent="selectRow(row)"
        >
          <template v-if="mode === 'model'">
            <span class="identity-cell">
              <b>{{ row.modelId }}</b>
              <small>{{ row.primary }}</small>
            </span>
            <span>{{ row.modelConfigHash }}</span>
            <span v-if="isColumnEnabled('score')">{{ formatPct(row.scoreValue) }}</span>
            <span v-if="isColumnEnabled('winRate')">{{ formatPct(row.winRateValue) }}</span>
            <span v-if="isColumnEnabled('delta')" :class="row.relativeScoreDelta >= 0 ? 'positive' : 'negative'">
              {{ formatSignedPct(row.relativeScoreDelta) }}
            </span>
            <span v-if="isColumnEnabled('confidence')" class="ci-cell">{{ formatInterval(row.interval) }}</span>
            <span v-if="isColumnEnabled('fallback')">{{ formatPct(row.fallbackRateValue) }}</span>
            <span v-if="isColumnEnabled('llmError')">{{ formatPct(row.llmErrorRateValue) }}</span>
            <span v-if="isColumnEnabled('policy')">{{ formatPct(row.policyAdjustedRateValue) }}</span>
            <span v-if="isColumnEnabled('rankable')">
              <b :class="['rankable-chip', { off: row.rankable === false, unknown: row.rankable == null }]">
                {{ row.rankableLabel }}
              </b>
            </span>
            <span v-if="isColumnEnabled('games')">{{ row.games }}</span>
          </template>

          <template v-else>
            <span class="identity-cell">
              <b>{{ row.version }}</b>
              <small>{{ row.secondary }}</small>
            </span>
            <span>{{ row.source }}</span>
            <span v-if="isColumnEnabled('score')">{{ formatPct(row.scoreValue) }}</span>
            <span v-if="isColumnEnabled('winRate')">{{ formatPct(row.winRateValue) }}</span>
            <span v-if="isColumnEnabled('delta')" :class="row.relativeScoreDelta >= 0 ? 'positive' : 'negative'">
              {{ formatSignedPct(row.relativeScoreDelta) }}
            </span>
            <span v-if="isColumnEnabled('confidence')">
              <b :class="'confidence-chip confidence-chip--' + row.confidenceTone">
                {{ row.confidenceLabel }}
              </b>
            </span>
            <span v-if="isColumnEnabled('rankable')">
              <b :class="['baseline-chip', { on: row.isBaseline }]">
                {{ row.isBaseline ? '基线' : '候选' }}
              </b>
            </span>
            <span v-if="isColumnEnabled('games')">{{ row.games }}</span>
          </template>
        </div>
      </div>
    </section>

    <section v-else class="empty-state">
      <strong>{{ emptyTitle }}</strong>
      <span>{{ emptyCaption }}</span>
    </section>

    <section v-if="selectedLeaderboardRow" class="row-detail-panel" aria-label="榜单行详情">
      <div class="row-detail-heading">
        <span>
          <small>行详情</small>
          <b>{{ selectedLeaderboardRow.primary }}</b>
        </span>
        <em>{{ selectedLeaderboardRow.rankableLabel }}</em>
      </div>
      <dl>
        <div>
          <dt>{{ mode === 'model' ? '配置 Hash' : '对象' }}</dt>
          <dd>{{ mode === 'model' ? selectedLeaderboardRow.modelConfigHash : selectedLeaderboardRow.secondary }}</dd>
        </div>
        <div>
          <dt>分差</dt>
          <dd :class="selectedLeaderboardRow.relativeScoreDelta >= 0 ? 'positive' : 'negative'">
            {{ formatSignedPct(selectedLeaderboardRow.relativeScoreDelta) }}
          </dd>
        </div>
        <div>
          <dt>胜率区间</dt>
          <dd>{{ formatInterval(selectedLeaderboardRow.interval) }}</dd>
        </div>
        <div>
          <dt>局数</dt>
          <dd>{{ selectedLeaderboardRow.games }}</dd>
        </div>
        <div v-if="mode === 'model'">
          <dt>回退率</dt>
          <dd>{{ formatPct(selectedLeaderboardRow.fallbackRateValue) }}</dd>
        </div>
        <div v-if="mode === 'model'">
          <dt>LLM 错误</dt>
          <dd>{{ formatPct(selectedLeaderboardRow.llmErrorRateValue) }}</dd>
        </div>
        <div v-if="mode === 'model'">
          <dt>策略修正</dt>
          <dd>{{ formatPct(selectedLeaderboardRow.policyAdjustedRateValue) }}</dd>
        </div>
      </dl>
      <p>
        {{ selectedLeaderboardRow.rankableReason || (selectedLeaderboardRow.rankable === false ? '未入榜，但后端未返回原因。' : '该行未报告门禁失败。') }}
      </p>
    </section>

    <section class="unrankable-panel" aria-label="未入榜证据">
      <div class="unrankable-title">
        <span>未入榜证据</span>
        <small>{{ unrankableEvidenceRows.length }} 条 / {{ unrankableEvidenceSourceLabel }}</small>
      </div>
      <div v-if="unrankableEvidenceRows.length" class="unrankable-list">
        <article v-for="row in unrankableEvidenceRows" :key="'unrankable-' + row.key" class="unrankable-row">
          <div class="unrankable-row-main">
            <b>{{ row.subject }}</b>
            <span>{{ row.subjectId }}</span>
            <em>{{ row.source }}</em>
          </div>
          <p>{{ row.reason }}</p>
          <dl>
            <div>
              <dt>状态</dt>
              <dd>{{ row.status }}</dd>
            </div>
            <div>
              <dt>局数</dt>
              <dd>{{ row.gamesLabel }}</dd>
            </div>
            <div>
              <dt>有效局率</dt>
              <dd>{{ row.validGameRateLabel }}</dd>
            </div>
            <div>
              <dt>batch_id</dt>
              <dd>{{ row.batchId }}</dd>
            </div>
          </dl>
        </article>
      </div>
      <div v-else class="compact-empty">当前比较结果没有返回未入榜证据。</div>
    </section>
  </section>
</template>

<style scoped>
.benchmark-comparison-view {
  --comparison-bg: var(--bench-bg-texture, var(--logbook-bg-texture, #f2dfae));
  --comparison-panel: var(--bench-panel, var(--logbook-panel, rgba(255, 252, 245, 0.82)));
  --comparison-panel-solid: var(--bench-panel-solid, var(--logbook-panel-solid, #fffaf0));
  --comparison-panel-soft: var(--bench-panel-soft, var(--logbook-panel-soft, rgba(255, 242, 210, 0.58)));
  --comparison-line: var(--bench-border, var(--logbook-border, rgba(139, 94, 52, 0.18)));
  --comparison-line-strong: var(--bench-border-strong, var(--logbook-border-strong, rgba(90, 51, 25, 0.34)));
  --comparison-text: var(--bench-text, var(--logbook-text, #3a2a18));
  --comparison-muted: var(--bench-text-secondary, var(--logbook-muted, #8b6b4a));
  --comparison-positive: var(--bench-accent, var(--logbook-accent, #8b5e34));
  --comparison-model: var(--bench-accent-strong, var(--logbook-accent-strong, #5a3319));
  --comparison-red: var(--bench-danger, var(--logbook-danger, #993026));
  --comparison-amber: var(--bench-warning, var(--logbook-warning, #9a6518));
  --comparison-danger-border: var(--bench-danger-border, rgba(153, 48, 38, 0.28));
  --comparison-danger-bg: var(--bench-danger-bg, rgba(153, 48, 38, 0.06));
  --comparison-warning-border: var(--bench-warning-border, rgba(139, 100, 31, 0.3));
  --comparison-warning-bg: var(--bench-warning-bg, rgba(139, 100, 31, 0.08));
  display: grid;
  gap: 10px;
  min-width: 980px;
  padding: 12px;
  border: 1px solid var(--comparison-line);
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(255, 252, 245, 0.72), rgba(235, 199, 136, 0.2)),
    var(--comparison-bg);
  color: var(--comparison-text);
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
}

.comparison-header,
.boundary-strip,
.metric-summary,
.compare-audit-strip,
.comparison-controls,
.boundary-mismatch-alert,
.comparison-source-alert,
.confidence-panel,
.baseline-panel,
.comparison-table-card,
.row-detail-panel,
.unrankable-panel,
.empty-state {
  border: 1px solid var(--comparison-line);
  border-radius: 8px;
  background: var(--comparison-panel);
}

.comparison-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 16px;
  min-height: 58px;
  padding: 11px 14px;
}

.comparison-header small,
.boundary-strip small,
.metric-summary small,
.compare-audit-strip small,
.confidence-title small,
.baseline-pin small,
.delta-panel-title small,
.unrankable-title small {
  color: var(--comparison-muted);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.comparison-header h2 {
  margin: 2px 0 0;
  color: var(--comparison-text);
  font-size: 18px;
  font-weight: 900;
  line-height: 1.1;
}

.comparison-header-status {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}

.mode-badge {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border: 1px solid var(--comparison-line-strong);
  border-radius: 6px;
  background: var(--comparison-panel-soft);
  color: var(--comparison-text);
  font-size: 12px;
  font-weight: 900;
}

.mode-badge--model {
  border-left: 4px solid var(--comparison-model);
}

.mode-badge--role_version {
  border-left: 4px solid var(--comparison-positive);
}

.compare-source-chip {
  display: grid;
  gap: 1px;
  min-width: 180px;
  max-width: 280px;
  min-height: 34px;
  padding: 5px 9px;
  border: 1px solid var(--comparison-line);
  border-radius: 6px;
  background: rgba(255, 250, 240, 0.72);
}

.compare-source-chip b,
.compare-source-chip small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.compare-source-chip b {
  color: var(--comparison-text);
  font-size: 11px;
  font-weight: 950;
}

.compare-source-chip small {
  color: var(--comparison-muted);
  font-size: 10px;
  font-weight: 800;
}

.compare-source-chip--server {
  border-color: rgba(139, 94, 52, 0.28);
  box-shadow: inset 3px 0 0 var(--comparison-positive);
}

.compare-source-chip--fallback {
  border-color: var(--comparison-danger-border);
  box-shadow: inset 3px 0 0 var(--comparison-red);
}

.compare-source-chip--loading {
  border-color: var(--comparison-warning-border);
  box-shadow: inset 3px 0 0 var(--comparison-amber);
}

.boundary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0;
  overflow: hidden;
}

.boundary-strip span,
.metric-summary span,
.compare-audit-strip span {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 10px 12px;
  border-right: 1px solid var(--comparison-line);
}

.boundary-strip span:last-child,
.metric-summary span:last-child,
.compare-audit-strip span:last-child {
  border-right: none;
}

.boundary-strip b,
.metric-summary b,
.metric-summary em,
.compare-audit-strip b,
.compare-audit-strip em,
.baseline-pin strong,
.baseline-pin span,
.baseline-pin b,
.comparison-row span,
.unrankable-row-main b,
.unrankable-row-main span,
.unrankable-row dd {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.boundary-strip b {
  color: var(--comparison-text);
  font-size: 12px;
  font-weight: 900;
}

.metric-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  overflow: hidden;
}

.compare-audit-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  overflow: hidden;
  background: rgba(255, 252, 245, 0.58);
}

.metric-summary b {
  color: var(--comparison-text);
  font-size: 19px;
  font-weight: 900;
  line-height: 1;
}

.metric-summary em,
.compare-audit-strip em {
  color: var(--comparison-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
}

.compare-audit-strip b {
  color: var(--comparison-text);
  font-size: 13px;
  font-weight: 900;
  line-height: 1.15;
}

.comparison-controls {
  display: grid;
  grid-template-columns: minmax(220px, 0.72fr) minmax(360px, 1.15fr) minmax(320px, 0.95fr);
  gap: 10px;
  padding: 10px 12px;
}

.view-filter,
.metric-toggle-panel,
.saved-view-panel {
  display: grid;
  align-content: start;
  gap: 6px;
  min-width: 0;
}

.comparison-controls small,
.boundary-mismatch-alert b,
.row-detail-heading small,
.row-detail-panel dt {
  color: var(--comparison-muted);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.segmented-control,
.metric-toggle-list,
.saved-view-panel div {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}

.segmented-control button,
.saved-view-panel button {
  min-height: 28px;
  padding: 0 9px;
  border: 1px solid var(--comparison-line);
  border-radius: 6px;
  background: var(--comparison-panel-solid);
  color: var(--comparison-text);
  font-size: 11px;
  font-weight: 900;
  cursor: pointer;
}

.segmented-control button.active {
  border-color: var(--comparison-positive);
  background: rgba(139, 94, 52, 0.12);
  color: var(--comparison-positive);
}

.metric-toggle-list label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 28px;
  padding: 0 8px;
  border: 1px solid var(--comparison-line);
  border-radius: 6px;
  background: rgba(255, 250, 240, 0.82);
  color: var(--comparison-text);
  font-size: 11px;
  font-weight: 850;
}

.metric-toggle-list input {
  width: 13px;
  height: 13px;
  margin: 0;
  accent-color: var(--comparison-positive);
}

.saved-view-panel input,
.saved-view-panel select {
  width: 132px;
  height: 28px;
  min-width: 0;
  padding: 0 8px;
  border: 1px solid var(--comparison-line);
  border-radius: 6px;
  background: var(--comparison-panel-solid);
  color: var(--comparison-text);
  font-size: 11px;
  font-weight: 850;
}

.saved-view-panel select {
  width: 158px;
}

.saved-view-panel em {
  min-width: 0;
  overflow: hidden;
  color: var(--comparison-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.boundary-mismatch-alert {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  padding: 9px 12px;
  border-color: var(--comparison-danger-border);
  background: var(--comparison-danger-bg);
}

.boundary-mismatch-alert b,
.boundary-mismatch-alert span {
  color: var(--comparison-red);
}

.boundary-mismatch-alert span {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.comparison-source-alert {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  padding: 9px 12px;
  border-color: var(--comparison-danger-border);
  background: var(--comparison-danger-bg);
}

.comparison-source-alert b,
.comparison-source-alert span {
  min-width: 0;
  overflow: hidden;
  color: var(--comparison-red);
  font-size: 12px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.confidence-panel {
  display: grid;
  gap: 8px;
  padding: 11px 12px;
}

.confidence-title {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
}

.confidence-title span {
  color: var(--comparison-text);
  font-size: 13px;
  font-weight: 900;
}

.confidence-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(260px, 1fr));
  gap: 7px 10px;
}

.confidence-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 38px;
  padding: 7px 9px;
  border: 1px solid var(--comparison-line);
  border-radius: 6px;
  background: rgba(255, 250, 240, 0.68);
}

.confidence-row span {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.confidence-row b,
.confidence-row small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.confidence-row b {
  color: var(--comparison-text);
  font-size: 12px;
  font-weight: 900;
}

.confidence-row small {
  color: var(--comparison-muted);
  font-size: 11px;
  font-weight: 750;
}

.baseline-panel {
  display: grid;
  grid-template-columns: minmax(250px, 0.72fr) minmax(0, 1fr);
  min-height: 116px;
  overflow: hidden;
}

.baseline-pin {
  display: grid;
  align-content: center;
  gap: 5px;
  min-width: 0;
  padding: 14px;
  border-left: 4px solid var(--comparison-amber);
  border-right: 1px solid var(--comparison-line);
  background: rgba(255, 245, 221, 0.78);
}

.baseline-pin strong {
  color: var(--comparison-text);
  font-size: 18px;
  font-weight: 900;
}

.baseline-pin span {
  color: var(--comparison-muted);
  font-size: 12px;
  font-weight: 800;
}

.baseline-pin b {
  color: var(--comparison-amber);
  font-size: 12px;
  font-weight: 900;
}

.delta-panel {
  display: grid;
  align-content: start;
  gap: 8px;
  min-width: 0;
  padding: 12px;
}

.delta-panel-title,
.unrankable-title {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
}

.delta-panel-title span,
.unrankable-title span {
  color: var(--comparison-text);
  font-size: 13px;
  font-weight: 900;
}

.delta-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(260px, 1fr));
  gap: 7px 14px;
}

.delta-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(88px, 0.42fr) 44px;
  align-items: center;
  gap: 8px;
  min-height: 28px;
}

.delta-row strong {
  min-width: 0;
  overflow: hidden;
  color: var(--comparison-text);
  font-size: 12px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.delta-row i {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.16);
}

.delta-row i b {
  display: block;
  height: 100%;
  border-radius: inherit;
}

.delta-row i.positive b {
  background: var(--comparison-positive);
}

.delta-row i.negative b {
  background: var(--comparison-red);
}

.delta-row span {
  font-size: 12px;
  font-weight: 900;
  text-align: right;
}

.comparison-table-card {
  overflow: auto;
}

.comparison-table {
  display: grid;
  min-width: 940px;
  padding: 6px;
}

.comparison-row {
  display: grid;
  align-items: center;
  gap: 10px;
  min-height: 42px;
  padding: 7px 9px;
  border-bottom: 1px solid var(--comparison-line);
  border-radius: 5px;
}

.comparison-row:last-child {
  border-bottom: none;
}

.comparison-row:not(.comparison-row--header):hover {
  background: rgba(139, 94, 52, 0.07);
  cursor: pointer;
}

.comparison-row--header {
  min-height: 30px;
  color: var(--comparison-muted);
  font-size: 11px;
  font-weight: 900;
  text-transform: uppercase;
}

.comparison-row--baseline {
  background: rgba(255, 245, 221, 0.78);
  box-shadow: inset 3px 0 0 var(--comparison-amber);
}

.comparison-row--unrankable {
  color: var(--comparison-muted);
  background: rgba(255, 252, 245, 0.48);
}

.comparison-row--selected {
  outline: 2px solid rgba(139, 94, 52, 0.28);
  background: rgba(255, 226, 157, 0.32);
}

.comparison-row span {
  color: inherit;
  font-size: 12px;
  font-weight: 800;
}

.identity-cell {
  display: grid;
  gap: 2px;
}

.identity-cell b,
.identity-cell small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.identity-cell b {
  color: var(--comparison-text);
  font-size: 12px;
  font-weight: 900;
}

.identity-cell small {
  color: var(--comparison-muted);
  font-size: 11px;
  font-weight: 700;
}

.rankable-chip,
.baseline-chip,
.confidence-chip {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 7px;
  border: 1px solid rgba(139, 94, 52, 0.32);
  border-radius: 5px;
  background: rgba(139, 94, 52, 0.1);
  color: var(--comparison-positive);
  font-size: 11px;
  font-weight: 900;
}

.rankable-chip.off {
  border-color: var(--comparison-danger-border);
  background: var(--comparison-danger-bg);
  color: var(--comparison-red);
}

.rankable-chip.unknown,
.baseline-chip {
  border-color: var(--comparison-line);
  background: var(--comparison-panel-soft);
  color: var(--comparison-muted);
}

.confidence-chip {
  border-color: var(--comparison-line);
  background: var(--comparison-panel-soft);
  color: var(--comparison-muted);
  white-space: nowrap;
}

.confidence-chip--reference {
  border-color: var(--comparison-warning-border);
  background: var(--comparison-warning-bg);
  color: var(--comparison-amber);
}

.confidence-chip--strong {
  border-color: rgba(139, 94, 52, 0.32);
  background: rgba(139, 94, 52, 0.1);
  color: var(--comparison-positive);
}

.confidence-chip--warning {
  border-color: var(--comparison-warning-border);
  background: var(--comparison-warning-bg);
  color: var(--comparison-amber);
}

.confidence-chip--muted {
  border-color: var(--comparison-line);
  background: rgba(255, 252, 245, 0.54);
  color: var(--comparison-muted);
}

.ci-cell {
  color: var(--comparison-muted) !important;
  font-weight: 850 !important;
}

.row-detail-panel {
  display: grid;
  gap: 10px;
  padding: 11px 12px;
}

.row-detail-heading {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
}

.row-detail-heading span {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.row-detail-heading b,
.row-detail-heading em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-detail-heading b {
  color: var(--comparison-text);
  font-size: 13px;
  font-weight: 950;
}

.row-detail-heading em {
  padding: 4px 8px;
  border: 1px solid var(--comparison-line);
  border-radius: 999px;
  background: rgba(255, 250, 240, 0.72);
  color: var(--comparison-text);
  font-size: 11px;
  font-style: normal;
  font-weight: 900;
}

.row-detail-panel dl {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.row-detail-panel dl div {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 8px 9px;
  border: 1px solid var(--comparison-line);
  border-radius: 7px;
  background: rgba(255, 250, 240, 0.68);
}

.row-detail-panel dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--comparison-text);
  font-size: 12px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-detail-panel p {
  margin: 0;
  color: var(--comparison-muted);
  font-size: 12px;
  font-weight: 800;
  line-height: 1.45;
}

.baseline-chip.on {
  border-color: var(--comparison-warning-border);
  background: var(--comparison-warning-bg);
  color: var(--comparison-amber);
}

.unrankable-panel {
  display: grid;
  gap: 8px;
  padding: 11px 12px;
}

.unrankable-list {
  display: grid;
  gap: 8px;
}

.unrankable-row {
  display: grid;
  grid-template-columns: minmax(180px, 0.66fr) minmax(0, 1fr) minmax(360px, 1.12fr);
  gap: 12px;
  align-items: stretch;
  min-height: 76px;
  padding: 9px 10px;
  border: 1px solid var(--comparison-danger-border);
  border-radius: 6px;
  background: var(--comparison-danger-bg);
}

.unrankable-row-main {
  display: grid;
  align-content: center;
  gap: 3px;
  min-width: 0;
}

.unrankable-row-main b {
  color: var(--comparison-text);
  font-size: 12px;
  font-weight: 900;
}

.unrankable-row-main span {
  color: var(--comparison-muted);
  font-size: 11px;
  font-weight: 800;
}

.unrankable-row-main em {
  width: fit-content;
  padding: 2px 6px;
  border: 1px solid rgba(139, 94, 52, 0.2);
  border-radius: 5px;
  background: rgba(255, 252, 245, 0.72);
  color: var(--comparison-positive);
  font-size: 10px;
  font-style: normal;
  font-weight: 900;
}

.unrankable-row p {
  min-width: 0;
  margin: 0;
  align-self: center;
  overflow: hidden;
  color: var(--comparison-text);
  font-size: 12px;
  font-weight: 850;
  line-height: 1.4;
  text-overflow: ellipsis;
}

.unrankable-row dl {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
  margin: 0;
}

.unrankable-row dl div {
  display: grid;
  align-content: center;
  gap: 2px;
  min-width: 0;
  padding: 6px 7px;
  border: 1px solid var(--comparison-line);
  border-radius: 6px;
  background: rgba(255, 250, 240, 0.68);
}

.unrankable-row dt {
  color: var(--comparison-muted);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0;
}

.unrankable-row dd {
  margin: 0;
  color: var(--comparison-red);
  font-size: 11px;
  font-weight: 900;
}

.empty-state,
.compact-empty {
  color: var(--comparison-muted);
  font-size: 12px;
  font-weight: 800;
}

.empty-state {
  display: grid;
  gap: 3px;
  min-height: 92px;
  align-content: center;
  padding: 18px;
  text-align: center;
}

.empty-state strong {
  color: var(--comparison-text);
  font-size: 14px;
  font-weight: 900;
}

.compact-empty {
  min-height: 30px;
  padding: 8px 10px;
  border: 1px dashed var(--comparison-line);
  border-radius: 6px;
  background: rgba(255, 250, 240, 0.68);
}

.positive {
  color: var(--comparison-positive) !important;
  font-weight: 900 !important;
}

.negative {
  color: var(--comparison-red) !important;
  font-weight: 900 !important;
}
</style>
