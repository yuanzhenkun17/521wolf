import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  benchmarkRunEvidenceId,
  buildEvidenceLink,
  buildEvidenceLinks,
  buildHashLink,
  gameEvidenceId,
  proposalEvidenceId,
  runEvidenceId,
  sourceEvidenceKey
} from '../src/components/history/evidenceLinks.ts'

test('evidence hash links use stable logs archive and evolution routes', () => {
  assert.equal(buildHashLink('logs', { game_id: 'game/1' }), '#logs?game_id=game%2F1')
  assert.equal(
    buildHashLink('logs', { game_id: 'game/1', workspace: 'archive' }),
    '#logs?game_id=game%2F1&workspace=archive'
  )
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
  assert.equal(link.href, '#logs?game_id=history-game&workspace=archive')
  assert.equal(link.label, 'Archive')
  assert.equal(link.id, 'history-game')
})

test('run and proposal evidence links preserve run-scoped proposal context', () => {
  const source = {
    evidence_source: {
      log_source: 'evolution',
      source_run_id: 'evo-run-7',
      proposal_id: 'proposal-a'
    }
  }

  assert.equal(sourceEvidenceKey(source), 'evolution')
  assert.equal(runEvidenceId(source), 'evo-run-7')
  assert.equal(proposalEvidenceId(source), 'proposal-a')
  assert.equal(buildEvidenceLink(source, { kind: 'run' }).href, '#evolution?run_id=evo-run-7')
  assert.equal(
    buildEvidenceLink(source, { kind: 'proposal' }).href,
    '#evolution?run_id=evo-run-7&proposal_id=proposal-a'
  )
})

test('run evidence routes by source instead of always opening evolution', () => {
  const benchmark = buildEvidenceLink({
    log_source: 'benchmark',
    source_run_id: 'bench-run-7'
  }, { kind: 'run' })
  const normal = buildEvidenceLink({
    log_source: 'normal',
    source_run_id: 'normal-run-7'
  }, { kind: 'run' })

  assert.equal(sourceEvidenceKey({ log_source: 'benchmark', source_run_id: 'bench-run-7' }), 'benchmark')
  assert.equal(benchmarkRunEvidenceId({ log_source: 'benchmark', source_run_id: 'bench-run-7' }), 'bench-run-7')
  assert.equal(benchmark.disabled, false)
  assert.equal(benchmark.href, '#benchmark?batch_id=bench-run-7')
  assert.deepEqual(benchmark.params, { batch_id: 'bench-run-7' })
  assert.equal(normal.disabled, true)
  assert.equal(normal.href, '')
  assert.match(normal.unavailableReason, /普通对局/)
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
    log_source: 'evolution',
    history_game_id: 'history-a',
    source_run_id: 'run-a',
    proposal_id: 'proposal-a'
  })

  assert.deepEqual(links.map((link) => link.kind), ['game', 'run', 'proposal'])
  assert.deepEqual(links.map((link) => link.href), [
    '#logs?game_id=history-a&workspace=archive',
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

test('EvidenceContextBar keeps Archive and Run in the summary row as links', () => {
  const component = readFileSync(new URL('../src/components/history/EvidenceContextBar.vue', import.meta.url), 'utf8')

  assert.match(component, /import \{ buildEvidenceLink \} from '\.\/evidenceLinks\.ts'/)
  assert.match(component, /const archiveLink = computed\(\(\) => buildEvidenceLink\(props\.game \|\| \{\}, \{ kind: 'game', label: 'Archive' \}\)\)/)
  assert.match(component, /const runLink = computed\(\(\) =>[\s\S]*buildEvidenceLink\(\{ \.\.\.\(props\.game \|\| \{\}\), source_run_id: sourceRunId\.value \}, \{ kind: 'run', label: 'Run' \}\)/)
  assert.match(component, /class="evidence-context-item evidence-context-item--archive"[\s\S]*v-if="!archiveLink\.disabled"[\s\S]*:href="archiveLink\.href"/)
  assert.match(component, /class="evidence-context-item evidence-context-item--run"[\s\S]*v-if="!runLink\.disabled"[\s\S]*:href="runLink\.href"/)
  assert.doesNotMatch(component, /import EvidenceLink from '\.\/EvidenceLink\.vue'/)
  assert.doesNotMatch(component, /const evidenceLinkTargets = computed/)
  assert.doesNotMatch(component, /proposalEvidenceMissing|proposalId|kind: 'proposal'|key: 'proposal'/)
  assert.doesNotMatch(component, /<EvidenceLink|evidence-context-links|evidence-context-status|未关联提案/)
})

test('BenchmarkPage consumes benchmark run deep links after the router preserves query params', () => {
  const component = readFileSync(new URL('../src/pages/BenchmarkPage.vue', import.meta.url), 'utf8')

  assert.match(component, /function benchmarkDeepLinkBatchId/)
  assert.match(component, /params\.get\('batch_id'\)/)
  assert.match(component, /params\.get\('source_run_id'\)/)
  assert.match(component, /activeView\.value = 'runs'/)
  assert.match(component, /benchmark\.selectBenchmarkBatch\(batchId\)/)
  assert.match(component, /addEventListener\('hashchange', handleBenchmarkHashChange\)/)
})

test('EvidenceContextBar keeps benchmark and evolution evidence visually aligned with normal games', () => {
  const component = readFileSync(new URL('../src/components/history/EvidenceContextBar.vue', import.meta.url), 'utf8')

  assert.doesNotMatch(component, /\.evidence-context-bar\[data-source="benchmark"\]/)
  assert.doesNotMatch(component, /\.evidence-context-bar\[data-source="evolution"\]/)
  assert.doesNotMatch(component, /background:\s*rgba\(232, 242, 248, 0\.78\)/)
  assert.doesNotMatch(component, /background:\s*rgba\(239, 236, 248, 0\.78\)/)
  assert.doesNotMatch(component, /class="evidence-context-links"/)
  assert.match(component, /<section v-if="game" class="evidence-context-bar" :data-source="sourceKey"/)
  assert.match(component, /<dl class="evidence-context-summary">[\s\S]*evidence-context-item--source[\s\S]*evidence-context-item--archive[\s\S]*evidence-context-item--run[\s\S]*evidence-context-item--phase[\s\S]*evidence-context-item--seed[\s\S]*evidence-context-item--versions/)
})
