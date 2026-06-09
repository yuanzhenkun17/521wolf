import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const proposalPanel = readFileSync(
  new URL('../src/components/evolution/EvolutionProposalReviewPanel.vue', import.meta.url),
  'utf8'
)

test('Evolution proposal review reuses JudgeEvidencePanel for gate and attribution evidence', () => {
  assert.match(proposalPanel, /import JudgeEvidencePanel from '\.\.\/history\/JudgeEvidencePanel\.vue'/)
  assert.match(proposalPanel, /const gateJudgeEvidence = computed\(\(\) => normalizeJudgeEvidence\(gate\.value, gate\.value\.releaseGate\)\)/)
  assert.match(proposalPanel, /const attributionJudgeEvidence = computed\(\(\) => normalizeJudgeEvidence\([\s\S]*proposalAttribution\.value[\s\S]*proposalAttribution\.value\.rows/)
  assert.match(proposalPanel, /data-evolution-judge-evidence="gate-attribution"/)
  assert.match(proposalPanel, /data-evolution-gate-judge-evidence/)
  assert.match(proposalPanel, /<JudgeEvidencePanel[\s\S]*:evidence="gateJudgeEvidence"[\s\S]*:row-key="`gate-\$\{gateReportId \|\| selectedEvidenceRunId\(\)\}`"/)
  assert.match(proposalPanel, /data-evolution-attribution-judge-evidence/)
  assert.match(proposalPanel, /<JudgeEvidencePanel[\s\S]*:evidence="attributionJudgeEvidence"[\s\S]*:row-key="`attribution-\$\{gateReportId \|\| selectedEvidenceRunId\(\)\}`"/)
})

test('Evolution judge evidence normalization accepts snake_case and camelCase judge fields', () => {
  assert.match(proposalPanel, /function normalizeJudgeEvidence\(\.\.\.sources\)/)
  assert.match(proposalPanel, /evidenceRefs:\s*\['evidenceRefs', 'evidence_refs', 'evidenceRef', 'evidence_ref'\]/)
  assert.match(proposalPanel, /counterfactuals:\s*\['counterfactuals', 'counterfactual'/)
  assert.match(proposalPanel, /rubricMisses:\s*\['rubricMisses', 'rubric_misses', 'rubricMiss', 'rubric_miss'\]/)
  assert.match(proposalPanel, /degradedReasons:\s*\['degradedReasons', 'degraded_reasons', 'degradedReason', 'degraded_reason'/)
  assert.match(proposalPanel, /warnings:\s*\['warnings', 'warning'\]/)
  assert.match(proposalPanel, /diagnostics:\s*\['diagnostics', 'diagnostic'\]/)
  assert.match(proposalPanel, /appendJudgeEvidenceSource\(target, source\[key\], seenSources\)/)
  assert.match(proposalPanel, /'decision_judge_evidence'/)
  assert.match(proposalPanel, /'proposal_evidence'/)
  assert.match(proposalPanel, /'attribution_evidence'/)
})

test('Evolution proposal rows show shared expandable judge evidence without replacing review actions', () => {
  assert.match(proposalPanel, /function proposalJudgeEvidence\(proposal\)[\s\S]*normalizeJudgeEvidence\(proposal, proposal\?\.gate, proposal\?\.risk, proposal\?\.preflight\)/)
  assert.match(proposalPanel, /function hasProposalJudgeEvidence\(proposal\)[\s\S]*hasJudgeEvidence\(proposalJudgeEvidence\(proposal\)\)/)
  assert.match(proposalPanel, /v-if="hasProposalJudgeEvidence\(proposal\)"/)
  assert.match(proposalPanel, /data-evolution-proposal-judge-evidence/)
  assert.match(proposalPanel, /:evidence="proposalJudgeEvidence\(proposal\)"/)
  assert.match(proposalPanel, /:row-key="`proposal-\$\{proposalKey\(proposal, index\)\}`"/)

  assert.match(proposalPanel, /data-bulk-review-tools/)
  assert.match(proposalPanel, /async function runBulkReview\(action, items\)/)
  assert.match(proposalPanel, /await props\.evo\.acceptProposal\(proposal, runId\)/)
  assert.match(proposalPanel, /await props\.evo\.rejectProposal\(proposal, runId, bulkRejectReason\.value\)/)
  assert.match(proposalPanel, /<RejectDialog[\s\S]*@confirm="confirmRejectDialog"/)
  assert.match(proposalPanel, /@click="openRejectDialog\(proposal, index\)"/)
})

test('Evolution judge evidence uses mobile-safe layout constraints', () => {
  assert.match(proposalPanel, /\.evo-judge-evidence-band\s*\{[\s\S]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)[\s\S]*min-width:\s*0/)
  assert.match(proposalPanel, /\.evo-judge-evidence-card\s*\{[\s\S]*--log-accent:\s*var\(--evo-accent\)[\s\S]*overflow:\s*hidden/)
  assert.match(proposalPanel, /\.evo-proposal-judge-evidence\s*\{[\s\S]*min-width:\s*0[\s\S]*overflow:\s*hidden/)
  assert.match(proposalPanel, /\.evo-judge-evidence-card :deep\(\.review-judge-evidence\),[\s\S]*\.evo-proposal-main :deep\(\.review-judge-evidence\)[\s\S]*max-width:\s*100%/)
  assert.match(proposalPanel, /@media \(max-width: 760px\)[\s\S]*\.evo-judge-evidence-band\s*\{[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\)/)
})
