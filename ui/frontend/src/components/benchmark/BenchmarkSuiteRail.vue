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

const seedTierLabels = {
  smoke: '冒烟',
  quick: '快速',
  standard: '标准',
  release: '发布',
  audit: '审计'
}

const usageBoundaryLabels = {
  smoke: '冒烟验证',
  quick_check: '快速验证',
  formal_benchmark: '正式评测',
  leaderboard: '榜单口径',
  release_gate: '发布门禁',
  audit: '审计回放'
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

function normalizeSuite(raw) {
  const id = String(raw?.id || raw?.benchmark_id || '').trim()
  if (!id) return null
  const targetType = normalizeTargetType(raw?.target_type || raw?.scope)
  const costTier = String(raw?.cost_tier || '').trim().toLowerCase()
  const status = normalizeStatus(raw)
  const gameCount = numberOrNull(raw?.game_count ?? raw?.battle_games ?? raw?.games)
  const maxDays = numberOrNull(raw?.max_days)
  const seedSet = objectOrEmpty(raw?.seed_set)
  const seedSetId = String(raw?.seed_set_id || seedSet.seed_set_id || seedSet.id || '').trim()
  const hasSeedSetBoundary = Boolean(seedSetId || Object.keys(seedSet).length)
  const seedCount = numberOrNull(raw?.seed_count ?? seedSet.seed_count ?? seedSet.count)
  const version = raw?.version == null || raw.version === '' ? '' : `v${raw.version}`
  const configHash = String(raw?.config_hash || raw?.benchmark_config_hash || '').trim()
  const seedPreview = normalizeSeedPreview(raw)
  const seedTier = String(seedSet.tier || '').trim().toLowerCase()
  const seedTargetType = seedSet.target_type ? normalizeTargetType(seedSet.target_type) : (hasSeedSetBoundary ? targetType : '')
  const usageBoundary = String(seedSet.usage_boundary || '').trim()
  const nonOverlapGroup = String(seedSet.non_overlap_group || '').trim()
  const seedWarnings = normalizeOverlapWarnings(seedSet, seedSetId)
  const launchable = raw?.launchable == null
    ? !['deprecated', 'disabled', 'archived', 'draft'].includes(status)
    : raw.launchable !== false && !['deprecated', 'disabled', 'archived', 'draft'].includes(status)
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
    seedSetId,
    gameCount,
    maxDays,
    seedCount,
    seedPreview,
    seedPreviewLabel: seedPreview.join('、'),
    pairedSeed: Boolean(raw?.paired_seed),
    configHash,
    shortConfigHash: shortHash(configHash),
    seedSet,
    seedSetVersionLabel: formatSeedSetVersion(seedSet.version),
    seedTier,
    seedTierLabel: seedTierLabels[seedTier] || (seedTier ? titleCase(seedTier) : ''),
    seedTargetType,
    seedTargetTypeLabel: targetTypeLabels[seedTargetType] || seedTargetType,
    usageBoundary,
    usageBoundaryLabel: usageBoundaryLabels[usageBoundary] || usageBoundary,
    nonOverlapGroup,
    seedImmutable: hasSeedSetBoundary ? seedSet.immutable !== false : null,
    seedWarnings,
    seedWarningCount: seedWarnings.length,
    metrics: objectOrEmpty(raw?.metrics),
    gates: objectOrEmpty(raw?.gates),
    judge: objectOrEmpty(raw?.judge),
    roles: Array.isArray(raw?.roles) ? raw.roles : [],
    lastRun: normalizeLastRun(raw?.last_run),
    latestSnapshot: normalizeLatestSnapshot(raw?.latest_snapshot),
    isQuick: isQuickSuite(raw, costTier),
    isRelease: isReleaseSuite(raw, costTier),
    enabled: launchable,
    launchable,
    launchDisabledReason: launchable
      ? ''
      : String(raw?.launch_disabled_reason || raw?.launchDisabledReason || '').trim() || defaultLaunchDisabledReason(status)
  }
}

function normalizeSeedPreview(raw) {
  const candidates = [raw?.seed_preview, raw?.seedPreview, raw?.seed_set?.seed_preview, raw?.seed_set?.seeds]
  const arrayValue = candidates.find((value) => Array.isArray(value))
  if (arrayValue) return arrayValue.map((seed) => String(seed ?? '').trim()).filter(Boolean).slice(0, 6)
  return []
}

function normalizeOverlapWarnings(seedSet, seedSetId) {
  const warnings = Array.isArray(seedSet?.overlap_warnings)
    ? seedSet.overlap_warnings
    : (Array.isArray(seedSet?.overlapWarnings) ? seedSet.overlapWarnings : [])
  return warnings
    .map((warning) => formatOverlapWarning(warning, seedSetId))
    .filter(Boolean)
}

function formatOverlapWarning(warning, seedSetId) {
  if (!warning || typeof warning !== 'object') return ''
  const currentId = String(seedSetId || '').trim()
  const otherIds = [
    warning.left_seed_set_id,
    warning.right_seed_set_id,
    ...(Array.isArray(warning.seed_set_ids) ? warning.seed_set_ids : [])
  ]
    .map((id) => String(id || '').trim())
    .filter((id, index, items) => id && id !== currentId && items.indexOf(id) === index)
  const count = numberOrNull(warning.overlap_count ?? warning.seed_overlap_count ?? warning.count)
  const ratio = numberOrNull(warning.overlap_ratio ?? warning.ratio)
  const parts = []
  if (otherIds.length) parts.push(`与 ${otherIds.join('、')} 重叠`)
  if (count != null) parts.push(`${count} 个种子`)
  if (ratio != null) parts.push(`${Math.round(ratio * 100)}%`)
  const message = String(warning.message || warning.reason || '').trim()
  return parts.length ? parts.join('，') : (message || '存在种子重叠')
}

function formatSeedSetVersion(value) {
  if (value == null || value === '') return ''
  const text = String(value).trim()
  return text.startsWith('v') ? text : `v${text}`
}

function objectOrEmpty(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
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

function defaultLaunchDisabledReason(status) {
  if (status === 'draft') return '草稿套件启用后才能启动。'
  if (status === 'deprecated') return '废弃套件只保留历史审计，不能启动。'
  if (status === 'disabled') return '停用套件不能启动。'
  if (status === 'archived') return '归档套件只能查看历史结果。'
  return '当前套件不能启动。'
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
        <h2>评测套件</h2>
      </div>
    </header>

    <div v-if="benchmark.benchmarkSuiteError.value" class="suite-rail-alert">
      {{ benchmark.benchmarkSuiteError.value }}
    </div>

    <section class="legacy-scope-group" aria-label="临时评测范围">
      <div class="suite-group-title">
        <span>临时 / 历史</span>
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
        </span>
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
        </button>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.benchmark-suite-rail {
  --rail-bg: var(--bench-bg-texture, var(--logbook-bg-texture, #f2dfae));
  --rail-panel: var(--bench-surface, var(--logbook-surface, rgba(255, 252, 245, 0.7)));
  --rail-line: var(--bench-border, var(--logbook-border, rgba(139, 94, 52, 0.15)));
  --rail-line-strong: var(--bench-border-strong, var(--logbook-border-strong, rgba(90, 51, 25, 0.34)));
  --rail-text: var(--bench-text, var(--logbook-text, #3a2a18));
  --rail-muted: var(--bench-text-secondary, var(--logbook-muted, #8b6b4a));
  --rail-soft: var(--bench-hover, var(--logbook-hover, rgba(139, 94, 52, 0.06)));
  --rail-soft-strong: var(--bench-active-bg, var(--logbook-active-bg, rgba(139, 94, 52, 0.1)));
  --rail-accent: var(--bench-accent-strong, var(--logbook-accent-strong, #5a3319));
  --rail-danger: var(--bench-danger, var(--logbook-danger, #993026));
  --rail-danger-border: var(--bench-danger-border, rgba(153, 48, 38, 0.28));
  --rail-danger-bg: var(--bench-danger-bg, rgba(153, 48, 38, 0.06));
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  height: 100%;
  min-height: 0;
  padding: 0 14px 0 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  background: transparent;
  border: 0;
  border-right: 1px solid rgba(91, 47, 18, 0.2);
  border-radius: 0;
  color: var(--rail-text);
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
}

.benchmark-suite-rail,
.benchmark-suite-rail * {
  box-sizing: border-box;
}

.suite-rail-header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
  min-height: 57px;
  padding: 10px 14px 12px 0;
  border-bottom: 1px solid var(--rail-line);
}

.suite-rail-header h2 {
  margin: 0;
}

.suite-rail-header h2 {
  color: var(--rail-text);
  font-size: 22px;
  font-weight: 950;
  line-height: 1.05;
}

.suite-rail-alert,
.suite-rail-empty {
  padding: 9px 10px;
  border: 1px solid rgba(90, 51, 25, 0.24);
  border-radius: 0;
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

.suite-rail-alert {
  flex: 0 0 auto;
}

.suite-rail-list {
  flex: 0 0 auto;
  display: grid;
  align-content: start;
  gap: 7px;
  min-height: 0;
  overflow: visible;
  padding-right: 2px;
}

.suite-group {
  display: grid;
  gap: 7px;
  min-height: 0;
}

.legacy-scope-group {
  display: grid;
  flex: 0 0 auto;
  gap: 7px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--rail-line);
}

.suite-group-title {
  display: block;
  padding-top: 0;
  color: var(--rail-accent);
  font-size: 12px;
  font-weight: 800;
}

.suite-group-title span {
  font-size: 12px;
  font-weight: 800;
}

.suite-row {
  display: grid;
  align-content: start;
  width: 100%;
  min-width: 0;
  min-height: 36px;
  padding: 9px 10px;
  overflow: hidden;
  text-align: left;
  color: rgba(59, 28, 9, 0.78);
  background: rgba(255, 239, 194, 0.42);
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-bottom-color: rgba(93, 48, 17, 0.34);
  border-radius: 6px;
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
  cursor: pointer;
}

.suite-row:hover {
  border-color: rgba(93, 48, 17, 0.32);
  color: var(--rail-text);
  background: rgba(255, 245, 214, 0.62);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.82);
}

.suite-row.selected {
  border-color: rgba(93, 48, 17, 0.45);
  color: var(--rail-text);
  background: rgba(224, 184, 111, 0.66);
  box-shadow: inset 0 1px 2px rgba(93, 48, 17, 0.18);
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
  grid-template-columns: minmax(0, 1fr);
  align-items: center;
  width: 100%;
  min-height: 36px;
  padding: 9px 10px;
  text-align: left;
  color: rgba(59, 28, 9, 0.78);
  background: rgba(255, 239, 194, 0.42);
  border: 1px solid rgba(93, 48, 17, 0.18);
  border-bottom-color: rgba(93, 48, 17, 0.34);
  border-radius: 6px;
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.76);
  cursor: pointer;
}

.legacy-scope-row:hover {
  border-color: rgba(93, 48, 17, 0.32);
  color: var(--rail-text);
  background: rgba(255, 245, 214, 0.62);
  box-shadow: inset 0 1px 0 rgba(255, 252, 228, 0.82);
}

.legacy-scope-row.selected {
  border-color: rgba(93, 48, 17, 0.45);
  color: var(--rail-text);
  background: rgba(224, 184, 111, 0.66);
  box-shadow: inset 0 1px 2px rgba(93, 48, 17, 0.18);
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
  font-weight: 800;
  line-height: 1.2;
}

.suite-row--deprecated,
.suite-row--disabled,
.suite-row--archived {
  border-left-color: var(--rail-danger);
}

.suite-row-main {
  display: grid;
  min-width: 0;
  max-width: 100%;
}

.suite-row-main {
  gap: 2px;
}

.suite-row-main em {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.suite-row-main strong {
  display: -webkit-box;
  max-width: 100%;
  overflow: hidden;
  color: inherit;
  font-size: 13px;
  font-weight: 800;
  line-height: 1.25;
  overflow-wrap: anywhere;
  white-space: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.suite-row-main em {
  max-width: 100%;
  min-width: 0;
  font-size: 13px;
}

.suite-row-main em {
  color: var(--rail-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
}

</style>
