import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { buildEvidenceLink } from '../src/components/history/evidenceLinks.js'

const proposalPanel = readFileSync(
  new URL('../src/components/evolution/EvolutionProposalReviewPanel.vue', import.meta.url),
  'utf8'
)
const evolutionWorkbench = readFileSync(
  new URL('../src/composables/useEvolutionWorkbench.js', import.meta.url),
  'utf8'
)

test('Proposal review renders evidence and counter evidence through EvidenceLink', () => {
  assert.match(proposalPanel, /import EvidenceLink from '\.\.\/history\/EvidenceLink\.vue'/)
  assert.match(proposalPanel, /function proposalGameEvidenceTargets/)
  assert.match(proposalPanel, /history_game_id:\s*gameId/)
  assert.match(proposalPanel, /game_id:\s*gameId/)
  assert.match(proposalPanel, /source_run_id:\s*selectedEvidenceRunId\(\)/)
  assert.match(proposalPanel, /proposal_id:\s*proposalEvidenceId\(proposal\)/)
  assert.match(proposalPanel, /class="evo-id-list evo-evidence-link-list"/)
  assert.match(proposalPanel, /<EvidenceLink[\s\S]*v-for="target in proposalEvidenceTargets\(proposal\)"[\s\S]*:kind="target\.kind \|\| 'game'"/)
  assert.doesNotMatch(proposalPanel, /<code\s+v-for="id in proposal\.evidenceGameIds/)
  assert.doesNotMatch(proposalPanel, /<code[\s\S]+v-for="id in proposal\.counterEvidenceGameIds/)
})

test('Proposal review falls back to run-scoped proposal evidence without empty links', () => {
  assert.match(proposalPanel, /function proposalFallbackEvidenceTarget/)
  assert.match(proposalPanel, /label:\s*'提案'/)
  assert.match(proposalPanel, /kind:\s*'proposal'/)
  assert.match(proposalPanel, /disabled-label="缺少证据定位字段"/)

  const proposalLink = buildEvidenceLink({
    source_run_id: 'evo-run-a',
    proposal_id: 'proposal-a'
  }, { kind: 'proposal', label: 'Proposal' })
  assert.equal(proposalLink.disabled, false)
  assert.equal(proposalLink.href, '#evolution?run_id=evo-run-a&proposal_id=proposal-a')

  const missingRun = buildEvidenceLink({ proposal_id: 'proposal-a' }, { kind: 'proposal' })
  assert.equal(missingRun.disabled, true)
  assert.equal(missingRun.href, '')
  assert.match(missingRun.unavailableReason, /source_run_id\/run_id/)

  const missingProposal = buildEvidenceLink({ source_run_id: 'evo-run-a' }, { kind: 'proposal' })
  assert.equal(missingProposal.disabled, true)
  assert.equal(missingProposal.href, '')
  assert.match(missingProposal.unavailableReason, /proposal_id/)
})

test('Proposal review evidence game ids deep-link to Logs archive workspace', () => {
  const gameLink = buildEvidenceLink({
    history_game_id: 'history-game-a',
    source_run_id: 'evo-run-a',
    proposal_id: 'proposal-a'
  }, { kind: 'game', label: 'Game' })
  assert.equal(gameLink.disabled, false)
  assert.equal(gameLink.href, '#logs?game_id=history-game-a&workspace=archive')
  assert.equal(gameLink.id, 'history-game-a')
})

test('Proposal review surfaces reject buffer dedupe and overfit audit results', () => {
  assert.match(evolutionWorkbench, /function normalizeRejectBuffer\(proposal, risk = \{\}\)/)
  assert.match(evolutionWorkbench, /proposal\?\.reject_buffer/)
  assert.match(evolutionWorkbench, /proposal\?\.rejectBuffer/)
  assert.match(evolutionWorkbench, /proposal\?\.reject_result/)
  assert.match(evolutionWorkbench, /similarity\.duplicate_rejected/)
  assert.match(evolutionWorkbench, /buffer\.dedupe_key \|\| buffer\.dedupeKey/)
  assert.match(evolutionWorkbench, /proposal\?\.overfit_risk_score/)
  assert.match(evolutionWorkbench, /matchedRejection\.source_run_id/)
  assert.match(evolutionWorkbench, /rejectBuffer,\s*\n\s*gateDecision:/)

  assert.match(proposalPanel, /function rejectBufferStatusLabel\(buffer = \{\}\)/)
  assert.match(proposalPanel, /function rejectBufferMatchedLabel\(matched = \{\}\)/)
  assert.match(proposalPanel, /data-reject-buffer-panel/)
  assert.match(proposalPanel, /proposal\.rejectBuffer\?\.visible/)
  assert.match(proposalPanel, /proposal\.rejectBuffer\.dedupeKey/)
  assert.match(proposalPanel, /proposal\.rejectBuffer\.similarityScore != null/)
  assert.match(proposalPanel, /proposal\.rejectBuffer\.overfitScore != null/)
  assert.match(proposalPanel, /proposal\.rejectBuffer\.matched\.proposalId/)
  assert.match(proposalPanel, /\.evo-reject-buffer-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/)
  assert.match(proposalPanel, /@media \(max-width: 760px\)[\s\S]*\.evo-reject-buffer-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/)
})
