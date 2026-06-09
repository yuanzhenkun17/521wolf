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
const snapshotRows = computed(() => selectedSnapshot.value?.rows || [])
const selectedSnapshotAudit = computed(() => snapshotAudit(selectedSnapshot.value))
const isModel = computed(() => props.benchmark.selectedBenchmarkIsModelSuite.value)
const isLoading = computed(() => Boolean(props.benchmark.benchmarkSnapshotLoading.value))
const compareLoading = computed(() => Boolean(props.benchmark.benchmarkSnapshotCompareLoading?.value))
const compareError = computed(() => String(props.benchmark.benchmarkSnapshotCompareError?.value || ''))
const boundaryWarnings = computed(() => Array.isArray(compare.value.boundary_warnings) ? compare.value.boundary_warnings : [])
const boundaryWarningLabels = computed(() => boundaryWarnings.value.map(warningLabel).filter(Boolean))
const compareSourceLabel = computed(() => {
  if (compareAgainstSnapshotId.value) return props.benchmark.benchmarkSnapshotServerCompare?.value ? '服务端快照对比' : '本地快照对比'
  if (props.benchmark.benchmarkSnapshotServerCompare?.value) return '服务端标准对比'
  if (compareLoading.value) return '正在加载对比'
  if (compareError.value) return '本地回退对比'
  return '本地对比'
})
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
const canCreate = computed(() =>
  !isLoading.value &&
  currentRows.value.length > 0 &&
  (isModel.value || Boolean(props.benchmark.selectedRole.value))
)

const scopeLabel = computed(() =>
  isModel.value ? '模型范围' : `${props.benchmark.selectedRoleLabel.value} 角色版本`
)
const defaultTitle = computed(() => {
  const suite = props.benchmark.selectedBenchmarkSuiteLabel.value || '基准'
  const subject = isModel.value ? '模型' : props.benchmark.selectedRoleLabel.value
  return `${suite} / ${subject} 发布快照`
})
const latestSnapshot = computed(() => snapshots.value[0] || null)
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

function refreshSnapshots() {
  props.benchmark.loadBenchmarkSnapshots()
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
      summary: snapshot.summary || {}
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

function snapshotHistoryCountLabel(snapshot) {
  const audit = snapshotAudit(snapshot)
  return [
    `行 ${formatNumber(audit.rowCount)}`,
    `可排名 ${formatNumber(audit.rankableCount)}`,
    `不可排名 ${formatNumber(audit.unrankableCount)}`
  ].join(' / ')
}

function snapshotSourceSummary(snapshot) {
  const audit = snapshotAudit(snapshot)
  const parts = [
    sourceCountText(audit.runCount, 'run'),
    sourceCountText(audit.reportCount, 'report'),
    sourceCountText(audit.resultBatchCount, 'batch', 'batches')
  ].filter((label) => label !== '未上报')
  return parts.length ? parts.join(' / ') : '来源未上报'
}

function sourceCountText(count, singular, plural = `${singular}s`) {
  if (count == null || count === '') return '未上报'
  const number = Number(count)
  if (!Number.isFinite(number)) return '未上报'
  const labelMap = {
    run: '运行',
    runs: '运行',
    report: '报告',
    reports: '报告',
    batch: '批次',
    batches: '批次'
  }
  return `${formatNumber(number)} ${labelMap[number === 1 ? singular : plural] || labelMap[singular] || singular}`
}

function sourceIdsPreview(ids) {
  if (!ids?.length) return '未上报关联 ID'
  const shown = ids.slice(0, 3).map(shortHash)
  const remaining = ids.length - shown.length
  return remaining > 0 ? `${shown.join(', ')} +${remaining}` : shown.join(', ')
}

function sourceIdsTitle(ids) {
  return ids?.length ? ids.join(', ') : ''
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
  if (format === 'delta-csv') return 'Delta CSV'
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
        <h2>冻结排行榜证据</h2>
        <p>{{ props.benchmark.selectedBenchmarkSuiteLabel.value }} / {{ scopeLabel }}</p>
      </div>
      <div class="snapshot-header-actions">
        <button type="button" class="snapshot-secondary-button" @click="refreshSnapshots">
          刷新
        </button>
        <button
          type="button"
          class="snapshot-primary-button"
          :disabled="!canCreate"
          @click="createSnapshot"
        >
          冻结快照
        </button>
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
        <div class="snapshot-boundary">
          <span>
            <small>评测集</small>
            <b>{{ props.benchmark.selectedBenchmarkEvaluationSetId.value || '临时' }}</b>
          </span>
          <span>
            <small>范围</small>
            <b>{{ props.benchmark.benchmarkSnapshotScope.value }}</b>
          </span>
          <span>
            <small>Content Hash</small>
            <b>{{ latestSnapshot ? shortHash(latestSnapshot.content_hash) : '尚未冻结' }}</b>
          </span>
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
              <small class="snapshot-source-line">{{ snapshotSourceSummary(snapshot) }}</small>
            </span>
            <span class="snapshot-list-meta">
              <small>Content Hash</small>
              <em :title="snapshot.content_hash || ''">{{ shortHash(snapshot.content_hash) }}</em>
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
          <button type="button" :disabled="!selectedSnapshot" @click="downloadSnapshot('delta-csv')">Delta CSV</button>
          <em>{{ exportState }}</em>
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
        <div class="snapshot-boundary compare-boundary">
          <span>
            <small>对比来源</small>
            <b>{{ compareSourceLabel }}</b>
          </span>
          <span>
            <small>边界告警</small>
            <b>{{ boundaryWarningLabels.length ? boundaryWarningLabels.join(', ') : '无' }}</b>
          </span>
        </div>
        <dl class="snapshot-audit">
          <div>
            <dt>行数</dt>
            <dd>
              <b>{{ formatNumber(selectedSnapshotAudit.rowCount) }}</b>
              <small>
                {{ formatNumber(selectedSnapshotAudit.rankableCount) }} 可排名 /
                {{ formatNumber(selectedSnapshotAudit.unrankableCount) }} 不可排名
              </small>
            </dd>
          </div>
          <div>
            <dt>Content Hash</dt>
            <dd class="snapshot-code-value" :title="selectedSnapshotAudit.contentHash">
              {{ selectedSnapshotAudit.contentHash || '未上报' }}
            </dd>
          </div>
          <div>
            <dt>运行</dt>
            <dd>
              <b>{{ sourceCountText(selectedSnapshotAudit.runCount, 'run') }}</b>
              <small :title="sourceIdsTitle(selectedSnapshotAudit.runIds)">
                {{ sourceIdsPreview(selectedSnapshotAudit.runIds) }}
              </small>
            </dd>
          </div>
          <div>
            <dt>报告</dt>
            <dd>
              <b>{{ sourceCountText(selectedSnapshotAudit.reportCount, 'report') }}</b>
              <small :title="sourceIdsTitle(selectedSnapshotAudit.reportIds)">
                {{ sourceIdsPreview(selectedSnapshotAudit.reportIds) }}
              </small>
            </dd>
          </div>
          <div>
            <dt>结果批次</dt>
            <dd>
              <b>{{ sourceCountText(selectedSnapshotAudit.resultBatchCount, 'batch', 'batches') }}</b>
              <small :title="sourceIdsTitle(selectedSnapshotAudit.resultBatchIds)">
                {{ sourceIdsPreview(selectedSnapshotAudit.resultBatchIds) }}
              </small>
            </dd>
          </div>
          <div>
            <dt>基准</dt>
            <dd>
              <b>{{ selectedSnapshot?.benchmark_id || props.benchmark.selectedBenchmarkId.value || '临时' }}</b>
            </dd>
          </div>
          <div>
            <dt>Seed Set</dt>
            <dd>
              <b>{{ selectedSnapshot?.seed_set_id || props.benchmark.selectedBenchmarkSuite.value?.seed_set_id || '临时' }}</b>
            </dd>
          </div>
          <div>
            <dt>Config Hash</dt>
            <dd class="snapshot-code-value" :title="selectedSnapshot?.benchmark_config_hash || ''">
              {{ selectedSnapshot?.benchmark_config_hash || '未上报' }}
            </dd>
          </div>
        </dl>
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
  --snapshot-bg: #f8f0e0;
  --snapshot-surface: rgba(255, 252, 245, 0.7);
  --snapshot-surface-strong: rgba(255, 252, 245, 0.92);
  --snapshot-border: rgba(139, 94, 52, 0.15);
  --snapshot-border-strong: rgba(139, 94, 52, 0.28);
  --snapshot-ink: #3a2a18;
  --snapshot-muted: #8b6b4a;
  --snapshot-accent: #8b5e34;
  --snapshot-strong: #5a3319;
  --snapshot-soft: rgba(248, 240, 224, 0.66);
  --snapshot-green: #8b5e34;
  --snapshot-blue: #5a3319;
  --snapshot-red: #5a3319;
  --snapshot-amber: #8b6b4a;
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

.snapshot-header p {
  margin: 4px 0 0;
  color: var(--snapshot-muted);
  font-size: 12px;
  font-weight: 800;
}

.snapshot-header small,
.snapshot-section-title small,
.snapshot-release-card label span,
.snapshot-boundary small,
.snapshot-list-row small,
.snapshot-metrics small,
.snapshot-audit dt,
.snapshot-delta-row small {
  color: var(--snapshot-muted);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.snapshot-header-actions {
  display: flex;
  gap: 8px;
}

.snapshot-primary-button,
.snapshot-secondary-button,
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

.snapshot-secondary-button {
  background: var(--snapshot-surface-strong);
  color: var(--snapshot-strong);
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
  color: var(--snapshot-red);
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

.snapshot-boundary {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 0.72fr) minmax(0, 0.9fr);
  gap: 8px;
}

.compare-boundary {
  grid-template-columns: minmax(0, 0.65fr) minmax(0, 1.35fr);
  margin: 10px 0;
}

.snapshot-boundary span,
.snapshot-metrics span {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid var(--snapshot-border);
  border-radius: 7px;
  background: var(--snapshot-soft);
}

.snapshot-boundary b,
.snapshot-metrics b,
.snapshot-audit dd,
.snapshot-delta-row span,
.snapshot-chip-list b {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.snapshot-boundary b {
  color: var(--snapshot-ink);
  font-size: 12px;
  font-weight: 900;
}

.snapshot-list {
  display: grid;
  gap: 7px;
  max-height: 244px;
  overflow: auto;
}

.snapshot-list-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(142px, 0.36fr);
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

.snapshot-list-meta {
  justify-items: end;
  text-align: right;
}

.snapshot-source-line {
  color: var(--snapshot-strong) !important;
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
  border-left: 4px solid var(--snapshot-red) !important;
}

.snapshot-audit {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 14px;
  margin: 0;
}

.snapshot-audit div {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr);
  gap: 10px;
  align-items: baseline;
  min-width: 0;
  min-height: 34px;
  padding: 7px 0;
  border-top: 1px solid var(--snapshot-border);
}

.snapshot-audit div:nth-child(-n + 2) {
  border-top: none;
}

.snapshot-audit dd {
  display: grid;
  gap: 2px;
  margin: 0;
  color: var(--snapshot-ink);
  font-size: 12px;
  font-weight: 850;
}

.snapshot-audit dd b,
.snapshot-audit dd small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.snapshot-audit dd small {
  color: var(--snapshot-muted);
  font-size: 10px;
  font-weight: 850;
}

.snapshot-code-value {
  display: block !important;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  font-size: 11px !important;
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
  color: var(--snapshot-green);
}

.negative {
  color: var(--snapshot-red);
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
