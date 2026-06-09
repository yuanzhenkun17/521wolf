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

const snapshots = computed(() => props.benchmark.benchmarkSnapshots.value || [])
const selectedSnapshot = computed(() => props.benchmark.activeBenchmarkSnapshotDetail.value || null)
const compare = computed(() => props.benchmark.benchmarkSnapshotCompare.value || {})
const currentRows = computed(() => props.benchmark.normalizedCurrentBenchmarkLeaderboardRows.value || [])
const snapshotRows = computed(() => selectedSnapshot.value?.rows || [])
const snapshotSummary = computed(() => selectedSnapshot.value?.summary || {})
const isModel = computed(() => props.benchmark.selectedBenchmarkIsModelSuite.value)
const isLoading = computed(() => Boolean(props.benchmark.benchmarkSnapshotLoading.value))
const canCreate = computed(() =>
  !isLoading.value &&
  currentRows.value.length > 0 &&
  (isModel.value || Boolean(props.benchmark.selectedRole.value))
)

const scopeLabel = computed(() =>
  isModel.value ? 'scope=model' : `${props.benchmark.selectedRoleLabel.value} role-version`
)
const defaultTitle = computed(() => {
  const suite = props.benchmark.selectedBenchmarkSuiteLabel.value || 'Benchmark'
  const subject = isModel.value ? 'Model' : props.benchmark.selectedRoleLabel.value
  return `${suite} / ${subject} release`
})
const latestSnapshot = computed(() => snapshots.value[0] || null)
const diffRows = computed(() => [
  { label: 'Changed', value: compare.value.changed?.length || 0, tone: 'blue' },
  { label: 'Added', value: compare.value.added?.length || 0, tone: 'green' },
  { label: 'Removed', value: compare.value.removed?.length || 0, tone: 'red' },
  { label: 'Frozen Rows', value: snapshotRows.value.length, tone: 'neutral' }
])
const topChangedRows = computed(() => (compare.value.changed || []).slice(0, 8))
const topAddedRows = computed(() => (compare.value.added || []).slice(0, 6))
const topRemovedRows = computed(() => (compare.value.removed || []).slice(0, 6))
const selectedSnapshotId = computed(() => props.benchmark.selectedBenchmarkSnapshotId.value || '')
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

function downloadSnapshot(format) {
  const text = format === 'json'
    ? selectedSnapshotJson.value
    : (format === 'delta-csv' ? snapshotDeltaCsv.value : selectedSnapshotCsv.value)
  if (!text) return
  const extension = format === 'json' ? 'json' : 'csv'
  const mime = format === 'json' ? 'application/json' : 'text/csv'
  const suffix = format === 'delta-csv' ? 'delta' : 'snapshot'
  if (downloadText(`${safeFilename(selectedSnapshotId.value || 'benchmark-snapshot')}-${suffix}.${extension}`, text, mime)) {
    exportState.value = `${format.toUpperCase()} exported`
    clearTransientState()
  }
}

async function copySnapshot(format) {
  const text = format === 'json' ? selectedSnapshotJson.value : selectedSnapshotCsv.value
  if (!text || typeof navigator === 'undefined' || !navigator.clipboard?.writeText) return
  try {
    await navigator.clipboard.writeText(text)
    exportState.value = `${format.toUpperCase()} copied`
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
  <section class="benchmark-snapshot-panel" aria-label="Benchmark snapshot release panel">
    <header class="snapshot-header">
      <div>
        <small>Release Snapshots</small>
        <h2>Freeze leaderboard evidence</h2>
        <p>{{ props.benchmark.selectedBenchmarkSuiteLabel.value }} / {{ scopeLabel }}</p>
      </div>
      <div class="snapshot-header-actions">
        <button type="button" class="snapshot-secondary-button" @click="refreshSnapshots">
          Refresh
        </button>
        <button
          type="button"
          class="snapshot-primary-button"
          :disabled="!canCreate"
          @click="createSnapshot"
        >
          Freeze Snapshot
        </button>
      </div>
    </header>

    <div v-if="props.benchmark.benchmarkSnapshotError.value" class="snapshot-warning">
      {{ props.benchmark.benchmarkSnapshotError.value }}
    </div>

    <section class="snapshot-release-grid">
      <article class="snapshot-release-card">
        <div class="snapshot-section-title">
          <span>
            <small>Publish</small>
            <b>Release note</b>
          </span>
          <em>{{ currentRows.length }} current rows</em>
        </div>
        <label>
          <span>Title</span>
          <input v-model.trim="title" type="text" autocomplete="off" :placeholder="defaultTitle" />
        </label>
        <label>
          <span>Notes</span>
          <textarea
            v-model.trim="releaseNotes"
            rows="4"
            spellcheck="false"
            placeholder="Record what changed, why this suite is releasable, and any residual risk."
          />
        </label>
        <div class="snapshot-boundary">
          <span>
            <small>Evaluation Set</small>
            <b>{{ props.benchmark.selectedBenchmarkEvaluationSetId.value || 'ad-hoc' }}</b>
          </span>
          <span>
            <small>Scope</small>
            <b>{{ props.benchmark.benchmarkSnapshotScope.value }}</b>
          </span>
          <span>
            <small>Content Hash</small>
            <b>{{ latestSnapshot ? shortHash(latestSnapshot.content_hash) : 'not frozen yet' }}</b>
          </span>
        </div>
      </article>

      <article class="snapshot-history-card">
        <div class="snapshot-section-title">
          <span>
            <small>History</small>
            <b>Frozen leaderboard versions</b>
          </span>
          <em>{{ snapshots.length }} snapshots</em>
        </div>
        <div v-if="snapshots.length" class="snapshot-list">
          <button
            v-for="snapshot in snapshots"
            :key="snapshot.snapshot_id"
            type="button"
            :class="['snapshot-list-row', { active: snapshot.snapshot_id === selectedSnapshotId }]"
            @click="selectSnapshot(snapshot)"
          >
            <span>
              <b>{{ snapshot.title }}</b>
              <small>{{ createdLabel(snapshot.created_at) }} / {{ snapshot.row_count }} rows</small>
            </span>
            <em>{{ shortHash(snapshot.content_hash) }}</em>
          </button>
        </div>
        <p v-else class="snapshot-empty">
          No release snapshot has been frozen for this suite boundary.
        </p>
      </article>
    </section>

    <section class="snapshot-compare-grid">
      <article class="snapshot-summary-card">
        <div class="snapshot-section-title">
          <span>
            <small>Selected Snapshot</small>
            <b>{{ selectedSnapshot?.title || 'No snapshot selected' }}</b>
          </span>
          <em>{{ selectedSnapshot ? createdLabel(selectedSnapshot.created_at) : '--' }}</em>
        </div>
        <div class="snapshot-export-row">
          <button type="button" :disabled="!selectedSnapshot" @click="copySnapshot('json')">Copy JSON</button>
          <button type="button" :disabled="!selectedSnapshot" @click="copySnapshot('csv')">Copy CSV</button>
          <button type="button" :disabled="!selectedSnapshot" @click="downloadSnapshot('json')">JSON</button>
          <button type="button" :disabled="!selectedSnapshot" @click="downloadSnapshot('csv')">CSV</button>
          <button type="button" :disabled="!selectedSnapshot" @click="downloadSnapshot('delta-csv')">Delta CSV</button>
          <em>{{ exportState }}</em>
        </div>
        <div class="snapshot-metrics">
          <span v-for="item in diffRows" :key="item.label" :class="'tone-' + item.tone">
            <small>{{ item.label }}</small>
            <b>{{ formatNumber(item.value) }}</b>
          </span>
        </div>
        <dl class="snapshot-audit">
          <div>
            <dt>Rankable</dt>
            <dd>{{ formatNumber(snapshotSummary.rankable_count) }}</dd>
          </div>
          <div>
            <dt>Benchmark</dt>
            <dd>{{ selectedSnapshot?.benchmark_id || props.benchmark.selectedBenchmarkId.value || 'ad-hoc' }}</dd>
          </div>
          <div>
            <dt>Seed Set</dt>
            <dd>{{ selectedSnapshot?.seed_set_id || props.benchmark.selectedBenchmarkSuite.value?.seed_set_id || 'ad-hoc' }}</dd>
          </div>
          <div>
            <dt>Config Hash</dt>
            <dd>{{ selectedSnapshot?.benchmark_config_hash || 'not reported' }}</dd>
          </div>
        </dl>
      </article>

      <article class="snapshot-delta-card">
        <div class="snapshot-section-title">
          <span>
            <small>Current vs Frozen</small>
            <b>Score deltas</b>
          </span>
          <em>{{ topChangedRows.length }} shown</em>
        </div>
        <div v-if="topChangedRows.length" class="snapshot-delta-table">
          <div class="snapshot-delta-row snapshot-delta-head">
            <span>Subject</span>
            <span>Score</span>
            <span>Win</span>
            <span>Games</span>
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
          Select a snapshot to compare, or freeze the current leaderboard to establish a release baseline.
        </p>
      </article>
    </section>

    <section class="snapshot-membership-grid">
      <article>
        <div class="snapshot-section-title compact">
          <span>
            <small>Added</small>
            <b>New current rows</b>
          </span>
          <em>{{ topAddedRows.length }}</em>
        </div>
        <div v-if="topAddedRows.length" class="snapshot-chip-list">
          <span v-for="row in topAddedRows" :key="'added-' + row.key">
            <b>{{ row.primary }}</b>
            <em>{{ formatPct(row.score) }}</em>
          </span>
        </div>
        <p v-else class="snapshot-empty small">No added rows.</p>
      </article>

      <article>
        <div class="snapshot-section-title compact">
          <span>
            <small>Removed</small>
            <b>Rows only in snapshot</b>
          </span>
          <em>{{ topRemovedRows.length }}</em>
        </div>
        <div v-if="topRemovedRows.length" class="snapshot-chip-list removed">
          <span v-for="row in topRemovedRows" :key="'removed-' + row.key">
            <b>{{ row.primary }}</b>
            <em>{{ formatPct(row.score) }}</em>
          </span>
        </div>
        <p v-else class="snapshot-empty small">No removed rows.</p>
      </article>
    </section>
  </section>
</template>

<style scoped>
.benchmark-snapshot-panel {
  --snapshot-ink: #202826;
  --snapshot-muted: #66736d;
  --snapshot-line: #d4ddd8;
  --snapshot-soft: #f4f7f6;
  --snapshot-panel: #ffffff;
  --snapshot-green: #1f6f54;
  --snapshot-blue: #235f7e;
  --snapshot-red: #a33b35;
  --snapshot-amber: #9a6518;
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
  border: 1px solid var(--snapshot-line);
  border-radius: 8px;
  background: var(--snapshot-panel);
}

.snapshot-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 16px;
  padding: 14px 16px;
  background:
    linear-gradient(90deg, rgba(35, 95, 126, 0.09), rgba(255, 255, 255, 0) 52%),
    var(--snapshot-panel);
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
  border: 1px solid var(--snapshot-green);
  border-radius: 7px;
  font-size: 12px;
  font-weight: 950;
  cursor: pointer;
}

.snapshot-primary-button {
  background: var(--snapshot-green);
  color: #ffffff;
}

.snapshot-secondary-button {
  background: #ffffff;
  color: var(--snapshot-green);
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
  background: #ffffff;
  color: var(--snapshot-green);
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

.snapshot-primary-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.snapshot-warning {
  padding: 9px 12px;
  border: 1px solid rgba(163, 59, 53, 0.25);
  border-radius: 8px;
  background: rgba(163, 59, 53, 0.06);
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
  border: 1px solid #cfd8d4;
  border-radius: 7px;
  background: #fbfcfc;
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

.snapshot-boundary span,
.snapshot-metrics span {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid #dbe3df;
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
  grid-template-columns: minmax(0, 1fr) 128px;
  gap: 10px;
  align-items: center;
  width: 100%;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid #dbe3df;
  border-radius: 7px;
  background: var(--snapshot-soft);
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.snapshot-list-row.active {
  border-color: var(--snapshot-green);
  background: #eef7f3;
  box-shadow: inset 3px 0 0 var(--snapshot-green);
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
  border-left: 4px solid var(--snapshot-green) !important;
}

.tone-blue {
  border-left: 4px solid var(--snapshot-blue) !important;
}

.tone-red {
  border-left: 4px solid var(--snapshot-red) !important;
}

.snapshot-audit {
  display: grid;
  gap: 6px;
  margin: 0;
}

.snapshot-audit div {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr);
  gap: 10px;
  align-items: baseline;
  min-width: 0;
  padding-top: 6px;
  border-top: 1px solid #e2e8e5;
}

.snapshot-audit div:first-child {
  border-top: none;
}

.snapshot-audit dd {
  margin: 0;
  color: var(--snapshot-ink);
  font-size: 12px;
  font-weight: 850;
}

.snapshot-delta-table {
  display: grid;
  overflow: hidden;
  border: 1px solid #dbe3df;
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
  border-top: 1px solid #e3e9e6;
  background: #ffffff;
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
  border: 1px solid rgba(31, 111, 84, 0.24);
  border-radius: 7px;
  background: rgba(31, 111, 84, 0.07);
}

.snapshot-chip-list.removed span {
  border-color: rgba(163, 59, 53, 0.24);
  background: rgba(163, 59, 53, 0.06);
}

.snapshot-chip-list b {
  color: var(--snapshot-ink);
  font-size: 12px;
  font-weight: 900;
}

.snapshot-empty {
  margin: 0;
  padding: 14px;
  border: 1px dashed #d6dfda;
  border-radius: 7px;
  background: #fbfcfc;
  color: var(--snapshot-muted);
  font-size: 12px;
  font-weight: 800;
  line-height: 1.45;
}

.snapshot-empty.small {
  padding: 10px;
}
</style>
