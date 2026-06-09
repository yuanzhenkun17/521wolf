import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

const reviewPanel = readSource('../src/components/evolution/EvolutionProposalReviewPanel.vue')

test('Evolution review workspace presents proposals as a compact audit list', () => {
  assert.match(reviewPanel, /data-review-audit-list/)
  assert.match(reviewPanel, /class="evo-proposal-list-head"[\s\S]*状态[\s\S]*目标[\s\S]*操作[\s\S]*预期[\s\S]*风险[\s\S]*证据[\s\S]*动作/)
  assert.match(reviewPanel, /class="evo-proposal-audit-row"/)
  assert.match(reviewPanel, /data-column="状态"/)
  assert.match(reviewPanel, /data-column="目标"/)
  assert.match(reviewPanel, /data-column="操作"/)
  assert.match(reviewPanel, /data-column="预期"/)
  assert.match(reviewPanel, /data-column="风险"/)
  assert.match(reviewPanel, /data-column="证据"/)
  assert.match(reviewPanel, /data-column="动作"/)
})

test('Evolution review compact rows keep existing audited proposal details expandable', () => {
  assert.match(reviewPanel, /const expandedProposalKeys = ref\(new Set\(\)\)/)
  assert.match(reviewPanel, /function toggleProposalDetails\(proposal, index\)/)
  assert.match(reviewPanel, /:aria-expanded="isProposalExpanded\(proposal, index\)"/)
  assert.match(reviewPanel, /data-proposal-details/)

  for (const required of [
    '假设',
    '触发条件',
    '预期效果',
    '指标目标',
    '证据',
    '预检',
    '拒绝缓冲',
    '差异'
  ]) {
    assert.match(reviewPanel, new RegExp(required))
  }
})

test('Evolution review compact rows preserve proposal actions and bulk reject guard', () => {
  assert.match(reviewPanel, /@click="accept\(proposal\)"/)
  assert.match(reviewPanel, /@click="openRejectDialog\(proposal, index\)"/)
  assert.match(reviewPanel, /data-open-reject-dialog/)
  assert.match(reviewPanel, /const bulkRejectReasonText = computed\(\(\) => textValue\(bulkRejectReason\.value\)\)/)
  assert.match(reviewPanel, /批量拒绝必须填写原因。/)
  assert.match(reviewPanel, /await props\.evo\.rejectProposal\(proposal, runId, bulkRejectReasonText\.value\)/)
})
