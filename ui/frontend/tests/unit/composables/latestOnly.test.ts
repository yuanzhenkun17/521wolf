import assert from 'node:assert/strict'
import { test } from 'vitest'
import { createLatestOnlyTracker } from '../../../src/composables/latestOnly.ts'

test('latest-only tracker aborts stale requests', () => {
  const tracker = createLatestOnlyTracker()

  const first = tracker.next()
  const second = tracker.next()

  assert.equal(first.isLatest(), false)
  assert.equal(first.signal?.aborted, true)
  assert.equal(second.isLatest(), true)
  assert.equal(second.signal?.aborted, false)

  tracker.invalidate()

  assert.equal(second.isLatest(), false)
  assert.equal(second.signal?.aborted, true)
})
