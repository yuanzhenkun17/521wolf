<script setup>
import { computed, reactive } from 'vue'

const props = defineProps({
  evo: { type: Object, required: true }
})

const rejectReasons = reactive({})

const review = computed(() => props.evo.selectedProposalReview.value || {})
const summary = computed(() => review.value.summary || {})
const proposals = computed(() => props.evo.selectedProposalRows.value || [])
const gate = computed(() => review.value.gate || {})
const pairedSeeds = computed(() => review.value.pairedSeeds || [])
const selectedRun = computed(() => props.evo.selectedRun.value || null)
const isBatch = computed(() => Boolean(props.evo.selectedIsBatch.value))
const hasRun = computed(() => Boolean(props.evo.selectedRunId.value))
const actionLoading = computed(() => String(props.evo.actionLoading.value || ''))
const canApplyAccepted = computed(() => {
  return hasRun.value && !isBatch.value && Number(summary.value.accepted || 0) > 0 && !isApplying.value
})
const isApplying = computed(() => actionLoading.value.startsWith('proposal-apply:'))

function displayText(value, fallback = '—') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function formatNumber(value, suffix = '') {
  if (value == null || value === '') return '—'
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  const fixed = Math.abs(number) < 1 ? number.toFixed(3) : number.toFixed(2)
  return `${Number(fixed).toString()}${suffix}`
}

function percentLabel(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return `${number > 0 ? '+' : ''}${Math.round(number * 100)}%`
}

function proposalKey(proposal, index) {
  return proposal?.apiId || proposal?.proposal_id || proposal?.id || index
}

function rowActionLoading(proposal, action) {
  const id = proposal?.apiId || proposal?.proposal_id || ''
  return Boolean(id) && actionLoading.value === `proposal-${action}:${id}`
}

function canReviewProposal(proposal) {
  return Boolean(hasRun.value && !isBatch.value && (proposal?.apiId || proposal?.proposal_id))
}

function isAccepted(proposal) {
  return ['accepted', 'accept', 'applied'].includes(String(proposal?.status || '').toLowerCase())
}

function isRejected(proposal) {
  return ['rejected', 'reject'].includes(String(proposal?.status || '').toLowerCase())
}

function rejectReason(proposal, index) {
  return rejectReasons[proposalKey(proposal, index)] || ''
}

function setRejectReason(proposal, index, value) {
  rejectReasons[proposalKey(proposal, index)] = value
}

async function accept(proposal) {
  await props.evo.acceptProposal(proposal, props.evo.selectedRunId.value)
}

async function reject(proposal, index) {
  await props.evo.rejectProposal(proposal, props.evo.selectedRunId.value, rejectReason(proposal, index))
}

async function applyAccepted() {
  await props.evo.applyAcceptedProposals(props.evo.selectedRunId.value)
}
</script>

<template>
  <div class="evo-tab-panel evo-proposal-review">
    <article class="evo-card">
      <header>
        <h2>提案审核</h2>
        <b>{{ selectedRun?.displayRole || selectedRun?.role || '—' }}</b>
      </header>

      <div class="evo-proposal-toolbar">
        <div class="evo-proposal-kpis">
          <span><small>总数</small><b>{{ summary.total || 0 }}</b></span>
          <span><small>已接受</small><b>{{ summary.accepted || 0 }}</b></span>
          <span><small>已拒绝</small><b>{{ summary.rejected || 0 }}</b></span>
          <span><small>待处理</small><b>{{ summary.pending || 0 }}</b></span>
        </div>
        <button
          type="button"
          class="evo-action"
          :disabled="!canApplyAccepted"
          @click="applyAccepted"
        >
          {{ isApplying ? '应用中' : '应用已接受' }}
        </button>
      </div>

      <div class="evo-gate-strip">
        <span><small>Gate</small><b>{{ gate.decisionLabel || '—' }}</b></span>
        <span><small>胜率差</small><b>{{ percentLabel(gate.winRateDelta) }}</b></span>
        <span><small>角色分差</small><b>{{ formatNumber(gate.roleScoreDelta) }}</b></span>
        <span><small>Paired Seeds</small><b>{{ summary.pairedSeedCount || gate.pairedValidCount || pairedSeeds.length || 0 }}</b></span>
      </div>

      <div v-if="review.loading" class="evo-loading">读取中</div>
      <div v-else-if="review.error" class="evo-alert compact">{{ review.error }}</div>
      <div v-else-if="review.unsupported" class="evo-empty compact">{{ review.error || '提案评审不可用' }}</div>
      <div v-else-if="!hasRun" class="evo-empty">暂无运行</div>
      <div v-else-if="isBatch" class="evo-empty">批量任务请查看子运行</div>
      <div v-else-if="!proposals.length" class="evo-empty">暂无可审核提案</div>

      <div v-else class="evo-proposal-list">
        <section
          v-for="(proposal, index) in proposals"
          :key="proposalKey(proposal, index)"
          class="evo-proposal-row"
          :data-status="proposal.status"
        >
          <div class="evo-proposal-main">
            <div class="evo-proposal-head">
              <strong>{{ proposal.title }}</strong>
              <span>{{ proposal.statusLabel }}</span>
            </div>
            <div class="evo-proposal-meta">
              <code>{{ displayText(proposal.targetFile) }}</code>
              <small>{{ proposal.operation }}</small>
              <small v-if="proposal.gateDecision">{{ proposal.gateLabel }}</small>
              <small v-if="proposal.riskLevel">风险 {{ proposal.riskLevel }}</small>
            </div>
            <p>{{ proposal.summary }}</p>
            <p v-if="proposal.rationale !== proposal.summary" class="evo-proposal-rationale">
              {{ proposal.rationale }}
            </p>
            <div v-if="proposal.riskTags.length || proposal.gateReasons.length" class="evo-proposal-tags">
              <span v-for="tag in proposal.riskTags" :key="`risk-${tag}`">{{ tag }}</span>
              <span v-for="reason in proposal.gateReasons" :key="`gate-${reason}`">{{ reason }}</span>
            </div>
            <pre v-if="proposal.diffPreview && proposal.diffPreview !== '—'">{{ proposal.diffPreview }}</pre>
          </div>

          <div class="evo-proposal-actions">
            <button
              type="button"
              class="evo-ghost-action"
              :disabled="!canReviewProposal(proposal) || rowActionLoading(proposal, 'accept') || isAccepted(proposal)"
              @click="accept(proposal)"
            >
              {{ rowActionLoading(proposal, 'accept') ? '处理中' : '接受' }}
            </button>
            <input
              :value="rejectReason(proposal, index)"
              type="text"
              placeholder="拒绝原因"
              :disabled="!canReviewProposal(proposal) || isRejected(proposal)"
              @input="setRejectReason(proposal, index, $event.target.value)"
            />
            <button
              type="button"
              class="evo-ghost-action danger"
              :disabled="!canReviewProposal(proposal) || rowActionLoading(proposal, 'reject') || isRejected(proposal)"
              @click="reject(proposal, index)"
            >
              {{ rowActionLoading(proposal, 'reject') ? '处理中' : '拒绝' }}
            </button>
          </div>
        </section>
      </div>

      <div v-if="pairedSeeds.length" class="evo-paired-seeds">
        <h3>Paired Seed 明细</h3>
        <div class="evo-paired-table">
          <span>Seed</span>
          <span>基线</span>
          <span>候选</span>
          <span>差值</span>
          <span>胜方</span>
          <template v-for="(seed, index) in pairedSeeds.slice(0, 12)" :key="seed.id || index">
            <code>{{ displayText(seed.seed) }}</code>
            <span>{{ formatNumber(seed.baselineScore) }}</span>
            <span>{{ formatNumber(seed.candidateScore) }}</span>
            <b>{{ formatNumber(seed.scoreDelta) }}</b>
            <span>{{ displayText(seed.winnerSide) }}</span>
          </template>
        </div>
      </div>
    </article>
  </div>
</template>

<style scoped>
.evo-proposal-review {
  min-width: 0;
}

.evo-proposal-toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.evo-proposal-kpis,
.evo-gate-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  min-width: 0;
}

.evo-proposal-kpis span,
.evo-gate-strip span {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid var(--evo-border);
  border-radius: 7px;
  background: var(--evo-input-bg);
}

.evo-proposal-kpis small,
.evo-gate-strip small {
  overflow: hidden;
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-proposal-kpis b,
.evo-gate-strip b {
  overflow: hidden;
  color: var(--evo-text);
  font-size: 13px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-gate-strip {
  margin-bottom: 14px;
}

.evo-proposal-list {
  display: grid;
  gap: 10px;
}

.evo-proposal-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(150px, 190px);
  gap: 12px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--evo-border);
  border-radius: 8px;
  background: var(--evo-input-bg);
}

.evo-proposal-row[data-status="accepted"],
.evo-proposal-row[data-status="applied"] {
  border-color: rgba(74, 124, 68, 0.34);
  background: rgba(74, 124, 68, 0.05);
}

.evo-proposal-row[data-status="rejected"] {
  border-color: rgba(139, 58, 42, 0.28);
  background: rgba(139, 58, 42, 0.045);
}

.evo-proposal-main {
  display: grid;
  gap: 7px;
  min-width: 0;
}

.evo-proposal-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.evo-proposal-head strong {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text);
  font-size: 13px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-proposal-head span {
  flex: 0 0 auto;
  padding: 2px 8px;
  border-radius: 5px;
  background: var(--evo-active-bg);
  color: var(--evo-accent-strong);
  font-size: 10px;
  font-weight: 800;
}

.evo-proposal-meta,
.evo-proposal-tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.evo-proposal-meta code,
.evo-proposal-meta small,
.evo-proposal-tags span {
  max-width: 100%;
  overflow: hidden;
  padding: 2px 7px;
  border-radius: 5px;
  background: rgba(58, 42, 24, 0.06);
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-proposal-main p {
  margin: 0;
  color: var(--evo-text);
  font-size: 12px;
  line-height: 1.55;
}

.evo-proposal-rationale {
  color: var(--evo-text-secondary) !important;
}

.evo-proposal-main pre {
  max-height: 150px;
  overflow: auto;
  margin: 2px 0 0;
  padding: 8px 10px;
  border-radius: 7px;
  background: #2d2218;
  color: rgba(232, 218, 196, 0.92);
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.evo-proposal-actions {
  display: grid;
  align-content: start;
  gap: 7px;
  min-width: 0;
}

.evo-proposal-actions input {
  box-sizing: border-box;
  width: 100%;
  height: 30px;
  padding: 0 8px;
  border: 1px solid var(--evo-input-border);
  border-radius: 6px;
  background: rgba(255, 255, 250, 0.68);
  color: var(--evo-text);
  font-size: 12px;
}

.evo-proposal-actions input:disabled {
  opacity: 0.45;
}

.evo-paired-seeds {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--evo-border);
}

.evo-paired-seeds h3 {
  margin: 0 0 8px;
  color: var(--evo-accent);
  font-size: 12px;
  font-weight: 800;
}

.evo-paired-table {
  display: grid;
  grid-template-columns: minmax(80px, 1fr) repeat(4, minmax(64px, 0.7fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--evo-border);
  border-radius: 7px;
  background: var(--evo-border);
}

.evo-paired-table > * {
  min-width: 0;
  overflow: hidden;
  padding: 6px 8px;
  background: var(--evo-input-bg);
  color: var(--evo-text-secondary);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-paired-table > span:nth-child(-n + 5) {
  color: var(--evo-accent-strong);
  font-weight: 800;
}

.evo-paired-table code,
.evo-paired-table b {
  color: var(--evo-text);
}

@media (max-width: 760px) {
  .evo-proposal-toolbar,
  .evo-proposal-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .evo-proposal-kpis,
  .evo-gate-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .evo-paired-table {
    grid-template-columns: repeat(5, minmax(74px, 1fr));
    overflow-x: auto;
  }
}
</style>
