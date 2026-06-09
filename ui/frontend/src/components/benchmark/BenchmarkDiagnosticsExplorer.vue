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

const summaryRows = computed(() => {
  const summary = diagnosticSummary.value
  const total = numberOrZero(summary.total ?? diagnostics.value.length)
  const byKind = countRows(summary.by_kind)
  const byOrigin = countRows(summary.by_origin)
  const severityRows = countRows(summary.severity || summary.by_severity || summary.by_level)
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

function countRows(source) {
  if (!source || typeof source !== 'object') return []
  return Object.entries(source)
    .map(([name, count]) => ({
      name: String(name || 'unknown'),
      label: String(name || '未知'),
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

function inspectSelectedGames() {
  setProblemGamesFilter()
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
                <small>{{ item.kindLabel }}</small>
                <b>{{ item.message || '无诊断信息' }}</b>
              </span>
              <em>{{ item.levelLabel }}</em>
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
            <b>{{ selectedDiagnostic?.kindLabel || '未选择' }}</b>
          </div>
          <article v-if="selectedDiagnostic" class="selected-diagnostic-card">
            <strong>{{ selectedDiagnostic.message || '无诊断信息' }}</strong>
            <span>{{ selectedDiagnostic.stage || '无阶段' }} / {{ originLabel(selectedDiagnostic.origin) }}</span>
            <em>{{ selectedDiagnostic.levelLabel }}</em>
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
  --diag-bg: #f8f0e0;
  --diag-ink: #3a2a18;
  --diag-muted: #8b6b4a;
  --diag-line: rgba(139, 94, 52, 0.15);
  --diag-panel: rgba(255, 252, 245, 0.7);
  --diag-soft: rgba(255, 252, 245, 0.48);
  --diag-accent: #8b5e34;
  --diag-accent-strong: #5a3319;
  --diag-warning: #8b5e34;
  --diag-error: #5a3319;
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
