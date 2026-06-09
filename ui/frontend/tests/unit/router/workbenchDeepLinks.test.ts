import assert from 'node:assert/strict'
import { test } from 'vitest'
import {
  benchmarkBatchIdFromHash,
  benchmarkBatchIdFromQuery,
  benchmarkBatchIdFromRoute,
  evolutionDeepLinkFromHash,
  evolutionDeepLinkFromQuery,
  evolutionDeepLinkFromRoute,
  evolutionDeepLinkPanel,
  historyDeepLinkFromHash,
  historyDeepLinkFromQuery,
  historyDeepLinkFromRoute,
  logsHash
} from '../../../src/router/workbenchDeepLinks'

test('extracts benchmark batch ids from route query aliases before legacy hash fallback', () => {
  assert.equal(benchmarkBatchIdFromQuery({ batch_id: 'batch-a' }), 'batch-a')
  assert.equal(benchmarkBatchIdFromQuery({ source_run_id: 'bench-run-a' }), 'bench-run-a')
  assert.equal(benchmarkBatchIdFromQuery({ run_id: ['run-a', 'run-b'] }), 'run-a')
  assert.equal(benchmarkBatchIdFromHash('#benchmark?source_run_id=bench-from-hash'), 'bench-from-hash')

  assert.equal(
    benchmarkBatchIdFromRoute({
      name: 'benchmark',
      path: '/benchmark',
      query: { batch_id: 'batch-from-route' },
      hash: '#benchmark?batch_id=batch-from-hash'
    }),
    'batch-from-route'
  )
})

test('falls back to benchmark legacy hash when the current route query has no id', () => {
  assert.equal(
    benchmarkBatchIdFromRoute({
      name: 'benchmark',
      path: '/benchmark',
      query: {},
      hash: '#benchmark?batch_id=batch-from-hash'
    }),
    'batch-from-hash'
  )

  assert.equal(
    benchmarkBatchIdFromRoute({
      name: 'logs',
      path: '/logs',
      query: { batch_id: 'wrong-route' },
      hash: '#benchmark?run_id=bench-from-hash'
    }),
    'bench-from-hash'
  )
})

test('builds logs hashes with optional game and non-default workspace query', () => {
  assert.equal(logsHash(), '#logs')
  assert.equal(logsHash({ gameId: 'game/1' }), '#logs?game_id=game%2F1')
  assert.equal(logsHash({ gameId: 'game/1', workspace: 'phase' }), '#logs?game_id=game%2F1')
  assert.equal(logsHash({ gameId: 'game/1', workspace: 'archive' }), '#logs?game_id=game%2F1&workspace=archive')
  assert.equal(logsHash({ workspace: 'review' }), '#logs?workspace=review')
})

test('extracts logs deep link targets from query and legacy hash aliases', () => {
  assert.deepEqual(historyDeepLinkFromQuery({ game_id: 'game-a', workspace: 'archive' }), {
    routeHash: '#logs',
    gameId: 'game-a',
    workspace: 'archive'
  })
  assert.deepEqual(historyDeepLinkFromHash('#logs?game=game-b&tab=review'), {
    routeHash: '#logs',
    gameId: 'game-b',
    workspace: 'review'
  })
  assert.deepEqual(historyDeepLinkFromHash('#logs?game_id=game-c&workspace=unknown'), {
    routeHash: '#logs',
    gameId: 'game-c',
    workspace: ''
  })
})

test('uses logs route query before legacy hash fallback', () => {
  assert.deepEqual(
    historyDeepLinkFromRoute({
      name: 'logs',
      path: '/logs',
      query: { game_id: 'route-game', workspace: 'archive' },
      hash: '#logs?game_id=hash-game&workspace=review'
    }),
    {
      routeHash: '#logs',
      gameId: 'route-game',
      workspace: 'archive'
    }
  )
  assert.deepEqual(
    historyDeepLinkFromRoute({
      name: 'lobby',
      path: '/',
      query: {},
      hash: '#logs?game_id=hash-game&workspace=review'
    }),
    {
      routeHash: '#logs',
      gameId: 'hash-game',
      workspace: 'review'
    }
  )
})

test('builds evolution deep link targets from route query aliases', () => {
  const target = evolutionDeepLinkFromQuery({
    run: 'run-a',
    proposalId: 'proposal-a',
    gate_report_id: 'gate-a'
  })

  assert.equal(target?.run_id, 'run-a')
  assert.equal(target?.proposal_id, 'proposal-a')
  assert.equal(target?.gate_report_id, 'gate-a')
  assert.equal(target?.panel, 'review')
  assert.equal(target?.status, 'pending')
  assert.deepEqual(target?.pending, [])
})

test('uses route query before evolution legacy hash fallback', () => {
  const target = evolutionDeepLinkFromRoute({
    name: 'evolution',
    path: '/evolution',
    query: { run_id: 'route-run', version_id: 'seer-v2', role: 'seer' },
    hash: '#evolution?run_id=hash-run&proposal_id=proposal-a'
  })

  assert.equal(target?.run_id, 'route-run')
  assert.equal(target?.version_id, 'seer-v2')
  assert.equal(target?.panel, 'versions')
})

test('keeps legacy evolution hash deep links as a compatibility fallback', () => {
  const target = evolutionDeepLinkFromHash(
    'http://localhost:5173/evolution#evolution?source_run_id=hash-run&gateReportId=gate-a'
  )

  assert.equal(target?.run_id, 'hash-run')
  assert.equal(target?.gate_report_id, 'gate-a')
  assert.equal(target?.panel, 'review')
  assert.equal(evolutionDeepLinkPanel({ run_id: 'run-a' }), 'runs')
  assert.equal(evolutionDeepLinkPanel({ version_id: 'version-a' }), 'versions')
})
