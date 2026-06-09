import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'vitest'

const rejectDialog = readFileSync(
  new URL('../src/components/evolution/RejectDialog.vue', import.meta.url),
  'utf8'
)
const proposalPanel = readFileSync(
  new URL('../src/components/evolution/EvolutionProposalReviewPanel.vue', import.meta.url),
  'utf8'
)
const evolutionWorkbench = readFileSync(
  new URL('../src/composables/useEvolutionWorkbench.ts', import.meta.url),
  'utf8'
)

function cssBlock(source, selector) {
  const index = source.indexOf(selector)
  assert.notEqual(index, -1, `Missing CSS selector: ${selector}`)
  const start = source.indexOf('{', index)
  let depth = 0
  for (let i = start; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1
    if (source[i] === '}') {
      depth -= 1
      if (depth === 0) return source.slice(start + 1, i)
    }
  }
  throw new Error(`Unclosed CSS selector: ${selector}`)
}

test('Evolution proposal review opens RejectDialog instead of inline reject input', () => {
  assert.match(proposalPanel, /import RejectDialog from '\.\/RejectDialog\.vue'/)
  assert.match(proposalPanel, /const rejectDialogOpen = ref\(false\)/)
  assert.match(proposalPanel, /const rejectDialogProposal = ref\(null\)/)
  assert.match(proposalPanel, /const rejectReviewMetadata = reactive\(\{\}\)/)
  assert.match(proposalPanel, /function openRejectDialog\(proposal, index\)[\s\S]*rejectDialogReason\.value = rejectReasons\[key\] \|\| proposal\?\.rejectBuffer\?\.reason \|\| ''[\s\S]*rejectDialogTags\.value = normalizeRejectTags/)
  assert.match(proposalPanel, /function rejectDialogActionDisabled\(proposal\)[\s\S]*if \(actionLoading\.value && !rowActionLoading\(proposal, 'reject'\)\) return true/)
  assert.match(proposalPanel, /data-open-reject-dialog/)
  assert.match(proposalPanel, /aria-haspopup="dialog"/)
  assert.match(proposalPanel, /@click="openRejectDialog\(proposal, index\)"/)
  assert.match(proposalPanel, /<RejectDialog[\s\S]*:reject-buffer="rejectDialogProposal\?\.rejectBuffer \|\| \{\}"[\s\S]*@confirm="confirmRejectDialog"/)
  assert.doesNotMatch(proposalPanel, /placeholder="拒绝原因"/)
  assert.doesNotMatch(proposalPanel, /function rejectInputDisabled/)
  assert.doesNotMatch(proposalPanel, /@click="reject\(proposal, index\)"/)
})

test('RejectDialog submits tags through the rejectProposal API and keeps local review metadata', () => {
  assert.match(proposalPanel, /function confirmRejectDialog\(payload\)[\s\S]*const reason = textValue\(payload\?\.reason\)[\s\S]*rejectReasons\[key\] = reason/)
  assert.match(proposalPanel, /const tags = normalizeRejectTags\(payload\?\.tags \|\| payload\?\.metadata\?\.tags \|\| \[\]\)/)
  assert.match(proposalPanel, /rejectReviewMetadata\[key\] = \{\s*\n\s*tags\s*\n\s*\}/)
  assert.match(proposalPanel, /await props\.evo\.rejectProposal\(proposal, props\.evo\.selectedRunId\.value, reason, \{ tags \}\)/)
  assert.match(evolutionWorkbench, /async function rejectProposal\(proposal, id = selectedRunId\.value, reason = '', options = \{\}\)/)
  assert.match(evolutionWorkbench, /const tags = textItems\(options\?\.tags, options\?\.metadata\?\.tags\)/)
  assert.match(evolutionWorkbench, /body: JSON\.stringify\(body\)/)
  assert.match(evolutionWorkbench, /reason: reason \|\| 'manual_reject',\s*\n\s*tags/)

  assert.match(rejectDialog, /const emit = defineEmits\(\['cancel', 'confirm'\]\)/)
  assert.match(rejectDialog, /metadata:\s*\{\s*\n\s*tags: \[\.\.\.tagDrafts\.value\],\s*\n\s*rejectBuffer: buffer\.value/)
  assert.match(rejectDialog, /标签会随拒绝原因写入后端拒绝缓冲，用于去重和过拟合审计。/)
  assert.match(rejectDialog, /data-review-metadata-tags/)
  assert.match(rejectDialog, /function normalizeTags\(tags\)/)
  assert.match(rejectDialog, /function handleTagKeydown\(event\)[\s\S]*event\.key !== 'Enter' && event\.key !== ','/)
  assert.match(rejectDialog, /@keydown="handleTagKeydown"/)
  assert.match(rejectDialog, /@click="removeTag\(tag\)"/)
})

test('RejectDialog requires reason and exposes busy disabled states', () => {
  assert.match(rejectDialog, /const normalizedReason = computed\(\(\) => reasonDraft\.value\.trim\(\)\)/)
  assert.match(rejectDialog, /const hasReason = computed\(\(\) => Boolean\(normalizedReason\.value\)\)/)
  assert.match(rejectDialog, /const canConfirm = computed\(\(\) => props\.open && !props\.busy && !props\.disabled && hasReason\.value\)/)
  assert.match(rejectDialog, /const showReasonError = computed\(\(\) => reasonTouched\.value && !hasReason\.value\)/)
  assert.match(rejectDialog, /<textarea[\s\S]*v-model="reasonDraft"[\s\S]*:aria-invalid="showReasonError \? 'true' : 'false'"[\s\S]*:disabled="busy \|\| disabled"[\s\S]*required/)
  assert.match(rejectDialog, /<em v-if="showReasonError">拒绝原因不能为空。<\/em>/)
  assert.match(rejectDialog, /data-reject-confirm[\s\S]*:disabled="!canConfirm"[\s\S]*\{\{ busy \? '拒绝中' : '确认拒绝' \}\}/)
  assert.match(rejectDialog, /function cancel\(\)[\s\S]*if \(props\.busy\) return[\s\S]*emit\('cancel'\)/)
  assert.match(rejectDialog, /@click\.self="cancel"/)
  assert.match(rejectDialog, /@keydown\.esc\.prevent="cancel"/)
})

test('RejectDialog summarizes reject buffer duplicate similarity and overfit risk', () => {
  assert.match(rejectDialog, /data-reject-buffer-summary/)
  assert.match(rejectDialog, /const hasBufferSummary = computed\(\(\) => Boolean\(buffer\.value\?\.visible\)\)/)
  assert.match(rejectDialog, /buffer\.value\.duplicateLabel/)
  assert.match(rejectDialog, /buffer\.value\.dedupeKey/)
  assert.match(rejectDialog, /buffer\.value\.similarityScore != null/)
  assert.match(rejectDialog, /buffer\.value\.overfitScore != null/)
  assert.match(rejectDialog, /const hasMatched = computed\(\(\) => Boolean\(matched\.value\.proposalId \|\| matched\.value\.sourceRunId \|\| matched\.value\.reason\)\)/)
  assert.match(rejectDialog, /命中拒绝记录/)
  assert.match(rejectDialog, /buffer\.value\.overfitEvidence/)
})

test('RejectDialog layout is constrained for mobile and cannot widen the viewport', () => {
  const dialogBlock = cssBlock(rejectDialog, '.evo-reject-dialog {')
  const gridBlock = cssBlock(rejectDialog, '.evo-reject-dialog-buffer-grid {')
  const mobileBlock = rejectDialog.slice(rejectDialog.indexOf('@media (max-width: 760px)'))

  assert.match(dialogBlock, /width:\s*min\(720px,\s*100%\)/)
  assert.match(dialogBlock, /max-height:\s*calc\(100dvh - 32px\)/)
  assert.match(dialogBlock, /overflow:\s*auto/)
  assert.match(gridBlock, /grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/)
  assert.match(mobileBlock, /\.evo-reject-dialog\s*\{[\s\S]*width:\s*min\(100%,\s*calc\(100vw - 20px\)\)/)
  assert.match(mobileBlock, /\.evo-reject-dialog\s*\{[\s\S]*max-height:\s*calc\(100dvh - 20px\)/)
  assert.match(mobileBlock, /\.evo-reject-dialog-buffer-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/)
  assert.match(mobileBlock, /\.evo-reject-dialog-tag-editor,[\s\S]*\.evo-reject-dialog-actions\s*\{[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\)/)
})
