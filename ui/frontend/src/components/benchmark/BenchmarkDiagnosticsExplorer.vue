<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  benchmark: {
    type: Object,
    required: true
  }
})

const activeGroupKey = ref('all')
const activeDiagnosticId = ref('')

const diagnosticKindLabels = {
  diagnostic: '诊断',
  rankable: '入榜门禁',
  rankable_failed: '入榜失败',
  rankable_gate: '入榜门禁',
  gate: '门禁',
  game: '对局',
  game_failure: '对局失败',
  timeout: '超时',
  runtime: '运行时',
  fallback: '回退',
  llm_error: 'LLM 错误',
  judge: 'Judge',
  judge_decision: 'Judge 判定',
  leaderboard: '排行榜',
  snapshot: '快照',
  policy_adjusted: '策略修正'
}

const diagnosticLevelLabels = {
  info: '信息',
  low: '低',
  warning: '警告',
  warn: '警告',
  medium: '中',
  high: '高',
  error: '错误',
  critical: '严重',
  fatal: '严重'
}

const selectedBatchId = computed(() => props.benchmark.selectedBenchmarkBatchId.value || '')
const useAggregateDiagnostics = computed(() => !selectedBatchId.value)
const diagnostics = computed(() =>
  useAggregateDiagnostics.value && Array.isArray(props.benchmark.benchmarkDiagnosticAggregateDiagnostics?.value)
    ? props.benchmark.benchmarkDiagnosticAggregateDiagnostics.value
    : (Array.isArray(props.benchmark.benchmarkBatchDiagnostics.value)
      ? props.benchmark.benchmarkBatchDiagnostics.value
      : [])
)
const diagnosticSummary = computed(() =>
  useAggregateDiagnostics.value
    ? (props.benchmark.benchmarkDiagnosticAggregateSummary?.value || {})
    : (props.benchmark.benchmarkBatchDiagnosticSummary.value || {})
)
const runs = computed(() =>
  useAggregateDiagnostics.value && Array.isArray(props.benchmark.benchmarkDiagnosticAggregateRuns?.value)
    ? props.benchmark.benchmarkDiagnosticAggregateRuns.value
    : (Array.isArray(props.benchmark.filteredBatchRunRows.value)
      ? props.benchmark.filteredBatchRunRows.value
      : [])
)
const games = computed(() =>
  useAggregateDiagnostics.value && Array.isArray(props.benchmark.benchmarkDiagnosticAggregateGames?.value)
    ? props.benchmark.benchmarkDiagnosticAggregateGames.value
    : (Array.isArray(props.benchmark.benchmarkBatchGames.value)
      ? props.benchmark.benchmarkBatchGames.value
      : [])
)
const selectedRun = computed(() => props.benchmark.selectedBenchmarkBatchRun.value || null)
const aggregateError = computed(() => props.benchmark.benchmarkDiagnosticAggregateError?.value || '')
const aggregateLoading = computed(() => Boolean(props.benchmark.benchmarkDiagnosticAggregateLoading?.value))
const diagnosticScopeLabel = computed(() =>
  `${props.benchmark.selectedBenchmarkSuiteLabel.value} / 汇总`
)
const emptyStateMessage = computed(() =>
  aggregateError.value ||
  (useAggregateDiagnostics.value
    ? '当前套件边界暂无诊断。启动或选择运行后可查看更多证据。'
    : '请选择带诊断的评测运行，查看类型、严重度、来源、问题对局和受影响运行。')
)
const emptyStateTitle = computed(() =>
  aggregateLoading.value ? '正在加载诊断' : '暂无诊断'
)
const hasDiagnosticFilters = computed(() => Boolean(
  props.benchmark.benchmarkDiagnosticKindFilter?.value ||
  props.benchmark.benchmarkDiagnosticLevelFilter?.value ||
  props.benchmark.benchmarkDiagnosticStatusFilter?.value ||
  props.benchmark.benchmarkDiagnosticStageFilter?.value ||
  props.benchmark.benchmarkDiagnosticSeedFilter?.value
))

const diagnosticKindOptions = [
  { value: '', label: '全部类型' },
  { value: 'rankable_failed', label: '入榜失败' },
  { value: 'leaderboard_gate_failed', label: '门禁失败' },
  { value: 'decision_judge_degraded', label: 'Judge 降级' },
  { value: 'game_failure', label: '失败局' },
  { value: 'game_error', label: '对局错误' },
  { value: 'result_warning', label: '结果警告' },
  { value: 'result_error', label: '结果错误' },
  { value: 'benchmark_error', label: '批次错误' },
  { value: 'llm_error', label: 'LLM 错误' },
  { value: 'fallback', label: '回退' }
]
const diagnosticLevelOptions = [
  { value: '', label: '全部等级' },
  { value: 'error', label: '错误' },
  { value: 'warning', label: '警告' },
  { value: 'info', label: '信息' }
]
const diagnosticStatusOptions = [
  { value: '', label: '全部状态' },
  { value: 'failed', label: '失败' },
  { value: 'timeout', label: '超时' },
  { value: 'abnormal', label: '异常' },
  { value: 'degraded', label: '降级' },
  { value: 'completed', label: '完成' }
]

const summaryRows = computed(() => {
  const summary = diagnosticSummary.value
  const total = numberOrZero(summary.total ?? diagnostics.value.length)
  const byKind = countRows(summary.by_kind, diagnosticKindLabel)
  const byOrigin = countRows(summary.by_origin, originLabel)
  const severityRows = countRows(summary.severity || summary.by_severity || summary.by_level, diagnosticLevelLabel)
  const runsWithDiagnostics = runs.value.filter((run) => runDiagnosticCount(run) > 0).length
  return [
    { key: 'total', label: '总数', value: total, caption: '已加载诊断' },
    { key: 'kind', label: '类型', value: byKind.length, caption: topCaption(byKind) },
    { key: 'origin', label: '来源', value: byOrigin.length, caption: topCaption(byOrigin) },
    { key: 'severity', label: '严重度', value: severityRows.length, caption: topCaption(severityRows) },
    { key: 'runs', label: '运行', value: runsWithDiagnostics, caption: '含诊断' }
  ]
})

const diagnosticGroups = computed(() => {
  const groups = new Map()
  for (const item of diagnostics.value) {
    addGroup(groups, 'kind', item.kind || 'diagnostic', displayDiagnosticKind(item), item)
    addGroup(groups, 'level', item.level || 'info', displayDiagnosticLevel(item), item)
    addGroup(groups, 'origin', item.origin || 'run', originLabel(item.origin), item)
  }
  const rows = [...groups.values()]
    .map((group) => ({
      ...group,
      problemGames: uniqueCount(group.items.map((item) => item.game_id).filter(Boolean)),
      stages: uniqueCount(group.items.map((item) => item.stage).filter(Boolean))
    }))
    .sort((a, b) => b.count - a.count || groupSortWeight(a.type) - groupSortWeight(b.type) || a.label.localeCompare(b.label))
  return [
    {
      key: 'all',
      type: 'all',
      label: '全部诊断',
      count: diagnostics.value.length,
      problemGames: uniqueCount(diagnostics.value.map((item) => item.game_id).filter(Boolean)),
      stages: uniqueCount(diagnostics.value.map((item) => item.stage).filter(Boolean))
    },
    ...rows
  ]
})

const activeGroup = computed(() =>
  diagnosticGroups.value.find((group) => group.key === activeGroupKey.value) || diagnosticGroups.value[0]
)

const visibleDiagnostics = computed(() => {
  const group = activeGroup.value
  if (!group || group.key === 'all') return diagnostics.value
  return diagnostics.value.filter((item) => diagnosticMatchesGroup(item, group))
})

const selectedDiagnostic = computed(() =>
  visibleDiagnostics.value.find((item) => item.id === activeDiagnosticId.value) ||
  visibleDiagnostics.value[0] ||
  null
)

const problemGames = computed(() => {
  const byGame = new Map()
  for (const game of games.value) {
    const id = String(game?.game_id || game?.id || '')
    if (!id) continue
    byGame.set(id, {
      ...game,
      diagnosticMatches: 0,
      diagnosticKinds: new Set()
    })
  }
  for (const item of visibleDiagnostics.value) {
    const id = String(item?.game_id || '')
    if (!id) continue
    const game = byGame.get(id) || {
      game_id: id,
      id,
      history_game_id: item?.history_game_id || id,
      replayHash: diagnosticReplayHash(item),
      statusLabel: '未加载',
      seedLabel: item?.seedLabel || '—',
      targetRoleLabel: item?.targetRoleLabel || '全部角色',
      diagnostic_count: 0,
      diagnosticMatches: 0,
      diagnosticKinds: new Set()
    }
    game.diagnosticMatches += 1
    if (!game.replayHash && diagnosticReplayHash(item)) game.replayHash = diagnosticReplayHash(item)
    if (!game.history_game_id && item?.history_game_id) game.history_game_id = item.history_game_id
    if (item.kindLabel || item.kind) game.diagnosticKinds.add(displayDiagnosticKind(item))
    byGame.set(id, game)
  }
  return [...byGame.values()]
    .filter((game) => game.diagnosticMatches > 0 || Number(game.diagnostic_count || 0) > 0)
    .sort((a, b) => Number(b.diagnosticMatches || b.diagnostic_count || 0) - Number(a.diagnosticMatches || a.diagnostic_count || 0))
    .slice(0, 8)
    .map((game) => ({
      ...game,
      diagnosticKindLabel: [...(game.diagnosticKinds || [])].slice(0, 2).join(' / ')
    }))
})

const selectedDiagnosticGames = computed(() => {
  const diagnostic = selectedDiagnostic.value
  if (!diagnostic) return problemGames.value
  const diagnosticGameId = String(diagnostic.game_id || '')
  const diagnosticSeed = String(diagnostic.seed ?? diagnostic.seedLabel ?? '')
  const diagnosticReplay = diagnosticReplayHash(diagnostic)
  if (!diagnosticGameId) return problemGames.value.slice(0, 4)
  const byGame = new Map()
  for (const game of problemGames.value) {
    if (selectedDiagnosticGameMatches(game, diagnosticGameId, diagnosticSeed, diagnosticReplay)) {
      byGame.set(selectedDiagnosticGameKey(game), game)
    }
  }
  for (const game of games.value) {
    if (selectedDiagnosticGameMatches(game, diagnosticGameId, diagnosticSeed, diagnosticReplay)) {
      byGame.set(selectedDiagnosticGameKey(game), game)
    }
  }
  if (!byGame.size) {
    const fallback = {
      game_id: diagnosticGameId,
      id: diagnosticGameId,
      history_game_id: diagnostic.history_game_id || diagnosticGameId,
      replayHash: diagnosticReplay,
      statusLabel: '未加载',
      seedLabel: diagnostic.seedLabel || '',
      targetRoleLabel: diagnostic.targetRoleLabel || '',
      diagnosticMatches: 1,
      diagnostic_count: 1
    }
    byGame.set(selectedDiagnosticGameKey(fallback), fallback)
  }
  return [...byGame.values()].slice(0, 6)
})

const selectedSuggestedActions = computed(() => suggestedActionsForDiagnostic(selectedDiagnostic.value))

const affectedRuns = computed(() =>
  runs.value
    .map((run) => ({
      ...run,
      diagnosticTotal: runDiagnosticCount(run),
      isSelected: String(run?.id || '') === selectedBatchId.value
    }))
    .filter((run) => run.diagnosticTotal > 0)
    .sort((a, b) => b.diagnosticTotal - a.diagnosticTotal || String(b.created_at || '').localeCompare(String(a.created_at || '')))
    .slice(0, 10)
)

const selectedRunLabel = computed(() => {
  if (useAggregateDiagnostics.value) return diagnosticScopeLabel.value
  if (!selectedRun.value) return '未选择运行'
  return selectedRun.value.benchmarkLabel || selectedRun.value.id || selectedBatchId.value
})

watch(diagnosticGroups, (groups) => {
  if (!groups.some((group) => group.key === activeGroupKey.value)) activeGroupKey.value = 'all'
})

watch(visibleDiagnostics, (items) => {
  if (!items.some((item) => item.id === activeDiagnosticId.value)) {
    activeDiagnosticId.value = items[0]?.id || ''
  }
})

function addGroup(groups, type, value, label, item) {
  const normalized = String(value || 'unknown').trim() || 'unknown'
  const key = `${type}:${normalized}`
  const current = groups.get(key) || {
    key,
    type,
    value: normalized,
    label: String(label || normalized),
    count: 0,
    items: []
  }
  current.count += 1
  current.items.push(item)
  groups.set(key, current)
}

function diagnosticMatchesGroup(item, group) {
  if (group.type === 'kind') return String(item.kind || 'diagnostic') === group.value
  if (group.type === 'level') return String(item.level || 'info') === group.value
  if (group.type === 'origin') return String(item.origin || 'run') === group.value
  return true
}

function countRows(source, labelFor = null) {
  if (!source || typeof source !== 'object') return []
  return Object.entries(source)
    .map(([name, count]) => ({
      name: String(name || 'unknown'),
      label: labelFor ? labelFor(name) : String(name || '未知'),
      count: numberOrZero(count)
    }))
    .filter((row) => row.count > 0)
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
}

function topCaption(rows) {
  if (!rows.length) return '无拆分'
  return `${rows[0].label}: ${rows[0].count}`
}

function numberOrZero(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

function uniqueCount(values) {
  return new Set(values.map((value) => String(value || '')).filter(Boolean)).size
}

function groupSortWeight(type) {
  if (type === 'kind') return 1
  if (type === 'level') return 2
  if (type === 'origin') return 3
  return 9
}

function originLabel(value) {
  const text = String(value || 'run')
  const labels = {
    run: '运行',
    game: '对局',
    judge: 'Judge',
    gate: '门禁',
    runtime: '运行时',
    leaderboard: '排行榜'
  }
  return labels[text] || text
}

function displayDiagnosticKind(item) {
  return item?.kindLabel || diagnosticKindLabel(item?.kind)
}

function displayDiagnosticLevel(item) {
  return item?.levelLabel || diagnosticLevelLabel(item?.level)
}

function diagnosticKindLabel(value) {
  const text = String(value || 'diagnostic').trim()
  if (!text) return '诊断'
  if (/[\u4e00-\u9fff]/.test(text)) return text
  const key = text.toLowerCase()
  return diagnosticKindLabels[key] || readableKeyLabel(text)
}

function diagnosticLevelLabel(value) {
  const text = String(value || 'info').trim()
  if (!text) return '信息'
  if (/[\u4e00-\u9fff]/.test(text)) return text
  const key = text.toLowerCase()
  return diagnosticLevelLabels[key] || readableKeyLabel(text)
}

function readableKeyLabel(value) {
  return String(value || '未知')
    .replace(/_/g, ' ')
    .replace(/\bllm\b/ig, 'LLM')
    .replace(/\bjudge\b/ig, 'Judge')
}

function groupTypeLabel(type) {
  if (type === 'kind') return '类型'
  if (type === 'level') return '等级'
  if (type === 'origin') return '来源'
  return '范围'
}

function runDiagnosticCount(run) {
  const direct = run?.diagnostic_summary?.total ?? run?.diagnostic_count ?? run?.warning_count
  return numberOrZero(direct)
}

function runTitle(run) {
  return run?.benchmarkLabel || run?.id || '评测运行'
}

function runSubtitle(run) {
  const parts = []
  if (run?.displayRole) parts.push(run.displayRole)
  if (run?.evaluationSetId) parts.push(run.evaluationSetId)
  if (run?.statusLabel) parts.push(run.statusLabel)
  return parts.length ? parts.join(' / ') : '无运行元数据'
}

function gameMeta(game) {
  const parts = []
  if (game?.seedLabel) parts.push(`种子 ${game.seedLabel}`)
  if (game?.targetRoleLabel) parts.push(game.targetRoleLabel)
  if (game?.statusLabel) parts.push(game.statusLabel)
  return parts.join(' / ')
}

function selectGroup(group) {
  activeGroupKey.value = group.key
}

function selectDiagnostic(item) {
  activeDiagnosticId.value = item?.id || ''
}

function selectRun(run) {
  if (!run?.id) return
  props.benchmark.selectBenchmarkBatch(run.id)
}

function setProblemGamesFilter() {
  props.benchmark.setBenchmarkGameStatusFilter('problem')
}

function setDiagnosticFilter(name, event) {
  props.benchmark.setBenchmarkDiagnosticFilter(name, event?.target?.value || '')
}

function clearDiagnosticFilters() {
  props.benchmark.clearBenchmarkDiagnosticFilters()
}

function diagnosticReplayHash(item) {
  if (!item) return ''
  if (item.replayHash) return archiveDiagnosticReplayHash(item.replayHash)
  const historyGameId = String(item.history_game_id || item.historyGameId || item.game_id || '')
  return historyGameId ? `#logs?workspace=archive&game_id=${encodeURIComponent(historyGameId)}` : ''
}

function archiveDiagnosticReplayHash(hash) {
  const text = String(hash || '').trim()
  if (!text.startsWith('#logs?')) return text
  const params = new URLSearchParams(text.slice('#logs?'.length))
  if (!params.has('game_id')) return text
  params.set('workspace', 'archive')
  return `#logs?${params.toString()}`
}

function selectedDiagnosticGameKey(game) {
  return [
    String(game?.game_id || game?.id || ''),
    String(game?.seed ?? game?.seedLabel ?? ''),
    diagnosticReplayHash(game)
  ].join(':')
}

function selectedDiagnosticGameMatches(game, diagnosticGameId, diagnosticSeed = '', diagnosticReplay = '') {
  const gameId = String(game?.game_id || game?.id || '')
  if (!diagnosticGameId || gameId !== diagnosticGameId) return false
  const gameSeed = String(game?.seed ?? game?.seedLabel ?? '')
  if (diagnosticSeed && gameSeed && gameSeed !== diagnosticSeed) return false
  const gameReplay = diagnosticReplayHash(game)
  if (diagnosticReplay && gameReplay && gameReplay !== diagnosticReplay) return false
  return true
}

function inspectSelectedGames() {
  const diagnostic = selectedDiagnostic.value
  if (
    diagnostic?.batch_id &&
    diagnostic.batch_id !== props.benchmark.selectedBenchmarkBatchId?.value &&
    typeof props.benchmark.selectBenchmarkBatch === 'function'
  ) {
    props.benchmark.selectBenchmarkBatch(diagnostic.batch_id)
  }
  setProblemGamesFilter()
  const seed = diagnostic?.seed ?? diagnostic?.seedLabel
  if (seed != null && seed !== '' && typeof props.benchmark.setBenchmarkGameSeedFilter === 'function') {
    props.benchmark.setBenchmarkGameSeedFilter(seed)
  }
}

function suggestedActionsForDiagnostic(item) {
  if (!item) {
    return [
      { label: '选择一条诊断', detail: '选择条目后查看具体处置建议。' }
    ]
  }
  const kind = String(item.kind || '').toLowerCase()
  const origin = String(item.origin || '').toLowerCase()
  const message = String(item.message || '').toLowerCase()
  if (kind.includes('rankable') || kind.includes('gate')) {
    return [
      { label: '打开问题对局', detail: '重跑前先检查失败、超时和异常对局。' },
      { label: '检查门禁阈值', detail: '对照套件门禁核对完成率、回退率、错误率和 Judge 降级率。' },
      { label: '按同一套件边界重跑', detail: '保持评测集、种子集和配置 Hash 不变，确保重试可比较。' }
    ]
  }
  if (kind.includes('judge') || origin === 'judge') {
    return [
      { label: '复核 Judge 汇总', detail: '在运行报告中检查坏率、跳过决策和主要错误标签。' },
      { label: '提高 Judge 预算', detail: '发布套件启动前确认 Judge 决策数和超时情况。' },
      { label: '抽样受影响对局', detail: '打开带 Judge 诊断的对局，核查判定证据。' }
    ]
  }
  if (kind.includes('timeout') || kind.includes('game') || message.includes('timeout')) {
    return [
      { label: '检查受影响对局', detail: '使用问题局筛选，比较反复超时的种子。' },
      { label: '检查运行时限制', detail: '在同一阶段查找 max-day、rate-limit、provider 或持久化错误。' },
      { label: '用相同种子重试', detail: '只有套件、种子集和目标对象不变时，重试结果才可比较。' }
    ]
  }
  if (origin === 'runtime' || message.includes('fallback')) {
    return [
      { label: '审计回退率', detail: '回退或运行时降级会让高分结果也变成不可排名。' },
      { label: '检查模型/运行时 Hash', detail: '确认 provider、模型 ID、配置 Hash 和 prompt 版本匹配目标对象。' }
    ]
  }
  return [
    { label: '打开运行报告', detail: '在报告面板导出诊断、门禁、问题对局和可复现包。' },
    { label: '固定比较边界', detail: '不要跨评测集、种子集或 benchmark 配置 Hash 比较行。' }
  ]
}
</script>

<template>
  <section class="benchmark-diagnostics-explorer" aria-label="评测诊断探索器">
    <header class="diagnostics-header">
      <div>
        <small>诊断探索器</small>
        <h2>失败信号图</h2>
        <p>{{ selectedRunLabel }}</p>
      </div>
      <button type="button" class="problem-filter-button" @click="setProblemGamesFilter">
        问题局
      </button>
    </header>

    <div class="diagnostics-filter-row" aria-label="诊断筛选">
      <select
        :value="benchmark.benchmarkDiagnosticKindFilter.value"
        aria-label="诊断类型筛选"
        @change="setDiagnosticFilter('kind', $event)"
      >
        <option v-for="item in diagnosticKindOptions" :key="item.value || 'all-kind'" :value="item.value">
          {{ item.label }}
        </option>
      </select>
      <select
        :value="benchmark.benchmarkDiagnosticLevelFilter.value"
        aria-label="诊断等级筛选"
        @change="setDiagnosticFilter('level', $event)"
      >
        <option v-for="item in diagnosticLevelOptions" :key="item.value || 'all-level'" :value="item.value">
          {{ item.label }}
        </option>
      </select>
      <select
        :value="benchmark.benchmarkDiagnosticStatusFilter.value"
        aria-label="诊断状态筛选"
        @change="setDiagnosticFilter('status', $event)"
      >
        <option v-for="item in diagnosticStatusOptions" :key="item.value || 'all-status'" :value="item.value">
          {{ item.label }}
        </option>
      </select>
      <input
        type="search"
        placeholder="阶段"
        :value="benchmark.benchmarkDiagnosticStageFilter.value"
        aria-label="诊断阶段筛选"
        @change="setDiagnosticFilter('stage', $event)"
        @keydown.enter.prevent="setDiagnosticFilter('stage', $event)"
      >
      <input
        type="search"
        inputmode="numeric"
        placeholder="种子"
        :value="benchmark.benchmarkDiagnosticSeedFilter.value"
        aria-label="诊断种子筛选"
        @change="setDiagnosticFilter('seed', $event)"
        @keydown.enter.prevent="setDiagnosticFilter('seed', $event)"
      >
      <button
        v-if="hasDiagnosticFilters"
        type="button"
        class="diagnostics-filter-clear"
        @click="clearDiagnosticFilters"
      >
        清除
      </button>
    </div>

    <div class="diagnostics-summary-grid">
      <article v-for="row in summaryRows" :key="row.key" class="diagnostics-summary-card">
        <small>{{ row.label }}</small>
        <b>{{ row.value }}</b>
        <em>{{ row.caption }}</em>
      </article>
    </div>

    <div v-if="diagnostics.length" class="diagnostics-workspace">
      <aside class="diagnostics-groups" aria-label="诊断分组">
        <div class="panel-heading">
          <small>分组方式</small>
          <b>类型 / 等级 / 来源</b>
        </div>
        <button
          v-for="group in diagnosticGroups"
          :key="group.key"
          type="button"
          :class="['diagnostic-group-button', { active: group.key === activeGroup.key }]"
          @click="selectGroup(group)"
        >
          <span>
            <small>{{ groupTypeLabel(group.type) }}</small>
            <b>{{ group.label }}</b>
          </span>
          <em>{{ group.count }}</em>
        </button>
      </aside>

      <main class="diagnostics-list-panel">
        <div class="panel-heading diagnostics-list-heading">
          <span>
            <small>诊断</small>
            <b>{{ activeGroup.label }}</b>
          </span>
          <em>{{ visibleDiagnostics.length }} 条</em>
        </div>

        <div class="diagnostics-list">
          <article
            v-for="item in visibleDiagnostics"
            :key="item.id"
            :class="['diagnostic-entry', 'level-' + item.level, { active: item.id === selectedDiagnostic?.id }]"
            role="button"
            tabindex="0"
            @click="selectDiagnostic(item)"
            @keydown.enter.prevent="selectDiagnostic(item)"
            @keydown.space.prevent="selectDiagnostic(item)"
          >
            <header>
              <span>
                <small>{{ displayDiagnosticKind(item) }}</small>
                <b>{{ item.message || '无诊断信息' }}</b>
              </span>
              <em>{{ displayDiagnosticLevel(item) }}</em>
              <a
                v-if="diagnosticReplayHash(item)"
                class="diagnostic-replay-link inline"
                :href="diagnosticReplayHash(item)"
                @click.stop
              >
                回放
              </a>
            </header>
            <dl>
              <div>
                <dt>阶段</dt>
                <dd>{{ item.stage || '—' }}</dd>
              </div>
              <div>
                <dt>来源</dt>
                <dd>{{ originLabel(item.origin) }}</dd>
              </div>
              <div>
                <dt>目标</dt>
                <dd>{{ item.targetRoleLabel || '全部角色' }}</dd>
              </div>
              <div>
                <dt>对局</dt>
                <dd>{{ item.game_id || '—' }}</dd>
              </div>
              <div>
                <dt>种子</dt>
                <dd>{{ item.seedLabel || '—' }}</dd>
              </div>
            </dl>
          </article>
        </div>
      </main>

      <aside class="diagnostics-side-panel">
        <section class="side-section">
          <div class="panel-heading">
            <small>已选诊断</small>
            <b>{{ selectedDiagnostic ? displayDiagnosticKind(selectedDiagnostic) : '未选择' }}</b>
          </div>
          <article v-if="selectedDiagnostic" class="selected-diagnostic-card">
            <strong>{{ selectedDiagnostic.message || '无诊断信息' }}</strong>
            <span>{{ selectedDiagnostic.stage || '无阶段' }} / {{ originLabel(selectedDiagnostic.origin) }}</span>
            <span>对局 {{ selectedDiagnostic.game_id || '—' }} / 种子 {{ selectedDiagnostic.seedLabel || '—' }}</span>
            <em>{{ displayDiagnosticLevel(selectedDiagnostic) }}</em>
            <a
              v-if="diagnosticReplayHash(selectedDiagnostic)"
              class="diagnostic-replay-link"
              :href="diagnosticReplayHash(selectedDiagnostic)"
            >
              回放
            </a>
          </article>
          <div class="suggested-action-list">
            <article v-for="action in selectedSuggestedActions" :key="action.label" class="suggested-action-card">
              <b>{{ action.label }}</b>
              <span>{{ action.detail }}</span>
            </article>
          </div>
          <button type="button" class="inspect-games-button" @click="inspectSelectedGames">
            检查受影响对局
          </button>
        </section>

        <section class="side-section">
          <div class="panel-heading">
            <small>受影响对局</small>
            <b>所选诊断样本</b>
          </div>
          <div v-if="selectedDiagnosticGames.length" class="problem-game-list">
            <article v-for="game in selectedDiagnosticGames" :key="game.game_id || game.id" class="problem-game-card">
              <strong>{{ game.game_id || game.id }}</strong>
              <span>{{ gameMeta(game) }}</span>
              <em>{{ game.diagnosticMatches || game.diagnostic_count || 0 }} 条诊断</em>
              <small v-if="game.diagnosticKindLabel">{{ game.diagnosticKindLabel }}</small>
              <a v-if="game.replayHash" class="diagnostic-replay-link" :href="game.replayHash">
                回放
              </a>
            </article>
          </div>
          <p v-else class="empty-inline">当前分组暂无已加载问题局。</p>
        </section>

        <section class="side-section">
          <div class="panel-heading">
            <small>受影响运行</small>
            <b>点击查看</b>
          </div>
          <div v-if="affectedRuns.length" class="affected-run-list">
            <button
              v-for="run in affectedRuns"
              :key="run.id"
              type="button"
              :class="['affected-run-button', { active: run.isSelected }]"
              @click="selectRun(run)"
            >
              <span>
                <b>{{ runTitle(run) }}</b>
                <small>{{ runSubtitle(run) }}</small>
              </span>
              <em>{{ run.diagnosticTotal }}</em>
            </button>
          </div>
          <p v-else class="empty-inline">暂无运行返回诊断。</p>
        </section>
      </aside>
    </div>

    <div v-else class="diagnostics-empty-state">
      <small>诊断探索器</small>
      <b>{{ emptyStateTitle }}</b>
      <p>{{ emptyStateMessage }}</p>
    </div>
  </section>
</template>

<style scoped>
.benchmark-diagnostics-explorer {
  --diag-bg: var(--bench-bg, var(--logbook-bg, #f2dfae));
  --diag-ink: var(--bench-text, var(--logbook-text, #3a2a18));
  --diag-muted: var(--bench-text-secondary, var(--logbook-muted, #8b6b4a));
  --diag-line: var(--bench-border, var(--logbook-border, rgba(139, 94, 52, 0.15)));
  --diag-panel: var(--bench-surface, var(--logbook-surface, rgba(255, 252, 245, 0.7)));
  --diag-soft: var(--bench-panel-soft, var(--logbook-panel-soft, rgba(255, 252, 245, 0.48)));
  --diag-accent: var(--bench-accent, var(--logbook-accent, #8b5e34));
  --diag-accent-strong: var(--bench-accent-strong, var(--logbook-accent-strong, #5a3319));
  --diag-warning: var(--bench-warning, var(--logbook-warning, #8b5e34));
  --diag-error: var(--bench-danger, var(--logbook-danger, #5a3319));
  display: grid;
  gap: 12px;
  min-width: 0;
  color: var(--diag-ink);
}

.diagnostics-header {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 16px;
  min-width: 0;
  padding: 14px 16px;
  border: 1px solid var(--diag-line);
  border-radius: 8px;
  background:
    linear-gradient(90deg, rgba(139, 94, 52, 0.08), rgba(255, 252, 245, 0) 44%),
    var(--diag-panel);
}

.diagnostics-header div,
.diagnostics-header span,
.diagnostics-header h2,
.diagnostics-header p,
.diagnostics-header small {
  min-width: 0;
}

.diagnostics-header small,
.panel-heading small,
.diagnostics-summary-card small,
.diagnostic-entry small,
.diagnostic-entry dt,
.problem-game-card small {
  color: var(--diag-muted);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.diagnostics-header h2 {
  margin: 2px 0 0;
  overflow: hidden;
  color: var(--diag-ink);
  font-size: 20px;
  font-weight: 900;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diagnostics-header p {
  margin: 4px 0 0;
  overflow: hidden;
  color: var(--diag-muted);
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.problem-filter-button {
  flex: 0 0 auto;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid var(--diag-accent-strong);
  border-radius: 7px;
  background: var(--diag-accent-strong);
  color: #f8f0e0;
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
}

.problem-filter-button:hover {
  background: var(--diag-accent);
}

.diagnostics-filter-row {
  display: grid;
  grid-template-columns: minmax(108px, 1fr) minmax(92px, 0.82fr) minmax(96px, 0.82fr) minmax(90px, 0.9fr) minmax(74px, 0.72fr) auto;
  gap: 8px;
  align-items: center;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--diag-line);
  border-radius: 8px;
  background: var(--diag-panel);
}

.diagnostics-filter-row select,
.diagnostics-filter-row input {
  min-width: 0;
  height: 30px;
  border: 1px solid rgba(139, 94, 52, 0.2);
  border-radius: 6px;
  background: rgba(255, 255, 250, 0.8);
  color: var(--diag-ink);
  font-size: 11px;
  font-weight: 850;
}

.diagnostics-filter-row input {
  padding: 0 8px;
}

.diagnostics-filter-clear {
  height: 30px;
  border: 1px solid var(--diag-accent-strong);
  border-radius: 6px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--diag-accent-strong);
  font-size: 11px;
  font-weight: 900;
  white-space: nowrap;
  cursor: pointer;
}

.diagnostics-filter-clear:hover {
  background: rgba(139, 94, 52, 0.14);
}

.diagnostics-summary-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 8px;
  min-width: 0;
}

.diagnostics-summary-card {
  display: grid;
  gap: 3px;
  min-width: 0;
  min-height: 74px;
  padding: 10px 12px;
  border: 1px solid var(--diag-line);
  border-radius: 8px;
  background: var(--diag-panel);
}

.diagnostics-summary-card b {
  color: var(--diag-ink);
  font-size: 24px;
  font-weight: 950;
  line-height: 1;
}

.diagnostics-summary-card em {
  overflow: hidden;
  color: var(--diag-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 750;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diagnostics-workspace {
  display: grid;
  grid-template-columns: minmax(220px, 0.82fr) minmax(420px, 1.6fr) minmax(260px, 0.95fr);
  gap: 10px;
  min-width: 0;
  align-items: start;
}

.diagnostics-groups,
.diagnostics-list-panel,
.diagnostics-side-panel,
.side-section {
  min-width: 0;
}

.diagnostics-groups,
.diagnostics-list-panel,
.side-section {
  border: 1px solid var(--diag-line);
  border-radius: 8px;
  background: var(--diag-panel);
}

.diagnostics-groups {
  display: grid;
  gap: 6px;
  padding: 10px;
  max-height: 650px;
  overflow: auto;
}

.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
  padding-bottom: 4px;
}

.panel-heading b,
.panel-heading em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-heading b {
  color: var(--diag-ink);
  font-size: 12px;
  font-weight: 900;
}

.panel-heading em {
  color: var(--diag-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
}

.diagnostic-group-button {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: var(--diag-soft);
  color: var(--diag-ink);
  text-align: left;
  cursor: pointer;
}

.diagnostic-group-button:hover {
  border-color: rgba(139, 94, 52, 0.28);
  background: rgba(139, 94, 52, 0.06);
}

.diagnostic-group-button.active {
  border-color: var(--diag-accent);
  background: rgba(139, 94, 52, 0.1);
}

.diagnostic-group-button span,
.diagnostic-group-button b,
.diagnostic-group-button small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diagnostic-group-button b {
  display: block;
  color: var(--diag-ink);
  font-size: 12px;
  font-weight: 900;
}

.diagnostic-group-button em {
  min-width: 26px;
  padding: 3px 6px;
  border-radius: 999px;
  background: var(--diag-panel);
  color: var(--diag-accent);
  font-size: 11px;
  font-style: normal;
  font-weight: 900;
  text-align: center;
}

.diagnostics-list-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  padding: 10px;
  max-height: 650px;
  overflow: hidden;
}

.diagnostics-list-heading {
  padding-bottom: 8px;
  border-bottom: 1px solid var(--diag-line);
}

.diagnostics-list {
  display: grid;
  gap: 8px;
  min-height: 0;
  padding-top: 10px;
  overflow: auto;
}

.diagnostic-entry {
  display: grid;
  gap: 9px;
  min-width: 0;
  padding: 11px 12px;
  border: 1px solid var(--diag-line);
  border-left: 4px solid rgba(139, 94, 52, 0.36);
  border-radius: 8px;
  background: var(--diag-panel);
  cursor: pointer;
}

.diagnostic-entry:hover,
.diagnostic-entry.active {
  border-color: var(--diag-accent);
  box-shadow: inset 3px 0 0 var(--diag-accent);
}

.diagnostic-entry.level-warning {
  border-left-color: var(--diag-warning);
  background: rgba(255, 252, 245, 0.78);
}

.diagnostic-entry.level-error,
.diagnostic-entry.level-critical {
  border-left-color: var(--diag-error);
  background: rgba(139, 94, 52, 0.08);
}

.diagnostic-entry header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 10px;
  align-items: start;
  min-width: 0;
}

.diagnostic-entry header span,
.diagnostic-entry header b {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.diagnostic-entry header b {
  display: block;
  margin-top: 2px;
  color: var(--diag-ink);
  font-size: 13px;
  font-weight: 900;
  line-height: 1.35;
}

.diagnostic-entry header em {
  padding: 3px 7px;
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--diag-ink);
  font-size: 10px;
  font-style: normal;
  font-weight: 900;
}

.diagnostic-entry dl {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 7px;
  margin: 0;
}

.diagnostic-entry div {
  display: grid;
  gap: 2px;
  min-width: 0;
  padding: 6px 7px;
  border-radius: 6px;
  background: rgba(255, 252, 245, 0.7);
}

.diagnostic-entry dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--diag-ink);
  font-size: 11px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diagnostics-side-panel {
  display: grid;
  gap: 10px;
}

.side-section {
  display: grid;
  gap: 8px;
  padding: 10px;
}

.selected-diagnostic-card,
.suggested-action-card {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid var(--diag-line);
  border-radius: 7px;
  background: var(--diag-soft);
}

.selected-diagnostic-card strong,
.selected-diagnostic-card span,
.selected-diagnostic-card em,
.selected-diagnostic-card a,
.suggested-action-card b,
.suggested-action-card span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.selected-diagnostic-card strong,
.suggested-action-card b {
  color: var(--diag-ink);
  font-size: 12px;
  font-weight: 900;
}

.selected-diagnostic-card span,
.selected-diagnostic-card em,
.suggested-action-card span {
  color: var(--diag-muted);
  font-size: 11px;
  line-height: 1.35;
}

.selected-diagnostic-card em {
  font-style: normal;
  font-weight: 900;
}

.suggested-action-list {
  display: grid;
  gap: 6px;
}

.inspect-games-button {
  min-height: 32px;
  border: 1px solid var(--diag-accent-strong);
  border-radius: 7px;
  background: var(--diag-accent-strong);
  color: #f8f0e0;
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
}

.problem-game-list,
.affected-run-list {
  display: grid;
  gap: 7px;
  min-width: 0;
}

.problem-game-card,
.affected-run-button {
  min-width: 0;
  border: 1px solid var(--diag-line);
  border-radius: 7px;
  background: var(--diag-soft);
}

.problem-game-card {
  display: grid;
  gap: 3px;
  padding: 9px 10px;
}

.problem-game-card strong,
.problem-game-card span,
.problem-game-card em,
.problem-game-card small,
.problem-game-card a {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.problem-game-card strong {
  color: var(--diag-ink);
  font-size: 12px;
  font-weight: 900;
}

.problem-game-card span,
.problem-game-card em {
  color: var(--diag-muted);
  font-size: 11px;
}

.problem-game-card em {
  font-style: normal;
  font-weight: 900;
}

.diagnostic-replay-link {
  justify-self: start;
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 8px;
  border: 1px solid var(--diag-accent);
  border-radius: 6px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--diag-accent);
  font-size: 11px;
  font-weight: 900;
  text-decoration: none;
}

.diagnostic-replay-link.inline {
  justify-self: end;
  min-height: 22px;
  padding: 0 7px;
  color: var(--diag-accent-strong);
}

.affected-run-button {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 9px 10px;
  color: var(--diag-ink);
  text-align: left;
  cursor: pointer;
}

.affected-run-button:hover {
  border-color: rgba(139, 94, 52, 0.28);
  background: rgba(139, 94, 52, 0.06);
}

.affected-run-button.active {
  border-color: var(--diag-accent);
  background: rgba(139, 94, 52, 0.1);
}

.affected-run-button span,
.affected-run-button b,
.affected-run-button small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.affected-run-button b {
  display: block;
  color: var(--diag-ink);
  font-size: 12px;
  font-weight: 900;
}

.affected-run-button small {
  display: block;
  margin-top: 2px;
  color: var(--diag-muted);
  font-size: 11px;
  font-weight: 750;
}

.affected-run-button em {
  min-width: 28px;
  padding: 4px 7px;
  border-radius: 999px;
  background: var(--diag-panel);
  color: var(--diag-accent);
  font-size: 11px;
  font-style: normal;
  font-weight: 900;
  text-align: center;
}

.empty-inline,
.diagnostics-empty-state p {
  margin: 0;
  color: var(--diag-muted);
  font-size: 12px;
  font-weight: 700;
  line-height: 1.45;
}

.diagnostics-empty-state {
  display: grid;
  gap: 6px;
  min-height: 210px;
  place-content: center;
  padding: 28px;
  border: 1px dashed rgba(139, 94, 52, 0.28);
  border-radius: 8px;
  background: var(--diag-soft);
  text-align: center;
}

.diagnostics-empty-state small {
  color: var(--diag-muted);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.diagnostics-empty-state b {
  color: var(--diag-ink);
  font-size: 18px;
  font-weight: 900;
}
</style>
