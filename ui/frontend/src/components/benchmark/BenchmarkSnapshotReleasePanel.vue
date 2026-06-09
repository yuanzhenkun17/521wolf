<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  benchmark: {
    type: Object,
    required: true
  }
})

const title = ref('')
const releaseNotes = ref('')
const exportState = ref('')
const compareAgainstSnapshotId = ref('')

const snapshots = computed(() => props.benchmark.benchmarkSnapshots.value || [])
const selectedSnapshot = computed(() => props.benchmark.activeBenchmarkSnapshotDetail.value || null)
const compareAgainstSnapshot = computed(() =>
  snapshots.value.find((snapshot) => snapshot.snapshot_id === compareAgainstSnapshotId.value) || null
)
const compare = computed(() => props.benchmark.benchmarkSnapshotCompare.value || {})
const currentRows = computed(() => props.benchmark.normalizedCurrentBenchmarkLeaderboardRows.value || [])
const selectedSuite = computed(() => props.benchmark.selectedBenchmarkSuite.value || {})
const snapshotRows = computed(() => selectedSnapshot.value?.rows || [])
const selectedSnapshotAudit = computed(() => snapshotAudit(selectedSnapshot.value))
const isModel = computed(() => props.benchmark.selectedBenchmarkIsModelSuite.value)
const isLoading = computed(() => Boolean(props.benchmark.benchmarkSnapshotLoading.value))
const compareError = computed(() => String(props.benchmark.benchmarkSnapshotCompareError?.value || ''))
const boundaryWarnings = computed(() => Array.isArray(compare.value.boundary_warnings) ? compare.value.boundary_warnings : [])
const boundaryWarningLabels = computed(() => boundaryWarnings.value.map(warningLabel).filter(Boolean))
const compareModeLabel = computed(() =>
  compareAgainstSnapshotId.value
    ? `${selectedSnapshot.value?.title || '已选快照'} 对比 ${compareAgainstSnapshot.value?.title || compareAgainstSnapshotId.value}`
    : '当前排行榜对比已选快照'
)
const compareHeadingLabel = computed(() =>
  compareAgainstSnapshotId.value ? '快照对比快照' : '当前榜单对比冻结快照'
)
const addedSectionTitle = computed(() =>
  compareAgainstSnapshotId.value ? '仅存在于对照快照的行' : '当前新增行'
)
const removedSectionTitle = computed(() =>
  compareAgainstSnapshotId.value ? '仅存在于已选快照的行' : '仅存在于快照的行'
)
const currentRankableRows = computed(() => currentRows.value.filter((row) => row.rankable !== false))
const currentUnrankableRows = computed(() => currentRows.value.filter((row) => row.rankable === false))
const topCurrentUnrankableRows = computed(() => currentUnrankableRows.value.slice(0, 4))
const currentReleaseAudit = computed(() => ({
  rowCount: currentRows.value.length,
  rankableCount: currentRankableRows.value.length,
  unrankableCount: currentUnrankableRows.value.length,
  totalGames: currentRows.value.reduce((sum, row) => sum + (firstFiniteNumber(
    row?.games,
    row?.game_count,
    row?.games_played,
    row?.total_games
  ) || 0), 0)
}))
const selectedSnapshotReleaseGate = computed(() =>
  objectValue(selectedSnapshot.value?.release_gate || selectedSnapshot.value?.summary?.release_gate)
)
const selectedSnapshotGateSummary = computed(() => objectValue(selectedSnapshotReleaseGate.value.summary))
const selectedSnapshotManifest = computed(() => objectValue(selectedSnapshot.value?.release_manifest))
const selectedSnapshotManifestGate = computed(() => objectValue(selectedSnapshotManifest.value.release_gate))
const selectedSnapshotSource = computed(() => objectValue(selectedSnapshotManifest.value.source))
const selectedSnapshotBoundaries = computed(() => objectValue(selectedSnapshotManifest.value.boundaries))
const selectedSnapshotGateStatus = computed(() => {
  const gate = selectedSnapshotReleaseGate.value
  const manifestGate = selectedSnapshotManifestGate.value
  const ok = typeof gate.ok === 'boolean'
    ? gate.ok
    : (typeof manifestGate.ok === 'boolean' ? manifestGate.ok : null)
  return {
    ok,
    label: ok === true ? '通过' : (ok === false ? '阻断' : '未上报'),
    tone: ok === true ? 'ready' : (ok === false ? 'blocked' : 'unknown')
  }
})
const selectedSnapshotGateIssues = computed(() => [
  ...issueRows(selectedSnapshotReleaseGate.value.blockers, '阻断'),
  ...issueRows(selectedSnapshotReleaseGate.value.warnings, '警告')
].slice(0, 5))
const selectedSnapshotEvidenceRows = computed(() => {
  if (!selectedSnapshot.value) return []
  const audit = selectedSnapshotAudit.value
  const gateSummary = selectedSnapshotGateSummary.value
  const manifestGate = selectedSnapshotManifestGate.value
  const thresholds = objectValue(gateSummary.thresholds || manifestGate.thresholds)
  const lifecycle = objectValue(gateSummary.suite_lifecycle || manifestGate.suite_lifecycle)
  const source = selectedSnapshotSource.value
  const boundaries = selectedSnapshotBoundaries.value
  const blockerCount = firstFiniteNumber(
    gateSummary.blocker_count,
    manifestGate.blocker_count,
    selectedSnapshot.value?.summary?.release_gate_blocker_count,
    selectedSnapshotReleaseGate.value.blockers?.length
  ) || 0
  const warningCount = firstFiniteNumber(
    gateSummary.warning_count,
    manifestGate.warning_count,
    selectedSnapshot.value?.summary?.release_gate_warning_count,
    selectedSnapshotReleaseGate.value.warnings?.length
  ) || 0
  return [
    {
      key: 'server-gate',
      label: '服务端门禁',
      value: selectedSnapshotGateStatus.value.label,
      caption: `阻断 ${formatNumber(blockerCount)} / 警告 ${formatNumber(warningCount)}`,
      tone: selectedSnapshotGateStatus.value.tone
    },
    {
      key: 'lifecycle',
      label: '套件状态',
      value: lifecycle.status ? `${lifecycle.status}${lifecycle.launchable ? ' / 可发布' : ' / 不可发布'}` : '未上报',
      caption: 'release gate lifecycle'
    },
    {
      key: 'thresholds',
      label: '门禁阈值',
      value: thresholdLabel(thresholds),
      caption: 'sample / completed / paired'
    },
    {
      key: 'content-hash',
      label: 'Content Hash',
      value: audit.contentHash ? shortHash(audit.contentHash) : '未上报',
      caption: audit.contentHash || '服务端未返回内容 hash'
    },
    {
      key: 'source-runs',
      label: '来源运行',
      value: sourceCountLabel(source.linked_run_ids, audit.runCount, '运行'),
      caption: sourceIdsPreview(audit.runIds)
    },
    {
      key: 'source-reports',
      label: '来源报告',
      value: sourceCountLabel(source.linked_report_ids, audit.reportCount, '报告'),
      caption: sourceIdsPreview(audit.reportIds)
    },
    {
      key: 'source-results',
      label: '结果批次',
      value: sourceCountLabel(source.linked_result_batch_ids, audit.resultBatchCount, '批次'),
      caption: sourceIdsPreview(audit.resultBatchIds)
    },
    {
      key: 'boundary',
      label: '评测边界',
      value: `${boundaries.scope || selectedSnapshot.value.scope || '--'} / ${boundaries.seed_set_id || selectedSnapshot.value.seed_set_id || '--'}`,
      caption: boundaries.benchmark_config_hash || selectedSnapshot.value.benchmark_config_hash || 'Config Hash 未上报'
    }
  ]
})
const boundaryWarningSummary = computed(() =>
  boundaryWarningLabels.value.length ? `${formatNumber(boundaryWarningLabels.value.length)} 条告警` : '无边界告警'
)
const benchmarkConfigHash = computed(() =>
  selectedSuite.value.config_hash ||
  selectedSuite.value.benchmark_config_hash ||
  props.benchmark.benchmarkPlan.value?.benchmark?.config_hash ||
  props.benchmark.benchmarkPlan.value?.benchmark_config_hash ||
  ''
)
const releaseBoundary = computed(() => {
  const scope = props.benchmark.benchmarkSnapshotScope.value || (isModel.value ? 'model' : 'role_version')
  return {
    benchmarkId: props.benchmark.selectedBenchmarkId.value || '',
    evaluationSetId: props.benchmark.selectedBenchmarkEvaluationSetId.value || selectedSuite.value.evaluation_set_id || '',
    seedSetId: selectedSuite.value.seed_set_id || props.benchmark.benchmarkPlan.value?.seed_set_id || '',
    configHash: benchmarkConfigHash.value,
    scope
  }
})
const releaseReadinessChecks = computed(() => {
  const audit = currentReleaseAudit.value
  const boundary = releaseBoundary.value
  return [
    {
      key: 'loading',
      label: '快照任务',
      value: isLoading.value ? '处理中' : '空闲',
      passed: !isLoading.value,
      required: true,
      blockedReason: '快照请求仍在处理中'
    },
    {
      key: 'suite',
      label: '评测套件',
      value: boundary.benchmarkId ? props.benchmark.selectedBenchmarkSuiteLabel.value : '未选择正式套件',
      passed: Boolean(boundary.benchmarkId),
      required: true,
      blockedReason: '需选择正式评测套件'
    },
    {
      key: 'rows',
      label: '当前行',
      value: `${formatNumber(audit.rowCount)} 行`,
      passed: audit.rowCount > 0,
      required: true,
      blockedReason: '当前排行榜没有行'
    },
    {
      key: 'rankable',
      label: '可排名行',
      value: `${formatNumber(audit.rankableCount)} 条`,
      passed: audit.rankableCount > 0,
      required: true,
      blockedReason: '没有可排名行'
    },
    {
      key: 'boundary',
      label: 'Evaluation Set',
      value: boundary.evaluationSetId || '未绑定评测集',
      passed: Boolean(boundary.evaluationSetId),
      required: true,
      blockedReason: '缺少 Evaluation Set，无法冻结正式快照'
    },
    {
      key: 'scope',
      label: 'scope',
      value: boundary.scope,
      passed: isModel.value || Boolean(props.benchmark.selectedRole.value),
      required: true,
      blockedReason: '角色版本范围需先选择角色'
    },
    {
      key: 'seed',
      label: 'Seed Set',
      value: boundary.seedSetId || '未上报',
      passed: Boolean(boundary.seedSetId),
      required: true,
      blockedReason: '缺少 Seed Set，无法证明种子边界'
    },
    {
      key: 'config',
      label: 'Config Hash',
      value: boundary.configHash ? shortHash(boundary.configHash) : '未上报',
      passed: Boolean(boundary.configHash),
      required: true,
      blockedReason: '缺少 Config Hash，无法证明配置边界'
    },
    {
      key: 'boundary-warning',
      label: '边界告警',
      value: boundaryWarningSummary.value,
      passed: boundaryWarnings.value.length === 0,
      required: true,
      blockedReason: '存在评测边界告警，需先处理后再冻结'
    },
    {
      key: 'unrankable',
      label: '不可排名证据',
      value: `${formatNumber(audit.unrankableCount)} 条`,
      passed: audit.unrankableCount === 0,
      required: false,
      attentionReason: '不可排名证据会保留，但不进入正式排名'
    }
  ]
})
const releaseBlockingReasons = computed(() =>
  releaseReadinessChecks.value
    .filter((item) => item.required && !item.passed)
    .map((item) => item.blockedReason)
)
const releaseAttentionReasons = computed(() =>
  releaseReadinessChecks.value
    .filter((item) => !item.required && !item.passed && item.attentionReason)
    .map((item) => item.attentionReason)
)
const canCreate = computed(() => releaseBlockingReasons.value.length === 0)
const releaseGateTone = computed(() => {
  if (isLoading.value) return 'loading'
  return canCreate.value ? 'ready' : 'blocked'
})
const releaseGateLabel = computed(() => {
  if (isLoading.value) return '检查中'
  return canCreate.value ? '可冻结' : '不可冻结'
})
const releaseGateDetail = computed(() => {
  if (!canCreate.value) return `禁用原因：${releaseBlockingReasons.value.join('；')}`
  const audit = currentReleaseAudit.value
  const unrankable = audit.unrankableCount > 0
    ? `${formatNumber(audit.unrankableCount)} 条不可排名证据会随快照保留`
    : '没有不可排名证据'
  return `可冻结：${formatNumber(audit.rankableCount)} 条可排名行将进入正式快照，${unrankable}。`
})

const defaultTitle = computed(() => {
  const suite = props.benchmark.selectedBenchmarkSuiteLabel.value || '基准'
  const subject = isModel.value ? '模型' : props.benchmark.selectedRoleLabel.value
  return `${suite} / ${subject} 发布快照`
})
const diffRows = computed(() => [
  { label: '变更', value: compare.value.changed?.length || 0, tone: 'blue' },
  { label: '新增', value: compare.value.added?.length || 0, tone: 'green' },
  { label: '移除', value: compare.value.removed?.length || 0, tone: 'red' },
  {
    label: '冻结行',
    value: compare.value.summary?.snapshot_row_count ?? selectedSnapshotAudit.value.rowCount ?? snapshotRows.value.length,
    tone: 'neutral'
  }
])
const topChangedRows = computed(() => (compare.value.changed || []).slice(0, 8))
const topAddedRows = computed(() => (compare.value.added || []).slice(0, 6))
const topRemovedRows = computed(() => (compare.value.removed || []).slice(0, 6))
const selectedSnapshotId = computed(() => props.benchmark.selectedBenchmarkSnapshotId.value || '')
const compareAgainstOptions = computed(() =>
  snapshots.value.filter((snapshot) => snapshot.snapshot_id && snapshot.snapshot_id !== selectedSnapshotId.value)
)
const selectedSnapshotJson = computed(() =>
  selectedSnapshot.value ? JSON.stringify(snapshotPayload(), null, 2) : ''
)
const selectedSnapshotCsv = computed(() =>
  selectedSnapshot.value
    ? toCsv([
        ['snapshot_id', 'title', 'scope', 'subject', 'score', 'win_rate', 'games', 'rankable', 'reason'],
        ...snapshotRows.value.map((row) => [
          selectedSnapshot.value.snapshot_id,
          selectedSnapshot.value.title,
          selectedSnapshot.value.scope,
          row.primary || row.model_id || row.target_version_id || row.key,
          row.score ?? row.target_role_role_weighted_score ?? row.strength_score ?? '',
          row.winRate ?? row.target_side_win_rate ?? '',
          row.games ?? row.game_count ?? '',
          row.rankable == null ? '' : String(row.rankable),
          row.rankableReason || row.rankable_reason || ''
        ])
      ])
    : ''
)
const snapshotDeltaCsv = computed(() =>
  toCsv([
    ['change_type', 'subject', 'score_delta', 'win_rate_delta', 'games_delta', 'rankable_changed'],
    ...topChangedRows.value.map((row) => [
      'changed',
      row.current.primary || row.key,
      row.scoreDelta,
      row.winRateDelta,
      row.gamesDelta,
      row.rankableChanged
    ]),
    ...topAddedRows.value.map((row) => ['added', row.primary || row.key, row.score ?? '', row.winRate ?? '', row.games ?? '', '']),
    ...topRemovedRows.value.map((row) => ['removed', row.primary || row.key, row.score ?? '', row.winRate ?? '', row.games ?? '', ''])
  ])
)

watch(
  defaultTitle,
  (value) => {
    if (!title.value.trim()) title.value = value
  },
  { immediate: true }
)

watch(selectedSnapshotId, () => {
  compareAgainstSnapshotId.value = ''
})

async function createSnapshot() {
  if (!canCreate.value) return
  const created = await props.benchmark.createBenchmarkSnapshot({
    title: title.value || defaultTitle.value,
    release_notes: releaseNotes.value
  })
  if (!created) return
  title.value = defaultTitle.value
  releaseNotes.value = ''
}

function selectSnapshot(snapshot) {
  if (!snapshot?.snapshot_id) return
  props.benchmark.selectBenchmarkSnapshot(snapshot.snapshot_id)
}

async function selectCompareAgainst(event) {
  const againstId = String(event?.target?.value || '').trim()
  compareAgainstSnapshotId.value = againstId
  if (!selectedSnapshotId.value) return
  await props.benchmark.loadBenchmarkSnapshotCompare(selectedSnapshotId.value, {
    againstSnapshotId: againstId,
    silent: false
  })
}

function downloadSnapshot(format) {
  const text = format === 'json'
    ? selectedSnapshotJson.value
    : (format === 'delta-csv' ? snapshotDeltaCsv.value : selectedSnapshotCsv.value)
  if (!text) return
  const extension = format === 'json' ? 'json' : 'csv'
  const mime = format === 'json' ? 'application/json' : 'text/csv'
  const suffix = format === 'delta-csv' ? 'delta' : 'snapshot'
  if (downloadText(`${safeFilename(selectedSnapshotId.value || 'benchmark-snapshot')}-${suffix}.${extension}`, text, mime)) {
    exportState.value = `${exportFormatLabel(format)} 已导出`
    clearTransientState()
  }
}

async function copySnapshot(format) {
  const text = format === 'json' ? selectedSnapshotJson.value : selectedSnapshotCsv.value
  if (!text || typeof navigator === 'undefined' || !navigator.clipboard?.writeText) return
  try {
    await navigator.clipboard.writeText(text)
    exportState.value = `${exportFormatLabel(format)} 已复制`
    clearTransientState()
  } catch {
    exportState.value = ''
  }
}

function snapshotPayload() {
  const snapshot = selectedSnapshot.value || {}
  return {
    kind: 'benchmark_leaderboard_snapshot_export',
    schema_version: 1,
    exported_at: new Date().toISOString(),
    snapshot: {
      snapshot_id: snapshot.snapshot_id,
      title: snapshot.title,
      release_notes: snapshot.release_notes || '',
      scope: snapshot.scope,
      benchmark_id: snapshot.benchmark_id,
      benchmark_version: snapshot.benchmark_version,
      evaluation_set_id: snapshot.evaluation_set_id,
      seed_set_id: snapshot.seed_set_id,
      benchmark_config_hash: snapshot.benchmark_config_hash,
      target_role: snapshot.target_role || '',
      content_hash: snapshot.content_hash,
      created_at: snapshot.created_at,
      summary: snapshot.summary || {},
      release_gate: snapshot.release_gate || {},
      release_manifest: snapshot.release_manifest || {}
    },
    rows: snapshotRows.value,
    current_vs_frozen: {
      changed: compare.value.changed || [],
      added: compare.value.added || [],
      removed: compare.value.removed || []
    }
  }
}

function formatNumber(value) {
  if (value == null || value === '') return '--'
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN') : '--'
}

function formatPct(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '--'
  return `${Math.round(number * 100)}%`
}

function formatSignedPct(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '--'
  return `${number >= 0 ? '+' : ''}${Math.round(number * 100)}%`
}

function shortHash(value) {
  const text = String(value || '').trim()
  return text ? text.slice(0, 18) : '--'
}

function snapshotAudit(snapshot) {
  const summary = snapshot?.summary || {}
  const rowCount = firstFiniteNumber(snapshot?.row_count, summary.row_count, Array.isArray(snapshot?.rows) ? snapshot.rows.length : null)
  const rankableCount = firstFiniteNumber(snapshot?.rankable_count, summary.rankable_count)
  const unrankableCount = firstFiniteNumber(
    snapshot?.unrankable_count,
    summary.unrankable_count,
    rowCount != null && rankableCount != null ? Math.max(rowCount - rankableCount, 0) : null
  )
  const runIds = snapshotLinkedIds(snapshot, 'linked_run_ids')
  const reportIds = snapshotLinkedIds(snapshot, 'linked_report_ids')
  const resultBatchIds = snapshotLinkedIds(snapshot, 'linked_result_batch_ids')
  return {
    rowCount,
    rankableCount,
    unrankableCount,
    contentHash: String(snapshot?.content_hash || summary.content_hash || '').trim(),
    runCount: snapshotSourceCount(snapshot, runIds, 'source_run_count'),
    reportCount: snapshotSourceCount(snapshot, reportIds, 'source_report_count'),
    resultBatchCount: snapshotSourceCount(snapshot, resultBatchIds, 'source_result_batch_count'),
    runIds,
    reportIds,
    resultBatchIds
  }
}

function firstFiniteNumber(...values) {
  for (const value of values) {
    if (value == null || value === '') continue
    const number = Number(value)
    if (Number.isFinite(number)) return number
  }
  return null
}

function snapshotLinkedIds(snapshot, key) {
  const summary = snapshot?.summary || {}
  return normalizedIdList(snapshot?.[key] ?? summary[key])
}

function normalizedIdList(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item || '').trim()).filter(Boolean)
  }
  const text = String(value || '').trim()
  return text ? [text] : []
}

function snapshotSourceCount(snapshot, ids, countKey) {
  const summary = snapshot?.summary || {}
  const reported = firstFiniteNumber(snapshot?.[countKey], summary[countKey])
  if (reported != null) return reported
  return ids.length ? ids.length : null
}

function objectValue(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function issueRows(items, label) {
  if (!Array.isArray(items)) return []
  return items
    .filter((item) => item && typeof item === 'object')
    .map((item, index) => ({
      key: `${label}-${item.code || item.message || index}`,
      label,
      code: String(item.code || item.kind || label),
      message: String(item.message || item.detail || item.reason || '无说明'),
      affected: normalizedIdList(item.affected_ids).slice(0, 3).join(', ')
    }))
}

function thresholdLabel(thresholds) {
  const sample = thresholds.min_sample_size ?? '--'
  const completed = thresholds.min_completed_games ?? '--'
  const paired = thresholds.min_paired_overlap ?? '--'
  return `${sample} / ${completed} / ${paired}`
}

function sourceCountLabel(ids, fallbackCount, label) {
  const count = normalizedIdList(ids).length || fallbackCount
  if (count == null || count === '') return '未上报'
  return `${formatNumber(count)} ${label}`
}

function sourceIdsPreview(ids) {
  const values = normalizedIdList(ids)
  if (!values.length) return '关联 ID 未上报'
  const shown = values.slice(0, 3).map(shortHash)
  const remaining = values.length - shown.length
  return remaining > 0 ? `${shown.join(', ')} +${remaining}` : shown.join(', ')
}

function snapshotHistoryCountLabel(snapshot) {
  const audit = snapshotAudit(snapshot)
  return [
    `行 ${formatNumber(audit.rowCount)}`,
    `可排名 ${formatNumber(audit.rankableCount)}`,
    `不可排名 ${formatNumber(audit.unrankableCount)}`
  ].join(' / ')
}

function rowSubjectLabel(row) {
  return row?.primary ||
    row?.subject_id ||
    row?.model_id ||
    row?.model_config_hash ||
    row?.target_version_id ||
    row?.key ||
    '未知对象'
}

function rowReasonLabel(row) {
  return row?.rankableReason ||
    row?.rankable_reason ||
    row?.reason ||
    row?.gate_reason ||
    '未达到发布门禁'
}

function rowGamesLabel(row) {
  const completed = firstFiniteNumber(row?.games_played, row?.completed_games, row?.completed)
  const total = firstFiniteNumber(row?.game_count, row?.total_games, row?.games)
  if (completed != null && total != null) return `${formatNumber(completed)}/${formatNumber(total)} 局`
  if (total != null) return `${formatNumber(total)} 局`
  return '局数未上报'
}

function createdLabel(value) {
  const text = String(value || '').trim()
  if (!text) return '--'
  const date = new Date(text)
  if (Number.isNaN(date.getTime())) return text
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function warningLabel(value) {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object') return value.kind || value.message || ''
  return ''
}

function exportFormatLabel(format) {
  if (format === 'delta-csv') return '差值 CSV'
  if (format === 'json') return 'JSON'
  return 'CSV'
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
  return String(value || 'benchmark-snapshot')
    .trim()
    .replace(/[^a-zA-Z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 96) || 'benchmark-snapshot'
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

function clearTransientState() {
  if (typeof window === 'undefined' || !window.setTimeout) return
  window.setTimeout(() => {
    exportState.value = ''
  }, 1600)
}
</script>

<template>
  <section class="benchmark-snapshot-panel" aria-label="基准快照发布面板">
    <header class="snapshot-header">
      <div>
        <small>发布快照</small>
        <h2>冻结排行榜</h2>
      </div>
      <div class="snapshot-header-actions">
        <span class="snapshot-freeze-stack">
          <button
            type="button"
            class="snapshot-primary-button"
            :disabled="!canCreate"
            :aria-disabled="String(!canCreate)"
            :aria-label="'冻结快照：' + releaseGateLabel"
            :title="releaseGateDetail"
            @click="createSnapshot"
          >
            冻结快照
          </button>
        </span>
      </div>
    </header>

    <div v-if="props.benchmark.benchmarkSnapshotError.value" class="snapshot-warning">
      {{ props.benchmark.benchmarkSnapshotError.value }}
    </div>
    <div v-if="compareError" class="snapshot-warning snapshot-warning-muted">
      {{ compareError }}
    </div>

    <section class="snapshot-release-grid">
      <article class="snapshot-release-card">
        <div class="snapshot-section-title">
          <span>
            <small>发布</small>
            <b>发布说明</b>
          </span>
          <em>{{ currentRows.length }} 当前行</em>
        </div>
        <div :class="['snapshot-release-gate', 'snapshot-release-gate--' + releaseGateTone]" aria-label="发布门禁">
          <div class="snapshot-gate-head">
            <span>
              <small>发布门禁</small>
              <b>{{ releaseGateLabel }}</b>
            </span>
            <em>{{ canCreate ? '冻结按钮已开放' : '冻结按钮已禁用' }}</em>
          </div>
          <p>{{ releaseGateDetail }}</p>
          <div v-if="releaseBlockingReasons.length" class="snapshot-disable-reasons" aria-label="禁用原因">
            <small>禁用原因</small>
            <span v-for="reason in releaseBlockingReasons" :key="reason">{{ reason }}</span>
          </div>
          <div v-if="releaseAttentionReasons.length" class="snapshot-attention-reasons" aria-label="发布复核项">
            <small>需复核</small>
            <span v-for="reason in releaseAttentionReasons" :key="reason">{{ reason }}</span>
          </div>
        </div>
        <label>
          <span>标题</span>
          <input v-model.trim="title" type="text" autocomplete="off" :placeholder="defaultTitle" />
        </label>
        <label>
          <span>说明</span>
          <textarea
            v-model.trim="releaseNotes"
            rows="4"
            spellcheck="false"
            placeholder="记录本次变更、为什么该套件可发布，以及仍需关注的风险。"
          />
        </label>
        <div class="snapshot-unrankable-evidence" aria-label="不可排名证据">
          <div class="snapshot-section-title compact">
            <span>
              <small>不可排名证据</small>
              <b>{{ formatNumber(currentReleaseAudit.unrankableCount) }} 条不会进入正式排名</b>
            </span>
            <em>随快照保留</em>
          </div>
          <div v-if="topCurrentUnrankableRows.length" class="snapshot-unrankable-list">
            <span v-for="row in topCurrentUnrankableRows" :key="'current-unrankable-' + row.key">
              <b>{{ rowSubjectLabel(row) }}</b>
              <small>{{ rowReasonLabel(row) }}</small>
              <em>{{ rowGamesLabel(row) }}</em>
            </span>
          </div>
          <p v-else class="snapshot-empty small">没有不可排名证据。</p>
        </div>
      </article>

      <article class="snapshot-history-card">
        <div class="snapshot-section-title">
          <span>
            <small>历史</small>
            <b>已冻结排行榜版本</b>
          </span>
          <em>{{ snapshots.length }} 个快照</em>
        </div>
        <div v-if="snapshots.length" class="snapshot-list">
          <button
            v-for="snapshot in snapshots"
            :key="snapshot.snapshot_id"
            type="button"
            :class="['snapshot-list-row', { active: snapshot.snapshot_id === selectedSnapshotId }]"
            @click="selectSnapshot(snapshot)"
          >
            <span class="snapshot-list-main">
              <b>{{ snapshot.title }}</b>
              <small>{{ createdLabel(snapshot.created_at) }} / {{ snapshotHistoryCountLabel(snapshot) }}</small>
            </span>
          </button>
        </div>
        <p v-else class="snapshot-empty">
          这个套件边界还没有冻结发布快照。
        </p>
      </article>
    </section>

    <section class="snapshot-compare-grid">
      <article class="snapshot-summary-card">
        <div class="snapshot-section-title">
          <span>
            <small>已选快照</small>
            <b>{{ selectedSnapshot?.title || '未选择快照' }}</b>
          </span>
          <em>{{ selectedSnapshot ? createdLabel(selectedSnapshot.created_at) : '--' }}</em>
        </div>
        <div class="snapshot-export-row">
          <button type="button" :disabled="!selectedSnapshot" @click="copySnapshot('json')">复制 JSON</button>
          <button type="button" :disabled="!selectedSnapshot" @click="copySnapshot('csv')">复制 CSV</button>
          <button type="button" :disabled="!selectedSnapshot" @click="downloadSnapshot('json')">JSON</button>
          <button type="button" :disabled="!selectedSnapshot" @click="downloadSnapshot('csv')">CSV</button>
          <button type="button" :disabled="!selectedSnapshot" @click="downloadSnapshot('delta-csv')">差值 CSV</button>
          <em>{{ exportState }}</em>
        </div>
        <div v-if="selectedSnapshot" class="snapshot-evidence-grid" aria-label="发布证据">
          <span
            v-for="item in selectedSnapshotEvidenceRows"
            :key="item.key"
            :class="['snapshot-evidence-item', item.tone ? 'is-' + item.tone : '']"
          >
            <small>{{ item.label }}</small>
            <b :title="String(item.value || '')">{{ item.value }}</b>
            <em :title="String(item.caption || '')">{{ item.caption }}</em>
          </span>
        </div>
        <div v-if="selectedSnapshotGateIssues.length" class="snapshot-gate-issues" aria-label="服务端门禁问题">
          <span v-for="issue in selectedSnapshotGateIssues" :key="issue.key">
            <small>{{ issue.label }}</small>
            <b :title="issue.code">{{ issue.code }}</b>
            <em :title="issue.message">{{ issue.message }}</em>
          </span>
        </div>
        <div class="snapshot-compare-picker">
          <label>
            <small>对照快照</small>
            <select
              :value="compareAgainstSnapshotId"
              :disabled="!selectedSnapshot || compareAgainstOptions.length === 0"
              @change="selectCompareAgainst"
            >
              <option value="">当前排行榜</option>
              <option
                v-for="snapshot in compareAgainstOptions"
                :key="'against-' + snapshot.snapshot_id"
                :value="snapshot.snapshot_id"
              >
                {{ snapshot.title }}
              </option>
            </select>
          </label>
          <span>{{ compareModeLabel }}</span>
        </div>
        <div class="snapshot-metrics">
          <span v-for="item in diffRows" :key="item.label" :class="'tone-' + item.tone">
            <small>{{ item.label }}</small>
            <b>{{ formatNumber(item.value) }}</b>
          </span>
        </div>
      </article>

      <article class="snapshot-delta-card">
        <div class="snapshot-section-title">
          <span>
            <small>{{ compareHeadingLabel }}</small>
            <b>分数变化</b>
          </span>
          <em>{{ topChangedRows.length }} 已显示</em>
        </div>
        <div v-if="topChangedRows.length" class="snapshot-delta-table">
          <div class="snapshot-delta-row snapshot-delta-head">
            <span>对象</span>
            <span>分数</span>
            <span>胜率</span>
            <span>局数</span>
          </div>
          <div v-for="row in topChangedRows" :key="row.key" class="snapshot-delta-row">
            <span>
              <b>{{ row.current.primary }}</b>
              <small>{{ row.current.secondary || row.key }}</small>
            </span>
            <strong :class="row.scoreDelta >= 0 ? 'positive' : 'negative'">
              {{ formatSignedPct(row.scoreDelta) }}
            </strong>
            <strong :class="row.winRateDelta >= 0 ? 'positive' : 'negative'">
              {{ formatSignedPct(row.winRateDelta) }}
            </strong>
            <em>{{ row.gamesDelta >= 0 ? '+' : '' }}{{ row.gamesDelta }}</em>
          </div>
        </div>
        <p v-else class="snapshot-empty">
          选择快照进行对比，或冻结当前排行榜作为发布基线。
        </p>
      </article>
    </section>

    <section class="snapshot-membership-grid">
      <article>
        <div class="snapshot-section-title compact">
          <span>
            <small>新增</small>
            <b>{{ addedSectionTitle }}</b>
          </span>
          <em>{{ topAddedRows.length }}</em>
        </div>
        <div v-if="topAddedRows.length" class="snapshot-chip-list">
          <span v-for="row in topAddedRows" :key="'added-' + row.key">
            <b>{{ row.primary }}</b>
            <em>{{ formatPct(row.score) }}</em>
          </span>
        </div>
        <p v-else class="snapshot-empty small">没有新增行。</p>
      </article>

      <article>
        <div class="snapshot-section-title compact">
          <span>
            <small>移除</small>
            <b>{{ removedSectionTitle }}</b>
          </span>
          <em>{{ topRemovedRows.length }}</em>
        </div>
        <div v-if="topRemovedRows.length" class="snapshot-chip-list removed">
          <span v-for="row in topRemovedRows" :key="'removed-' + row.key">
            <b>{{ row.primary }}</b>
            <em>{{ formatPct(row.score) }}</em>
          </span>
        </div>
        <p v-else class="snapshot-empty small">没有移除行。</p>
      </article>
    </section>
  </section>
</template>

<style scoped>
.benchmark-snapshot-panel {
  --snapshot-bg: var(--bench-bg, var(--logbook-bg, #f2dfae));
  --snapshot-surface: var(--bench-surface, var(--logbook-surface, rgba(255, 252, 245, 0.7)));
  --snapshot-surface-strong: var(--bench-panel-solid, var(--logbook-panel-solid, rgba(255, 252, 245, 0.92)));
  --snapshot-border: var(--bench-border, var(--logbook-border, rgba(139, 94, 52, 0.15)));
  --snapshot-border-strong: var(--bench-border-strong, var(--logbook-border-strong, rgba(139, 94, 52, 0.28)));
  --snapshot-ink: var(--bench-text, var(--logbook-text, #3a2a18));
  --snapshot-muted: var(--bench-text-secondary, var(--logbook-muted, #8b6b4a));
  --snapshot-accent: var(--bench-accent, var(--logbook-accent, #8b5e34));
  --snapshot-strong: var(--bench-accent-strong, var(--logbook-accent-strong, #5a3319));
  --snapshot-soft: var(--bench-panel-soft, var(--logbook-panel-soft, rgba(248, 240, 224, 0.66)));
  --snapshot-danger: var(--bench-danger, var(--logbook-danger, #5a3319));
  --snapshot-warning: var(--bench-warning, var(--logbook-warning, #8b6b4a));
  display: grid;
  gap: 12px;
  min-width: 0;
  color: var(--snapshot-ink);
}

.snapshot-header,
.snapshot-release-card,
.snapshot-history-card,
.snapshot-summary-card,
.snapshot-delta-card,
.snapshot-membership-grid article {
  border: 1px solid var(--snapshot-border);
  border-radius: 8px;
  background: var(--snapshot-surface);
}

.snapshot-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 16px;
  padding: 14px 16px;
  background:
    linear-gradient(90deg, rgba(139, 94, 52, 0.12), rgba(255, 252, 245, 0) 56%),
    var(--snapshot-surface);
}

.snapshot-header h2 {
  margin: 2px 0 0;
  color: var(--snapshot-ink);
  font-size: 20px;
  font-weight: 950;
  line-height: 1.1;
}

.snapshot-header small,
.snapshot-section-title small,
.snapshot-gate-head small,
.snapshot-disable-reasons small,
.snapshot-attention-reasons small,
.snapshot-release-card label span,
.snapshot-evidence-grid small,
.snapshot-gate-issues small,
.snapshot-list-row small,
.snapshot-metrics small,
.snapshot-delta-row small,
.snapshot-unrankable-list small {
  color: var(--snapshot-muted);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.snapshot-header-actions {
  display: grid;
  grid-template-columns: auto minmax(220px, 280px);
  align-items: start;
  gap: 8px;
  min-width: 0;
}

.snapshot-freeze-stack {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.snapshot-freeze-stack .snapshot-primary-button {
  width: 100%;
}

.snapshot-primary-button,
.snapshot-export-row button {
  height: 34px;
  padding: 0 12px;
  border: 1px solid var(--snapshot-accent);
  border-radius: 7px;
  font-size: 12px;
  font-weight: 950;
  cursor: pointer;
}

.snapshot-primary-button {
  background: var(--snapshot-accent);
  color: rgb(255, 252, 245);
}

.snapshot-export-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}

.snapshot-export-row button {
  height: 30px;
  background: var(--snapshot-surface-strong);
  color: var(--snapshot-strong);
}

.snapshot-export-row button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.snapshot-export-row em {
  color: var(--snapshot-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 850;
}

.snapshot-compare-picker {
  display: grid;
  grid-template-columns: minmax(220px, 0.48fr) minmax(0, 1fr);
  gap: 10px;
  align-items: end;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid var(--snapshot-border);
  border-radius: 7px;
  background: var(--snapshot-soft);
}

.snapshot-compare-picker label {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.snapshot-compare-picker select {
  width: 100%;
  height: 30px;
  min-width: 0;
  padding: 0 8px;
  border: 1px solid var(--snapshot-border-strong);
  border-radius: 6px;
  background: var(--snapshot-surface-strong);
  color: var(--snapshot-ink);
  font-size: 11px;
  font-weight: 850;
}

.snapshot-compare-picker span {
  min-width: 0;
  overflow: hidden;
  color: var(--snapshot-muted);
  font-size: 12px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.snapshot-primary-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.snapshot-warning {
  padding: 9px 12px;
  border: 1px solid rgba(90, 51, 25, 0.25);
  border-radius: 8px;
  background: rgba(90, 51, 25, 0.08);
  color: var(--snapshot-danger);
  font-size: 12px;
  font-weight: 850;
}

.snapshot-release-grid,
.snapshot-compare-grid,
.snapshot-membership-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(380px, 0.86fr);
  gap: 12px;
  min-width: 0;
}

.snapshot-release-card,
.snapshot-history-card,
.snapshot-summary-card,
.snapshot-delta-card,
.snapshot-membership-grid article {
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 12px;
}

.snapshot-section-title {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.snapshot-section-title.compact {
  align-items: center;
}

.snapshot-section-title span {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.snapshot-section-title b {
  overflow: hidden;
  color: var(--snapshot-ink);
  font-size: 13px;
  font-weight: 950;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.snapshot-section-title em,
.snapshot-list-row em,
.snapshot-delta-row em,
.snapshot-chip-list em {
  color: var(--snapshot-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 850;
}

.snapshot-release-card label {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.snapshot-release-card input,
.snapshot-release-card textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--snapshot-border-strong);
  border-radius: 7px;
  background: var(--snapshot-surface-strong);
  color: var(--snapshot-ink);
  font-size: 12px;
  font-weight: 800;
}

.snapshot-release-card input {
  height: 34px;
  padding: 0 10px;
}

.snapshot-release-card textarea {
  min-height: 86px;
  resize: vertical;
  padding: 9px 10px;
  line-height: 1.45;
}

.snapshot-release-gate {
  display: grid;
  gap: 9px;
  min-width: 0;
  padding: 11px;
  border: 1px solid var(--snapshot-border-strong);
  border-radius: 8px;
  background:
    linear-gradient(180deg, rgba(255, 252, 245, 0.86), rgba(248, 240, 224, 0.72)),
    var(--snapshot-surface);
}

.snapshot-release-gate--ready {
  border-color: rgba(139, 94, 52, 0.34);
  box-shadow: inset 4px 0 0 var(--snapshot-accent);
}

.snapshot-release-gate--blocked,
.snapshot-release-gate--loading {
  border-color: rgba(90, 51, 25, 0.3);
  box-shadow: inset 4px 0 0 var(--snapshot-strong);
}

.snapshot-gate-head {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.snapshot-gate-head span {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.snapshot-gate-head b {
  color: var(--snapshot-ink);
  font-size: 18px;
  font-weight: 950;
  line-height: 1;
}

.snapshot-gate-head em {
  flex: 0 0 auto;
  padding: 4px 7px;
  border: 1px solid rgba(139, 94, 52, 0.2);
  border-radius: 999px;
  background: rgba(139, 94, 52, 0.08);
  color: var(--snapshot-strong);
  font-size: 10px;
  font-style: normal;
  font-weight: 900;
}

.snapshot-release-gate p {
  margin: 0;
  color: var(--snapshot-strong);
  font-size: 12px;
  font-weight: 850;
  line-height: 1.45;
}

.snapshot-evidence-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  min-width: 0;
}

.snapshot-evidence-item {
  display: grid;
  gap: 3px;
  min-width: 0;
  min-height: 58px;
  padding: 8px 9px;
  border: 1px solid var(--snapshot-border);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.56);
}

.snapshot-evidence-item.is-ready {
  border-color: rgba(139, 94, 52, 0.32);
  background: rgba(139, 94, 52, 0.07);
}

.snapshot-evidence-item.is-blocked {
  border-color: rgba(90, 51, 25, 0.34);
  background: rgba(90, 51, 25, 0.08);
}

.snapshot-evidence-item b,
.snapshot-evidence-item em,
.snapshot-gate-issues b,
.snapshot-gate-issues em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.snapshot-evidence-item b {
  color: var(--snapshot-ink);
  font-size: 12px;
  font-weight: 950;
}

.snapshot-evidence-item em,
.snapshot-gate-issues em {
  color: var(--snapshot-muted);
  font-size: 10px;
  font-style: normal;
  font-weight: 850;
}

.snapshot-gate-issues {
  display: grid;
  gap: 6px;
  min-width: 0;
  padding: 8px;
  border: 1px solid rgba(90, 51, 25, 0.24);
  border-radius: 7px;
  background: rgba(90, 51, 25, 0.07);
}

.snapshot-gate-issues span {
  display: grid;
  grid-template-columns: 44px minmax(86px, 0.32fr) minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  min-width: 0;
}

.snapshot-gate-issues b {
  color: var(--snapshot-strong);
  font-size: 11px;
  font-weight: 950;
}

.snapshot-disable-reasons,
.snapshot-attention-reasons {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
  padding: 8px;
  border: 1px solid rgba(139, 94, 52, 0.18);
  border-radius: 7px;
  background: rgba(255, 252, 245, 0.56);
}

.snapshot-disable-reasons small,
.snapshot-attention-reasons small {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
}

.snapshot-disable-reasons span,
.snapshot-attention-reasons span {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  min-height: 22px;
  padding: 0 7px;
  border-radius: 999px;
  background: rgba(90, 51, 25, 0.08);
  color: var(--snapshot-strong);
  font-size: 11px;
  font-weight: 850;
}

.snapshot-attention-reasons span {
  background: rgba(139, 94, 52, 0.08);
  color: var(--snapshot-accent);
}

.snapshot-metrics span {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid var(--snapshot-border);
  border-radius: 7px;
  background: var(--snapshot-soft);
}

.snapshot-metrics b,
.snapshot-delta-row span,
.snapshot-chip-list b {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.snapshot-unrankable-evidence {
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--snapshot-border);
  border-radius: 8px;
  background: rgba(255, 252, 245, 0.5);
}

.snapshot-unrankable-list {
  display: grid;
  gap: 7px;
  min-width: 0;
}

.snapshot-unrankable-list span {
  display: grid;
  grid-template-columns: minmax(130px, 0.72fr) minmax(0, 1fr) minmax(72px, auto);
  gap: 8px;
  align-items: center;
  min-width: 0;
  padding: 8px 9px;
  border: 1px solid rgba(139, 94, 52, 0.16);
  border-radius: 7px;
  background: rgba(139, 94, 52, 0.06);
}

.snapshot-unrankable-list b,
.snapshot-unrankable-list small,
.snapshot-unrankable-list em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.snapshot-unrankable-list b {
  color: var(--snapshot-ink);
  font-size: 12px;
  font-weight: 900;
}

.snapshot-unrankable-list em {
  color: var(--snapshot-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 850;
  text-align: right;
}

.snapshot-list {
  display: grid;
  gap: 7px;
  max-height: 244px;
  overflow: auto;
}

.snapshot-list-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  width: 100%;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid var(--snapshot-border);
  border-radius: 7px;
  background: var(--snapshot-soft);
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.snapshot-list-row.active {
  border-color: var(--snapshot-accent);
  background: rgba(139, 94, 52, 0.1);
  box-shadow: inset 3px 0 0 var(--snapshot-accent);
}

.snapshot-list-row span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.snapshot-list-row b {
  min-width: 0;
  overflow: hidden;
  color: var(--snapshot-ink);
  font-size: 12px;
  font-weight: 950;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.snapshot-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.snapshot-metrics b {
  color: var(--snapshot-ink);
  font-size: 20px;
  font-weight: 950;
  line-height: 1;
}

.tone-green {
  border-left: 4px solid var(--snapshot-accent) !important;
}

.tone-blue {
  border-left: 4px solid var(--snapshot-strong) !important;
}

.tone-red {
  border-left: 4px solid var(--snapshot-danger) !important;
}

.snapshot-delta-table {
  display: grid;
  overflow: hidden;
  border: 1px solid var(--snapshot-border);
  border-radius: 7px;
}

.snapshot-delta-row {
  display: grid;
  grid-template-columns: minmax(190px, 1fr) 70px 70px 62px;
  gap: 8px;
  align-items: center;
  min-width: 0;
  min-height: 36px;
  padding: 7px 9px;
  border-top: 1px solid var(--snapshot-border);
  background: var(--snapshot-surface-strong);
}

.snapshot-delta-row:first-child {
  border-top: 0;
}

.snapshot-delta-head {
  min-height: 30px;
  background: var(--snapshot-soft);
  color: var(--snapshot-muted);
  font-size: 10px;
  font-weight: 950;
  text-transform: uppercase;
}

.snapshot-delta-row span {
  display: grid;
  gap: 2px;
}

.snapshot-delta-row b {
  color: var(--snapshot-ink);
  font-size: 12px;
  font-weight: 950;
}

.snapshot-delta-row strong {
  font-size: 12px;
  font-weight: 950;
  text-align: right;
}

.positive {
  color: var(--snapshot-accent);
}

.negative {
  color: var(--snapshot-danger);
}

.snapshot-chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.snapshot-chip-list span {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  min-height: 28px;
  padding: 0 8px;
  border: 1px solid rgba(139, 94, 52, 0.24);
  border-radius: 7px;
  background: rgba(139, 94, 52, 0.08);
}

.snapshot-chip-list.removed span {
  border-color: rgba(90, 51, 25, 0.24);
  background: rgba(90, 51, 25, 0.08);
}

.snapshot-chip-list b {
  color: var(--snapshot-ink);
  font-size: 12px;
  font-weight: 900;
}

.snapshot-empty {
  margin: 0;
  padding: 14px;
  border: 1px dashed var(--snapshot-border-strong);
  border-radius: 7px;
  background: var(--snapshot-soft);
  color: var(--snapshot-muted);
  font-size: 12px;
  font-weight: 800;
  line-height: 1.45;
}

.snapshot-empty.small {
  padding: 10px;
}
</style>
