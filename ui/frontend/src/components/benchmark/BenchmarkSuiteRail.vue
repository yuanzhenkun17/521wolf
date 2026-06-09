<script setup>
import { computed } from 'vue'

const props = defineProps({
  benchmark: {
    type: Object,
    required: true
  }
})

const targetTypeLabels = {
  model: '模型',
  role_version: '角色版本'
}

const costTierLabels = {
  smoke: '冒烟',
  low: '低成本',
  medium: '中等',
  standard: '标准',
  release: '发布',
  high: '高成本'
}

const statusLabels = {
  enabled: '启用',
  active: '启用',
  draft: '草稿',
  deprecated: '废弃',
  disabled: '停用',
  archived: '归档'
}

const runStatusLabels = {
  queued: '排队中',
  running: '运行中',
  rate_limited: '限速中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断'
}

const runStageLabels = {
  planning: '规划中',
  queued: '排队中',
  launching: '启动中',
  running: '运行中',
  collecting: '采集中',
  scoring: '计分中',
  aggregating: '汇总中',
  judge_decisions: 'Judge 判定',
  judge_decision: 'Judge 判定',
  runtime: '运行时',
  diagnostics: '诊断中',
  reporting: '生成报告',
  snapshot: '生成快照',
  completed: '已完成',
  failed: '失败'
}

const suites = computed(() =>
  props.benchmark.benchmarkSuites.value.map(normalizeSuite).filter(Boolean)
)

const selectedSuiteId = computed(() => props.benchmark.selectedBenchmarkId.value)
const legacyTargetType = computed(() => props.benchmark.legacyBenchmarkTargetType?.value || 'role_version')
const legacyRows = computed(() => props.benchmark.unscopedBenchmarkRunRows?.value || [])
const legacyScopes = computed(() => [
  {
    targetType: 'role_version',
    label: '临时角色',
    caption: '未绑定套件的角色评测',
    count: legacyRows.value.filter((run) => run.benchmarkTargetType !== 'model').length
  },
  {
    targetType: 'model',
    label: '临时模型',
    caption: '未绑定套件的模型评测',
    count: legacyRows.value.filter((run) => run.benchmarkTargetType === 'model').length
  }
])

const suiteCounts = computed(() => {
  const counts = {
    total: suites.value.length,
    model: 0,
    role_version: 0,
    quick: 0,
    release: 0
  }
  for (const suite of suites.value) {
    if (suite.targetType === 'model') counts.model += 1
    if (suite.targetType === 'role_version') counts.role_version += 1
    if (suite.isQuick) counts.quick += 1
    if (suite.isRelease) counts.release += 1
  }
  return counts
})

const suiteGroups = computed(() => {
  const groups = [
    { key: 'quick', label: '快速 / 冒烟', caption: '低成本验证', rows: [] },
    { key: 'standard', label: '标准', caption: '正式比较', rows: [] },
    { key: 'release', label: '发布', caption: '发布口径', rows: [] },
    { key: 'other', label: '其他', caption: '未归类', rows: [] }
  ]
  const byKey = new Map(groups.map((group) => [group.key, group]))
  for (const suite of suites.value) {
    byKey.get(groupKey(suite)).rows.push(suite)
  }
  return groups.filter((group) => group.rows.length)
})

const selectedSuite = computed(() =>
  suites.value.find((suite) => suite.id === selectedSuiteId.value) || null
)

function normalizeSuite(raw) {
  const id = String(raw?.id || raw?.benchmark_id || '').trim()
  if (!id) return null
  const targetType = normalizeTargetType(raw?.target_type || raw?.scope)
  const costTier = String(raw?.cost_tier || '').trim().toLowerCase()
  const status = normalizeStatus(raw)
  const gameCount = numberOrNull(raw?.game_count ?? raw?.battle_games ?? raw?.games)
  const seedCount = numberOrNull(raw?.seed_count)
  const version = raw?.version == null || raw.version === '' ? '' : `v${raw.version}`
  return {
    raw,
    id,
    label: String(raw?.label || raw?.name || id),
    version,
    description: String(raw?.description || ''),
    targetType,
    targetTypeLabel: targetTypeLabels[targetType] || targetType,
    costTier,
    costTierLabel: costTierLabels[costTier] || (costTier ? titleCase(costTier) : '未标记'),
    status,
    statusLabel: statusLabels[status] || titleCase(status),
    evaluationSetId: String(raw?.evaluation_set_id || ''),
    seedSetId: String(raw?.seed_set_id || ''),
    gameCount,
    seedCount,
    roles: Array.isArray(raw?.roles) ? raw.roles : [],
    lastRun: normalizeLastRun(raw?.last_run),
    latestSnapshot: normalizeLatestSnapshot(raw?.latest_snapshot),
    isQuick: isQuickSuite(raw, costTier),
    isRelease: isReleaseSuite(raw, costTier),
    enabled: !['deprecated', 'disabled', 'archived'].includes(status)
  }
}

function normalizeTargetType(value) {
  const text = String(value || '').trim().toLowerCase()
  return text === 'model' ? 'model' : 'role_version'
}

function normalizeStatus(raw) {
  const direct = String(raw?.status || '').trim().toLowerCase()
  if (direct) return direct
  if (raw?.deprecated) return 'deprecated'
  if (raw?.enabled === false) return 'disabled'
  return 'enabled'
}

function numberOrNull(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function normalizeLastRun(raw) {
  if (!raw || typeof raw !== 'object') return null
  const id = String(raw.batch_id || raw.run_id || '').trim()
  const status = String(raw.status || '').trim().toLowerCase()
  const stage = String(raw.current_stage || raw.stage || '').trim()
  const resultCount = numberOrNull(raw.result_count)
  const diagnosticCount = numberOrNull(raw.diagnostic_count)
  const time = raw.finished_at || raw.last_heartbeat_at || raw.started_at || ''
  return {
    id,
    shortId: shortToken(id),
    status,
    statusLabel: runStatusLabels[status] || (status ? titleCase(status) : '未知'),
    stage,
    stageLabel: stage ? runStageLabels[stage] || titleCase(stage.replace(/_/g, ' ')) : '',
    resultCount,
    diagnosticCount,
    timeLabel: formatDateTime(time),
    tone: runTone(status)
  }
}

function normalizeLatestSnapshot(raw) {
  if (!raw || typeof raw !== 'object') return null
  const id = String(raw.snapshot_id || raw.id || '').trim()
  const rowCount = numberOrNull(raw.row_count)
  const contentHash = String(raw.content_hash || '').trim()
  return {
    id,
    shortId: shortToken(id),
    title: String(raw.title || id || '未命名快照'),
    rowCount,
    contentHash,
    shortHash: shortHash(contentHash),
    createdAtLabel: formatDateTime(raw.created_at || '')
  }
}

function runTone(status) {
  if (['completed'].includes(status)) return 'ok'
  if (['queued', 'running', 'rate_limited'].includes(status)) return 'live'
  if (['failed', 'cancelled', 'interrupted'].includes(status)) return 'bad'
  return 'idle'
}

function shortToken(value, size = 12) {
  const text = String(value || '').trim()
  if (!text) return ''
  return text.length > size ? `${text.slice(0, size - 1)}...` : text
}

function shortHash(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  const hash = text.includes(':') ? text.split(':').pop() : text
  return hash.length > 10 ? hash.slice(0, 10) : hash
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

function isQuickSuite(raw, costTier) {
  const id = String(raw?.id || '').toLowerCase()
  const name = String(raw?.name || raw?.label || '').toLowerCase()
  return ['smoke', 'quick', 'low'].includes(costTier) || id.includes('quick') || name.includes('quick')
}

function isReleaseSuite(raw, costTier) {
  const id = String(raw?.id || '').toLowerCase()
  const name = String(raw?.name || raw?.label || '').toLowerCase()
  return costTier === 'release' || id.includes('release') || name.includes('release')
}

function groupKey(suite) {
  if (suite.isQuick) return 'quick'
  if (suite.isRelease) return 'release'
  if (['standard', 'medium', 'high'].includes(suite.costTier)) return 'standard'
  return 'other'
}

function titleCase(value) {
  const text = String(value || '').trim()
  if (!text) return '未知'
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function roleScopeLabel(suite) {
  if (suite.targetType === 'model') return '全角色覆盖'
  if (!suite.roles.length) return '全角色'
  return `${suite.roles.length} 个角色`
}

function suiteMetaLine(suite) {
  const parts = []
  if (suite.gameCount != null) parts.push(`${suite.gameCount} 局`)
  if (suite.seedCount != null) parts.push(`${suite.seedCount} 个种子`)
  parts.push(roleScopeLabel(suite))
  return parts.join(' / ')
}

function selectSuite(id) {
  props.benchmark.selectBenchmarkSuite(id)
}

function selectLegacyScope(targetType) {
  props.benchmark.selectLegacyBenchmarkScope(targetType)
}
</script>

<template>
  <aside class="benchmark-suite-rail" aria-label="评测套件库">
    <header class="suite-rail-header">
      <div>
        <p>套件索引</p>
        <h2>评测套件</h2>
      </div>
      <span>{{ suiteCounts.total }}</span>
    </header>

    <section class="suite-rail-summary" aria-label="套件计数">
      <span>
        <small>模型</small>
        <b>{{ suiteCounts.model }}</b>
      </span>
      <span>
        <small>角色</small>
        <b>{{ suiteCounts.role_version }}</b>
      </span>
      <span>
        <small>快速</small>
        <b>{{ suiteCounts.quick }}</b>
      </span>
      <span>
        <small>发布</small>
        <b>{{ suiteCounts.release }}</b>
      </span>
    </section>

    <div v-if="benchmark.benchmarkSuiteError.value" class="suite-rail-alert">
      {{ benchmark.benchmarkSuiteError.value }}
    </div>

    <section class="legacy-scope-group" aria-label="临时评测范围">
      <div class="suite-group-title">
        <span>临时 / 历史</span>
        <small>历史无边界数据</small>
      </div>
      <button
        v-for="scope in legacyScopes"
        :key="scope.targetType"
        type="button"
        :class="[
          'legacy-scope-row',
          'legacy-scope-row--' + scope.targetType,
          { selected: !selectedSuiteId && legacyTargetType === scope.targetType }
        ]"
        @click="selectLegacyScope(scope.targetType)"
      >
        <span>
          <strong>{{ scope.label }}</strong>
          <em>{{ scope.caption }}</em>
        </span>
        <b>{{ scope.count }}</b>
      </button>
    </section>

    <div class="suite-rail-list">
      <section v-if="!suites.length" class="suite-rail-empty">
        <strong>暂无评测套件</strong>
        <span>正式套件加载后会显示在这里。</span>
      </section>

      <section
        v-for="group in suiteGroups"
        :key="group.key"
        class="suite-group"
        :aria-label="group.label"
      >
        <div class="suite-group-title">
          <span>{{ group.label }}</span>
          <small>{{ group.caption }}</small>
        </div>

        <button
          v-for="suite in group.rows"
          :key="suite.id"
          type="button"
          :class="[
            'suite-row',
            'suite-row--' + suite.targetType,
            'suite-row--' + suite.status,
            { selected: suite.id === selectedSuiteId, muted: !suite.enabled }
          ]"
          @click="selectSuite(suite.id)"
        >
          <span class="suite-row-main">
            <strong>{{ suite.label }}</strong>
            <em>{{ suite.id }}</em>
          </span>
          <span class="suite-row-tags">
            <b>{{ suite.targetTypeLabel }}</b>
            <b>{{ suite.costTierLabel }}</b>
            <b>{{ suite.statusLabel }}</b>
          </span>
          <span class="suite-row-meta">
            <small>{{ suite.evaluationSetId || '临时评测集' }}</small>
            <small>{{ suite.seedSetId || '临时种子集' }}</small>
          </span>
          <span class="suite-row-foot">
            <small>{{ suiteMetaLine(suite) }}</small>
            <small v-if="suite.version">{{ suite.version }}</small>
          </span>
          <span class="suite-row-activity" aria-label="套件活动">
            <span :class="['suite-activity-line', suite.lastRun ? `suite-activity-line--${suite.lastRun.tone}` : 'suite-activity-line--empty']">
              <small>运行</small>
              <b>{{ suite.lastRun?.statusLabel || '暂无运行' }}</b>
              <em>
                {{ suite.lastRun?.stageLabel || suite.lastRun?.shortId || '等待启动' }}
                <template v-if="suite.lastRun?.timeLabel"> · {{ suite.lastRun.timeLabel }}</template>
              </em>
            </span>
            <span :class="['suite-activity-line', suite.latestSnapshot ? 'suite-activity-line--snapshot' : 'suite-activity-line--empty']">
              <small>快照</small>
              <b>{{ suite.latestSnapshot ? `${suite.latestSnapshot.rowCount ?? 0} 行` : '无' }}</b>
              <em>
                {{ suite.latestSnapshot?.shortHash || suite.latestSnapshot?.shortId || '未发布' }}
                <template v-if="suite.latestSnapshot?.createdAtLabel"> · {{ suite.latestSnapshot.createdAtLabel }}</template>
              </em>
            </span>
          </span>
        </button>
      </section>
    </div>

    <footer v-if="selectedSuite" class="suite-rail-selected">
      <small>已选择</small>
      <b>{{ selectedSuite.label }}</b>
      <span>{{ selectedSuite.targetTypeLabel }} / {{ selectedSuite.costTierLabel }}</span>
    </footer>
  </aside>
</template>

<style scoped>
.benchmark-suite-rail {
  --rail-bg: #f8f0e0;
  --rail-panel: rgba(255, 252, 245, 0.7);
  --rail-line: rgba(139, 94, 52, 0.15);
  --rail-line-strong: rgba(90, 51, 25, 0.34);
  --rail-text: #3a2a18;
  --rail-muted: #8b6b4a;
  --rail-soft: rgba(139, 94, 52, 0.08);
  --rail-soft-strong: rgba(90, 51, 25, 0.12);
  --rail-accent: #5a3319;
  --rail-danger: #5a3319;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 292px;
  height: 100%;
  min-height: 0;
  padding: 12px;
  background: var(--rail-bg);
  border: 1px solid var(--rail-line);
  border-radius: 8px;
  color: var(--rail-text);
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
}

.suite-rail-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
}

.suite-rail-header p,
.suite-rail-header h2 {
  margin: 0;
}

.suite-rail-header p {
  color: var(--rail-muted);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}

.suite-rail-header h2 {
  margin-top: 2px;
  font-size: 17px;
  line-height: 1.15;
}

.suite-rail-header > span {
  display: grid;
  place-items: center;
  min-width: 34px;
  height: 28px;
  border: 1px solid var(--rail-line);
  border-radius: 6px;
  background: var(--rail-panel);
  font-size: 13px;
  font-weight: 800;
}

.suite-rail-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}

.suite-rail-summary span {
  display: grid;
  gap: 1px;
  min-width: 0;
  padding: 7px 6px;
  background: var(--rail-panel);
  border: 1px solid var(--rail-line);
  border-radius: 6px;
}

.suite-rail-summary small {
  color: var(--rail-muted);
  font-size: 10px;
  font-weight: 800;
  line-height: 1;
}

.suite-rail-summary b {
  font-size: 14px;
  line-height: 1.1;
}

.suite-rail-alert,
.suite-rail-empty {
  padding: 9px 10px;
  border: 1px solid rgba(90, 51, 25, 0.24);
  border-radius: 6px;
  background: rgba(90, 51, 25, 0.08);
  color: var(--rail-danger);
  font-size: 12px;
  font-weight: 700;
}

.suite-rail-empty {
  display: grid;
  gap: 3px;
  border-color: var(--rail-line);
  background: var(--rail-panel);
  color: var(--rail-text);
}

.suite-rail-empty span {
  color: var(--rail-muted);
  font-weight: 600;
}

.suite-rail-list {
  flex: 1 1 auto;
  display: grid;
  align-content: start;
  gap: 10px;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.suite-group {
  display: grid;
  gap: 7px;
  min-height: 0;
}

.legacy-scope-group {
  display: grid;
  gap: 7px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--rail-line);
}

.suite-group-title {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: 10px;
  padding-top: 2px;
}

.suite-group-title span {
  font-size: 12px;
  font-weight: 900;
}

.suite-group-title small {
  color: var(--rail-muted);
  font-size: 11px;
  font-weight: 700;
}

.suite-row {
  display: grid;
  gap: 7px;
  width: 100%;
  padding: 10px;
  text-align: left;
  color: inherit;
  background: var(--rail-panel);
  border: 1px solid var(--rail-line);
  border-left: 4px solid var(--rail-line-strong);
  border-radius: 8px;
  cursor: pointer;
}

.suite-row:hover {
  border-color: var(--rail-line-strong);
}

.suite-row.selected {
  border-color: var(--rail-accent);
  border-left-color: var(--rail-accent);
  background: var(--rail-soft-strong);
  box-shadow: inset 0 0 0 1px var(--rail-accent);
}

.suite-row.muted {
  opacity: 0.62;
}

.suite-row--model {
  border-left-color: rgba(90, 51, 25, 0.72);
}

.suite-row--role_version {
  border-left-color: rgba(139, 94, 52, 0.58);
}

.legacy-scope-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 58px;
  padding: 10px;
  text-align: left;
  color: inherit;
  background: var(--rail-panel);
  border: 1px solid var(--rail-line);
  border-left: 4px solid var(--rail-line-strong);
  border-radius: 8px;
  cursor: pointer;
}

.legacy-scope-row:hover {
  border-color: var(--rail-line-strong);
}

.legacy-scope-row.selected {
  border-color: var(--rail-accent);
  border-left-color: var(--rail-accent);
  background: var(--rail-soft-strong);
  box-shadow: inset 0 0 0 1px var(--rail-accent);
}

.legacy-scope-row--model {
  border-left-color: rgba(90, 51, 25, 0.72);
}

.legacy-scope-row--role_version {
  border-left-color: rgba(139, 94, 52, 0.58);
}

.legacy-scope-row span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.legacy-scope-row strong,
.legacy-scope-row em {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.legacy-scope-row strong {
  font-size: 13px;
  line-height: 1.2;
}

.legacy-scope-row em {
  color: var(--rail-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
}

.legacy-scope-row b {
  min-width: 32px;
  min-height: 28px;
  display: inline-grid;
  place-items: center;
  border-radius: 6px;
  background: var(--rail-soft);
  color: var(--rail-accent);
  font-size: 12px;
  font-weight: 900;
}

.suite-row--deprecated,
.suite-row--disabled,
.suite-row--archived {
  border-left-color: var(--rail-danger);
}

.suite-row-main,
.suite-row-meta,
.suite-row-foot {
  display: grid;
  min-width: 0;
}

.suite-row-main {
  gap: 2px;
}

.suite-row-main strong,
.suite-row-main em,
.suite-row-meta small,
.suite-row-foot small,
.suite-rail-selected b,
.suite-rail-selected span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.suite-row-main strong {
  font-size: 13px;
  line-height: 1.2;
}

.suite-row-main em {
  color: var(--rail-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
}

.suite-row-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.suite-row-tags b {
  padding: 2px 6px;
  background: var(--rail-soft);
  border: 1px solid var(--rail-line);
  border-radius: 5px;
  color: var(--rail-accent);
  font-size: 10px;
  font-weight: 900;
  line-height: 1.2;
}

.suite-row-meta {
  gap: 2px;
  color: var(--rail-muted);
  font-size: 11px;
  font-weight: 700;
}

.suite-row-foot {
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  color: var(--rail-muted);
  font-size: 11px;
  font-weight: 800;
}

.suite-row-activity {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding-top: 2px;
  border-top: 1px solid var(--rail-line);
}

.suite-activity-line {
  display: grid;
  grid-template-columns: 52px 78px minmax(0, 1fr);
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: var(--rail-text);
  font-size: 10px;
  line-height: 1.2;
}

.suite-activity-line small,
.suite-activity-line b,
.suite-activity-line em {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.suite-activity-line small {
  color: var(--rail-muted);
  font-weight: 900;
  text-transform: uppercase;
}

.suite-activity-line b {
  position: relative;
  padding-left: 9px;
  font-weight: 900;
}

.suite-activity-line b::before {
  content: "";
  position: absolute;
  left: 0;
  top: 50%;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--rail-line-strong);
  transform: translateY(-50%);
}

.suite-activity-line em {
  color: var(--rail-muted);
  font-style: normal;
  font-weight: 750;
}

.suite-activity-line--ok b::before,
.suite-activity-line--snapshot b::before {
  background: var(--rail-accent);
}

.suite-activity-line--live b::before {
  background: rgba(90, 51, 25, 0.72);
}

.suite-activity-line--bad b::before {
  background: var(--rail-danger);
}

.suite-activity-line--empty {
  color: var(--rail-muted);
}

.suite-activity-line--empty b::before {
  background: rgba(139, 94, 52, 0.28);
}

.suite-rail-selected {
  display: grid;
  gap: 2px;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid var(--rail-line-strong);
  border-radius: 7px;
  background: var(--rail-soft-strong);
}

.suite-rail-selected small {
  color: var(--rail-muted);
  font-size: 10px;
  font-weight: 900;
  text-transform: uppercase;
}

.suite-rail-selected b {
  font-size: 12px;
}

.suite-rail-selected span {
  color: var(--rail-muted);
  font-size: 11px;
  font-weight: 700;
}
</style>
