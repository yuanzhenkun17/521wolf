import assert from 'node:assert/strict'
import { afterEach, test } from 'vitest'
import {
  hashForView,
  registerLegacyViewRouter,
  routePathForView,
  routeQueryFromLegacyHash,
  syncRouterToLegacyView,
  viewFromHash,
  writeViewHash
} from '../../../src/router/legacyViewNavigation'

const originalWindow = globalThis.window

afterEach(() => {
  registerLegacyViewRouter(null)
  if (originalWindow === undefined) delete (globalThis as { window?: Window }).window
  else globalThis.window = originalWindow
})

function locationLike(hash = ''): Pick<Location, 'hash'> {
  return { hash }
}

test('maps legacy app views to router paths', () => {
  assert.equal(routePathForView('lobby'), '/')
  assert.equal(routePathForView('match'), '/match')
  assert.equal(routePathForView('logs'), '/logs')
  assert.equal(routePathForView('benchmark'), '/benchmark')
  assert.equal(routePathForView('evolution'), '/evolution')
})

test('maps app views to legacy hashes and parses legacy hash routes', () => {
  assert.equal(hashForView('lobby'), '')
  assert.equal(hashForView('match'), 'match')
  assert.equal(hashForView('logs'), 'logs')
  assert.equal(hashForView('benchmark'), 'benchmark')
  assert.equal(hashForView('evolution'), 'evolution')

  assert.equal(viewFromHash(''), 'lobby')
  assert.equal(viewFromHash('#logs?game_id=game-7'), 'logs')
  assert.equal(viewFromHash('#benchmark?batch_id=bench-1'), 'benchmark')
  assert.equal(viewFromHash('#evidence?game_id=game-2'), 'lobby')
})

test('extracts router query from legacy hash deep links', () => {
  assert.deepEqual(routeQueryFromLegacyHash('#logs?game_id=game-7&workspace=archive'), {
    game_id: 'game-7',
    workspace: 'archive'
  })
  assert.deepEqual(routeQueryFromLegacyHash('#benchmark?batch_id=a&batch_id=b'), {
    batch_id: ['a', 'b']
  })
  assert.deepEqual(routeQueryFromLegacyHash('#match'), {})
})

test('syncs a legacy view navigation into vue-router', () => {
  const calls: unknown[] = []
  registerLegacyViewRouter({
    replace(to: unknown) {
      calls.push(to)
      return Promise.resolve()
    }
  })

  syncRouterToLegacyView('logs', '#logs?game_id=game-7&workspace=archive')

  assert.deepEqual(calls, [{
    path: '/logs',
    query: { game_id: 'game-7', workspace: 'archive' },
    hash: '#logs?game_id=game-7&workspace=archive'
  }])
})

test('writeViewHash keeps legacy hash behavior and mirrors the router path', () => {
  const calls: unknown[] = []
  globalThis.window = { location: locationLike() } as Window & typeof globalThis
  registerLegacyViewRouter({
    replace(to: unknown) {
      calls.push(to)
      return Promise.resolve()
    }
  })

  writeViewHash('match')

  assert.equal(window.location.hash, '#match')
  assert.deepEqual(calls, [{ path: '/match', query: {}, hash: '#match' }])
})
