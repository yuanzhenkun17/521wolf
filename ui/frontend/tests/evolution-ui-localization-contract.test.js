import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'vitest'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

const page = readSource('../src/pages/EvolutionPage.vue')
const proposalPanel = readSource('../src/components/evolution/EvolutionProposalReviewPanel.vue')
const rejectDialog = readSource('../src/components/evolution/RejectDialog.vue')
const trustDrawer = readSource('../src/components/evolution/TrustBundleDrawer.vue')
const versionsPanel = readSource('../src/components/evolution/EvolutionVersionsPanel.vue')
const workbench = readSource('../src/composables/useEvolutionWorkbench.ts')

test('Evolution review, reject, trust, and version panels use Chinese-first visible labels', () => {
  const combined = [proposalPanel, rejectDialog, trustDrawer, versionsPanel].join('\n')

  for (const required of [
    '门禁',
    '发布',
    '配对种子',
    '场景复盘',
    '策略违规',
    '归因',
    '定位链接',
    '假设',
    '触发条件',
    '预期效果',
    '证据',
    '预检',
    '拒绝缓冲',
    '去重键',
    '范围',
    '命中拒绝记录',
    '审核标签',
    '信任包',
    '一致性检查',
    '训练证据',
    '提案证据',
    '来源运行'
  ]) {
    assert.match(combined, new RegExp(required))
  }

  for (const legacyVisibleLabel of [
    /<small>Gate<\/small>/,
    /<small>Release<\/small>/,
    /<small>Paired Seeds<\/small>/,
    /<small>Scenario<\/small>/,
    /<small>Policy<\/small>/,
    /<small>Attribution<\/small>/,
    /<small>Deep Link<\/small>/,
    /<small>Hypothesis<\/small>/,
    /<small>Trigger<\/small>/,
    /<small>Expected<\/small>/,
    /<small>Evidence<\/small>/,
    /<small>Preflight<\/small>/,
    /<small>Reject Buffer<\/small>/,
    /<small>Dedupe Key<\/small>/,
    /<small>Scope<\/small>/,
    /<small>Matched Rejection<\/small>/,
    /<small>Review Tags<\/small>/,
    /<h2>Trust Bundle<\/h2>/,
    /aria-label="Trust Bundle 审计"/,
    /<h3>Training Evidence<\/h3>/,
    /<h3>Proposal Evidence<\/h3>/,
    /<h3>Paired Seeds<\/h3>/,
    /<button[^>]*>Trust 审计<\/button>/,
    /Proposal Reject/,
    /Tags 会随拒绝原因写入后端 reject buffer/
  ]) {
    assert.doesNotMatch(combined, legacyVisibleLabel)
  }
})

test('Evolution batch reject requires a visible reason before submitting', () => {
  assert.match(proposalPanel, /const bulkRejectReasonText = computed\(\(\) => textValue\(bulkRejectReason\.value\)\)/)
  assert.match(proposalPanel, /const bulkRejectDisabledReason = computed\(\(\) =>/)
  assert.match(proposalPanel, /批量拒绝必须填写原因。/)
  assert.match(proposalPanel, /const canBulkReject = computed\(\(\) => \([\s\S]*!bulkRejectDisabledReason\.value/)
  assert.match(proposalPanel, /if \(action === 'reject' && !bulkRejectReasonText\.value\) return/)
  assert.match(proposalPanel, /await props\.evo\.rejectProposal\(proposal, runId, bulkRejectReasonText\.value\)/)
  assert.match(proposalPanel, /<em v-if="bulkRejectDisabledReason">\{\{ bulkRejectDisabledReason \}\}<\/em>/)
})

test('Evolution page avoids non-functional tab icons and account-style chrome', () => {
  assert.doesNotMatch(page, /icon:\s*['"]/)
  assert.doesNotMatch([page, proposalPanel, rejectDialog, trustDrawer, versionsPanel].join('\n'), /Owner|Profile|Settings|Account|Team|通知中心|账号|团队/)
})

test('Evolution trust audit messages are localized while keeping code field names', () => {
  assert.match(workbench, /authority:\s*'权威信任包'/)
  assert.match(workbench, /review:\s*'提案审核'/)
  assert.match(workbench, /message: panel \? '等待恢复定位链接目标。' : '等待恢复自进化定位链接。'/)
  assert.match(workbench, /缺少信任包：未收到 trust_bundle_id 或 bundle_hash。/)
  assert.match(workbench, /权威信任包与当前页面缓存不一致。/)
  assert.match(workbench, /缓存、版本库\/来源运行与权威包一致。/)
  assert.doesNotMatch(workbench, /权威 Trust Bundle|Evolution deep link|deep link 目标|Authority Bundle|Proposal Review/)
})
