<script setup>
import { computed, ref, watch } from 'vue'

const MIN_CONFIDENT_GAMES = 30
const STORAGE_PREFIX = 'benchmark-comparison-view'

const props = defineProps({
  benchmark: {
    type: Object,
    required: true
  }
})

const selectedMetricColumns = ref([])
const rankFilter = ref('all')
const savedViewName = ref('Default view')
const savedViewState = ref('')
const selectedRowKey = ref('')
let viewLoadSequence = 0

const mode = computed(() =>
  props.benchmark.selectedBenchmarkIsModelSuite.value ? 'model' : 'role_version'
)

const rawRows = computed(() =>
  mode.value === 'model'
    ? props.benchmark.modelLeaderboardRows.value
    : props.benchmark.roleLeaderboardRows.value
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
  const rankableLabel = mode.value === 'model' ? 'Rankable' : 'Baseline'
  return [
    { key: 'score', label: 'Score', width: '70px' },
    { key: 'winRate', label: 'Win Rate', width: '76px' },
    { key: 'delta', label: 'Delta', width: '70px' },
    { key: 'confidence', label: mode.value === 'model' ? '95% CI' : 'Confidence', width: confidenceWidth },
    { key: 'rankable', label: rankableLabel, width: '96px' },
    { key: 'games', label: 'Games', width: '70px' }
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
  const suite = props.benchmark.selectedBenchmarkId.value || 'ad-hoc'
  const evaluationSet = props.benchmark.selectedBenchmarkEvaluationSetId.value || 'no-eval-set'
  const subject = mode.value === 'model' ? 'model' : (props.benchmark.selectedRole.value || 'role')
  return `${STORAGE_PREFIX}:${mode.value}:${suite}:${evaluationSet}:${subject}`
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

const tableViewSummary = computed(() =>
  `${rankFilter.value} / ${enabledMetricColumnDefs.value.map((column) => column.label).join(', ')}`
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
      label: 'Ranked',
      value: ranked.length.toLocaleString('zh-CN'),
      caption: `${unrankableRows.value.length} unrankable`
    },
    {
      label: 'Best Score',
      value: topRow.value ? formatPct(topRow.value.scoreValue) : '--',
      caption: topRow.value ? topRow.value.primary : 'no ranked row'
    },
    {
      label: 'Average Win',
      value: winRates.length ? formatPct(average(winRates)) : '--',
      caption: 'rankable rows'
    },
    {
      label: 'Confidence',
      value: lowSampleCount ? `${lowSampleCount} low n` : 'CI ok',
      caption: topDelta == null ? 'baseline pending' : `${formatSignedPct(topDelta)} top score delta`
    }
  ]
})

const boundaryRows = computed(() => {
  if (mode.value === 'model') {
    return [
      { label: 'Scope', value: 'model' },
      { label: 'Suite', value: props.benchmark.selectedBenchmarkSuiteLabel.value || '--' },
      { label: 'Evaluation Set', value: props.benchmark.selectedBenchmarkEvaluationSetId.value || '--' },
      { label: 'Ranking Unit', value: 'model_id / model_config_hash' }
    ]
  }
  return [
    { label: 'Scope', value: 'role_version' },
    { label: 'Target Role', value: props.benchmark.selectedRoleLabel.value || '--' },
    { label: 'Suite', value: props.benchmark.selectedBenchmarkSuiteLabel.value || '--' },
    { label: 'Evaluation Set', value: props.benchmark.selectedBenchmarkEvaluationSetId.value || '--' }
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
  mode.value === 'model' ? 'No model benchmark rows' : 'No role-version benchmark rows'
)

const emptyCaption = computed(() =>
  mode.value === 'model'
    ? 'Run a model benchmark suite to populate scope=model leaderboard entries.'
    : 'Select a role and run a role-version benchmark suite to populate this comparison.'
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
    deltaValue: hasDelta ? delta : 0,
    hasDelta,
    rankable,
    rankableLabel: rankable == null ? '--' : (rankable ? 'Rankable' : 'Unrankable'),
    rankableReason: String(row?.rankable_reason || row?.reason || row?.gate_reason || '').trim(),
    isBaseline: Boolean(
      row?.is_baseline ||
      row?.isBaseline ||
      String(row?.source || '').toLowerCase() === 'baseline' ||
      String(row?.recommendation || '').toLowerCase() === 'baseline'
    ),
    games: numberFrom(row?.games, row?.game_count, row?.games_played, row?.total_games, row?.completed) || 0
  }
}

function defaultMetricColumns(currentMode) {
  const keys = currentMode === 'model'
    ? ['score', 'winRate', 'delta', 'confidence', 'rankable', 'games']
    : ['score', 'winRate', 'delta', 'confidence', 'rankable', 'games']
  return metricColumnDefs.value.filter((column) => keys.includes(column.key))
}

function isColumnEnabled(key) {
  return enabledMetricColumnKeys.value.has(key)
}

async function saveView() {
  const payload = {
    name: savedViewName.value || 'Default view',
    mode: mode.value,
    rank_filter: rankFilter.value,
    columns: enabledMetricColumnDefs.value.map((column) => column.key),
    saved_at: new Date().toISOString()
  }
  writeLocalView(payload)
  savedViewState.value = 'Saved locally'
  try {
    if (typeof props.benchmark.saveBenchmarkView === 'function') {
      await props.benchmark.saveBenchmarkView(serverViewPayload(payload))
      savedViewState.value = 'Saved'
    }
  } catch {
    savedViewState.value = 'Saved locally'
  }
  clearSavedViewState()
}

async function loadSavedView() {
  const sequence = ++viewLoadSequence
  const defaults = defaultMetricColumns(mode.value).map((column) => column.key)
  applySavedViewPayload(readLocalView(), defaults)
  if (typeof props.benchmark.loadBenchmarkView !== 'function') return
  try {
    const serverView = await props.benchmark.loadBenchmarkView(viewStorageKey.value)
    if (sequence !== viewLoadSequence || !serverView) return
    applySavedViewPayload(serverView, defaults)
  } catch {
    // Local fallback already applied.
  }
}

async function resetView() {
  selectedMetricColumns.value = defaultMetricColumns(mode.value).map((column) => column.key)
  rankFilter.value = 'all'
  savedViewName.value = 'Default view'
  const storage = localStorageApi()
  if (storage) storage.removeItem(viewStorageKey.value)
  savedViewState.value = 'Reset'
  if (typeof props.benchmark.deleteBenchmarkView === 'function') {
    await props.benchmark.deleteBenchmarkView(viewStorageKey.value)
  }
  clearSavedViewState()
}

function selectRow(row) {
  selectedRowKey.value = row?.key || ''
}

function localStorageApi() {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    return null
  }
}

function writeLocalView(payload) {
  const storage = localStorageApi()
  if (!storage) return
  try {
    storage.setItem(viewStorageKey.value, JSON.stringify(payload))
  } catch {}
}

function readLocalView() {
  const storage = localStorageApi()
  if (!storage) return null
  try {
    return JSON.parse(storage.getItem(viewStorageKey.value) || 'null')
  } catch {
    return null
  }
}

function serverViewPayload(payload) {
  return {
    view_key: viewStorageKey.value,
    name: payload.name || 'Default view',
    scope: mode.value,
    benchmark_id: props.benchmark.selectedBenchmarkId.value || null,
    evaluation_set_id: props.benchmark.selectedBenchmarkEvaluationSetId.value || null,
    target_role: mode.value === 'model' ? null : (props.benchmark.selectedRole.value || null),
    view_config: {
      mode: payload.mode,
      rank_filter: payload.rank_filter,
      columns: payload.columns
    }
  }
}

function applySavedViewPayload(raw, defaults) {
  const parsed = raw?.view_config && typeof raw.view_config === 'object' ? raw.view_config : raw
  const validKeys = new Set(metricColumnDefs.value.map((column) => column.key))
  const columns = Array.isArray(parsed?.columns)
    ? parsed.columns.filter((key) => validKeys.has(key))
    : []
  selectedMetricColumns.value = columns.length ? columns : defaults
  rankFilter.value = ['all', 'rankable', 'unrankable'].includes(parsed?.rank_filter)
    ? parsed.rank_filter
    : 'all'
  savedViewName.value = String(raw?.name || parsed?.name || 'Default view')
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
  return String(value || `${currentMode}-${index}`)
}

function modelPrimary(row, index) {
  return String(
    row?.model_id ||
    row?.model_config_hash ||
    row?.subject_id ||
    row?.hash ||
    `model-${index + 1}`
  )
}

function modelSecondary(row) {
  const parts = [
    row?.model_config_hash || row?.subject_id || row?.hash,
    row?.provider,
    row?.runtime || row?.runtime_id
  ].map((value) => String(value || '').trim()).filter(Boolean)
  return parts.length ? parts.join(' / ') : 'model benchmark subject'
}

function rolePrimary(row, index) {
  if (row?.is_baseline) return 'Baseline Version'
  return String(row?.short || row?.version_id || row?.target_version_id || `version-${index + 1}`)
}

function roleSecondary(row) {
  return String(row?.version_id || row?.target_version_id || row?.hash || 'role-version subject')
}

function sourceLabel(source) {
  const labels = {
    baseline: 'Baseline',
    evolution: 'Evolution',
    version: 'Version',
    candidate: 'Candidate',
    manual: 'Manual',
    default_baseline: 'Default'
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
  if (isReference) return 'Reference'
  if (!row?.games) return 'No sample'
  if (row.games < MIN_CONFIDENT_GAMES || (baseline && baseline.games < MIN_CONFIDENT_GAMES)) return 'Low sample'
  return likelyDifferent && enoughSamples ? 'Likely different' : 'Inconclusive'
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
  <section class="benchmark-comparison-view" aria-label="Benchmark leaderboard comparison">
    <header class="comparison-header">
      <div>
        <small>Leaderboard Comparison</small>
        <h2 v-if="mode === 'model'">Model Benchmark</h2>
        <h2 v-else>{{ benchmark.selectedRoleLabel.value }} Role-Version Benchmark</h2>
      </div>
      <span :class="['mode-badge', 'mode-badge--' + mode]">
        {{ mode === 'model' ? 'scope=model' : 'target_role boundary' }}
      </span>
    </header>

    <section class="boundary-strip" aria-label="Comparison boundary">
      <span v-for="item in boundaryRows" :key="item.label">
        <small>{{ item.label }}</small>
        <b>{{ item.value }}</b>
      </span>
    </section>

    <section class="metric-summary" aria-label="Metric summary">
      <span v-for="item in summary" :key="item.label">
        <small>{{ item.label }}</small>
        <b>{{ item.value }}</b>
        <em>{{ item.caption }}</em>
      </span>
    </section>

    <section class="comparison-controls" aria-label="Leaderboard view controls">
      <div class="view-filter">
        <small>Rank Filter</small>
        <div class="segmented-control">
          <button type="button" :class="{ active: rankFilter === 'all' }" @click="rankFilter = 'all'">All</button>
          <button type="button" :class="{ active: rankFilter === 'rankable' }" @click="rankFilter = 'rankable'">Rankable</button>
          <button type="button" :class="{ active: rankFilter === 'unrankable' }" @click="rankFilter = 'unrankable'">Unrankable</button>
        </div>
      </div>
      <div class="metric-toggle-panel">
        <small>Metric Columns</small>
        <div class="metric-toggle-list">
          <label v-for="column in metricColumnDefs" :key="column.key">
            <input v-model="selectedMetricColumns" type="checkbox" :value="column.key" />
            <span>{{ column.label }}</span>
          </label>
        </div>
      </div>
      <div class="saved-view-panel">
        <small>Saved View</small>
        <div>
          <input v-model.trim="savedViewName" type="text" autocomplete="off" />
          <button type="button" @click="saveView">Save</button>
          <button type="button" @click="resetView">Reset</button>
        </div>
        <em>{{ savedViewState || tableViewSummary }}</em>
      </div>
    </section>

    <section v-if="boundaryMismatchRows.length" class="boundary-mismatch-alert" aria-label="Boundary mismatch warning">
      <b>Boundary mismatch</b>
      <span>{{ boundaryMismatchRows.length }} rows report a different evaluation set and should not be compared as formal evidence.</span>
    </section>

    <section v-if="confidenceRows.length" class="confidence-panel" aria-label="Statistical confidence">
      <div class="confidence-title">
        <span>Statistical Confidence</span>
        <small>95% CI estimated from win rate and completed games</small>
      </div>
      <div class="confidence-list">
        <div v-for="row in confidenceRows" :key="'confidence-' + row.key" class="confidence-row">
          <span>
            <b>{{ row.primary }}</b>
            <small>{{ row.games }} games / {{ formatInterval(row.interval) }} win CI</small>
          </span>
          <em :class="'confidence-chip confidence-chip--' + row.confidenceTone">
            {{ row.confidenceLabel }}
          </em>
        </div>
      </div>
    </section>

    <section v-if="baselineRow" class="baseline-panel" aria-label="Baseline comparison">
      <div class="baseline-pin">
        <small>{{ baselineRow.isBaseline ? 'Pinned Baseline' : 'Reference Baseline' }}</small>
        <strong>{{ baselineRow.primary }}</strong>
        <span>{{ baselineRow.secondary }}</span>
        <b>{{ formatPct(baselineRow.scoreValue) }} score / {{ formatPct(baselineRow.winRateValue) }} win</b>
      </div>
      <div class="delta-panel">
        <div class="delta-panel-title">
          <span>Relative Delta</span>
          <small>{{ baselineDeltaRows.length ? 'score delta vs pinned baseline' : 'no candidate delta yet' }}</small>
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
        <div v-else class="compact-empty">Need at least two rows for relative comparison.</div>
      </div>
    </section>

    <section v-if="tableRows.length" class="comparison-table-card">
      <div :class="['comparison-table', 'comparison-table--' + mode]">
        <div class="comparison-row comparison-row--header" :style="comparisonGridStyle">
          <template v-if="mode === 'model'">
            <span>Model</span>
            <span>Config Hash</span>
          </template>
          <template v-else>
            <span>Version</span>
            <span>Source</span>
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
                {{ row.isBaseline ? 'Baseline' : 'Candidate' }}
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

    <section v-if="selectedLeaderboardRow" class="row-detail-panel" aria-label="Leaderboard row detail">
      <div class="row-detail-heading">
        <span>
          <small>Row Detail</small>
          <b>{{ selectedLeaderboardRow.primary }}</b>
        </span>
        <em>{{ selectedLeaderboardRow.rankableLabel }}</em>
      </div>
      <dl>
        <div>
          <dt>{{ mode === 'model' ? 'Config Hash' : 'Subject' }}</dt>
          <dd>{{ mode === 'model' ? selectedLeaderboardRow.modelConfigHash : selectedLeaderboardRow.secondary }}</dd>
        </div>
        <div>
          <dt>Score Delta</dt>
          <dd :class="selectedLeaderboardRow.relativeScoreDelta >= 0 ? 'positive' : 'negative'">
            {{ formatSignedPct(selectedLeaderboardRow.relativeScoreDelta) }}
          </dd>
        </div>
        <div>
          <dt>Win CI</dt>
          <dd>{{ formatInterval(selectedLeaderboardRow.interval) }}</dd>
        </div>
        <div>
          <dt>Games</dt>
          <dd>{{ selectedLeaderboardRow.games }}</dd>
        </div>
      </dl>
      <p>
        {{ selectedLeaderboardRow.rankableReason || (selectedLeaderboardRow.rankable === false ? 'Unrankable without a reported reason.' : 'No gate failure reported for this row.') }}
      </p>
    </section>

    <section class="unrankable-panel" aria-label="Unrankable entries">
      <div class="unrankable-title">
        <span>Unrankable</span>
        <small>{{ unrankableRows.length }} rows excluded from formal ranking</small>
      </div>
      <div v-if="unrankableRows.length" class="unrankable-list">
        <div v-for="row in unrankableRows" :key="'unrankable-' + row.key" class="unrankable-row">
          <b>{{ row.primary }}</b>
          <span>{{ row.rankableReason || 'rankable=false without reason' }}</span>
          <em>{{ formatPct(row.scoreValue) }}</em>
        </div>
      </div>
      <div v-else class="compact-empty">No explicit unrankable rows in the current leaderboard payload.</div>
    </section>
  </section>
</template>

<style scoped>
.benchmark-comparison-view {
  --comparison-bg: #f6f8f7;
  --comparison-panel: #ffffff;
  --comparison-panel-soft: #eef2f0;
  --comparison-line: #d8dedb;
  --comparison-line-strong: #aebbb5;
  --comparison-text: #1f2a27;
  --comparison-muted: #66736d;
  --comparison-green: #24704d;
  --comparison-blue: #256b8f;
  --comparison-red: #a13d36;
  --comparison-amber: #8b641f;
  display: grid;
  gap: 10px;
  min-width: 980px;
  padding: 12px;
  border: 1px solid var(--comparison-line);
  border-radius: 8px;
  background: var(--comparison-bg);
  color: var(--comparison-text);
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
}

.comparison-header,
.boundary-strip,
.metric-summary,
.comparison-controls,
.boundary-mismatch-alert,
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

.mode-badge {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border: 1px solid var(--comparison-line-strong);
  border-radius: 6px;
  background: var(--comparison-panel-soft);
  color: #30413b;
  font-size: 12px;
  font-weight: 900;
}

.mode-badge--model {
  border-left: 4px solid var(--comparison-blue);
}

.mode-badge--role_version {
  border-left: 4px solid var(--comparison-green);
}

.boundary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0;
  overflow: hidden;
}

.boundary-strip span,
.metric-summary span {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 10px 12px;
  border-right: 1px solid var(--comparison-line);
}

.boundary-strip span:last-child,
.metric-summary span:last-child {
  border-right: none;
}

.boundary-strip b,
.metric-summary b,
.metric-summary em,
.baseline-pin strong,
.baseline-pin span,
.baseline-pin b,
.comparison-row span,
.unrankable-row b,
.unrankable-row span {
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
  border: 1px solid #cfd8d4;
  border-radius: 6px;
  background: #ffffff;
  color: var(--comparison-text);
  font-size: 11px;
  font-weight: 900;
  cursor: pointer;
}

.segmented-control button.active {
  border-color: var(--comparison-green);
  background: rgba(36, 112, 77, 0.08);
  color: var(--comparison-green);
}

.metric-toggle-list label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 28px;
  padding: 0 8px;
  border: 1px solid #dbe3df;
  border-radius: 6px;
  background: #f9fbfa;
  color: var(--comparison-text);
  font-size: 11px;
  font-weight: 850;
}

.metric-toggle-list input {
  width: 13px;
  height: 13px;
  margin: 0;
  accent-color: var(--comparison-green);
}

.saved-view-panel input {
  width: 132px;
  height: 28px;
  min-width: 0;
  padding: 0 8px;
  border: 1px solid #cfd8d4;
  border-radius: 6px;
  background: #ffffff;
  color: var(--comparison-text);
  font-size: 11px;
  font-weight: 850;
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
  border-color: rgba(161, 61, 54, 0.28);
  background: rgba(161, 61, 54, 0.06);
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
  border: 1px solid #dde5e1;
  border-radius: 6px;
  background: #f9fbfa;
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
  background: #fbfaf5;
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
  background: #e3e8e5;
}

.delta-row i b {
  display: block;
  height: 100%;
  border-radius: inherit;
}

.delta-row i.positive b {
  background: var(--comparison-green);
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
  border-bottom: 1px solid rgba(216, 222, 219, 0.76);
  border-radius: 5px;
}

.comparison-row:last-child {
  border-bottom: none;
}

.comparison-row:not(.comparison-row--header):hover {
  background: #f8faf9;
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
  background: #fbfaf5;
  box-shadow: inset 3px 0 0 var(--comparison-amber);
}

.comparison-row--unrankable {
  color: var(--comparison-muted);
  background: #f7f7f6;
}

.comparison-row--selected {
  outline: 2px solid rgba(36, 112, 77, 0.28);
  background: #eef7f3;
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
  border: 1px solid rgba(36, 112, 77, 0.32);
  border-radius: 5px;
  background: rgba(36, 112, 77, 0.08);
  color: var(--comparison-green);
  font-size: 11px;
  font-weight: 900;
}

.rankable-chip.off {
  border-color: rgba(161, 61, 54, 0.3);
  background: rgba(161, 61, 54, 0.07);
  color: var(--comparison-red);
}

.rankable-chip.unknown,
.baseline-chip {
  border-color: var(--comparison-line);
  background: var(--comparison-panel-soft);
  color: #43524d;
}

.confidence-chip {
  border-color: var(--comparison-line);
  background: var(--comparison-panel-soft);
  color: #43524d;
  white-space: nowrap;
}

.confidence-chip--reference {
  border-color: rgba(139, 100, 31, 0.32);
  background: rgba(139, 100, 31, 0.08);
  color: var(--comparison-amber);
}

.confidence-chip--strong {
  border-color: rgba(36, 112, 77, 0.32);
  background: rgba(36, 112, 77, 0.08);
  color: var(--comparison-green);
}

.confidence-chip--warning {
  border-color: rgba(139, 100, 31, 0.32);
  background: rgba(139, 100, 31, 0.08);
  color: var(--comparison-amber);
}

.confidence-chip--muted {
  border-color: #d6dfda;
  background: #f4f7f6;
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
  border: 1px solid #d6dfda;
  border-radius: 999px;
  background: #f4f7f6;
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
  border: 1px solid #dbe3df;
  border-radius: 7px;
  background: #f9fbfa;
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
  border-color: rgba(139, 100, 31, 0.36);
  background: rgba(139, 100, 31, 0.08);
  color: var(--comparison-amber);
}

.unrankable-panel {
  display: grid;
  gap: 8px;
  padding: 11px 12px;
}

.unrankable-list {
  display: grid;
  gap: 6px;
}

.unrankable-row {
  display: grid;
  grid-template-columns: minmax(160px, 0.8fr) minmax(0, 1fr) 54px;
  gap: 10px;
  align-items: center;
  min-height: 32px;
  padding: 7px 8px;
  border: 1px solid rgba(161, 61, 54, 0.16);
  border-radius: 6px;
  background: rgba(161, 61, 54, 0.04);
}

.unrankable-row b {
  color: var(--comparison-text);
  font-size: 12px;
  font-weight: 900;
}

.unrankable-row span {
  color: var(--comparison-muted);
  font-size: 12px;
  font-weight: 800;
}

.unrankable-row em {
  color: var(--comparison-red);
  font-size: 12px;
  font-style: normal;
  font-weight: 900;
  text-align: right;
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
  background: #fbfcfb;
}

.positive {
  color: var(--comparison-green) !important;
  font-weight: 900 !important;
}

.negative {
  color: var(--comparison-red) !important;
  font-weight: 900 !important;
}
</style>
