<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  benchmark: {
    type: Object,
    required: true
  }
})

const copyState = ref('')
const exportState = ref('')

const selectedRun = computed(() => props.benchmark.selectedBenchmarkBatchRun.value || null)
const selectedBatchId = computed(() => props.benchmark.selectedBenchmarkBatchId.value || '')
const detail = computed(() => props.benchmark.benchmarkBatchDetail.value || null)
const results = computed(() => asArray(detail.value?.resultRows))
const games = computed(() => asArray(props.benchmark.benchmarkBatchGames.value))
const diagnostics = computed(() => asArray(props.benchmark.benchmarkBatchDiagnostics.value))
const recentRuns = computed(() => asArray(props.benchmark.filteredBatchRunRows.value).slice(0, 8))
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
  { label: 'Run ID', value: selectedRunId.value },
  { label: 'Suite', value: suiteLabel.value },
  { label: 'Status', value: statusLabel.value },
  { label: 'Target Type', value: targetTypeLabel.value },
  { label: 'Evaluation Set', value: evaluationSetId.value },
  { label: 'Seed Set', value: seedSetId.value },
  { label: 'Subject', value: subjectLabel.value }
])

const selectedRunId = computed(() =>
  String(detail.value?.batch_id || selectedRun.value?.id || selectedBatchId.value || '')
)
const suiteLabel = computed(() =>
  detail.value?.benchmarkLabel ||
  selectedRun.value?.benchmarkLabel ||
  props.benchmark.selectedBenchmarkSuiteLabel.value ||
  'ad-hoc benchmark'
)
const statusLabel = computed(() =>
  detail.value?.statusLabel ||
  selectedRun.value?.statusLabel ||
  valueOrDash(selectedRun.value?.status)
)
const targetType = computed(() =>
  detail.value?.target_type ||
  selectedRun.value?.benchmarkTargetType ||
  benchmarkMeta.value?.target_type ||
  (isModelSuite.value ? 'model' : 'role_version')
)
const targetTypeLabel = computed(() =>
  detail.value?.targetTypeLabel ||
  selectedRun.value?.benchmarkTargetTypeLabel ||
  (targetType.value === 'model' ? 'Model Benchmark' : 'Role Version')
)
const evaluationSetId = computed(() =>
  benchmarkMeta.value?.evaluation_set_id ||
  detail.value?.evaluation_set_id ||
  selectedRun.value?.evaluationSetId ||
  props.benchmark.selectedBenchmarkEvaluationSetId.value ||
  'ad-hoc'
)
const seedSetId = computed(() =>
  benchmarkMeta.value?.seed_set_id ||
  detail.value?.seed_set_id ||
  selectedConfig.value?.seed_set_id ||
  'ad-hoc'
)
const configHash = computed(() =>
  benchmarkMeta.value?.config_hash ||
  benchmarkMeta.value?.benchmark_config_hash ||
  selectedConfig.value?.benchmark_config_hash ||
  selectedConfig.value?.config_hash ||
  ''
)

const modelId = computed(() =>
  selectedConfig.value?.model_id ||
  selectedResult.value?.model_id ||
  selectedRun.value?.model_id ||
  props.benchmark.form.value?.model_id ||
  ''
)
const modelConfigHash = computed(() =>
  selectedConfig.value?.model_config_hash ||
  selectedResult.value?.model_config_hash ||
  selectedRun.value?.model_config_hash ||
  props.benchmark.form.value?.model_config_hash ||
  ''
)
const targetRole = computed(() =>
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
  selectedResult.value?.target_version_id ||
  selectedConfig.value?.target_version_id ||
  selectedConfig.value?.target_versions?.[targetRole.value] ||
  props.benchmark.form.value?.target_version_id ||
  ''
)
const subjectLabel = computed(() => {
  if (targetType.value === 'model') {
    return compactJoin([modelId.value, modelConfigHash.value], ' / ') || 'current backend model'
  }
  return compactJoin([targetRoleLabel.value, targetVersionId.value || 'baseline version'], ' / ')
})

const gameSummary = computed(() => detail.value?.gameSummary || detail.value?.game_summary || {})
const diagnosticSummary = computed(() =>
  detail.value?.diagnosticSummary ||
  detail.value?.diagnostic_summary ||
  props.benchmark.benchmarkBatchDiagnosticSummary.value ||
  {}
)

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
  numberOrZero(detail.value?.result_count ?? results.value.length)
)
const rankableRows = computed(() => results.value.filter((row) => row?.rankable !== false))
const unrankableRows = computed(() => results.value.filter((row) => row?.rankable === false))
const rankableLabel = computed(() => {
  if (!results.value.length) return 'No result rows'
  if (unrankableRows.value.length) return `${rankableRows.value.length}/${results.value.length} rankable`
  return 'All rankable'
})

const summaryRows = computed(() => [
  { key: 'rankable', label: 'Rankable', value: rankableLabel.value, caption: gateCaption.value },
  { key: 'results', label: 'Results', value: resultCount.value, caption: 'result batches' },
  { key: 'games', label: 'Games', value: gameTotal.value, caption: problemGameCaption.value },
  { key: 'diagnostics', label: 'Diagnostics', value: diagnosticTotal.value, caption: topDiagnosticCaption.value },
  { key: 'leaderboard', label: 'Leaderboard', value: leaderboardRows.value.length, caption: leaderboardScopeLabel.value }
])

const gateRows = computed(() => {
  const rows = results.value.map((result, index) => ({
    key: result?.result_batch_id || result?.batch_id || `result-${index}`,
    title: result?.targetRoleLabel || result?.model_id || result?.result_batch_id || `Result ${index + 1}`,
    status: result?.rankableLabel || (result?.rankable === false ? 'Unrankable' : 'Rankable'),
    reason: result?.rankableReason || result?.rankable_reason || 'No gate reason reported',
    meta: compactJoin([
      result?.targetVersionShort || result?.target_version_id,
      result?.completed == null ? '' : `${result.completed} completed`,
      result?.game_count == null ? '' : `${result.game_count} games`
    ], ' / '),
    blocked: result?.rankable === false
  }))
  for (const kind of detailDiagnosticKindRows.value) {
    rows.push({
      key: `kind-${kind.name}`,
      title: kind.label || kind.name,
      status: `${kind.count} diagnostics`,
      reason: 'Diagnostic kind reported by selected run',
      meta: 'diagnostic kind',
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
  games.value
    .map((game) => ({
      ...game,
      id: String(game?.game_id || game?.id || ''),
      statusWeight: problemStatusWeight(game?.status),
      diagnostics: numberOrZero(game?.diagnostic_count),
      seed: game?.seedLabel || valueOrDash(game?.seed),
      target: game?.targetRoleLabel || valueOrDash(game?.target_role)
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
  const groups = new Map()
  for (const item of diagnostics.value) {
    const key = String(item?.kind || 'diagnostic')
    const level = String(item?.level || 'info').toLowerCase()
    const current = groups.get(key) || {
      key,
      kind: key,
      kindLabel: item?.kindLabel || key,
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

const topTags = computed(() => {
  const tagCounts = new Map()
  for (const tag of asArray(selectedRun.value?.judgeTags)) {
    const label = String(tag?.tag || '').trim()
    if (!label) continue
    tagCounts.set(label, (tagCounts.get(label) || 0) + numberOrZero(tag?.count))
  }
  for (const item of diagnostics.value) {
    const label = String(item?.kindLabel || item?.kind || '').trim()
    if (!label) continue
    tagCounts.set(label, (tagCounts.get(label) || 0) + 1)
  }
  return [...tagCounts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
    .slice(0, 8)
})

const reproducibilityRows = computed(() => [
  { label: 'Suite', value: suiteLabel.value },
  { label: 'Benchmark ID', value: benchmarkMeta.value?.id || selectedRun.value?.benchmarkId || 'ad-hoc' },
  { label: 'Evaluation Set', value: evaluationSetId.value },
  { label: 'Seed Set', value: seedSetId.value },
  { label: 'Config Hash', value: configHash.value || 'not reported' },
  { label: 'Model ID', value: modelId.value || 'not reported' },
  { label: 'Model Config Hash', value: modelConfigHash.value || 'not reported' },
  { label: 'Target Role', value: targetRole.value || targetRoleLabel.value || 'not reported' },
  { label: 'Target Version', value: targetVersionId.value || 'baseline version' }
])

const leaderboardScopeLabel = computed(() =>
  targetType.value === 'model'
    ? `scope=model / ${evaluationSetId.value}`
    : `scope=role_version / ${targetRoleLabel.value}`
)
const gateCaption = computed(() => {
  if (!results.value.length) return 'detail pending'
  if (!unrankableRows.value.length) return 'gate passed'
  return unrankableRows.value[0]?.rankableReason || unrankableRows.value[0]?.rankable_reason || 'gate failed'
})
const problemGameCaption = computed(() => {
  const count = problemGames.value.filter((game) => game.statusWeight > 0 || game.diagnostics > 0).length
  return count ? `${count} problem samples loaded` : 'no loaded problem sample'
})
const topDiagnosticCaption = computed(() =>
  diagnosticGroups.value[0]
    ? `${diagnosticGroups.value[0].kindLabel}: ${diagnosticGroups.value[0].total}`
    : 'none loaded'
)

const markdownReport = computed(() => {
  if (!selectedRun.value) return ''
  const lines = [
    `# Benchmark Run Report: ${selectedRunId.value}`,
    '',
    '## Header',
    ...headerRows.value.map((row) => `- ${row.label}: ${markdownValue(row.value)}`),
    '',
    '## Summary',
    ...summaryRows.value.map((row) => `- ${row.label}: ${markdownValue(row.value)} (${markdownValue(row.caption)})`),
    '',
    '## Gate Summary',
    ...markdownGateRows.value,
    '',
    '## Worst / Problem Games',
    ...markdownGameRows.value,
    '',
    '## Top Diagnostics / Tags',
    ...markdownDiagnosticRows.value,
    '',
    '## Reproducibility Bundle',
    ...reproducibilityRows.value.map((row) => `- ${row.label}: ${markdownValue(row.value)}`)
  ]
  return lines.join('\n')
})

const jsonReport = computed(() =>
  selectedRun.value ? JSON.stringify(reportPayload(), null, 2) : ''
)

const csvReport = computed(() =>
  selectedRun.value
    ? toCsv([
        ['section', 'label', 'value', 'detail'],
        ...headerRows.value.map((row) => ['header', row.label, row.value, '']),
        ...summaryRows.value.map((row) => ['summary', row.label, row.value, row.caption]),
        ...gateRows.value.map((row) => ['gate', row.title, row.status, compactJoin([row.reason, row.meta], ' / ')]),
        ...problemGames.value.map((game) => [
          'game',
          game.id,
          game.statusLabel || game.status || '',
          compactJoin([
            `seed ${game.seed}`,
            game.target,
            `${game.diagnostics} diagnostics`,
            game.history_game_id ? `history ${game.history_game_id}` : '',
            game.replayHash ? `replay ${game.replayHash}` : 'replay unavailable'
          ], ' / ')
        ]),
        ...diagnosticGroups.value.map((group) => [
          'diagnostic',
          group.kindLabel,
          group.total,
          compactJoin([group.levelLabel, `${group.gameCount} games`, `${group.stageCount} stages`], ' / ')
        ]),
        ...topTags.value.map((tag) => ['tag', tag.label, tag.count, '']),
        ...reproducibilityRows.value.map((row) => ['reproducibility', row.label, row.value, ''])
      ])
    : ''
)

const markdownGateRows = computed(() =>
  gateRows.value.length
    ? gateRows.value.map((row) =>
        `- ${markdownValue(row.title)}: ${markdownValue(row.status)} - ${markdownValue(row.reason)}`
      )
    : ['- No gate rows loaded']
)
const markdownGameRows = computed(() =>
  problemGames.value.length
    ? problemGames.value.slice(0, 6).map((game) =>
        `- ${markdownValue(game.id)}: ${markdownValue(game.statusLabel || game.status)} / seed ${markdownValue(game.seed)} / diagnostics ${game.diagnostics} / replay ${markdownValue(game.replayHash || game.replay_unavailable_reason || 'unavailable')}`
      )
    : ['- No loaded game samples']
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
  return ['- No diagnostics loaded']
})

async function copyReport() {
  copyState.value = ''
  if (!markdownReport.value || typeof navigator === 'undefined' || !navigator.clipboard?.writeText) return
  try {
    await navigator.clipboard.writeText(markdownReport.value)
    copyState.value = 'Copied'
    window.setTimeout(() => {
      copyState.value = ''
    }, 1600)
  } catch {
    copyState.value = ''
  }
}

async function copyExport(format) {
  const text = exportText(format)
  copyState.value = ''
  if (!text || typeof navigator === 'undefined' || !navigator.clipboard?.writeText) return
  try {
    await navigator.clipboard.writeText(text)
    copyState.value = `${format.toUpperCase()} copied`
    clearTransientState(copyState)
  } catch {
    copyState.value = ''
  }
}

function downloadReport(format) {
  const text = exportText(format)
  if (!text) return
  const extension = format === 'markdown' ? 'md' : format
  const mime = format === 'json'
    ? 'application/json'
    : (format === 'csv' ? 'text/csv' : 'text/markdown')
  if (downloadText(`${safeFilename(selectedRunId.value || 'benchmark-run-report')}.${extension}`, text, mime)) {
    exportState.value = `${format.toUpperCase()} exported`
    clearTransientState(exportState)
  }
}

function exportText(format) {
  if (format === 'json') return jsonReport.value
  if (format === 'csv') return csvReport.value
  return markdownReport.value
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
      scope: leaderboardScopeLabel.value,
      rows: leaderboardRows.value.slice(0, 20)
    }
  }
}

function selectRun(run) {
  if (!run?.id) return
  props.benchmark.selectBenchmarkBatch(run.id)
}

function isSelectedRecentRun(run) {
  return run?.id && run.id === selectedBatchId.value
}

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function numberOrZero(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

function valueOrDash(value) {
  const text = String(value ?? '').trim()
  return text || '--'
}

function compactJoin(values, separator) {
  return values.map((value) => String(value || '').trim()).filter(Boolean).join(separator)
}

function countRows(source) {
  if (!source || typeof source !== 'object') return []
  return Object.entries(source)
    .map(([name, count]) => ({
      name: String(name || 'unknown'),
      label: String(name || 'unknown'),
      count: numberOrZero(count)
    }))
    .filter((row) => row.count > 0)
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
}

function topMapEntry(map) {
  const [entry] = [...map.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  return entry ? `${entry[0]}: ${entry[1]}` : 'no level'
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

function markdownValue(value) {
  return String(value ?? '--').replace(/\n/g, ' ').replace(/\|/g, '\\|')
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
  <section class="benchmark-report-panel" aria-label="Benchmark run report">
    <template v-if="selectedRun">
      <header class="report-header">
        <div class="report-title">
          <small>Run Report</small>
          <h2>{{ selectedRunId }}</h2>
          <p>{{ suiteLabel }} / {{ targetTypeLabel }}</p>
        </div>
        <div class="report-status">
          <span>{{ statusLabel }}</span>
          <em>{{ leaderboardScopeLabel }}</em>
        </div>
      </header>

      <section class="report-header-grid" aria-label="Report header">
        <article v-for="row in headerRows" :key="row.label" class="report-kv">
          <small>{{ row.label }}</small>
          <b>{{ row.value }}</b>
        </article>
      </section>

      <section class="report-summary-grid" aria-label="Report summary">
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
                <small>Gate Summary</small>
                <b>Rankability and diagnostic gates</b>
              </span>
              <em>{{ gateRows.length }} rows</em>
            </div>
            <div v-if="gateRows.length" class="gate-list">
              <article
                v-for="row in gateRows"
                :key="row.key"
                :class="['gate-row', { blocked: row.blocked }]"
              >
                <span>
                  <small>{{ row.meta || 'gate' }}</small>
                  <b>{{ row.title }}</b>
                  <em>{{ row.reason }}</em>
                </span>
                <strong>{{ row.status }}</strong>
              </article>
            </div>
            <p v-else class="report-empty-inline">No gate rows loaded for the selected run.</p>
          </section>

          <section class="report-section">
            <div class="report-section-heading">
              <span>
                <small>Worst / Problem Games</small>
                <b>Loaded samples</b>
              </span>
              <em>{{ problemGames.length }} games</em>
            </div>
            <div v-if="problemGames.length" class="game-table">
              <div class="game-row game-row-header">
                <span>Game</span>
                <span>Status</span>
                <span>Seed</span>
                <span>Target</span>
                <span>Diagnostics</span>
                <span>Replay</span>
              </div>
              <div v-for="game in problemGames" :key="game.id" class="game-row">
                <span class="mono">{{ game.id }}</span>
                <span>{{ game.statusLabel || game.status || '--' }}</span>
                <span>{{ game.seed }}</span>
                <span>{{ game.target }}</span>
                <span>{{ game.diagnostics }}</span>
                <span>
                  <a v-if="game.replayHash" class="report-replay-link" :href="game.replayHash">
                    Open
                  </a>
                  <small v-else>{{ game.replay_unavailable_reason || 'No replay' }}</small>
                </span>
              </div>
            </div>
            <p v-else class="report-empty-inline">No loaded game samples. Select a completed run detail or switch games filter to problem/all.</p>
          </section>

          <section class="report-section">
            <div class="report-section-heading">
              <span>
                <small>Top Diagnostics / Tags</small>
                <b>Failure signal rollup</b>
              </span>
              <em>{{ diagnosticGroups.length || topTags.length }} groups</em>
            </div>
            <div v-if="diagnosticGroups.length" class="diagnostic-rollup">
              <article v-for="group in diagnosticGroups" :key="group.key" class="diagnostic-rollup-row">
                <span>
                  <b>{{ group.kindLabel }}</b>
                  <small>{{ group.levelLabel }} / {{ group.gameCount }} games / {{ group.stageCount }} stages</small>
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
            <p v-else class="report-empty-inline">No diagnostics or judge tags loaded.</p>
          </section>
        </main>

        <aside class="report-side">
          <section class="report-section report-bundle">
            <div class="report-section-heading">
              <span>
                <small>Reproducibility Bundle</small>
                <b>Audit boundary</b>
              </span>
            </div>
            <dl>
              <div v-for="row in reproducibilityRows" :key="row.label">
                <dt>{{ row.label }}</dt>
                <dd>{{ row.value }}</dd>
              </div>
            </dl>
          </section>

          <section class="report-section report-export">
            <div class="report-section-heading export-heading">
              <span>
                <small>Export Preview</small>
                <b>Markdown / JSON / CSV</b>
              </span>
              <div class="export-actions">
                <button type="button" class="copy-button" @click="copyReport">
                  {{ copyState || 'Copy MD' }}
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
            <div class="copy-row">
              <button type="button" @click="copyExport('json')">Copy JSON</button>
              <button type="button" @click="copyExport('csv')">Copy CSV</button>
              <em>{{ exportState }}</em>
            </div>
            <textarea :value="markdownReport" readonly spellcheck="false" />
          </section>
        </aside>
      </div>
    </template>

    <section v-else class="report-empty-state">
      <div>
        <small>Run Report</small>
        <h2>No run selected</h2>
        <p>Select a benchmark run from Runs to generate a reportable summary, gate explanation, problem game list, diagnostics rollup, and reproducibility bundle.</p>
      </div>
      <div v-if="recentRuns.length" class="recent-run-list">
        <button
          v-for="run in recentRuns"
          :key="run.id"
          type="button"
          :class="['recent-run-button', { active: isSelectedRecentRun(run) }]"
          @click="selectRun(run)"
        >
          <span>
            <b>{{ run.benchmarkLabel || run.id }}</b>
            <small>{{ run.displayRole || run.benchmarkTargetTypeLabel || 'benchmark subject' }}</small>
          </span>
          <em>{{ run.statusLabel || run.status || '--' }}</em>
        </button>
      </div>
      <p v-else class="report-empty-inline">No recent benchmark runs are loaded.</p>
    </section>
  </section>
</template>

<style scoped>
.benchmark-report-panel {
  --report-ink: #202826;
  --report-muted: #66736d;
  --report-line: #d4ddd8;
  --report-panel: #ffffff;
  --report-soft: #f4f7f6;
  --report-accent: #1f6f54;
  --report-blue: #235f7e;
  --report-warn: #9a6518;
  --report-danger: #a33b35;
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
    linear-gradient(90deg, rgba(31, 111, 84, 0.1), rgba(255, 255, 255, 0) 48%),
    var(--report-panel);
}

.report-title,
.report-title h2,
.report-title p,
.report-status,
.report-status span,
.report-status em {
  min-width: 0;
}

.report-title small,
.report-kv small,
.report-summary-card small,
.report-section-heading small,
.gate-row small,
.diagnostic-rollup-row small,
.report-bundle dt,
.recent-run-button small {
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
  border: 1px solid #bdd2c8;
  border-radius: 999px;
  background: #eef7f3;
  color: #1d614b;
  font-size: 12px;
  font-weight: 900;
}

.report-status em,
.report-summary-card em,
.report-section-heading em,
.gate-row em,
.tag-pill em,
.recent-run-button em {
  color: var(--report-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
}

.report-header-grid {
  display: grid;
  grid-template-columns: 1.2fr 1.15fr 0.8fr 0.95fr 1.05fr 1.05fr 1.25fr;
  gap: 8px;
  min-width: 0;
}

.report-kv,
.report-summary-card,
.report-section,
.report-empty-state {
  border: 1px solid var(--report-line);
  border-radius: 8px;
  background: var(--report-panel);
}

.report-kv {
  display: grid;
  gap: 4px;
  min-width: 0;
  min-height: 58px;
  padding: 9px 10px;
}

.report-kv b {
  min-width: 0;
  overflow: hidden;
  color: var(--report-ink);
  font-size: 12px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  border-left: 4px solid var(--report-blue);
}

.report-summary-card.summary-rankable {
  border-left-color: var(--report-accent);
}

.report-summary-card.summary-diagnostics {
  border-left-color: var(--report-warn);
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
.recent-run-list {
  display: grid;
  gap: 6px;
}

.gate-row,
.diagnostic-rollup-row,
.recent-run-button {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid #d8e0dc;
  border-radius: 7px;
  background: var(--report-soft);
}

.gate-row.blocked {
  border-color: #e2c5c2;
  background: #fff7f6;
}

.gate-row span,
.diagnostic-rollup-row span,
.recent-run-button span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.gate-row b,
.diagnostic-rollup-row b,
.recent-run-button b {
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
  border: 1px solid #d8e0dc;
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
  border-top: 1px solid #e2e8e5;
  background: #ffffff;
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
  background: rgba(31, 111, 84, 0.08);
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
  border: 1px solid #d8e0dc;
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

.report-bundle dl {
  display: grid;
  gap: 6px;
  margin: 0;
}

.report-bundle div {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  gap: 10px;
  align-items: baseline;
  min-width: 0;
  padding: 7px 0;
  border-top: 1px solid #e1e7e4;
}

.report-bundle div:first-child {
  border-top: 0;
}

.report-bundle dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--report-ink);
  font-size: 12px;
  font-weight: 850;
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
  color: #ffffff;
}

.ghost-button,
.copy-row button {
  background: #ffffff;
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

.report-export textarea {
  display: block;
  width: 100%;
  min-height: 320px;
  resize: vertical;
  box-sizing: border-box;
  padding: 10px;
  border: 1px solid #d8e0dc;
  border-radius: 7px;
  background: #fbfcfc;
  color: var(--report-ink);
  font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.55;
}

.report-empty-state {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(360px, 0.85fr);
  gap: 16px;
  min-width: 0;
  padding: 18px;
  background:
    linear-gradient(90deg, rgba(35, 95, 126, 0.08), rgba(255, 255, 255, 0) 50%),
    var(--report-panel);
}

.report-empty-state h2 {
  margin: 3px 0 0;
  color: var(--report-ink);
  font-size: 20px;
  font-weight: 950;
}

.report-empty-state p,
.report-empty-inline {
  margin: 6px 0 0;
  color: var(--report-muted);
  font-size: 12px;
  font-weight: 750;
  line-height: 1.45;
}

.recent-run-button {
  width: 100%;
  border-color: #d8e0dc;
  text-align: left;
  cursor: pointer;
}

.recent-run-button.active {
  border-color: var(--report-accent);
  background: #eef7f3;
}
</style>
