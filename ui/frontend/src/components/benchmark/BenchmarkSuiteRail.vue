<script setup>
import { computed } from 'vue'

const props = defineProps({
  benchmark: {
    type: Object,
    required: true
  }
})

const targetTypeLabels = {
  model: 'Model',
  role_version: 'Role-Version'
}

const costTierLabels = {
  smoke: 'Smoke',
  low: 'Low',
  medium: 'Medium',
  standard: 'Standard',
  release: 'Release',
  high: 'High'
}

const statusLabels = {
  enabled: 'Enabled',
  active: 'Enabled',
  draft: 'Draft',
  deprecated: 'Deprecated',
  disabled: 'Disabled',
  archived: 'Archived'
}

const suites = computed(() =>
  props.benchmark.benchmarkSuites.value.map(normalizeSuite).filter(Boolean)
)

const selectedSuiteId = computed(() => props.benchmark.selectedBenchmarkId.value)

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
    { key: 'quick', label: 'Quick / Smoke', caption: '低成本验证', rows: [] },
    { key: 'standard', label: 'Standard', caption: '正式比较', rows: [] },
    { key: 'release', label: 'Release', caption: '发布口径', rows: [] },
    { key: 'other', label: 'Other', caption: '未归类', rows: [] }
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
    costTierLabel: costTierLabels[costTier] || (costTier ? titleCase(costTier) : 'Unmarked'),
    status,
    statusLabel: statusLabels[status] || titleCase(status),
    evaluationSetId: String(raw?.evaluation_set_id || ''),
    seedSetId: String(raw?.seed_set_id || ''),
    gameCount,
    seedCount,
    roles: Array.isArray(raw?.roles) ? raw.roles : [],
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
  if (!text) return 'Unknown'
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function roleScopeLabel(suite) {
  if (suite.targetType === 'model') return 'all-role coverage'
  if (!suite.roles.length) return 'all roles'
  return `${suite.roles.length} roles`
}

function suiteMetaLine(suite) {
  const parts = []
  if (suite.gameCount != null) parts.push(`${suite.gameCount} games`)
  if (suite.seedCount != null) parts.push(`${suite.seedCount} seeds`)
  parts.push(roleScopeLabel(suite))
  return parts.join(' / ')
}

function selectSuite(id) {
  props.benchmark.selectBenchmarkSuite(id)
}
</script>

<template>
  <aside class="benchmark-suite-rail" aria-label="Benchmark suite library">
    <header class="suite-rail-header">
      <div>
        <p>Suite Library</p>
        <h2>Benchmark Suites</h2>
      </div>
      <span>{{ suiteCounts.total }}</span>
    </header>

    <section class="suite-rail-summary" aria-label="Suite counts">
      <span>
        <small>Model</small>
        <b>{{ suiteCounts.model }}</b>
      </span>
      <span>
        <small>Role</small>
        <b>{{ suiteCounts.role_version }}</b>
      </span>
      <span>
        <small>Quick</small>
        <b>{{ suiteCounts.quick }}</b>
      </span>
      <span>
        <small>Release</small>
        <b>{{ suiteCounts.release }}</b>
      </span>
    </section>

    <div v-if="benchmark.benchmarkSuiteError.value" class="suite-rail-alert">
      {{ benchmark.benchmarkSuiteError.value }}
    </div>

    <section v-if="!suites.length" class="suite-rail-empty">
      <strong>No benchmark suites</strong>
      <span>正式 suite 加载后会显示在这里。</span>
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
          <small>{{ suite.evaluationSetId || 'ad-hoc evaluation set' }}</small>
          <small>{{ suite.seedSetId || 'ad-hoc seed set' }}</small>
        </span>
        <span class="suite-row-foot">
          <small>{{ suiteMetaLine(suite) }}</small>
          <small v-if="suite.version">{{ suite.version }}</small>
        </span>
      </button>
    </section>

    <footer v-if="selectedSuite" class="suite-rail-selected">
      <small>Selected</small>
      <b>{{ selectedSuite.label }}</b>
      <span>{{ selectedSuite.targetTypeLabel }} / {{ selectedSuite.costTierLabel }}</span>
    </footer>
  </aside>
</template>

<style scoped>
.benchmark-suite-rail {
  --rail-bg: #f7f8f8;
  --rail-panel: #ffffff;
  --rail-line: #d8dedb;
  --rail-line-strong: #aebbb5;
  --rail-text: #1f2a27;
  --rail-muted: #66736d;
  --rail-soft: #eef2f0;
  --rail-blue: #256b8f;
  --rail-green: #24704d;
  --rail-amber: #8b641f;
  --rail-red: #a13d36;
  display: grid;
  grid-template-rows: auto auto auto 1fr auto;
  gap: 10px;
  width: 292px;
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
  border: 1px solid rgba(161, 61, 54, 0.24);
  border-radius: 6px;
  background: rgba(161, 61, 54, 0.06);
  color: var(--rail-red);
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

.suite-group {
  display: grid;
  gap: 7px;
  min-height: 0;
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
  border-color: #35433e;
  border-left-color: #111b18;
  box-shadow: inset 0 0 0 1px #35433e;
}

.suite-row.muted {
  opacity: 0.62;
}

.suite-row--model {
  border-left-color: var(--rail-blue);
}

.suite-row--role_version {
  border-left-color: var(--rail-green);
}

.suite-row--deprecated,
.suite-row--disabled,
.suite-row--archived {
  border-left-color: var(--rail-red);
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
  color: #30413b;
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
  color: #43524d;
  font-size: 11px;
  font-weight: 800;
}

.suite-rail-selected {
  display: grid;
  gap: 2px;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid var(--rail-line-strong);
  border-radius: 7px;
  background: #e9eeeb;
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
