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

const diagnostics = computed(() =>
  Array.isArray(props.benchmark.benchmarkBatchDiagnostics.value)
    ? props.benchmark.benchmarkBatchDiagnostics.value
    : []
)
const diagnosticSummary = computed(() => props.benchmark.benchmarkBatchDiagnosticSummary.value || {})
const runs = computed(() =>
  Array.isArray(props.benchmark.filteredBatchRunRows.value)
    ? props.benchmark.filteredBatchRunRows.value
    : []
)
const games = computed(() =>
  Array.isArray(props.benchmark.benchmarkBatchGames.value)
    ? props.benchmark.benchmarkBatchGames.value
    : []
)
const selectedRun = computed(() => props.benchmark.selectedBenchmarkBatchRun.value || null)
const selectedBatchId = computed(() => props.benchmark.selectedBenchmarkBatchId.value || '')

const summaryRows = computed(() => {
  const summary = diagnosticSummary.value
  const total = numberOrZero(summary.total ?? diagnostics.value.length)
  const byKind = countRows(summary.by_kind)
  const byOrigin = countRows(summary.by_origin)
  const severityRows = countRows(summary.severity || summary.by_severity || summary.by_level)
  const runsWithDiagnostics = runs.value.filter((run) => runDiagnosticCount(run) > 0).length
  return [
    { key: 'total', label: 'Total', value: total, caption: 'diagnostics loaded' },
    { key: 'kind', label: 'Kinds', value: byKind.length, caption: topCaption(byKind) },
    { key: 'origin', label: 'Origins', value: byOrigin.length, caption: topCaption(byOrigin) },
    { key: 'severity', label: 'Severity', value: severityRows.length, caption: topCaption(severityRows) },
    { key: 'runs', label: 'Runs', value: runsWithDiagnostics, caption: 'with diagnostics' }
  ]
})

const diagnosticGroups = computed(() => {
  const groups = new Map()
  for (const item of diagnostics.value) {
    addGroup(groups, 'kind', item.kind || 'diagnostic', item.kindLabel || item.kind || 'diagnostic', item)
    addGroup(groups, 'level', item.level || 'info', item.levelLabel || item.level || 'info', item)
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
      label: 'All diagnostics',
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
      statusLabel: '未加载',
      seedLabel: item?.seedLabel || '—',
      targetRoleLabel: item?.targetRoleLabel || '全部角色',
      diagnostic_count: 0,
      diagnosticMatches: 0,
      diagnosticKinds: new Set()
    }
    game.diagnosticMatches += 1
    if (item.kindLabel || item.kind) game.diagnosticKinds.add(item.kindLabel || item.kind)
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
  const ids = new Set()
  if (diagnostic.game_id) ids.add(String(diagnostic.game_id))
  for (const item of visibleDiagnostics.value) {
    if (
      diagnostic.kind &&
      item.kind === diagnostic.kind &&
      item.game_id
    ) {
      ids.add(String(item.game_id))
    }
  }
  if (!ids.size) return problemGames.value.slice(0, 4)
  const byGame = new Map(problemGames.value.map((game) => [String(game.game_id || game.id), game]))
  for (const game of games.value) {
    const id = String(game?.game_id || game?.id || '')
    if (id && ids.has(id) && !byGame.has(id)) byGame.set(id, game)
  }
  for (const id of ids) {
    if (!byGame.has(id)) {
      byGame.set(id, {
        game_id: id,
        id,
        statusLabel: '未加载',
        seedLabel: diagnostic.seedLabel || '',
        targetRoleLabel: diagnostic.targetRoleLabel || '',
        diagnosticMatches: 1,
        diagnostic_count: 1
      })
    }
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
  if (!selectedRun.value) return 'No run selected'
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

function topCaption(rows) {
  if (!rows.length) return 'no breakdown'
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
    run: 'Run',
    game: 'Game',
    judge: 'Judge',
    gate: 'Gate',
    runtime: 'Runtime',
    leaderboard: 'Leaderboard'
  }
  return labels[text] || text
}

function groupTypeLabel(type) {
  if (type === 'kind') return 'Kind'
  if (type === 'level') return 'Level'
  if (type === 'origin') return 'Origin'
  return 'Scope'
}

function runDiagnosticCount(run) {
  const direct = run?.diagnostic_summary?.total ?? run?.diagnostic_count ?? run?.warning_count
  return numberOrZero(direct)
}

function runTitle(run) {
  return run?.benchmarkLabel || run?.id || 'benchmark run'
}

function runSubtitle(run) {
  const parts = []
  if (run?.displayRole) parts.push(run.displayRole)
  if (run?.evaluationSetId) parts.push(run.evaluationSetId)
  if (run?.statusLabel) parts.push(run.statusLabel)
  return parts.length ? parts.join(' / ') : 'no run metadata'
}

function gameMeta(game) {
  const parts = []
  if (game?.seedLabel) parts.push(`seed ${game.seedLabel}`)
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

function inspectSelectedGames() {
  setProblemGamesFilter()
}

function suggestedActionsForDiagnostic(item) {
  if (!item) {
    return [
      { label: 'Select a diagnostic', detail: 'Choose an entry to see concrete next steps.' }
    ]
  }
  const kind = String(item.kind || '').toLowerCase()
  const origin = String(item.origin || '').toLowerCase()
  const message = String(item.message || '').toLowerCase()
  if (kind.includes('rankable') || kind.includes('gate')) {
    return [
      { label: 'Open problem games', detail: 'Inspect failed, timeout, and abnormal games before rerunning.' },
      { label: 'Check gate thresholds', detail: 'Compare completed, fallback, error, and judge degraded rates against the suite gate.' },
      { label: 'Rerun same suite boundary', detail: 'Keep evaluation set, seed set, and config hash unchanged for a comparable retry.' }
    ]
  }
  if (kind.includes('judge') || origin === 'judge') {
    return [
      { label: 'Review judge aggregate', detail: 'Check bad rate, skipped decisions, and top mistake tags in the run report.' },
      { label: 'Increase judge budget', detail: 'For release suites, confirm judge decisions and timeout before launch.' },
      { label: 'Sample affected games', detail: 'Open games with judge diagnostics and inspect decision evidence.' }
    ]
  }
  if (kind.includes('timeout') || kind.includes('game') || message.includes('timeout')) {
    return [
      { label: 'Inspect affected games', detail: 'Use problem-game filter and compare seeds that timeout repeatedly.' },
      { label: 'Check runtime limits', detail: 'Look for max-day, rate-limit, provider, or persistence errors in the same stage.' },
      { label: 'Retry with same seeds', detail: 'Only compare the retry if suite, seed set, and target subject are unchanged.' }
    ]
  }
  if (origin === 'runtime' || message.includes('fallback')) {
    return [
      { label: 'Audit fallback rate', detail: 'Fallback or runtime degradation can make a result unrankable even if score is high.' },
      { label: 'Check model/runtime hash', detail: 'Confirm provider, model id, config hash, and prompt version match the intended subject.' }
    ]
  }
  return [
    { label: 'Open run report', detail: 'Use the report panel to export diagnostics, gates, problem games, and reproducibility bundle.' },
    { label: 'Keep boundary fixed', detail: 'Do not compare rows across different evaluation set, seed set, or benchmark config hash.' }
  ]
}
</script>

<template>
  <section class="benchmark-diagnostics-explorer" aria-label="Benchmark diagnostics explorer">
    <header class="diagnostics-header">
      <div>
        <small>Diagnostics Explorer</small>
        <h2>Failure signal map</h2>
        <p>{{ selectedRunLabel }}</p>
      </div>
      <button type="button" class="problem-filter-button" @click="setProblemGamesFilter">
        Problem games
      </button>
    </header>

    <div class="diagnostics-summary-grid">
      <article v-for="row in summaryRows" :key="row.key" class="diagnostics-summary-card">
        <small>{{ row.label }}</small>
        <b>{{ row.value }}</b>
        <em>{{ row.caption }}</em>
      </article>
    </div>

    <div v-if="diagnostics.length" class="diagnostics-workspace">
      <aside class="diagnostics-groups" aria-label="Diagnostic groups">
        <div class="panel-heading">
          <small>Group by</small>
          <b>Kind / level / origin</b>
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
            <small>Diagnostics</small>
            <b>{{ activeGroup.label }}</b>
          </span>
          <em>{{ visibleDiagnostics.length }} entries</em>
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
                <small>{{ item.kindLabel }}</small>
                <b>{{ item.message || 'No diagnostic message' }}</b>
              </span>
              <em>{{ item.levelLabel }}</em>
            </header>
            <dl>
              <div>
                <dt>Stage</dt>
                <dd>{{ item.stage || '—' }}</dd>
              </div>
              <div>
                <dt>Origin</dt>
                <dd>{{ originLabel(item.origin) }}</dd>
              </div>
              <div>
                <dt>Target</dt>
                <dd>{{ item.targetRoleLabel || '全部角色' }}</dd>
              </div>
              <div>
                <dt>Game</dt>
                <dd>{{ item.game_id || '—' }}</dd>
              </div>
              <div>
                <dt>Seed</dt>
                <dd>{{ item.seedLabel || '—' }}</dd>
              </div>
            </dl>
          </article>
        </div>
      </main>

      <aside class="diagnostics-side-panel">
        <section class="side-section">
          <div class="panel-heading">
            <small>Selected diagnostic</small>
            <b>{{ selectedDiagnostic?.kindLabel || 'No selection' }}</b>
          </div>
          <article v-if="selectedDiagnostic" class="selected-diagnostic-card">
            <strong>{{ selectedDiagnostic.message || 'No diagnostic message' }}</strong>
            <span>{{ selectedDiagnostic.stage || 'no stage' }} / {{ originLabel(selectedDiagnostic.origin) }}</span>
            <em>{{ selectedDiagnostic.levelLabel }}</em>
          </article>
          <div class="suggested-action-list">
            <article v-for="action in selectedSuggestedActions" :key="action.label" class="suggested-action-card">
              <b>{{ action.label }}</b>
              <span>{{ action.detail }}</span>
            </article>
          </div>
          <button type="button" class="inspect-games-button" @click="inspectSelectedGames">
            Inspect affected games
          </button>
        </section>

        <section class="side-section">
          <div class="panel-heading">
            <small>Affected games</small>
            <b>Selected diagnostic sample</b>
          </div>
          <div v-if="selectedDiagnosticGames.length" class="problem-game-list">
            <article v-for="game in selectedDiagnosticGames" :key="game.game_id || game.id" class="problem-game-card">
              <strong>{{ game.game_id || game.id }}</strong>
              <span>{{ gameMeta(game) }}</span>
              <em>{{ game.diagnosticMatches || game.diagnostic_count || 0 }} diagnostics</em>
              <small v-if="game.diagnosticKindLabel">{{ game.diagnosticKindLabel }}</small>
              <a v-if="game.replayHash" class="diagnostic-replay-link" :href="game.replayHash">
                Replay
              </a>
            </article>
          </div>
          <p v-else class="empty-inline">No loaded problem games for this group.</p>
        </section>

        <section class="side-section">
          <div class="panel-heading">
            <small>Affected runs</small>
            <b>Click to inspect</b>
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
          <p v-else class="empty-inline">No run has reported diagnostics.</p>
        </section>
      </aside>
    </div>

    <div v-else class="diagnostics-empty-state">
      <small>Diagnostics Explorer</small>
      <b>No diagnostics loaded</b>
      <p>Select a benchmark run with diagnostics to inspect kind, severity, origin, problem games, and affected runs.</p>
    </div>
  </section>
</template>

<style scoped>
.benchmark-diagnostics-explorer {
  --diag-ink: #1e2825;
  --diag-muted: #65726d;
  --diag-line: #d5ddd9;
  --diag-panel: #ffffff;
  --diag-soft: #f4f7f6;
  --diag-accent: #11684f;
  --diag-warning: #a76816;
  --diag-error: #a53a35;
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
    linear-gradient(90deg, rgba(17, 104, 79, 0.08), rgba(255, 255, 255, 0) 44%),
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
  border: 1px solid #1f6f54;
  border-radius: 7px;
  background: #1f6f54;
  color: #ffffff;
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
}

.problem-filter-button:hover {
  background: #16563f;
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
  border-color: #abc1b9;
  background: #edf3f1;
}

.diagnostic-group-button.active {
  border-color: #1f6f54;
  background: #e7f1ed;
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
  background: #ffffff;
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
  border: 1px solid #dbe3e0;
  border-left: 4px solid #77847f;
  border-radius: 8px;
  background: #ffffff;
  cursor: pointer;
}

.diagnostic-entry:hover,
.diagnostic-entry.active {
  border-color: #1f6f54;
  box-shadow: inset 3px 0 0 #1f6f54;
}

.diagnostic-entry.level-warning {
  border-left-color: var(--diag-warning);
  background: #fffaf0;
}

.diagnostic-entry.level-error,
.diagnostic-entry.level-critical {
  border-left-color: var(--diag-error);
  background: #fff6f5;
}

.diagnostic-entry header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
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
  background: #eef2f0;
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
  background: rgba(244, 247, 246, 0.9);
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
  border: 1px solid #dbe3e0;
  border-radius: 7px;
  background: var(--diag-soft);
}

.selected-diagnostic-card strong,
.selected-diagnostic-card span,
.selected-diagnostic-card em,
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
  border: 1px solid #1f6f54;
  border-radius: 7px;
  background: #1f6f54;
  color: #ffffff;
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
  border: 1px solid #dbe3e0;
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
  border: 1px solid #1f6f54;
  border-radius: 6px;
  background: rgba(31, 111, 84, 0.08);
  color: #1f6f54;
  font-size: 11px;
  font-weight: 900;
  text-decoration: none;
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
  border-color: #abc1b9;
  background: #edf3f1;
}

.affected-run-button.active {
  border-color: #1f6f54;
  background: #e7f1ed;
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
  background: #ffffff;
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
  border: 1px dashed #b9c8c2;
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
