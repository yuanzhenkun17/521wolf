<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

const MIN_CONFIDENT_GAMES = 30
const STORAGE_PREFIX = 'benchmark-comparison-view'
const RANK_FILTER_LABELS = {
  all: '全部',
  rankable: '可入榜',
  unrankable: '未入榜'
}
const WARNING_LABELS = {
  low_sample: '小样本',
  unpaired_seeds: '未配对种子',
  insufficient_overlap: '配对重叠不足'
}

const props = defineProps({
  benchmark: {
    type: Object,
    required: true
  }
})

const savedViewState = ref('')

onMounted(async () => {
  await props.benchmark.loadBenchmarkViews({ silent: true })
  await props.benchmark.loadCurrentBenchmarkView()
})

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
  if (hasApiCompareRows.value) return 'server'
  if (compareError.value) return 'fallback'
  if (comparePayload.value) return 'fallback'
  return 'local'
})
const compareSourceLabel = computed(() => {
  if (compareLoading.value) return '正在加载服务端比较'
  if (hasApiCompareRows.value) return '服务端标准比较'
  if (compareError.value) return '本地兜底比较'
  if (comparePayload.value) return '服务端比较为空，保留本地榜单'
  return '本地当前榜单'
})
const compareSourceDetail = computed(() => {
  if (compareLoading.value) return '正在读取 /leaderboards/compare'
  if (hasApiCompareRows.value) return '正式 rows 与未入榜证据已分离'
  if (compareError.value) return compareError.value
  if (comparePayload.value) return '服务端 compare 暂无 rows，当前展示不会清空已加载榜单。'
  return '等待服务端 compare，暂按当前榜单行计算'
})

const apiCompareRows = computed(() => {
  const compare = comparePayload.value
  if (!compare || !Array.isArray(compare.rows)) return []
  return compare.rows
})
const hasApiCompareRows = computed(() => apiCompareRows.value.length > 0)

const rawRows = computed(() =>
  hasApiCompareRows.value
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
  const baselineInterval = effectiveConfidenceInterval(baseline)
  const baselineSe = effectiveStandardError(baseline, baselineInterval)
  return rows.value
    .map((row) => {
      const interval = effectiveConfidenceInterval(row)
      const rowSe = effectiveStandardError(row, interval)
      const relativeWinRateDelta = row.winRateValue - baselineWinRate
      const combinedSe = Math.sqrt((rowSe || 0) ** 2 + (baselineSe || 0) ** 2)
      const margin = combinedSe * 1.96
      const enoughSamples = Boolean(
        row.sampleSize >= MIN_CONFIDENT_GAMES &&
        (!baseline || baseline.sampleSize >= MIN_CONFIDENT_GAMES)
      )
      const isReference = Boolean(baseline && row.key === baseline.key)
      const likelyDifferent = row.significantValue ?? (
        !isReference && enoughSamples && Math.abs(relativeWinRateDelta) > margin
      )
      const relativeScoreDelta = row.hasDelta ? row.deltaValue : row.scoreValue - baselineScore
      return {
        ...row,
        interval,
        confidenceLabel: confidenceLabel(row, baseline, { isReference, likelyDifferent, enoughSamples }),
        confidenceTone: confidenceTone(row, { isReference, likelyDifferent, enoughSamples }),
        relativeScoreDelta,
        displayDeltaValue: row.pairedDeltaValue ?? relativeScoreDelta,
        displayDeltaSource: row.pairedDeltaValue == null ? '分数差' : 'paired delta',
        relativeWinRateDelta,
        relativeWinRateMargin: margin,
        standardErrorValue: row.standardErrorValue ?? rowSe ?? null
      }
    })
    .sort((a, b) => {
      if (a.rankable === false && b.rankable !== false) return 1
      if (a.rankable !== false && b.rankable === false) return -1
      return b.scoreValue - a.scoreValue || b.winRateValue - a.winRateValue
    })
})

const metricColumnDefs = computed(() => {
  const confidenceWidth = mode.value === 'model' ? '150px' : '148px'
  const rankableLabel = mode.value === 'model' ? '入榜' : '基线'
  const baseColumns = [
    { key: 'score', label: '分数', width: '70px' },
    { key: 'winRate', label: '胜率', width: '76px' },
    { key: 'delta', label: 'paired delta', width: '104px' },
    { key: 'confidence', label: '置信证据', width: confidenceWidth },
    { key: 'rankable', label: rankableLabel, width: '96px' },
    { key: 'games', label: '样本量', width: '104px' }
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

const boundaryMismatchRows = computed(() => {
  const evaluationSet = props.benchmark.selectedBenchmarkEvaluationSetId.value
  if (!evaluationSet) return []
  return rows.value.filter((row) => {
    const rowEvaluationSet = String(row.raw?.evaluation_set_id || row.raw?.evaluationSetId || '').trim()
    return rowEvaluationSet && rowEvaluationSet !== evaluationSet
  })
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
      value: topRow.value ? formatScore(topRow.value.scoreValue) : '--',
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
      caption: topDelta == null ? '基线待定' : `${formatSignedScore(topDelta)} 最高分差`
    }
  ]
})

const emptyTitle = computed(() =>
  mode.value === 'model' ? '暂无模型评测行' : '暂无角色版本评测行'
)

const emptyCaption = computed(() =>
  mode.value === 'model'
    ? '运行模型套件后会生成模型榜单行。'
    : '选择角色并运行角色版本套件后会生成比较数据。'
)

function normalizeRow(row, index, currentMode) {
  const score = numberFrom(
    percentFromFraction(row?.strength_score),
    percentFromFraction(row?.avg_role_score),
    percentFromFraction(row?.target_role_role_weighted_score),
    row?.scorePct,
    percentFromFraction(row?.score)
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
  const sampleSize = numberFrom(
    row?.sample_size,
    row?.sampleSize,
    row?.sample_n,
    row?.n,
    row?.games,
    row?.game_count,
    row?.games_played,
    row?.total_games,
    row?.completed
  ) ?? 0
  const pairedSampleSize = numberFrom(
    row?.paired_sample_size,
    row?.pairedSampleSize,
    row?.paired_n,
    row?.paired_games,
    row?.overlap_sample_size,
    row?.seed_overlap
  )
  const standardError = numberFrom(
    percentFromFraction(row?.standard_error),
    percentFromFraction(row?.standardError),
    percentFromFraction(row?.win_rate_standard_error),
    percentFromFraction(row?.winRateStandardError),
    percentFromFraction(row?.se)
  )
  const standardDeviation = numberFrom(
    row?.standard_deviation,
    row?.standardDeviation,
    row?.stddev,
    row?.std_dev,
    row?.score_std,
    row?.summary?.standard_deviation,
    row?.summary?.stddev
  )
  const pairedDelta = numberFrom(
    percentFromFraction(row?.paired_delta),
    percentFromFraction(row?.pairedDelta),
    percentFromFraction(row?.paired_win_rate_delta),
    percentFromFraction(row?.pairedWinRateDelta),
    percentFromFraction(row?.paired_delta_pct)
  )
  const pairedWinRate = numberFrom(
    percentFromFraction(row?.paired_win_rate),
    percentFromFraction(row?.pairedWinRate),
    percentFromFraction(row?.paired_seed_win_rate),
    percentFromFraction(row?.summary?.paired_win_rate)
  )
  const validGames = numberFrom(
    row?.valid_games,
    row?.validGames,
    row?.completed_games,
    row?.summary?.valid_games
  )
  const abnormalGames = numberFrom(
    row?.abnormal_games,
    row?.abnormalGames,
    row?.invalid_games,
    row?.failed_games,
    row?.summary?.abnormal_games,
    row?.summary?.invalid_games
  )
  const significant = booleanFrom(row?.significant)
  const warnings = normalizeWarnings(row, sampleSize)
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
    sampleSize,
    pairedSampleSize,
    apiInterval: normalizeWinRateInterval(row, winRate, standardError),
    standardErrorValue: standardError,
    standardDeviationValue: standardDeviation,
    pairedDeltaValue: pairedDelta,
    pairedWinRateValue: pairedWinRate,
    validGames,
    abnormalGames,
    significantValue: significant,
    significanceLabel: normalizeSignificanceLabel(row, significant),
    warningCodes: warnings.codes,
    warningLabels: warnings.labels,
    warningText: warnings.text,
    hasWarnings: warnings.codes.length > 0,
    isBaseline: Boolean(
      row?.is_reference ||
      row?.is_baseline ||
      row?.isBaseline ||
      String(row?.source || '').toLowerCase() === 'baseline' ||
      String(row?.recommendation || '').toLowerCase() === 'baseline'
    ),
    games: sampleSize
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
    if (value == null || value === '') continue
    const number = Number(value)
    if (Number.isFinite(number)) return number
  }
  return null
}

function percentFromFraction(value) {
  if (value == null || value === '') return null
  const number = Number(value)
  if (!Number.isFinite(number)) return null
  return Math.abs(number) <= 1 ? number * 100 : number
}

function booleanFrom(value) {
  if (typeof value === 'boolean') return value
  const text = String(value ?? '').trim().toLowerCase()
  if (['true', '1', 'yes', 'significant'].includes(text)) return true
  if (['false', '0', 'no', 'not_significant', 'insignificant'].includes(text)) return false
  return null
}

function normalizeWinRateInterval(row, winRateValue, standardErrorValue = null) {
  const direct = row?.win_rate_ci || row?.winRateCi || row?.winRateCI || row?.confidence_interval || row?.confidenceInterval || row?.ci
  let low = null
  let high = null
  if (Array.isArray(direct)) {
    low = direct[0]
    high = direct[1]
  } else if (direct && typeof direct === 'object') {
    low = direct.low ?? direct.lower ?? direct.ci_low ?? direct.ciLow
    high = direct.high ?? direct.upper ?? direct.ci_high ?? direct.ciHigh
  }
  low = numberFrom(
    percentFromFraction(low),
    percentFromFraction(row?.ci_low),
    percentFromFraction(row?.ciLow),
    percentFromFraction(row?.win_rate_ci_low),
    percentFromFraction(row?.winRateCiLow)
  )
  high = numberFrom(
    percentFromFraction(high),
    percentFromFraction(row?.ci_high),
    percentFromFraction(row?.ciHigh),
    percentFromFraction(row?.win_rate_ci_high),
    percentFromFraction(row?.winRateCiHigh)
  )
  if (low == null || high == null) return null
  const orderedLow = Math.min(low, high)
  const orderedHigh = Math.max(low, high)
  const center = Number(winRateValue)
  const margin = Number.isFinite(center)
    ? Math.max(Math.abs(center - orderedLow), Math.abs(orderedHigh - center))
    : (orderedHigh - orderedLow) / 2
  return {
    low: clampPercent(orderedLow),
    high: clampPercent(orderedHigh),
    margin,
    se: standardErrorValue ?? (margin ? margin / 1.96 : null)
  }
}

function normalizeSignificanceLabel(row, significant) {
  const label = String(row?.significance_label || row?.significanceLabel || '').trim()
  if (label) return label
  if (significant === true) return '差异显著'
  if (significant === false) return '差异不显著'
  return ''
}

function normalizeWarnings(row, sampleSize) {
  const codes = new Set([
    ...warningCodesFrom(row?.warnings),
    ...warningCodesFrom(row?.warning),
    ...warningCodesFrom(row?.statistical_warnings),
    ...warningCodesFrom(row?.statisticalWarnings),
    ...warningCodesFrom(row?.confidence_warnings),
    ...warningCodesFrom(row?.confidenceWarnings)
  ])
  if (sampleSize > 0 && sampleSize < MIN_CONFIDENT_GAMES) codes.add('low_sample')
  const normalized = [...codes].map(normalizeWarningCode).filter(Boolean)
  const labels = normalized.map((code) => WARNING_LABELS[code] || code)
  return {
    codes: normalized,
    labels,
    text: labels.join(' / ')
  }
}

function warningCodesFrom(value) {
  if (Array.isArray(value)) return value
  if (value && typeof value === 'object') {
    return Object.entries(value)
      .filter(([, enabled]) => Boolean(enabled))
      .map(([code]) => code)
  }
  const text = String(value || '').trim()
  if (!text) return []
  return text.split(/[,，\s/]+/).filter(Boolean)
}

function normalizeWarningCode(value) {
  return String(value || '').trim().toLowerCase().replace(/[-\s]+/g, '_')
}

function average(values) {
  if (!values.length) return 0
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function effectiveConfidenceInterval(row) {
  if (!row) return null
  return row.apiInterval || confidenceInterval(row)
}

function effectiveStandardError(row, interval) {
  return row?.standardErrorValue ?? interval?.se ?? null
}

function confidenceInterval(row) {
  if (!row) return null
  const games = Number(row.sampleSize ?? row.games)
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
  if (row?.significanceLabel) return row.significanceLabel
  if (!row?.sampleSize) return '无样本'
  if (row.warningCodes?.includes('low_sample') || (baseline && baseline.sampleSize < MIN_CONFIDENT_GAMES)) return '小样本'
  return likelyDifferent && enoughSamples ? '差异显著' : '差异不显著'
}

function confidenceTone(row, { isReference, likelyDifferent, enoughSamples }) {
  if (isReference) return 'reference'
  if (!row?.sampleSize || row.warningCodes?.some((code) => ['low_sample', 'insufficient_overlap'].includes(code))) return 'warning'
  if (row.significantValue === true) return 'strong'
  if (row.significantValue === false) return 'muted'
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

function formatOptionalNumber(value, digits = 2) {
  if (value == null || value === '') return '--'
  const number = Number(value)
  if (!Number.isFinite(number)) return '--'
  return number.toFixed(digits)
}

function formatOptionalPct(value) {
  if (value == null || value === '') return '--'
  return formatPct(value)
}

function formatScore(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '--'
  return number.toFixed(2)
}

function formatStandardError(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '--'
  return `${number < 10 ? number.toFixed(1) : Math.round(number)}%`
}

function formatSignedPct(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '--'
  return `${number >= 0 ? '+' : ''}${Math.round(number)}%`
}

function formatSignedScore(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '--'
  return `${number >= 0 ? '+' : ''}${number.toFixed(2)}`
}

function valueOrDash(value) {
  const text = String(value || '').trim()
  return text || '--'
}

function clampPercent(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0
  return Math.max(0, Math.min(100, number))
}

watch(viewStorageKey, () => {
  loadSavedView()
}, { immediate: true })
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

    <section class="metric-summary" aria-label="指标汇总">
      <span v-for="item in summary" :key="item.label">
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
              'comparison-row--unrankable': row.rankable === false
            }
          ]"
          :style="comparisonGridStyle"
        >
          <template v-if="mode === 'model'">
            <span class="identity-cell">
              <b>{{ row.modelId }}</b>
              <small>{{ row.primary }}</small>
            </span>
            <span>{{ row.modelConfigHash }}</span>
            <span v-if="isColumnEnabled('score')">{{ formatScore(row.scoreValue) }}</span>
            <span v-if="isColumnEnabled('winRate')">{{ formatPct(row.winRateValue) }}</span>
            <span v-if="isColumnEnabled('delta')" :class="['delta-cell', row.displayDeltaValue >= 0 ? 'positive' : 'negative']">
              <b>{{ formatSignedScore(row.displayDeltaValue) }}</b>
              <small>{{ row.displayDeltaSource }}</small>
            </span>
            <span v-if="isColumnEnabled('confidence')" class="ci-cell">
              <b :class="'confidence-chip confidence-chip--' + row.confidenceTone">
                {{ row.confidenceLabel }}
              </b>
              <small>95%置信区间 {{ formatInterval(row.interval) }} / 标准差 {{ formatOptionalNumber(row.standardDeviationValue) }}</small>
              <small v-if="row.warningText">{{ row.warningText }}</small>
            </span>
            <span v-if="isColumnEnabled('fallback')">{{ formatPct(row.fallbackRateValue) }}</span>
            <span v-if="isColumnEnabled('llmError')">{{ formatPct(row.llmErrorRateValue) }}</span>
            <span v-if="isColumnEnabled('policy')">{{ formatPct(row.policyAdjustedRateValue) }}</span>
            <span v-if="isColumnEnabled('rankable')">
              <b :class="['rankable-chip', { off: row.rankable === false, unknown: row.rankable == null }]">
                {{ row.rankableLabel }}
              </b>
            </span>
            <span v-if="isColumnEnabled('games')" class="sample-cell">
              <b>{{ row.sampleSize }} 样本</b>
              <small>有效 {{ row.validGames ?? '--' }} / 异常 {{ row.abnormalGames ?? '--' }}</small>
              <small>配对 {{ row.pairedSampleSize ?? 0 }} / 胜率 {{ formatOptionalPct(row.pairedWinRateValue) }}</small>
            </span>
          </template>

          <template v-else>
            <span class="identity-cell">
              <b>{{ row.version }}</b>
              <small>{{ row.secondary }}</small>
            </span>
            <span>{{ row.source }}</span>
            <span v-if="isColumnEnabled('score')">{{ formatScore(row.scoreValue) }}</span>
            <span v-if="isColumnEnabled('winRate')">{{ formatPct(row.winRateValue) }}</span>
            <span v-if="isColumnEnabled('delta')" :class="['delta-cell', row.displayDeltaValue >= 0 ? 'positive' : 'negative']">
              <b>{{ formatSignedScore(row.displayDeltaValue) }}</b>
              <small>{{ row.displayDeltaSource }}</small>
            </span>
            <span v-if="isColumnEnabled('confidence')" class="ci-cell">
              <b :class="'confidence-chip confidence-chip--' + row.confidenceTone">
                {{ row.confidenceLabel }}
              </b>
              <small>95%置信区间 {{ formatInterval(row.interval) }} / 标准差 {{ formatOptionalNumber(row.standardDeviationValue) }}</small>
              <small v-if="row.warningText">{{ row.warningText }}</small>
            </span>
            <span v-if="isColumnEnabled('rankable')">
              <b :class="['baseline-chip', { on: row.isBaseline }]">
                {{ row.isBaseline ? '基线' : '候选' }}
              </b>
            </span>
            <span v-if="isColumnEnabled('games')" class="sample-cell">
              <b>{{ row.sampleSize }} 样本</b>
              <small>有效 {{ row.validGames ?? '--' }} / 异常 {{ row.abnormalGames ?? '--' }}</small>
              <small>配对 {{ row.pairedSampleSize ?? 0 }} / 胜率 {{ formatOptionalPct(row.pairedWinRateValue) }}</small>
            </span>
          </template>
        </div>
      </div>
    </section>

    <section v-else class="empty-state">
      <strong>{{ emptyTitle }}</strong>
      <span>{{ emptyCaption }}</span>
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
  align-content: start;
  align-self: start;
  gap: 10px;
  width: 100%;
  min-width: 980px;
  padding: 12px;
  border: 1px solid rgba(93, 48, 17, 0.15);
  border-radius: 0;
  overflow: visible;
  background:
    linear-gradient(180deg, rgba(255, 252, 245, 0.22), rgba(255, 239, 194, 0.1)),
    rgba(255, 252, 245, 0.14);
  color: var(--comparison-text);
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
}

.comparison-header,
.metric-summary,
.comparison-controls,
.boundary-mismatch-alert,
.comparison-source-alert,
.comparison-table-card,
.unrankable-panel,
.empty-state {
  border: 1px solid var(--comparison-line);
  border-radius: 0;
  background:
    linear-gradient(180deg, rgba(255, 252, 245, 0.28), rgba(255, 239, 194, 0.12)),
    rgba(255, 252, 245, 0.18);
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
.metric-summary small,
.unrankable-title small {
  color: var(--comparison-muted);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.comparison-header > div:first-child small {
  display: none;
}

.comparison-header h2 {
  margin: 0;
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

.compare-source-chip {
  display: grid;
  gap: 1px;
  min-width: 180px;
  max-width: 280px;
  min-height: 34px;
  padding: 5px 9px;
  border: 1px solid var(--comparison-line);
  border-radius: 0;
  background: rgba(255, 252, 245, 0.32);
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

.metric-summary span {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 10px 12px;
  border-right: 1px solid var(--comparison-line);
}

.metric-summary span:last-child {
  border-right: none;
}

.metric-summary b,
.metric-summary em,
.comparison-row span,
.unrankable-row-main b,
.unrankable-row-main span,
.unrankable-row dd {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  overflow: hidden;
}

.metric-summary b {
  color: var(--comparison-text);
  font-size: 19px;
  font-weight: 900;
  line-height: 1;
}

.metric-summary em {
  color: var(--comparison-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
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
.boundary-mismatch-alert b {
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
  border-radius: 4px;
  background: rgba(255, 252, 245, 0.36);
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
  border-radius: 4px;
  background: rgba(255, 250, 240, 0.36);
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
  border-radius: 0;
  background: rgba(255, 252, 245, 0.46);
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

.unrankable-title {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
}

.unrankable-title span {
  color: var(--comparison-text);
  font-size: 13px;
  font-weight: 900;
}

.comparison-table-card {
  min-width: 0;
  overflow: hidden;
  overflow-x: auto;
  overscroll-behavior-x: contain;
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
  border-radius: 0;
}

.comparison-row:last-child {
  border-bottom: none;
}

.comparison-row:not(.comparison-row--header):hover {
  background: rgba(139, 94, 52, 0.07);
}

.comparison-row--header {
  min-height: 30px;
  color: var(--comparison-muted);
  font-size: 11px;
  font-weight: 900;
  text-transform: uppercase;
}

.comparison-row--baseline {
  background: rgba(255, 245, 221, 0.36);
  box-shadow: inset 3px 0 0 var(--comparison-amber);
}

.comparison-row--unrankable {
  color: var(--comparison-muted);
  background: rgba(255, 252, 245, 0.22);
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
  border-radius: 4px;
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

.ci-cell,
.sample-cell,
.delta-cell {
  display: grid;
  gap: 2px;
  min-width: 0;
  line-height: 1.15;
}

.ci-cell {
  color: var(--comparison-muted) !important;
  font-weight: 850 !important;
}

.ci-cell small,
.sample-cell small,
.delta-cell small {
  min-width: 0;
  overflow: hidden;
  color: var(--comparison-muted);
  font-size: 10px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sample-cell b,
.delta-cell b {
  min-width: 0;
  overflow: hidden;
  color: inherit;
  font-size: 12px;
  font-weight: 950;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  border-radius: 0;
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
  border-radius: 4px;
  background: rgba(255, 252, 245, 0.36);
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
  border-radius: 0;
  background: rgba(255, 250, 240, 0.26);
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
  border-radius: 0;
  background: rgba(255, 250, 240, 0.28);
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
