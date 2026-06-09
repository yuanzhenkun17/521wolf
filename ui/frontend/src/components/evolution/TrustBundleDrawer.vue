<script setup>
import { computed } from 'vue'

const props = defineProps({
  evo: { type: Object, required: true }
})

const open = computed(() => Boolean(props.evo.trustBundleDrawerOpen?.value))
const audit = computed(() => props.evo.trustBundleAudit?.value || {})
const loading = computed(() => Boolean(props.evo.trustBundleAuditLoading?.value))
const authorityMessage = computed(() => props.evo.trustBundleAuditError?.value || audit.value.authorityMessage || '')
const completeness = computed(() => audit.value.completeness || {})
const missingLabels = computed(() => audit.value.missingLabels || [])
const trainingEvidence = computed(() => audit.value.training_evidence || [])
const proposalEvidence = computed(() => audit.value.proposal_evidence || [])
const trainingGameIds = computed(() => audit.value.training_game_ids || trainingEvidence.value.map((row) => row.id))
const proposalIds = computed(() => audit.value.proposal_ids || proposalEvidence.value.map((row) => row.id))
const pairedSeeds = computed(() => audit.value.paired_seeds || [])

const trainingRows = computed(() => trainingEvidence.value.length
  ? trainingEvidence.value.slice(0, 16)
  : trainingGameIds.value.slice(0, 16).map((id) => ({ id, href: '' }))
)
const proposalRows = computed(() => proposalEvidence.value.length
  ? proposalEvidence.value.slice(0, 16)
  : proposalIds.value.slice(0, 16).map((id) => ({ id, href: '' }))
)
const seedRows = computed(() => pairedSeeds.value.slice(0, 12).map(normalizeSeedRow))
const authorityClass = computed(() => `status-${audit.value.authorityStatus || 'cached'}`)
const authorityLabel = computed(() => ({
  cached: '缓存',
  loading: '读取中',
  verified: '已校验',
  mismatch: '不一致',
  unavailable: '不可用'
}[audit.value.authorityStatus || 'cached'] || '缓存'))
const mismatchLabels = computed(() => audit.value.mismatchLabels || [])
const consistencyChecks = computed(() => audit.value.consistency_checks || audit.value.consistencyChecks || [])
const consistencySummary = computed(() => {
  const rows = consistencyChecks.value
  const mismatches = rows.filter((row) => row.status === 'mismatch').length
  const missing = rows.filter((row) => row.status === 'missing').length
  const unknown = rows.filter((row) => row.status === 'unknown').length
  if (mismatches) return `${mismatches} mismatch`
  if (missing) return `${missing} missing`
  if (unknown) return `${unknown} unknown`
  return rows.length ? 'ok' : '—'
})

function display(value, fallback = '—') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function textValue(...values) {
  for (const value of values) {
    const text = String(value ?? '').trim()
    if (text) return text
  }
  return ''
}

function seedGameId(seed, side) {
  const prefix = side === 'candidate' ? 'candidate' : 'baseline'
  const nested = seed?.[prefix] || seed?.[`${prefix}_result`] || {}
  return textValue(
    seed?.[`${prefix}GameId`],
    seed?.[`${prefix}_game_id`],
    nested.game_id,
    nested.gameId
  )
}

function seedGameHref(gameId) {
  const id = textValue(gameId)
  if (!id) return ''
  return `#logs?${new URLSearchParams({ game_id: id, workspace: 'archive' }).toString()}`
}

function rankableLabel(seed) {
  const value = seed?.rankable ?? seed?.rankableStatus ?? seed?.rankable_status
  if (value == null || value === '') return ''
  if (typeof value === 'boolean') return value ? '可入榜' : '未入榜'
  const text = textValue(value)
  const normalized = text.toLowerCase()
  return {
    true: '可入榜',
    rankable: '可入榜',
    eligible: '可入榜',
    false: '未入榜',
    unrankable: '未入榜',
    ineligible: '未入榜',
    failed: '未入榜'
  }[normalized] || text
}

function seedStatusLabel(seed) {
  const text = textValue(seed?.status, seed?.result, seed?.outcome, seed?.pair_status)
  const normalized = text.toLowerCase()
  return {
    pass: '通过',
    passed: '通过',
    success: '通过',
    completed: '完成',
    rankable: '可入榜',
    fail: '失败',
    failed: '失败',
    error: '失败',
    timeout: '超时',
    unrankable: '未入榜'
  }[normalized] || text
}

function failureReason(seed) {
  const failure = seed?.failure || seed?.diagnostic || {}
  return textValue(
    seed?.failureReason,
    seed?.failure_reason,
    seed?.rankableReason,
    seed?.rankable_reason,
    seed?.reason,
    seed?.error,
    failure.reason,
    failure.failure_reason,
    failure.message
  )
}

function seedAuditBadges(seed) {
  const badges = []
  const rankable = rankableLabel(seed)
  const status = seedStatusLabel(seed)
  const failure = failureReason(seed)

  if (rankable) {
    badges.push({
      key: 'rankable',
      label: 'rankable',
      value: rankable,
      tone: rankable === '未入榜' ? 'warn' : 'ok'
    })
  }
  if (status && status !== rankable) {
    badges.push({
      key: 'status',
      label: 'status',
      value: status,
      tone: ['失败', '超时', '未入榜'].includes(status) ? 'warn' : 'neutral'
    })
  }
  if (failure) {
    badges.push({
      key: 'failure',
      label: 'failure',
      value: failure,
      tone: 'danger'
    })
  }
  return badges
}

function normalizeSeedRow(seed, index) {
  const record = seed && typeof seed === 'object' ? seed : { seed }
  const baselineGameId = seedGameId(record, 'baseline')
  const candidateGameId = seedGameId(record, 'candidate')
  return {
    ...record,
    key: record.id || record.pair_id || record.seed || record.battle_seed || index,
    baselineGameId,
    candidateGameId,
    baselineGameHref: seedGameHref(baselineGameId),
    candidateGameHref: seedGameHref(candidateGameId),
    auditBadges: seedAuditBadges(record)
  }
}

function scoreLabel(value) {
  if (value == null || value === '') return '—'
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return number <= 1 ? `${Math.round(number * 100)}%` : String(Math.round(number * 100) / 100)
}

function numberLabel(value) {
  if (value == null || value === '') return '—'
  const number = Number(value)
  if (!Number.isFinite(number)) return display(value)
  const fixed = Math.abs(number) < 1 ? number.toFixed(3) : number.toFixed(2)
  return Number(fixed).toString()
}

function consistencyStatusLabel(status) {
  return {
    match: '一致',
    mismatch: '不一致',
    missing: '缺失',
    unknown: '未知'
  }[String(status || 'unknown')] || '未知'
}

function close() {
  props.evo.closeTrustBundleDrawer?.()
}

async function refresh() {
  await props.evo.refreshTrustBundleAudit?.()
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="evo-trust-drawer-backdrop"
      @click.self="close"
    >
      <aside
        class="evo-trust-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Trust Bundle 审计"
      >
        <header class="evo-trust-drawer-head">
          <span>
            <small>{{ audit.sourceLabel || 'Trust Bundle' }}</small>
            <h2>Trust Bundle</h2>
          </span>
          <div class="evo-trust-drawer-actions">
            <button type="button" class="evo-ghost-action" :disabled="loading" @click="refresh">
              {{ loading ? '读取中' : '刷新' }}
            </button>
            <button type="button" class="evo-ghost-action" @click="close">关闭</button>
          </div>
        </header>

        <div :class="['evo-trust-authority', authorityClass]">
          <b>{{ authorityLabel }}</b>
          <span>{{ authorityMessage || '当前展示页面缓存中的 Trust Bundle。' }}</span>
          <em v-if="mismatchLabels.length">{{ mismatchLabels.join(' / ') }}</em>
        </div>

        <section v-if="consistencyChecks.length" class="evo-trust-section evo-trust-consistency">
          <header>
            <h3>Consistency Checks</h3>
            <b>{{ consistencySummary }}</b>
          </header>
          <div class="evo-trust-check-list">
            <article
              v-for="check in consistencyChecks"
              :key="check.field"
              :class="['evo-trust-check', `status-${check.status || 'unknown'}`]"
            >
              <div class="evo-trust-check-main">
                <span>
                  <small>{{ check.label || check.field }}</small>
                  <b>{{ consistencyStatusLabel(check.status) }}</b>
                </span>
                <p>{{ check.message || '—' }}</p>
              </div>
              <div
                v-if="check.cached_value || check.registry_value || check.source_run_value || check.authority_value"
                class="evo-trust-check-values"
              >
                <span v-if="check.cached_value">
                  <small>cached</small>
                  <code>{{ check.cached_value }}</code>
                </span>
                <span v-if="check.registry_value">
                  <small>registry</small>
                  <code>{{ check.registry_value }}</code>
                </span>
                <span v-if="check.source_run_value">
                  <small>source</small>
                  <code>{{ check.source_run_value }}</code>
                </span>
                <span v-if="check.authority_value">
                  <small>authority</small>
                  <code>{{ check.authority_value }}</code>
                </span>
              </div>
            </article>
          </div>
        </section>

        <div v-if="!audit.hasTrustBundle" class="evo-trust-empty">
          <strong>缺少 Trust Bundle</strong>
          <span>{{ audit.emptyMessage || '未收到 trust_bundle_id 或 bundle_hash。' }}</span>
        </div>

        <section class="evo-trust-field-grid">
          <span>
            <small>trust_bundle_id</small>
            <code>{{ display(audit.trust_bundle_id) }}</code>
          </span>
          <span>
            <small>bundle_hash</small>
            <code>{{ display(audit.bundle_hash) }}</code>
          </span>
          <span>
            <small>gate_report_id</small>
            <a v-if="audit.gate_report_href" :href="audit.gate_report_href">{{ display(audit.gate_report_id) }}</a>
            <code v-else>{{ display(audit.gate_report_id) }}</code>
          </span>
          <span>
            <small>rollback_target</small>
            <code>{{ display(audit.rollback_target) }}</code>
          </span>
          <span>
            <small>source_run_id</small>
            <a v-if="audit.source_run_href" :href="audit.source_run_href">{{ display(audit.source_run_id) }}</a>
            <code v-else>{{ display(audit.source_run_id) }}</code>
          </span>
          <span>
            <small>version_id</small>
            <a v-if="audit.version_href" :href="audit.version_href">{{ display(audit.version_id) }}</a>
            <code v-else>{{ display(audit.version_id) }}</code>
          </span>
        </section>

        <section class="evo-trust-completeness" :data-status="completeness.status || 'unknown'">
          <span>
            <small>Completeness</small>
            <b>{{ completeness.statusLabel || '未上报' }}</b>
          </span>
          <span>
            <small>Score</small>
            <b>{{ scoreLabel(completeness.score) }}</b>
          </span>
          <div>
            <small>Missing</small>
            <div v-if="missingLabels.length" class="evo-trust-chip-row">
              <span v-for="label in missingLabels" :key="label">{{ label }}</span>
            </div>
            <b v-else>—</b>
          </div>
        </section>

        <section class="evo-trust-section">
          <header>
            <h3>Training Evidence</h3>
            <b>{{ trainingGameIds.length }}</b>
          </header>
          <div v-if="trainingRows.length" class="evo-trust-id-grid">
            <template v-for="row in trainingRows" :key="`train-${row.id}`">
              <a v-if="row.href" :href="row.href">{{ row.id }}</a>
              <code v-else>{{ row.id }}</code>
            </template>
            <span v-if="trainingGameIds.length > trainingRows.length">+{{ trainingGameIds.length - trainingRows.length }}</span>
          </div>
          <div v-else class="evo-trust-muted">未上报训练证据</div>
        </section>

        <section class="evo-trust-section">
          <header>
            <h3>Proposal Evidence</h3>
            <b>{{ proposalIds.length }}</b>
          </header>
          <div v-if="proposalRows.length" class="evo-trust-id-grid">
            <template v-for="row in proposalRows" :key="`proposal-${row.id}`">
              <a v-if="row.href" :href="row.href">{{ row.id }}</a>
              <code v-else>{{ row.id }}</code>
            </template>
            <span v-if="proposalIds.length > proposalRows.length">+{{ proposalIds.length - proposalRows.length }}</span>
          </div>
          <div v-else class="evo-trust-muted">未上报提案证据</div>
        </section>

        <section class="evo-trust-section">
          <header>
            <h3>Paired Seeds</h3>
            <b>{{ pairedSeeds.length }}</b>
          </header>
          <div v-if="seedRows.length" class="evo-trust-seed-table">
            <span>Seed</span>
            <span>基线</span>
            <span>候选</span>
            <span>差值</span>
            <span>胜方</span>
            <span>基线局</span>
            <span>候选局</span>
            <span>审计</span>
            <template v-for="seed in seedRows" :key="seed.key">
              <code>{{ display(seed.seed) }}</code>
              <span>{{ numberLabel(seed.baselineScore) }}</span>
              <span>{{ numberLabel(seed.candidateScore) }}</span>
              <b>{{ numberLabel(seed.scoreDelta) }}</b>
              <span>{{ display(seed.winnerSide) }}</span>
              <a v-if="seed.baselineGameHref" :href="seed.baselineGameHref">{{ seed.baselineGameId }}</a>
              <code v-else>{{ display(seed.baselineGameId) }}</code>
              <a v-if="seed.candidateGameHref" :href="seed.candidateGameHref">{{ seed.candidateGameId }}</a>
              <code v-else>{{ display(seed.candidateGameId) }}</code>
              <div class="evo-trust-seed-audit">
                <span
                  v-for="badge in seed.auditBadges"
                  :key="badge.key"
                  :class="['evo-trust-seed-badge', `tone-${badge.tone}`]"
                  :title="badge.value"
                >
                  <small>{{ badge.label }}</small>
                  <b>{{ badge.value }}</b>
                </span>
              </div>
            </template>
          </div>
          <div v-else class="evo-trust-muted">未上报 paired seed 明细</div>
        </section>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.evo-trust-drawer-backdrop {
  --logbook-bg: #f2dfae;
  --logbook-bg-texture:
    repeating-linear-gradient(90deg, rgba(118, 71, 27, 0.024) 0 1px, transparent 1px 34px),
    var(--logbook-bg);
  --logbook-surface: rgba(255, 252, 245, 0.7);
  --logbook-border: rgba(139, 94, 52, 0.15);
  --logbook-text: #3a2a18;
  --logbook-muted: #8b6b4a;
  --logbook-accent: #8b5e34;
  --logbook-accent-strong: #5a3319;
  --logbook-input-bg: rgba(255, 255, 250, 0.8);
  --logbook-danger: #993026;
  --evo-bg: var(--logbook-bg);
  --evo-bg-texture: var(--logbook-bg-texture);
  --evo-border: var(--logbook-border, rgba(139, 94, 52, 0.15));
  --evo-text: var(--logbook-text, #3a2a18);
  --evo-text-secondary: var(--logbook-muted, #8b6b4a);
  --evo-accent: var(--logbook-accent, #8b5e34);
  --evo-accent-strong: var(--logbook-accent-strong, #5a3319);
  --evo-card-bg: var(--logbook-surface);
  --evo-input-bg: var(--logbook-input-bg, rgba(255, 255, 250, 0.8));
  --evo-success: var(--evo-accent, var(--logbook-accent, #8b5e34));
  --evo-success-bg: rgba(211, 190, 112, 0.2);
  --evo-success-border: rgba(117, 91, 31, 0.28);
  --evo-danger: var(--logbook-danger, #993026);
  --evo-danger-bg: rgba(248, 205, 181, 0.6);
  --evo-danger-border: rgba(154, 45, 36, 0.3);
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  justify-content: flex-end;
  background: rgba(38, 29, 19, 0.34);
}

.evo-trust-drawer {
  box-sizing: border-box;
  display: grid;
  align-content: start;
  gap: 14px;
  width: min(540px, 100vw);
  max-height: 100vh;
  overflow: auto;
  padding: 18px;
  border-left: 1px solid var(--evo-border, rgba(58, 42, 24, 0.16));
  background: var(--evo-bg-texture);
  box-shadow: -18px 0 42px rgba(38, 29, 19, 0.2);
}

.evo-trust-drawer-head,
.evo-trust-section header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.evo-trust-drawer-head span {
  min-width: 0;
}

.evo-trust-drawer-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
}

.evo-trust-drawer-head small,
.evo-trust-field-grid small,
.evo-trust-completeness small,
.evo-trust-section header b {
  color: var(--evo-text-secondary, #756957);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}

.evo-trust-drawer-head h2,
.evo-trust-section h3 {
  margin: 0;
  color: var(--evo-text, #2f261c);
  font-size: 16px;
  font-weight: 850;
}

.evo-trust-section h3 {
  font-size: 12px;
}

.evo-trust-empty {
  display: grid;
  gap: 3px;
  padding: 10px 12px;
  border: 1px solid rgba(139, 58, 42, 0.22);
  border-radius: 8px;
  background: rgba(139, 58, 42, 0.06);
  color: var(--evo-text, #2f261c);
}

.evo-trust-empty strong {
  font-size: 12px;
  font-weight: 850;
}

.evo-trust-empty span,
.evo-trust-muted {
  color: var(--evo-text-secondary, #756957);
  font-size: 12px;
}

.evo-trust-authority {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 4px 8px;
  align-items: center;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid rgba(139, 108, 50, 0.22);
  border-radius: 8px;
  background: rgba(139, 108, 50, 0.055);
}

.evo-trust-authority b {
  color: var(--evo-accent-strong, #7b4d1f);
  font-size: 11px;
  font-weight: 850;
}

.evo-trust-authority span,
.evo-trust-authority em {
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--evo-text-secondary, #756957);
  font-size: 12px;
  font-style: normal;
}

.evo-trust-authority em {
  grid-column: 2;
  font-size: 11px;
  font-weight: 800;
}

.evo-trust-authority.status-verified {
  border-color: var(--evo-success-border);
  background: var(--evo-success-bg);
}

.evo-trust-authority.status-mismatch,
.evo-trust-authority.status-unavailable {
  border-color: rgba(139, 58, 42, 0.24);
  background: rgba(139, 58, 42, 0.055);
}

.evo-trust-consistency {
  gap: 8px;
}

.evo-trust-check-list {
  display: grid;
  gap: 6px;
}

.evo-trust-check {
  display: grid;
  gap: 6px;
  min-width: 0;
  padding: 8px;
  border: 1px solid rgba(139, 108, 50, 0.2);
  border-radius: 7px;
  background: rgba(139, 108, 50, 0.045);
}

.evo-trust-check-main {
  display: grid;
  grid-template-columns: minmax(96px, 0.42fr) minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  min-width: 0;
}

.evo-trust-check-main span {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.evo-trust-check-main b {
  color: var(--evo-text, #2f261c);
  font-size: 12px;
  font-weight: 850;
}

.evo-trust-check-main p {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--evo-text-secondary, #756957);
  font-size: 12px;
}

.evo-trust-check.status-match {
  border-color: var(--evo-success-border);
  background: var(--evo-success-bg);
}

.evo-trust-check.status-mismatch,
.evo-trust-check.status-missing {
  border-color: rgba(139, 58, 42, 0.24);
  background: rgba(139, 58, 42, 0.052);
}

.evo-trust-check.status-mismatch .evo-trust-check-main b,
.evo-trust-check.status-missing .evo-trust-check-main b {
  color: var(--evo-danger);
}

.evo-trust-check-values {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  min-width: 0;
}

.evo-trust-check-values span {
  display: inline-grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 4px;
  align-items: center;
  max-width: 100%;
  min-width: 0;
  padding: 3px 6px;
  border-radius: 6px;
  background: rgba(58, 42, 24, 0.06);
}

.evo-trust-check-values small {
  color: var(--evo-text-secondary, #756957);
  font-size: 9px;
  font-weight: 850;
}

.evo-trust-check-values code {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text, #2f261c);
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 10px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-trust-field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.evo-trust-field-grid span,
.evo-trust-completeness,
.evo-trust-section {
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--evo-border, rgba(58, 42, 24, 0.14));
  border-radius: 8px;
  background: var(--evo-input-bg, rgba(255, 255, 250, 0.68));
}

.evo-trust-field-grid span {
  display: grid;
  gap: 4px;
}

.evo-trust-field-grid code,
.evo-trust-field-grid a,
.evo-trust-id-grid code,
.evo-trust-id-grid a,
.evo-trust-seed-table code,
.evo-trust-seed-table a {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text, #2f261c);
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 11px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-trust-field-grid a,
.evo-trust-id-grid a,
.evo-trust-seed-table a {
  text-decoration: none;
}

.evo-trust-field-grid a:hover,
.evo-trust-id-grid a:hover,
.evo-trust-seed-table a:hover {
  color: var(--evo-accent-strong, #7b4d1f);
  text-decoration: underline;
}

.evo-trust-completeness {
  display: grid;
  grid-template-columns: 0.55fr 0.45fr minmax(0, 1fr);
  gap: 10px;
  border-color: rgba(139, 108, 50, 0.24);
}

.evo-trust-completeness[data-status="complete"] {
  border-color: var(--evo-success-border);
  background: var(--evo-success-bg);
}

.evo-trust-completeness[data-status="incomplete"],
.evo-trust-completeness[data-status="missing"] {
  border-color: rgba(139, 58, 42, 0.24);
  background: rgba(139, 58, 42, 0.055);
}

.evo-trust-completeness > span,
.evo-trust-completeness > div {
  display: grid;
  align-content: start;
  gap: 4px;
  min-width: 0;
}

.evo-trust-completeness b {
  color: var(--evo-text, #2f261c);
  font-size: 13px;
  font-weight: 850;
}

.evo-trust-chip-row,
.evo-trust-id-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.evo-trust-chip-row span,
.evo-trust-id-grid code,
.evo-trust-id-grid a,
.evo-trust-id-grid span {
  max-width: 100%;
  overflow: hidden;
  padding: 3px 7px;
  border-radius: 6px;
  background: rgba(58, 42, 24, 0.07);
  color: var(--evo-text-secondary, #756957);
  font-size: 10px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-trust-section {
  display: grid;
  gap: 9px;
}

.evo-trust-seed-table {
  display: grid;
  grid-template-columns:
    minmax(70px, 0.78fr)
    repeat(3, minmax(56px, 0.58fr))
    minmax(62px, 0.58fr)
    repeat(2, minmax(112px, 1fr))
    minmax(168px, 1.38fr);
  gap: 1px;
  max-width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  border: 1px solid var(--evo-border, rgba(58, 42, 24, 0.14));
  border-radius: 7px;
  background: var(--evo-border, rgba(58, 42, 24, 0.14));
}

.evo-trust-seed-table > * {
  min-width: 0;
  overflow: hidden;
  padding: 6px 7px;
  background: var(--evo-card-bg, #fffdfa);
  color: var(--evo-text-secondary, #756957);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-trust-seed-table > span:nth-child(-n + 8) {
  color: var(--evo-accent-strong, #7b4d1f);
  font-weight: 850;
}

.evo-trust-seed-table b {
  color: var(--evo-text, #2f261c);
}

.evo-trust-seed-audit {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
  min-width: 0;
  white-space: normal;
}

.evo-trust-seed-badge {
  display: inline-grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 4px;
  align-items: center;
  min-width: 0;
  max-width: 100%;
  padding: 2px 5px;
  border-radius: 6px;
  background: rgba(58, 42, 24, 0.07);
}

.evo-trust-seed-badge small {
  color: var(--evo-text-secondary, #756957);
  font-size: 9px;
  font-weight: 850;
  text-transform: uppercase;
}

.evo-trust-seed-badge b {
  min-width: 0;
  overflow: hidden;
  font-size: 10px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-trust-seed-badge.tone-ok {
  background: var(--evo-success-bg);
}

.evo-trust-seed-badge.tone-warn {
  background: rgba(139, 108, 50, 0.12);
}

.evo-trust-seed-badge.tone-danger {
  background: rgba(139, 58, 42, 0.1);
}

.evo-trust-seed-badge.tone-danger b {
  color: var(--evo-danger);
}

@media (max-width: 760px) {
  .evo-trust-drawer {
    width: 100vw;
    min-height: 100vh;
    padding: 14px;
    border-left: 0;
  }

  .evo-trust-field-grid,
  .evo-trust-completeness,
  .evo-trust-authority {
    grid-template-columns: minmax(0, 1fr);
  }

  .evo-trust-authority em {
    grid-column: auto;
  }

  .evo-trust-check-main {
    grid-template-columns: minmax(0, 1fr);
  }

  .evo-trust-seed-table {
    grid-template-columns:
      minmax(72px, 0.78fr)
      repeat(3, minmax(64px, 0.58fr))
      minmax(72px, 0.58fr)
      repeat(2, minmax(128px, 1fr))
      minmax(176px, 1.38fr);
    overflow-x: auto;
  }
}
</style>
