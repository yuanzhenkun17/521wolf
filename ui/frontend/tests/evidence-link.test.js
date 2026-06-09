import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  buildEvidenceLink,
  buildEvidenceLinks,
  buildHashLink,
  gameEvidenceId,
  proposalEvidenceId,
  runEvidenceId
} from '../src/components/history/evidenceLinks.js'

test('evidence hash links use stable archive and evolution routes', () => {
  assert.equal(buildHashLink('logs', { game_id: 'game/1' }), '#logs?game_id=game%2F1')
  assert.equal(buildHashLink('evidence', { game_id: 'game/1' }), '#evidence?game_id=game%2F1')
  assert.equal(
    buildHashLink('evolution', { run_id: 'run 1', proposal_id: 'proposal+1' }),
    '#evolution?run_id=run+1&proposal_id=proposal%2B1'
  )
})

test('game evidence prefers persisted history game id for archive jumps', () => {
  const link = buildEvidenceLink({
    game_id: 'runtime-game',
    history_game_id: 'history-game'
  }, { kind: 'game', label: 'Archive' })

  assert.equal(gameEvidenceId({ game_id: 'runtime-game', history_game_id: 'history-game' }), 'history-game')
  assert.equal(link.disabled, false)
  assert.equal(link.href, '#evidence?game_id=history-game')
  assert.equal(link.label, 'Archive')
  assert.equal(link.id, 'history-game')
})

test('run and proposal evidence links preserve run-scoped proposal context', () => {
  const source = {
    evidence_source: {
      source_run_id: 'evo-run-7',
      proposal_id: 'proposal-a'
    }
  }

  assert.equal(runEvidenceId(source), 'evo-run-7')
  assert.equal(proposalEvidenceId(source), 'proposal-a')
  assert.equal(buildEvidenceLink(source, { kind: 'run' }).href, '#evolution?run_id=evo-run-7')
  assert.equal(
    buildEvidenceLink(source, { kind: 'proposal' }).href,
    '#evolution?run_id=evo-run-7&proposal_id=proposal-a'
  )
})

test('evidence links return disabled reasons when a target cannot be generated', () => {
  const archive = buildEvidenceLink({}, { kind: 'game' })
  const proposal = buildEvidenceLink({ proposal_id: 'proposal-a' }, { kind: 'proposal' })
  const unavailable = buildEvidenceLink({
    game_id: 'game-a',
    archive_available: false,
    archive_unavailable_reason: 'archive file missing'
  }, { kind: 'game' })

  assert.equal(archive.disabled, true)
  assert.match(archive.unavailableReason, /game_id/)
  assert.equal(proposal.disabled, true)
  assert.match(proposal.unavailableReason, /source_run_id\/run_id/)
  assert.equal(unavailable.disabled, true)
  assert.equal(unavailable.unavailableReason, 'archive file missing')
})

test('buildEvidenceLinks returns the minimal archive/run/proposal bundle', () => {
  const links = buildEvidenceLinks({
    history_game_id: 'history-a',
    source_run_id: 'run-a',
    proposal_id: 'proposal-a'
  })

  assert.deepEqual(links.map((link) => link.kind), ['game', 'run', 'proposal'])
  assert.deepEqual(links.map((link) => link.href), [
    '#evidence?game_id=history-a',
    '#evolution?run_id=run-a',
    '#evolution?run_id=run-a&proposal_id=proposal-a'
  ])
})

test('EvidenceLink component renders hrefs and visible unavailable reasons', () => {
  const component = readFileSync(new URL('../src/components/history/EvidenceLink.vue', import.meta.url), 'utf8')

  assert.match(component, /buildEvidenceLink/)
  assert.match(component, /v-if="!link\.disabled"/)
  assert.match(component, /:href="link\.href"/)
  assert.match(component, /aria-disabled="true"/)
  assert.match(component, /unavailableReason/)
  assert.match(component, /<small>\{\{ detailText \}\}<\/small>/)
})

test('EvidenceContextBar exposes unified EvidenceLink targets for history views', () => {
  const component = readFileSync(new URL('../src/components/history/EvidenceContextBar.vue', import.meta.url), 'utf8')

  assert.match(component, /import EvidenceLink from '\.\/EvidenceLink\.vue'/)
  assert.match(component, /const evidenceLinkTargets = computed/)
  assert.match(component, /kind: 'game'/)
  assert.match(component, /kind: 'run'/)
  assert.match(component, /kind: 'proposal'/)
  assert.match(component, /<EvidenceLink/)
})
