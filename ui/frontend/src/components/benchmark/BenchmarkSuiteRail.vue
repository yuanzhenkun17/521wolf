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

const metricLabels = {
  avg_role_score: '角色均分',
  strength_score: '模型强度',
  target_side_win_rate: '目标阵营胜率',
  villagers_win_rate: '好人胜率',
  werewolves_win_rate: '狼人胜率',
  fallback_rate: '回退率',
  llm_error_rate: 'LLM 错误率',
  policy_adjusted_rate: '策略修正率',
  decision_judge_avg_score: '裁判均分'
}

const gateLabels = {
  min_completed_games: '最少完成局',
  min_valid_game_rate: '有效局率',
  max_fallback_rate: '最大回退率',
  max_llm_error_rate: '最大 LLM 错误率',
  max_policy_adjusted_rate: '最大策略修正率'
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
const selectedSpecRows = computed(() => {
  const suite = selectedSuite.value
  if (!suite) return []
  return [
    { key: 'target', label: '对象', value: suite.targetTypeLabel },
    { key: 'games', label: '局数', value: suite.gameCount == null ? '未设置' : `${suite.gameCount} 局` },
    { key: 'days', label: '最大天数', value: suite.maxDays == null ? '未设置' : `${suite.maxDays} 天` },
    { key: 'roles', label: '覆盖角色', value: roleScopeLabel(suite) },
    { key: 'evaluation', label: '评测集', value: suite.evaluationSetId || '临时' },
    { key: 'hash', label: 'Config Hash', value: suite.shortConfigHash || '未上报', title: suite.configHash }
  ]
})
const selectedSeedRows = computed(() => {
  const suite = selectedSuite.value
  if (!suite) return []
  const seedPurpose = String(suite.seedSet?.purpose || '').trim()
  const seedHash = String(suite.seedSet?.config_hash || '').trim()
  return [
    { key: 'seed-set', label: '种子集', value: suite.seedSetId || '临时' },
    { key: 'seed-version', label: '版本', value: suite.seedSetVersionLabel || '未标记' },
    { key: 'seed-tier', label: '层级', value: suite.seedTierLabel || '未标记' },
    { key: 'seed-target', label: '对象类型', value: suite.seedTargetTypeLabel || '未标记' },
    { key: 'usage-boundary', label: '使用边界', value: suite.usageBoundaryLabel || '未标记' },
    { key: 'non-overlap', label: '非重叠组', value: suite.nonOverlapGroup || '未标记' },
    { key: 'immutable', label: '不可变', value: suite.seedImmutable == null ? '未标记' : (suite.seedImmutable ? '是' : '否') },
    { key: 'seed-count', label: '种子数', value: suite.seedCount == null ? '未上报' : `${suite.seedCount} 个` },
    { key: 'seed-preview', label: '种子预览', value: suite.seedPreviewLabel || '未上报' },
    { key: 'paired', label: '配对种子', value: suite.pairedSeed ? '启用' : '未启用' },
    { key: 'purpose', label: '用途', value: seedPurpose || '未标记' },
    { key: 'seed-hash', label: '种子 Hash', value: shortHash(seedHash) || '未上报', title: seedHash }
  ]
})
const selectedSeedWarnings = computed(() => selectedSuite.value?.seedWarnings || [])
const selectedMetricRows = computed(() => {
  const suite = selectedSuite.value
  if (!suite) return []
  const primary = metricLabel(suite.metrics?.primary)
  const secondary = Array.isArray(suite.metrics?.secondary)
    ? suite.metrics.secondary.map(metricLabel).filter(Boolean)
    : []
  return [
    { key: 'primary', label: '主指标', value: primary || '未设置' },
    { key: 'secondary', label: '辅助指标', value: secondary.length ? secondary.join('、') : '未设置' }
  ]
})
const selectedGateRows = computed(() => {
  const suite = selectedSuite.value
  if (!suite) return []
  const rows = Object.entries(suite.gates || {})
    .filter(([, value]) => value != null && value !== '')
    .map(([key, value]) => ({ key, label: gateLabels[key] || key, value: formatGateValue(key, value) }))
  return rows.length ? rows : [{ key: 'empty', label: '门禁', value: '未设置' }]
})
const selectedJudgeRows = computed(() => {
  const suite = selectedSuite.value
  if (!suite) return []
  const judge = suite.judge || {}
  const enabled = Boolean(judge.enable_decision_judge)
  return [
    { key: 'enabled', label: '裁判判定', value: enabled ? '启用' : '未启用' },
    { key: 'max', label: '每局上限', value: enabled && judge.judge_max_decisions != null ? `${judge.judge_max_decisions} 次` : '无' },
    { key: 'concurrency', label: '并发', value: enabled && judge.judge_concurrency != null ? `${judge.judge_concurrency} 个任务` : '后端默认' },
    { key: 'timeout', label: '超时', value: enabled && judge.judge_timeout_seconds != null ? `${judge.judge_timeout_seconds} 秒` : '后端默认' }
  ]
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

function metricLabel(value) {
  const key = String(value || '').trim()
  if (!key) return ''
  return metricLabels[key] || key
}

function formatGateValue(key, value) {
  const number = Number(value)
  if (Number.isFinite(number) && String(key || '').includes('rate')) return `${Math.round(number * 100)}%`
  return String(value)
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
            <b v-if="suite.seedWarningCount">重叠警告 {{ suite.seedWarningCount }}</b>
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

    <footer v-if="selectedSuite" class="suite-rail-selected" aria-label="选中套件详情">
      <header>
        <div>
          <small>套件详情</small>
          <b>{{ selectedSuite.label }}</b>
        </div>
        <span :class="['suite-selected-status', selectedSuite.launchable ? 'ok' : 'blocked']">
          {{ selectedSuite.launchable ? '可启动' : '不可启动' }}
        </span>
      </header>
      <p v-if="selectedSuite.description">{{ selectedSuite.description }}</p>
      <div v-if="selectedSuite.launchDisabledReason" class="suite-selected-warning">
        {{ selectedSuite.launchDisabledReason }}
      </div>

      <section class="suite-selected-grid" aria-label="协议摘要">
        <span v-for="item in selectedSpecRows" :key="item.key" :title="item.title || String(item.value || '')">
          <small>{{ item.label }}</small>
          <b>{{ item.value }}</b>
        </span>
      </section>

      <section class="suite-selected-section" aria-label="种子集">
        <div class="suite-selected-subtitle">
          <b>种子集</b>
          <small>{{ selectedSeedWarnings.length ? `${selectedSeedWarnings.length} 条重叠警告` : (selectedSuite.seedSet?.enabled === false ? '停用' : '固定边界') }}</small>
        </div>
        <span v-for="item in selectedSeedRows" :key="item.key" :title="item.title || String(item.value || '')">
          <small>{{ item.label }}</small>
          <b>{{ item.value }}</b>
        </span>
        <div v-if="selectedSeedWarnings.length" class="suite-selected-warning suite-selected-warning--seed">
          <strong>重叠警告</strong>
          <span v-for="warning in selectedSeedWarnings" :key="warning">{{ warning }}</span>
        </div>
      </section>

      <section class="suite-selected-section" aria-label="指标和门禁">
        <div class="suite-selected-subtitle">
          <b>指标 / 门禁</b>
          <small>{{ selectedSuite.costTierLabel }}</small>
        </div>
        <span v-for="item in selectedMetricRows" :key="item.key">
          <small>{{ item.label }}</small>
          <b>{{ item.value }}</b>
        </span>
        <span v-for="item in selectedGateRows" :key="item.key">
          <small>{{ item.label }}</small>
          <b>{{ item.value }}</b>
        </span>
      </section>

      <section class="suite-selected-section" aria-label="裁判配置">
        <div class="suite-selected-subtitle">
          <b>裁判配置</b>
          <small>{{ selectedSuite.pairedSeed ? 'paired seed' : '非配对' }}</small>
        </div>
        <span v-for="item in selectedJudgeRows" :key="item.key">
          <small>{{ item.label }}</small>
          <b>{{ item.value }}</b>
        </span>
      </section>

      <section class="suite-selected-activity" aria-label="最近产物">
        <span>
          <small>最近运行</small>
          <b>{{ selectedSuite.lastRun?.statusLabel || '暂无运行' }}</b>
          <em>{{ selectedSuite.lastRun?.shortId || selectedSuite.lastRun?.timeLabel || '等待启动' }}</em>
        </span>
        <span>
          <small>最新快照</small>
          <b>{{ selectedSuite.latestSnapshot ? `${selectedSuite.latestSnapshot.rowCount ?? 0} 行` : '未发布' }}</b>
          <em>{{ selectedSuite.latestSnapshot?.shortHash || selectedSuite.latestSnapshot?.shortId || '无冻结榜单' }}</em>
        </span>
      </section>
    </footer>
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
.suite-row-foot small {
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
  gap: 8px;
  min-width: 0;
  max-height: 44%;
  overflow-y: auto;
  padding: 10px;
  border: 1px solid var(--rail-line-strong);
  border-radius: 8px;
  background: var(--rail-soft-strong);
}

.suite-rail-selected header,
.suite-selected-subtitle {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.suite-rail-selected header div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.suite-rail-selected header b {
  color: var(--rail-text);
  font-size: 13px;
  font-weight: 950;
}

.suite-selected-status {
  display: inline-grid;
  place-items: center;
  min-height: 24px;
  padding: 3px 8px;
  border: 1px solid var(--rail-line);
  border-radius: 6px;
  background: rgba(255, 250, 240, 0.7);
  color: var(--rail-accent);
  font-size: 11px;
  font-weight: 950;
}

.suite-selected-status.blocked {
  border-color: var(--rail-danger-border);
  background: var(--rail-danger-bg);
  color: var(--rail-danger);
}

.suite-rail-selected p,
.suite-selected-warning {
  margin: 0;
  color: var(--rail-muted);
  font-size: 11px;
  font-weight: 750;
  line-height: 1.45;
}

.suite-selected-warning {
  padding: 7px 8px;
  border: 1px solid var(--rail-danger-border);
  border-radius: 6px;
  background: var(--rail-danger-bg);
  color: var(--rail-danger);
  font-weight: 850;
}

.suite-selected-warning--seed {
  grid-column: 1 / -1;
  display: grid;
  gap: 4px;
}

.suite-selected-warning--seed strong,
.suite-selected-warning--seed span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.suite-selected-warning--seed strong {
  font-size: 11px;
  font-weight: 950;
}

.suite-selected-grid,
.suite-selected-section,
.suite-selected-activity {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.suite-selected-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.suite-selected-section,
.suite-selected-activity {
  padding-top: 8px;
  border-top: 1px solid var(--rail-line);
}

.suite-selected-section {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.suite-selected-subtitle {
  grid-column: 1 / -1;
}

.suite-selected-subtitle b {
  color: var(--rail-text);
  font-size: 12px;
  font-weight: 950;
}

.suite-selected-grid span,
.suite-selected-section > span,
.suite-selected-activity span {
  display: grid;
  gap: 2px;
  min-width: 0;
  padding: 7px 8px;
  border: 1px solid var(--rail-line);
  border-radius: 6px;
  background: rgba(255, 250, 240, 0.62);
}

.suite-selected-activity {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.suite-rail-selected small,
.suite-selected-subtitle small,
.suite-selected-activity small {
  color: var(--rail-muted);
  font-size: 10px;
  font-weight: 900;
}

.suite-selected-grid b,
.suite-selected-section > span b,
.suite-selected-activity b,
.suite-selected-activity em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.suite-selected-grid b,
.suite-selected-section > span b,
.suite-selected-activity b {
  color: var(--rail-text);
  font-size: 12px;
  font-weight: 900;
}

.suite-selected-activity em {
  color: var(--rail-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
}
</style>
