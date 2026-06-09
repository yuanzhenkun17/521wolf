<script setup>
import { computed, reactive, ref } from 'vue'
import EvidenceLink from '../history/EvidenceLink.vue'
import JudgeEvidencePanel from '../history/JudgeEvidencePanel.vue'
import RejectDialog from './RejectDialog.vue'
import TrustBundleDrawer from './TrustBundleDrawer.vue'

const props = defineProps({
  evo: { type: Object, required: true }
})

const rejectReasons = reactive({})
const rejectReviewMetadata = reactive({})
const bulkRejectReason = ref('')
const bulkReviewAction = ref('')
const rejectDialogOpen = ref(false)
const rejectDialogProposal = ref(null)
const rejectDialogIndex = ref(-1)
const rejectDialogReason = ref('')
const rejectDialogTags = ref([])
const expandedProposalKeys = ref(new Set())
const collapsedProposalKeys = ref(new Set())

const review = computed(() => props.evo.selectedProposalReview.value || {})
const summary = computed(() => review.value.summary || {})
const proposals = computed(() => props.evo.selectedProposalRows.value || [])
const gate = computed(() => review.value.gate || {})
const pairedSeeds = computed(() => review.value.pairedSeeds || [])
const scenarioReplay = computed(() => review.value.scenarioReplay || {})
const trustBundle = computed(() => review.value.trustBundle || review.value.trust_bundle || {})
const proposalAttribution = computed(() => review.value.proposalAttribution || gate.value.proposalAttribution || {})
const selectedRun = computed(() => props.evo.selectedRun.value || null)
const isBatch = computed(() => Boolean(props.evo.selectedIsBatch.value))
const hasRun = computed(() => Boolean(props.evo.selectedRunId.value))
const actionLoading = computed(() => String(props.evo.actionLoading.value || ''))
const deepLinkTarget = computed(() => props.evo.evolutionDeepLinkTarget?.value || null)
const deepLinkStatus = computed(() => textValue(deepLinkTarget.value?.status))
const deepLinkPendingItems = computed(() => new Set(Array.isArray(deepLinkTarget.value?.pending) ? deepLinkTarget.value.pending : []))
const deepLinkProposalId = computed(() => textValue(deepLinkTarget.value?.proposal_id))
const deepLinkGateReportId = computed(() => textValue(deepLinkTarget.value?.gate_report_id))
const proposalDeepLinkMatch = computed(() => Boolean(deepLinkProposalId.value && proposals.value.some(proposalDeepLinkMatched)))
const gateReportId = computed(() => textValue(
  gate.value.gate_report_id ||
    gate.value.gateReportId ||
    trustBundle.value.gate_report_id ||
    trustBundle.value.gateReportId ||
    selectedRun.value?.gate_report_id ||
    selectedRun.value?.gateReportId ||
    selectedRun.value?.trust_bundle?.gate_report_id ||
    selectedRun.value?.trustBundle?.gateReportId
))
const gateDeepLinkMatched = computed(() => {
  const id = deepLinkGateReportId.value
  if (!id) return false
  return [
    gate.value.gate_report_id,
    gate.value.gateReportId,
    trustBundle.value.gate_report_id,
    trustBundle.value.gateReportId,
    selectedRun.value?.gate_report_id,
    selectedRun.value?.gateReportId,
    selectedRun.value?.trust_bundle?.gate_report_id,
    selectedRun.value?.trustBundle?.gateReportId
  ].some((value) => textValue(value) === id)
})
const proposalDeepLinkState = computed(() => deepLinkState('proposal', proposalDeepLinkMatch.value, Boolean(deepLinkProposalId.value)))
const gateDeepLinkState = computed(() => deepLinkState('gate_report', gateDeepLinkMatched.value, Boolean(deepLinkGateReportId.value)))
const gateDeepLinkClass = computed(() => [
  deepLinkGateReportId.value ? 'evo-gate-strip--deep-link-target' : '',
  gateDeepLinkState.value ? `evo-gate-strip--deep-link-${gateDeepLinkState.value}` : ''
])
const gateDeepLinkLabel = computed(() => deepLinkStateLabel(gateDeepLinkState.value))
const deepLinkInlineMessages = computed(() => {
  const messages = []
  if (deepLinkProposalId.value && !proposalDeepLinkMatch.value) {
    messages.push(`提案 ${deepLinkStateLabel(proposalDeepLinkState.value)}: ${deepLinkProposalId.value}`)
  }
  if (deepLinkGateReportId.value && !gateDeepLinkMatched.value) {
    messages.push(`门禁 ${deepLinkStateLabel(gateDeepLinkState.value)}: ${deepLinkGateReportId.value}`)
  }
  return messages
})
const deepLinkInlineState = computed(() => (
  [proposalDeepLinkState.value, gateDeepLinkState.value].includes('pending') ? 'pending' : 'unmatched'
))
const canApplyAccepted = computed(() => {
  return hasRun.value && !isBatch.value && Number(summary.value.accepted || 0) > 0 && !isApplying.value && !isProposalActionBusy.value
})
const isApplying = computed(() => actionLoading.value.startsWith('proposal-apply:'))
const isBulkReviewing = computed(() => Boolean(bulkReviewAction.value))
const isProposalActionBusy = computed(() => Boolean(actionLoading.value || isBulkReviewing.value))
const rejectDialogBusy = computed(() => (
  rejectDialogProposal.value ? rowActionLoading(rejectDialogProposal.value, 'reject') : false
))
const rejectDialogDisabled = computed(() => rejectDialogActionDisabled(rejectDialogProposal.value))
const pendingReviewProposals = computed(() => proposals.value.filter(isPendingReviewProposal))
const acceptableProposals = computed(() => pendingReviewProposals.value.filter(canBulkAcceptProposal))
const rejectableProposals = computed(() => pendingReviewProposals.value.filter(canBulkRejectProposal))
const pendingReviewCount = computed(() => pendingReviewProposals.value.length)
const acceptableCount = computed(() => acceptableProposals.value.length)
const rejectableCount = computed(() => rejectableProposals.value.length)
const isBulkAccepting = computed(() => bulkReviewAction.value === 'accept')
const isBulkRejecting = computed(() => bulkReviewAction.value === 'reject')
const canBulkAccept = computed(() => acceptableCount.value > 0 && !isProposalActionBusy.value)
const bulkRejectReasonText = computed(() => textValue(bulkRejectReason.value))
const bulkRejectDisabledReason = computed(() => (
  bulkRejectReasonText.value ? '' : '批量拒绝必须填写原因。'
))
const canBulkReject = computed(() => (
  rejectableCount.value > 0 && !isProposalActionBusy.value && !bulkRejectDisabledReason.value
))
const canOpenTrustBundle = computed(() => hasRun.value && !isBatch.value)
const gateJudgeEvidence = computed(() => normalizeJudgeEvidence(gate.value, gate.value.releaseGate))
const attributionJudgeEvidence = computed(() => normalizeJudgeEvidence(
  proposalAttribution.value,
  Array.isArray(proposalAttribution.value.rows) ? proposalAttribution.value.rows : []
))
const hasGateJudgeEvidence = computed(() => hasJudgeEvidence(gateJudgeEvidence.value))
const hasAttributionJudgeEvidence = computed(() => hasJudgeEvidence(attributionJudgeEvidence.value))
const trustAuditButtonLabel = computed(() => {
  return trustBundle.value.trust_bundle_id || trustBundle.value.trustBundleId || trustBundle.value.bundle_hash || trustBundle.value.bundleHash
    ? '信任包审计'
    : '信任包缺失'
})

const PROPOSAL_STATUS_LABELS = {
  pending: '待处理',
  reviewing: '待处理',
  accepted: '已接受',
  accept: '已接受',
  rejected: '已拒绝',
  reject: '已拒绝',
  applied: '已应用'
}

const PROPOSAL_OPERATION_LABELS = {
  create: '新建',
  new: '新建',
  add: '新建',
  update: '修改',
  modify: '修改',
  edit: '修改',
  patch: '修改',
  delete: '删除',
  remove: '删除'
}

const JUDGE_EVIDENCE_FIELD_ALIASES = {
  evidenceRefs: ['evidenceRefs', 'evidence_refs', 'evidenceRef', 'evidence_ref'],
  counterfactuals: ['counterfactuals', 'counterfactual', 'counterFactuals', 'counter_factuals', 'counter_factual'],
  rubricMisses: ['rubricMisses', 'rubric_misses', 'rubricMiss', 'rubric_miss'],
  degradedReasons: ['degradedReasons', 'degraded_reasons', 'degradedReason', 'degraded_reason', 'degradationReasons', 'degradation_reasons'],
  warnings: ['warnings', 'warning'],
  diagnostics: ['diagnostics', 'diagnostic']
}

const JUDGE_EVIDENCE_NESTED_KEYS = [
  'judgeEvidence',
  'judge_evidence',
  'decisionJudgeEvidence',
  'decision_judge_evidence',
  'gateEvidence',
  'gate_evidence',
  'proposalEvidence',
  'proposal_evidence',
  'attributionEvidence',
  'attribution_evidence',
  'reviewEvidence',
  'review_evidence',
  'evidenceSummary',
  'evidence_summary',
  'evidence',
  'decisionJudge',
  'decision_judge',
  'judge',
  'review'
]

function displayText(value, fallback = '—') {
  const text = String(value ?? '').trim()
  return text || fallback
}

function textValue(value) {
  return String(value ?? '').trim()
}

function textArray(value) {
  if (Array.isArray(value)) return value.map(textValue).filter(Boolean)
  const text = textValue(value)
  return text ? [text] : []
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

function scoreLabel(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  const pct = Math.abs(number) <= 1 ? number * 100 : number
  return `${Math.round(pct)}%`
}

function rejectBufferStatusLabel(buffer = {}) {
  if (buffer.savedLabel) return buffer.savedLabel
  if (buffer.status) return displayText(buffer.status)
  if (buffer.duplicateLabel) return buffer.duplicateLabel
  return '已记录'
}

function rejectBufferMatchedLabel(matched = {}) {
  const parts = [
    matched.proposalId ? `提案 ${matched.proposalId}` : '',
    matched.sourceRunId ? `运行 ${matched.sourceRunId}` : ''
  ].filter(Boolean)
  return parts.join(' · ')
}

function attributionLabel() {
  const label = displayText(
    summary.value.proposalAttributionLabel ||
      gate.value.proposalAttributionLabel ||
      proposalAttribution.value.statusLabel,
    ''
  )
  const rows = Number(
    summary.value.proposalAttributionRowCount ??
      gate.value.proposalAttributionRowCount ??
      proposalAttribution.value.rowCount
  )
  if (!label && !Number.isFinite(rows)) return '—'
  if (!Number.isFinite(rows) || rows <= 0) return label || '—'
  return label ? `${label} / ${rows}` : String(rows)
}

function isEvidenceObject(value) {
  return value && typeof value === 'object'
}

function evidenceRows(value) {
  if (Array.isArray(value)) return value.filter((row) => row != null && row !== '')
  return value == null || value === '' ? [] : [value]
}

function evidenceRowKey(value) {
  if (isEvidenceObject(value)) {
    try {
      return JSON.stringify(value)
    } catch {
      return Object.prototype.toString.call(value)
    }
  }
  return String(value)
}

function appendUniqueEvidenceRows(target, values, seen) {
  for (const row of evidenceRows(values)) {
    const key = evidenceRowKey(row)
    if (seen.has(key)) continue
    seen.add(key)
    target.push(row)
  }
}

function appendJudgeEvidenceSource(target, source, seenSources) {
  if (Array.isArray(source)) {
    source.forEach((item) => appendJudgeEvidenceSource(target, item, seenSources))
    return
  }
  if (!isEvidenceObject(source)) return
  if (seenSources.has(source)) return
  seenSources.add(source)
  target.push(source)
  for (const key of JUDGE_EVIDENCE_NESTED_KEYS) {
    appendJudgeEvidenceSource(target, source[key], seenSources)
  }
}

function normalizeJudgeEvidence(...sources) {
  const evidenceSources = []
  const seenSources = new WeakSet()
  sources.forEach((source) => appendJudgeEvidenceSource(evidenceSources, source, seenSources))
  return Object.fromEntries(Object.entries(JUDGE_EVIDENCE_FIELD_ALIASES).map(([field, aliases]) => {
    const rows = []
    const seenRows = new Set()
    for (const source of evidenceSources) {
      aliases.forEach((alias) => appendUniqueEvidenceRows(rows, source[alias], seenRows))
    }
    return [field, rows]
  }))
}

function hasJudgeEvidence(evidence) {
  return Object.keys(JUDGE_EVIDENCE_FIELD_ALIASES).some((field) => {
    const rows = evidence?.[field]
    return Array.isArray(rows) && rows.length > 0
  })
}

function proposalJudgeEvidence(proposal) {
  return normalizeJudgeEvidence(proposal, proposal?.gate, proposal?.risk, proposal?.preflight)
}

function hasProposalJudgeEvidence(proposal) {
  return hasJudgeEvidence(proposalJudgeEvidence(proposal))
}

function proposalKey(proposal, index) {
  return proposal?.apiId || proposal?.proposal_id || proposal?.id || index
}

function proposalExpansionKey(proposal, index) {
  return String(proposalKey(proposal, index))
}

function isProposalExpanded(proposal, index) {
  const key = proposalExpansionKey(proposal, index)
  if (collapsedProposalKeys.value.has(key)) return false
  return proposalDeepLinkMatched(proposal) || expandedProposalKeys.value.has(key)
}

function toggleProposalDetails(proposal, index) {
  const key = proposalExpansionKey(proposal, index)
  const nextExpanded = new Set(expandedProposalKeys.value)
  const nextCollapsed = new Set(collapsedProposalKeys.value)
  if (isProposalExpanded(proposal, index)) {
    nextExpanded.delete(key)
    if (proposalDeepLinkMatched(proposal)) nextCollapsed.add(key)
  } else {
    nextExpanded.add(key)
    nextCollapsed.delete(key)
  }
  expandedProposalKeys.value = nextExpanded
  collapsedProposalKeys.value = nextCollapsed
}

function proposalId(proposal) {
  return [proposal?.apiId, proposal?.proposal_id, proposal?.id].map(textValue).find(Boolean) || ''
}

function proposalStatusLabel(proposal) {
  const status = textValue(proposal?.status).toLowerCase()
  return displayText(proposal?.statusLabel || PROPOSAL_STATUS_LABELS[status] || proposal?.status)
}

function proposalOperationLabel(proposal) {
  const operation = textValue(proposal?.operation || proposal?.action)
  return displayText(PROPOSAL_OPERATION_LABELS[operation.toLowerCase()] || operation)
}

function proposalTargetLabel(proposal, index) {
  return displayText(proposal?.targetFile || proposal?.title || proposalId(proposal), `提案 ${index + 1}`)
}

function proposalExpectedLabel(proposal) {
  return displayText(proposal?.expectedEffect || proposal?.summary || proposal?.rationale)
}

function uniqueTextRows(rows) {
  return [...new Set(rows.map(textValue).filter(Boolean))]
}

function proposalRiskItems(proposal) {
  const rows = []
  if (proposal?.preflightStatus) rows.push(`预检 ${displayText(proposal.preflightLabel || proposal.preflightStatus, '')}`)
  if (proposal?.riskLevel) rows.push(`风险 ${proposal.riskLevel}`)
  if (proposal?.gateDecision) rows.push(proposal.gateLabel || `门禁 ${proposal.gateDecision}`)
  if (proposal?.rejectBuffer?.visible) rows.push(`拒绝缓冲 ${rejectBufferStatusLabel(proposal.rejectBuffer)}`)
  if (proposal?.rejectBuffer?.overfitScore != null) rows.push(`过拟合 ${scoreLabel(proposal.rejectBuffer.overfitScore)}`)
  rows.push(...textArray(proposal?.riskTags))
  rows.push(...textArray(proposal?.gateReasons))
  rows.push(...textArray(proposal?.preflightReasons).slice(0, 2))
  return uniqueTextRows(rows).slice(0, 6)
}

function proposalEvidenceItems(proposal) {
  const evidenceGameCount = Array.isArray(proposal?.evidenceGameIds) ? proposal.evidenceGameIds.length : 0
  const counterEvidenceGameCount = Array.isArray(proposal?.counterEvidenceGameIds) ? proposal.counterEvidenceGameIds.length : 0
  const rows = []
  if (evidenceGameCount) rows.push(`样本局 ${evidenceGameCount}`)
  if (counterEvidenceGameCount) rows.push(`反证局 ${counterEvidenceGameCount}`)
  if (hasProposalJudgeEvidence(proposal)) rows.push('裁判证据')
  if (proposal?.diffPreview && proposal.diffPreview !== '—') rows.push('差异')
  if (proposalEvidenceId(proposal)) rows.push('提案链接')
  if (proposalDeepLinkMatched(proposal)) rows.push(proposalDeepLinkLabel(proposal))
  return uniqueTextRows(rows).slice(0, 5)
}

function proposalEvidenceId(proposal) {
  return [proposal?.apiId, proposal?.proposal_id].map(textValue).find(Boolean) || ''
}

function selectedEvidenceRunId() {
  return [
    props.evo.selectedRunId.value,
    selectedRun.value?.run_id,
    selectedRun.value?.id,
    selectedRun.value?.source_run_id,
    selectedRun.value?.sourceRunId
  ].map(textValue).find(Boolean) || ''
}

function proposalGameEvidenceTargets(proposal, ids = [], counter = false) {
  return ids.slice(0, 8).map((id) => {
    const gameId = textValue(id)
    return {
      key: `${counter ? 'counter' : 'support'}-${proposalKey(proposal, 0)}-${gameId}`,
      label: counter ? '反证局' : '样本局',
      className: counter ? 'counter' : '',
      target: {
        history_game_id: gameId,
        game_id: gameId,
        source_run_id: selectedEvidenceRunId(),
        proposal_id: proposalEvidenceId(proposal)
      }
    }
  })
}

function proposalFallbackEvidenceTarget(proposal) {
  return {
    key: `proposal-${proposalKey(proposal, 0)}`,
    label: '提案',
    className: 'proposal',
    kind: 'proposal',
    target: {
      source_run_id: selectedEvidenceRunId(),
      proposal_id: proposalEvidenceId(proposal)
    }
  }
}

function proposalEvidenceTargets(proposal) {
  const gameTargets = [
    ...proposalGameEvidenceTargets(proposal, proposal?.evidenceGameIds || []),
    ...proposalGameEvidenceTargets(proposal, proposal?.counterEvidenceGameIds || [], true)
  ]
  return gameTargets.length ? gameTargets : [proposalFallbackEvidenceTarget(proposal)]
}

function hasProposalEvidenceTargets(proposal) {
  return Boolean(proposalEvidenceTargets(proposal).length)
}

function proposalDeepLinkMatched(proposal) {
  const id = deepLinkProposalId.value
  return Boolean(id && [proposal?.apiId, proposal?.proposal_id, proposal?.id].some((value) => textValue(value) === id))
}

function deepLinkState(scope, matched, hasTarget) {
  if (!hasTarget) return ''
  if (['pending', 'applying'].includes(deepLinkStatus.value)) return 'pending'
  if (deepLinkPendingItems.value.has(scope) || !matched) return 'unmatched'
  return 'matched'
}

function deepLinkStateLabel(state) {
  return {
    matched: '链接目标',
    pending: '待恢复',
    unmatched: '未匹配'
  }[state] || '链接目标'
}

function proposalDeepLinkStateForRow(proposal) {
  return proposalDeepLinkMatched(proposal) ? proposalDeepLinkState.value : ''
}

function proposalDeepLinkClass(proposal) {
  const state = proposalDeepLinkStateForRow(proposal)
  return state ? ['evo-proposal-row--deep-link-target', `evo-proposal-row--deep-link-${state}`] : []
}

function proposalDeepLinkLabel(proposal) {
  return proposalDeepLinkMatched(proposal) ? deepLinkStateLabel(proposalDeepLinkState.value) : ''
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

function isPendingReviewProposal(proposal) {
  return canReviewProposal(proposal) && !isAccepted(proposal) && !isRejected(proposal)
}

function canBulkAcceptProposal(proposal) {
  return isPendingReviewProposal(proposal)
}

function canBulkRejectProposal(proposal) {
  return isPendingReviewProposal(proposal)
}

function hasHypothesisDetails(proposal) {
  return Boolean(
    proposal?.hypothesis ||
      proposal?.triggerCondition ||
      proposal?.expectedEffect ||
      proposal?.metricTargetRows?.length ||
      hasProposalEvidenceTargets(proposal) ||
      proposal?.preflightStatus ||
      proposal?.preflightReasons?.length
  )
}

function rejectReason(proposal, index) {
  return rejectReasons[proposalKey(proposal, index)] || ''
}

function normalizeRejectTags(tags) {
  const values = Array.isArray(tags) ? tags : String(tags || '').split(/[,\s]+/)
  return [...new Set(values.map((tag) => String(tag ?? '').trim()).filter(Boolean))].slice(0, 12)
}

function rejectMetadataTags(proposal, index) {
  return normalizeRejectTags(rejectReviewMetadata[proposalKey(proposal, index)]?.tags || [])
}

function rowActionDisabled(proposal, action) {
  if (!canReviewProposal(proposal)) return true
  if (isBulkReviewing.value) return true
  if (actionLoading.value && !rowActionLoading(proposal, action)) return true
  if (rowActionLoading(proposal, action)) return true
  return action === 'accept' ? isAccepted(proposal) : isRejected(proposal)
}

function hasBlockingReviewError() {
  const notice = props.evo.notice?.value || {}
  return notice.type === 'error' || Boolean(props.evo.error?.value)
}

async function accept(proposal) {
  await props.evo.acceptProposal(proposal, props.evo.selectedRunId.value)
}

function rejectDialogActionDisabled(proposal) {
  if (!proposal) return true
  if (!canReviewProposal(proposal)) return true
  if (isBulkReviewing.value) return true
  if (actionLoading.value && !rowActionLoading(proposal, 'reject')) return true
  return isRejected(proposal)
}

function openRejectDialog(proposal, index) {
  if (rejectDialogActionDisabled(proposal)) return
  const key = proposalKey(proposal, index)
  rejectDialogProposal.value = proposal
  rejectDialogIndex.value = index
  rejectDialogReason.value = rejectReasons[key] || proposal?.rejectBuffer?.reason || ''
  rejectDialogTags.value = normalizeRejectTags(
    rejectReviewMetadata[key]?.tags?.length ? rejectReviewMetadata[key].tags : proposal?.rejectBuffer?.tags || []
  )
  rejectDialogOpen.value = true
}

function closeRejectDialog() {
  if (rejectDialogBusy.value) return
  rejectDialogOpen.value = false
  rejectDialogProposal.value = null
  rejectDialogIndex.value = -1
  rejectDialogReason.value = ''
  rejectDialogTags.value = []
}

async function confirmRejectDialog(payload) {
  const proposal = rejectDialogProposal.value
  if (!proposal) return
  const index = rejectDialogIndex.value
  const key = proposalKey(proposal, index)
  const reason = textValue(payload?.reason)
  if (!reason) return
  const tags = normalizeRejectTags(payload?.tags || payload?.metadata?.tags || [])
  rejectReasons[key] = reason
  rejectReviewMetadata[key] = {
    tags
  }
  await props.evo.rejectProposal(proposal, props.evo.selectedRunId.value, reason, { tags })
  if (!hasBlockingReviewError()) closeRejectDialog()
}

async function runBulkReview(action, items) {
  if (isProposalActionBusy.value || !items.length) return
  if (action === 'reject' && !bulkRejectReasonText.value) return
  bulkReviewAction.value = action
  try {
    const runId = props.evo.selectedRunId.value
    for (const proposal of items) {
      if (action === 'accept') {
        await props.evo.acceptProposal(proposal, runId)
      } else if (bulkRejectReason.value !== bulkRejectReasonText.value) {
        await props.evo.rejectProposal(proposal, runId, bulkRejectReasonText.value)
      } else {
        await props.evo.rejectProposal(proposal, runId, bulkRejectReason.value)
      }
      if (hasBlockingReviewError()) break
    }
  } finally {
    bulkReviewAction.value = ''
  }
}

async function bulkAcceptProposals() {
  await runBulkReview('accept', [...acceptableProposals.value])
}

async function bulkRejectProposals() {
  await runBulkReview('reject', [...rejectableProposals.value])
}

async function applyAccepted() {
  await props.evo.applyAcceptedProposals(props.evo.selectedRunId.value)
}

function openTrustBundleAudit() {
  props.evo.openTrustBundleDrawer?.('review')
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
        <div class="evo-proposal-toolbar-actions">
          <button
            type="button"
            class="evo-ghost-action"
            :disabled="!canOpenTrustBundle"
            @click="openTrustBundleAudit"
          >
            {{ trustAuditButtonLabel }}
          </button>
          <button
            type="button"
            class="evo-action"
            :disabled="!canApplyAccepted"
            @click="applyAccepted"
          >
            {{ isApplying ? '应用中' : '应用已接受' }}
          </button>
        </div>
      </div>

      <div
        v-if="hasRun && !isBatch && proposals.length"
        class="evo-proposal-bulk-tools"
        data-bulk-review-tools
      >
        <div class="evo-proposal-bulk-counts">
          <span><small>待处理</small><b>{{ pendingReviewCount }}</b></span>
          <span><small>可接受</small><b>{{ acceptableCount }}</b></span>
          <span><small>可拒绝</small><b>{{ rejectableCount }}</b></span>
        </div>
        <label class="evo-proposal-bulk-reason">
          <small>批量拒绝原因</small>
          <input
            v-model="bulkRejectReason"
            type="text"
            placeholder="批量拒绝原因"
            :disabled="isProposalActionBusy"
          />
          <em v-if="bulkRejectDisabledReason">{{ bulkRejectDisabledReason }}</em>
        </label>
        <div class="evo-proposal-bulk-actions">
          <button
            type="button"
            class="evo-ghost-action"
            :disabled="!canBulkAccept"
            @click="bulkAcceptProposals"
          >
            {{ isBulkAccepting ? '接受中' : '接受全部可处理' }}
          </button>
          <button
            type="button"
            class="evo-ghost-action danger"
            :disabled="!canBulkReject"
            @click="bulkRejectProposals"
          >
            {{ isBulkRejecting ? '拒绝中' : '拒绝全部可处理' }}
          </button>
        </div>
      </div>

      <div
        :class="['evo-gate-strip', ...gateDeepLinkClass]"
        :data-gate-report-id="gateReportId || null"
        :data-deep-link-target="deepLinkGateReportId ? 'gate' : null"
        :data-deep-link-gate-id="deepLinkGateReportId || null"
        :data-deep-link-state="gateDeepLinkState || null"
      >
        <span><small>门禁</small><b>{{ gate.decisionLabel || '—' }}</b></span>
        <span><small>发布</small><b>{{ gate.releaseLabel || '—' }}</b></span>
        <span><small>胜率差</small><b>{{ percentLabel(gate.winRateDelta) }}</b></span>
        <span><small>角色分差</small><b>{{ formatNumber(gate.roleScoreDelta) }}</b></span>
        <span><small>配对种子</small><b>{{ summary.pairedSeedCount || gate.pairedValidCount || pairedSeeds.length || 0 }}</b></span>
        <span><small>场景复盘</small><b>{{ summary.scenarioCount || gate.scenarioCount || scenarioReplay.scenario_count || 0 }}</b></span>
        <span><small>策略违规</small><b>{{ summary.scenarioPolicyViolationCount || gate.scenarioPolicyViolationCount || scenarioReplay.policy_violation_count || 0 }}</b></span>
        <span><small>归因</small><b>{{ attributionLabel() }}</b></span>
        <span><small>信任包</small><b>{{ formatNumber(summary.trustCompletenessScore ?? trustBundle.completeness?.score ?? gate.trustCompletenessScore) }}</b></span>
        <span
          v-if="gateDeepLinkLabel"
          class="evo-deep-link-badge evo-gate-deep-link-marker"
          data-deep-link-marker="gate"
          :data-deep-link-state="gateDeepLinkState"
        >
          <small>定位链接</small>
          <b>{{ gateDeepLinkLabel }}</b>
        </span>
      </div>

      <div
        v-if="deepLinkInlineMessages.length"
        class="evo-deep-link-inline"
        :data-deep-link-state="deepLinkInlineState"
      >
        <span v-for="message in deepLinkInlineMessages" :key="message">{{ message }}</span>
      </div>

      <div
        v-if="hasGateJudgeEvidence || hasAttributionJudgeEvidence"
        class="evo-judge-evidence-band"
        data-evolution-judge-evidence="gate-attribution"
      >
        <section
          v-if="hasGateJudgeEvidence"
          class="evo-judge-evidence-card"
          data-evolution-gate-judge-evidence
        >
          <header>
            <small>门禁证据</small>
            <b>{{ gateReportId || gate.decisionLabel || '门禁' }}</b>
          </header>
          <JudgeEvidencePanel
            :evidence="gateJudgeEvidence"
            :row-key="`gate-${gateReportId || selectedEvidenceRunId()}`"
          />
        </section>
        <section
          v-if="hasAttributionJudgeEvidence"
          class="evo-judge-evidence-card"
          data-evolution-attribution-judge-evidence
        >
          <header>
            <small>归因证据</small>
            <b>{{ proposalAttribution.statusLabel || attributionLabel() }}</b>
          </header>
          <JudgeEvidencePanel
            :evidence="attributionJudgeEvidence"
            :row-key="`attribution-${gateReportId || selectedEvidenceRunId()}`"
          />
        </section>
      </div>

      <div v-if="review.loading" class="evo-loading">读取中</div>
      <div v-else-if="review.error" class="evo-alert compact">{{ review.error }}</div>
      <div v-else-if="review.unsupported" class="evo-empty compact">{{ review.error || '提案评审不可用' }}</div>
      <div v-else-if="!hasRun" class="evo-empty">暂无运行</div>
      <div v-else-if="isBatch" class="evo-empty">批量任务请查看子运行</div>
      <div v-else-if="!proposals.length" class="evo-empty">暂无可审核提案</div>

      <div v-else class="evo-proposal-list" data-review-audit-list>
        <div class="evo-proposal-list-head" aria-hidden="true">
          <span>状态</span>
          <span>目标</span>
          <span>操作</span>
          <span>预期</span>
          <span>风险</span>
          <span>证据</span>
          <span>动作</span>
        </div>
        <section
          v-for="(proposal, index) in proposals"
          :key="proposalKey(proposal, index)"
          :class="['evo-proposal-row', ...proposalDeepLinkClass(proposal)]"
          :data-proposal-id="proposalId(proposal) || null"
          :data-deep-link-target="proposalDeepLinkMatched(proposal) ? 'proposal' : null"
          :data-deep-link-proposal-id="proposalDeepLinkMatched(proposal) ? deepLinkProposalId : null"
          :data-deep-link-state="proposalDeepLinkStateForRow(proposal) || null"
          :data-status="proposal.status"
        >
          <div class="evo-proposal-audit-row">
            <div class="evo-proposal-status-cell" data-column="状态">
              <span class="evo-proposal-status-pill">{{ proposalStatusLabel(proposal) }}</span>
              <span
                v-if="proposalDeepLinkMatched(proposal)"
                class="evo-deep-link-badge"
                data-deep-link-marker="proposal"
                :data-deep-link-state="proposalDeepLinkStateForRow(proposal)"
              >
                {{ proposalDeepLinkLabel(proposal) }}
              </span>
              <code v-if="proposalId(proposal)">{{ proposalId(proposal) }}</code>
            </div>

            <div class="evo-proposal-target-cell" data-column="目标">
              <strong>{{ proposalTargetLabel(proposal, index) }}</strong>
              <code>{{ displayText(proposal.targetFile) }}</code>
            </div>

            <div class="evo-proposal-operation-cell" data-column="操作">
              <b>{{ proposalOperationLabel(proposal) }}</b>
            </div>

            <div class="evo-proposal-expected-cell" data-column="预期">
              <p>{{ proposalExpectedLabel(proposal) }}</p>
            </div>

            <div class="evo-proposal-risk-cell" data-column="风险">
              <span
                v-for="item in proposalRiskItems(proposal)"
                :key="`risk-audit-${proposalKey(proposal, index)}-${item}`"
              >
                {{ item }}
              </span>
              <span v-if="!proposalRiskItems(proposal).length">—</span>
            </div>

            <div class="evo-proposal-evidence-cell" data-column="证据">
              <span
                v-for="item in proposalEvidenceItems(proposal)"
                :key="`evidence-audit-${proposalKey(proposal, index)}-${item}`"
              >
                {{ item }}
              </span>
              <span v-if="!proposalEvidenceItems(proposal).length">—</span>
            </div>

            <div class="evo-proposal-actions" data-column="动作">
              <button
                type="button"
                class="evo-ghost-action"
                :aria-expanded="isProposalExpanded(proposal, index)"
                @click="toggleProposalDetails(proposal, index)"
              >
                {{ isProposalExpanded(proposal, index) ? '收起' : '详情' }}
              </button>
              <button
                type="button"
                class="evo-ghost-action"
                :disabled="rowActionDisabled(proposal, 'accept')"
                @click="accept(proposal)"
              >
                {{ rowActionLoading(proposal, 'accept') ? '处理中' : '接受' }}
              </button>
              <div
                v-if="rejectMetadataTags(proposal, index).length"
                class="evo-reject-metadata-preview"
                data-review-metadata-preview
              >
                <small>审核标签</small>
                <span v-for="tag in rejectMetadataTags(proposal, index)" :key="`review-tag-${proposalKey(proposal, index)}-${tag}`">
                  {{ tag }}
                </span>
              </div>
              <button
                type="button"
                class="evo-ghost-action danger"
                aria-haspopup="dialog"
                data-open-reject-dialog
                :disabled="rowActionDisabled(proposal, 'reject')"
                @click="openRejectDialog(proposal, index)"
              >
                {{ rowActionLoading(proposal, 'reject') ? '拒绝中' : '拒绝' }}
              </button>
            </div>
          </div>

          <div v-if="isProposalExpanded(proposal, index)" class="evo-proposal-main" data-proposal-details>
            <div class="evo-proposal-head">
              <strong>{{ proposal.title }}</strong>
              <span>{{ proposalStatusLabel(proposal) }}</span>
              <span
                v-if="proposalDeepLinkMatched(proposal)"
                class="evo-deep-link-badge"
                data-deep-link-marker="proposal"
                :data-deep-link-state="proposalDeepLinkStateForRow(proposal)"
              >
                {{ proposalDeepLinkLabel(proposal) }}
              </span>
            </div>
            <div class="evo-proposal-meta">
              <code>{{ displayText(proposal.targetFile) }}</code>
              <small>{{ proposalOperationLabel(proposal) }}</small>
              <small v-if="proposal.gateDecision">{{ proposal.gateLabel }}</small>
              <small v-if="proposal.preflightStatus">预检 {{ proposal.preflightLabel }}</small>
              <small v-if="proposal.riskLevel">风险 {{ proposal.riskLevel }}</small>
            </div>
            <p>{{ proposal.summary }}</p>
            <p v-if="proposal.rationale !== proposal.summary" class="evo-proposal-rationale">
              {{ proposal.rationale }}
            </p>
            <div v-if="hasHypothesisDetails(proposal)" class="evo-hypothesis-grid">
              <div v-if="proposal.hypothesis" class="wide">
                <small>假设</small>
                <p>{{ proposal.hypothesis }}</p>
              </div>
              <div v-if="proposal.triggerCondition">
                <small>触发条件</small>
                <p>{{ proposal.triggerCondition }}</p>
              </div>
              <div v-if="proposal.expectedEffect">
                <small>预期效果</small>
                <p>{{ proposal.expectedEffect }}</p>
              </div>
              <div v-if="proposal.metricTargetRows.length">
                <small>指标目标</small>
                <dl>
                  <template v-for="metric in proposal.metricTargetRows" :key="metric.name">
                    <dt>{{ metric.name }}</dt>
                    <dd>{{ metric.value }}</dd>
                  </template>
                </dl>
              </div>
              <div v-if="hasProposalEvidenceTargets(proposal)">
                <small>证据</small>
                <div class="evo-id-list evo-evidence-link-list">
                  <EvidenceLink
                    v-for="target in proposalEvidenceTargets(proposal)"
                    :key="target.key"
                    :target="target.target"
                    :kind="target.kind || 'game'"
                    :label="target.label"
                    :class="target.className"
                    compact
                    disabled-label="缺少证据定位字段"
                  />
                </div>
              </div>
              <div v-if="proposal.preflightReasons.length" class="wide">
                <small>预检</small>
                <div class="evo-proposal-tags compact">
                  <span v-for="reason in proposal.preflightReasons" :key="`preflight-${proposal.id}-${reason}`">{{ reason }}</span>
                </div>
              </div>
            </div>
            <div v-if="proposal.riskTags.length || proposal.gateReasons.length" class="evo-proposal-tags">
              <span v-for="tag in proposal.riskTags" :key="`risk-${tag}`">{{ tag }}</span>
              <span v-for="reason in proposal.gateReasons" :key="`gate-${reason}`">{{ reason }}</span>
            </div>
            <JudgeEvidencePanel
              v-if="hasProposalJudgeEvidence(proposal)"
              class="evo-proposal-judge-evidence"
              data-evolution-proposal-judge-evidence
              :evidence="proposalJudgeEvidence(proposal)"
              :row-key="`proposal-${proposalKey(proposal, index)}`"
            />
            <section
              v-if="proposal.rejectBuffer?.visible"
              class="evo-reject-buffer-panel"
              data-reject-buffer-panel
            >
              <header>
                <small>拒绝缓冲</small>
                <b>{{ rejectBufferStatusLabel(proposal.rejectBuffer) }}</b>
              </header>
              <div class="evo-reject-buffer-grid">
                <span v-if="proposal.rejectBuffer.savedLabel">
                  <small>保存</small><b>{{ proposal.rejectBuffer.savedLabel }}</b>
                </span>
                <span v-if="proposal.rejectBuffer.duplicateLabel">
                  <small>去重</small><b>{{ proposal.rejectBuffer.duplicateLabel }}</b>
                </span>
                <span v-if="proposal.rejectBuffer.dedupeKey">
                  <small>去重键</small><code>{{ proposal.rejectBuffer.dedupeKey }}</code>
                </span>
                <span v-if="proposal.rejectBuffer.scope">
                  <small>范围</small><b>{{ proposal.rejectBuffer.scope }}</b>
                </span>
                <span v-if="proposal.rejectBuffer.similarityScore != null">
                  <small>相似度</small><b>{{ scoreLabel(proposal.rejectBuffer.similarityScore) }}</b>
                </span>
                <span v-if="proposal.rejectBuffer.overfitScore != null">
                  <small>过拟合</small><b>{{ scoreLabel(proposal.rejectBuffer.overfitScore) }}</b>
                </span>
              </div>
              <p v-if="proposal.rejectBuffer.reason">{{ proposal.rejectBuffer.reason }}</p>
              <div
                v-if="proposal.rejectBuffer.tags.length || proposal.rejectBuffer.overfitEvidence.length"
                class="evo-proposal-tags compact"
              >
                <span v-for="tag in proposal.rejectBuffer.tags" :key="`reject-tag-${proposal.id}-${tag}`">{{ tag }}</span>
                <span v-for="item in proposal.rejectBuffer.overfitEvidence" :key="`overfit-${proposal.id}-${item}`">{{ item }}</span>
              </div>
              <div
                v-if="proposal.rejectBuffer.matched.proposalId || proposal.rejectBuffer.matched.sourceRunId || proposal.rejectBuffer.matched.reason"
                class="evo-reject-buffer-match"
              >
                <small>命中拒绝记录</small>
                <b v-if="rejectBufferMatchedLabel(proposal.rejectBuffer.matched)">
                  {{ rejectBufferMatchedLabel(proposal.rejectBuffer.matched) }}
                </b>
                <p v-if="proposal.rejectBuffer.matched.reason">{{ proposal.rejectBuffer.matched.reason }}</p>
              </div>
            </section>
            <pre v-if="proposal.diffPreview && proposal.diffPreview !== '—'">{{ proposal.diffPreview }}</pre>
          </div>
        </section>
      </div>

      <div v-if="pairedSeeds.length" class="evo-paired-seeds">
        <h3>配对种子明细</h3>
        <div class="evo-paired-table">
          <span>种子</span>
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
    <RejectDialog
      :open="rejectDialogOpen"
      :proposal="rejectDialogProposal"
      :reason="rejectDialogReason"
      :tags="rejectDialogTags"
      :reject-buffer="rejectDialogProposal?.rejectBuffer || {}"
      :busy="rejectDialogBusy"
      :disabled="rejectDialogDisabled"
      @cancel="closeRejectDialog"
      @confirm="confirmRejectDialog"
    />
    <TrustBundleDrawer :evo="evo" />
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

.evo-proposal-toolbar-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}

.evo-proposal-bulk-tools {
  display: grid;
  grid-template-columns: minmax(190px, 0.8fr) minmax(180px, 1fr) auto;
  align-items: end;
  gap: 8px;
  min-width: 0;
  margin: 0 0 12px;
  padding: 8px;
  border: 1px solid rgba(58, 42, 24, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 250, 0.52);
}

.evo-proposal-bulk-counts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  min-width: 0;
}

.evo-proposal-bulk-counts span {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid var(--evo-border);
  border-radius: 6px;
  background: var(--evo-input-bg);
}

.evo-proposal-bulk-counts small,
.evo-proposal-bulk-reason small {
  overflow: hidden;
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-proposal-bulk-reason em {
  color: var(--evo-danger);
  font-size: 10px;
  font-style: normal;
  font-weight: 800;
}

.evo-proposal-bulk-counts b {
  color: var(--evo-text);
  font-size: 13px;
  font-weight: 850;
}

.evo-proposal-bulk-reason {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.evo-proposal-bulk-reason input {
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

.evo-proposal-bulk-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 7px;
  min-width: 0;
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

.evo-gate-strip--deep-link-target {
  padding: 2px;
  border: 1px solid rgba(139, 108, 50, 0.26);
  border-radius: 9px;
  background: rgba(139, 108, 50, 0.045);
}

.evo-gate-strip--deep-link-pending,
.evo-gate-strip--deep-link-unmatched {
  border-color: rgba(139, 58, 42, 0.24);
  background: rgba(139, 58, 42, 0.045);
}

.evo-deep-link-inline {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
  margin: -6px 0 12px;
}

.evo-deep-link-inline span,
.evo-deep-link-badge {
  max-width: 100%;
  overflow: hidden;
  padding: 3px 7px;
  border: 1px solid rgba(139, 108, 50, 0.24);
  border-radius: 6px;
  background: rgba(139, 108, 50, 0.08);
  color: var(--evo-accent-strong);
  font-size: 10px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-deep-link-inline[data-deep-link-state="pending"] span,
.evo-deep-link-badge[data-deep-link-state="pending"] {
  border-color: rgba(139, 108, 50, 0.28);
  background: rgba(139, 108, 50, 0.1);
}

.evo-deep-link-inline[data-deep-link-state="unmatched"] span,
.evo-deep-link-badge[data-deep-link-state="unmatched"] {
  border-color: rgba(139, 58, 42, 0.24);
  background: rgba(139, 58, 42, 0.07);
  color: var(--evo-danger);
}

.evo-gate-deep-link-marker {
  display: grid;
  gap: 3px;
}

.evo-judge-evidence-band {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  min-width: 0;
  margin: -4px 0 14px;
}

.evo-judge-evidence-card {
  --log-accent: var(--evo-accent);
  --log-text: var(--evo-text);
  --log-text-secondary: var(--evo-text-secondary);
  display: grid;
  gap: 7px;
  min-width: 0;
  overflow: hidden;
  padding: 9px 10px;
  border: 1px solid rgba(139, 108, 50, 0.18);
  border-radius: 8px;
  background: rgba(255, 255, 250, 0.55);
}

.evo-judge-evidence-card > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.evo-judge-evidence-card > header small {
  overflow: hidden;
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-weight: 850;
  letter-spacing: 0;
  line-height: 1.1;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}

.evo-judge-evidence-card > header b {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text);
  font-size: 11px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-proposal-judge-evidence {
  --log-accent: var(--evo-accent);
  --log-text: var(--evo-text);
  --log-text-secondary: var(--evo-text-secondary);
  min-width: 0;
  overflow: hidden;
}

.evo-judge-evidence-card :deep(.review-judge-evidence),
.evo-proposal-main :deep(.review-judge-evidence) {
  min-width: 0;
  max-width: 100%;
}

.evo-judge-evidence-card :deep(.review-judge-evidence-grid),
.evo-proposal-main :deep(.review-judge-evidence-grid),
.evo-judge-evidence-card :deep(.review-judge-evidence-block),
.evo-proposal-main :deep(.review-judge-evidence-block) {
  min-width: 0;
}

.evo-proposal-list {
  display: grid;
  gap: 1px;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--evo-border);
  border-radius: 8px;
  background: var(--evo-border);
}

.evo-proposal-list-head,
.evo-proposal-audit-row {
  display: grid;
  grid-template-columns:
    minmax(86px, 0.7fr)
    minmax(150px, 1.35fr)
    minmax(62px, 0.55fr)
    minmax(180px, 1.7fr)
    minmax(150px, 1.25fr)
    minmax(118px, 0.95fr)
    minmax(138px, 0.82fr);
  gap: 1px;
  min-width: 0;
}

.evo-proposal-list-head {
  background: rgba(58, 42, 24, 0.08);
}

.evo-proposal-list-head span {
  min-width: 0;
  overflow: hidden;
  padding: 6px 8px;
  background: rgba(255, 255, 250, 0.64);
  color: var(--evo-accent-strong);
  font-size: 10px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-proposal-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0;
  min-width: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: var(--evo-input-bg);
}

.evo-proposal-row[data-status="accepted"],
.evo-proposal-row[data-status="applied"] {
  border-color: var(--evo-success-border);
  background: var(--evo-success-bg);
}

.evo-proposal-row[data-status="rejected"] {
  border-color: rgba(139, 58, 42, 0.28);
  background: rgba(139, 58, 42, 0.045);
}

.evo-proposal-row--deep-link-target {
  border-color: rgba(139, 108, 50, 0.48);
  box-shadow: inset 3px 0 0 rgba(139, 108, 50, 0.36);
}

.evo-proposal-row--deep-link-pending {
  border-color: rgba(139, 108, 50, 0.48);
  background: rgba(139, 108, 50, 0.055);
}

.evo-proposal-row--deep-link-unmatched {
  border-color: rgba(139, 58, 42, 0.28);
  background: rgba(139, 58, 42, 0.045);
}

.evo-proposal-main {
  display: grid;
  gap: 7px;
  min-width: 0;
  padding: 10px 12px 12px;
  border-top: 1px solid var(--evo-border);
  background: rgba(255, 255, 250, 0.52);
}

.evo-proposal-audit-row > div {
  display: grid;
  align-content: start;
  gap: 5px;
  min-width: 0;
  padding: 8px;
  background: var(--evo-input-bg);
}

.evo-proposal-status-cell code,
.evo-proposal-target-cell code {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text-secondary);
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 10px;
  font-weight: 750;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-proposal-status-pill {
  width: max-content;
  max-width: 100%;
  overflow: hidden;
  padding: 2px 7px;
  border: 1px solid rgba(139, 108, 50, 0.18);
  border-radius: 5px;
  background: var(--evo-active-bg);
  color: var(--evo-accent-strong);
  font-size: 10px;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-proposal-target-cell strong,
.evo-proposal-operation-cell b {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text);
  font-size: 12px;
  font-weight: 850;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-proposal-operation-cell b {
  color: var(--evo-accent);
}

.evo-proposal-expected-cell p {
  display: -webkit-box;
  min-width: 0;
  overflow: hidden;
  margin: 0;
  color: var(--evo-text);
  font-size: 11px;
  font-weight: 650;
  line-height: 1.35;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.evo-proposal-risk-cell,
.evo-proposal-evidence-cell {
  display: flex !important;
  flex-wrap: wrap;
  align-content: flex-start;
  align-items: flex-start;
  gap: 4px;
}

.evo-proposal-risk-cell span,
.evo-proposal-evidence-cell span {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  padding: 2px 6px;
  border-radius: 5px;
  background: rgba(58, 42, 24, 0.06);
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-weight: 750;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.evo-proposal-head .evo-deep-link-badge {
  padding: 2px 7px;
  border-radius: 6px;
  background: rgba(139, 108, 50, 0.08);
  color: var(--evo-accent-strong);
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

.evo-hypothesis-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
  min-width: 0;
}

.evo-hypothesis-grid > div {
  display: grid;
  align-content: start;
  gap: 4px;
  min-width: 0;
  padding: 7px 8px;
  border: 1px solid rgba(58, 42, 24, 0.08);
  border-radius: 7px;
  background: rgba(255, 255, 250, 0.54);
}

.evo-hypothesis-grid > .wide {
  grid-column: 1 / -1;
}

.evo-hypothesis-grid small {
  overflow: hidden;
  color: var(--evo-accent-strong);
  font-size: 10px;
  font-weight: 800;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}

.evo-hypothesis-grid p {
  color: var(--evo-text-secondary);
  font-size: 11px;
  line-height: 1.45;
}

.evo-hypothesis-grid dl {
  display: grid;
  grid-template-columns: minmax(72px, 0.55fr) minmax(0, 1fr);
  gap: 3px 7px;
  margin: 0;
  min-width: 0;
}

.evo-hypothesis-grid dt,
.evo-hypothesis-grid dd {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text-secondary);
  font-size: 11px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-hypothesis-grid dt {
  color: var(--evo-text);
  font-weight: 800;
}

.evo-hypothesis-grid dd {
  margin: 0;
}

.evo-id-list {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  min-width: 0;
}

.evo-id-list code {
  max-width: 100%;
  overflow: hidden;
  padding: 2px 6px;
  border-radius: 5px;
  background: var(--evo-active-bg);
  color: var(--evo-text);
  font-size: 10px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-id-list code.counter {
  background: rgba(139, 58, 42, 0.1);
}

.evo-evidence-link-list {
  align-items: stretch;
}

.evo-evidence-link-list :deep(.evidence-link) {
  flex: 1 1 118px;
  max-width: 180px;
}

.evo-evidence-link-list :deep(.evidence-link.counter) {
  border-color: rgba(139, 58, 42, 0.18);
  background: rgba(139, 58, 42, 0.075);
}

.evo-evidence-link-list :deep(.evidence-link.proposal) {
  border-color: rgba(139, 108, 50, 0.22);
  background: rgba(139, 108, 50, 0.08);
}

.evo-proposal-tags.compact {
  gap: 5px;
}

.evo-proposal-tags.compact span {
  white-space: normal;
}

.evo-reject-buffer-panel {
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid rgba(139, 58, 42, 0.2);
  border-radius: 8px;
  background: rgba(139, 58, 42, 0.045);
}

.evo-reject-buffer-panel header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.evo-reject-buffer-panel header small,
.evo-reject-buffer-grid small,
.evo-reject-buffer-match small {
  overflow: hidden;
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-weight: 850;
  letter-spacing: 0;
  line-height: 1.1;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}

.evo-reject-buffer-panel header b,
.evo-reject-buffer-grid b,
.evo-reject-buffer-grid code,
.evo-reject-buffer-match b {
  min-width: 0;
  overflow: hidden;
  color: var(--evo-text);
  font-size: 11px;
  font-weight: 850;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-reject-buffer-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  min-width: 0;
}

.evo-reject-buffer-grid span {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 6px 7px;
  border: 1px solid rgba(139, 58, 42, 0.12);
  border-radius: 6px;
  background: rgba(255, 255, 250, 0.58);
}

.evo-reject-buffer-panel p,
.evo-reject-buffer-match p {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--evo-text-secondary);
  font-size: 11px;
  font-weight: 650;
  line-height: 1.35;
}

.evo-reject-buffer-match {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 7px 8px;
  border: 1px dashed rgba(139, 58, 42, 0.22);
  border-radius: 6px;
  background: rgba(255, 255, 250, 0.46);
}

.evo-proposal-main pre {
  max-height: 150px;
  overflow: auto;
  margin: 2px 0 0;
  padding: 8px 10px;
  border-radius: 7px;
  background: var(--evo-code-bg);
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

.evo-reject-metadata-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  min-width: 0;
  padding: 7px;
  border: 1px dashed rgba(139, 58, 42, 0.18);
  border-radius: 7px;
  background: rgba(139, 58, 42, 0.045);
}

.evo-reject-metadata-preview small,
.evo-reject-metadata-preview span {
  max-width: 100%;
  overflow: hidden;
  padding: 2px 6px;
  border-radius: 5px;
  background: rgba(58, 42, 24, 0.06);
  color: var(--evo-text-secondary);
  font-size: 10px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evo-reject-metadata-preview small {
  color: var(--evo-accent-strong);
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
  .evo-proposal-bulk-tools,
  .evo-proposal-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .evo-proposal-toolbar-actions {
    justify-content: stretch;
  }

  .evo-proposal-toolbar-actions > button,
  .evo-proposal-bulk-actions > button {
    flex: 1 1 0;
  }

  .evo-proposal-bulk-actions {
    justify-content: stretch;
  }

  .evo-proposal-kpis,
  .evo-gate-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .evo-judge-evidence-band {
    grid-template-columns: minmax(0, 1fr);
  }

  .evo-judge-evidence-card > header {
    align-items: start;
  }

  .evo-hypothesis-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .evo-reject-buffer-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .evo-paired-table {
    grid-template-columns: repeat(5, minmax(74px, 1fr));
    overflow-x: auto;
  }
}
</style>
