import assert from 'node:assert/strict'
import test from 'node:test'
import { ApiError, createGameApi, normalizeApiError } from '../src/composables/gameApi.ts'

async function withFetch(fetchImpl, callback) {
  const originalFetch = globalThis.fetch
  globalThis.fetch = fetchImpl
  try {
    return await callback()
  } finally {
    if (originalFetch === undefined) delete globalThis.fetch
    else globalThis.fetch = originalFetch
  }
}

test('apiFetch throws ApiError with backend error shape fields intact', () => withFetch(
  async () => new Response(JSON.stringify({
    detail: 'game not found',
    error: {
      code: 'not_found',
      message: 'game not found',
      diagnostics: [{ kind: 'lookup_failed', id: 'missing-game' }]
    }
  }), {
    status: 404,
    headers: {
      'content-type': 'application/json',
      'x-request-id': 'req-backend-1'
    }
  }),
  async () => {
    const { apiFetch } = createGameApi('/api')
    await assert.rejects(
      apiFetch('/games/missing-game'),
      (error) => {
        assert.equal(error instanceof ApiError, true)
        assert.equal(error.name, 'ApiError')
        assert.equal(error.status, 404)
        assert.equal(error.code, 'not_found')
        assert.equal(error.message, 'game not found')
        assert.equal(error.detail, 'game not found')
        assert.deepEqual(error.diagnostics, [{ kind: 'lookup_failed', id: 'missing-game' }])
        assert.equal(error.requestId, 'req-backend-1')
        return true
      }
    )
  }
))

test('apiFetch preserves FastAPI validation detail arrays', () => withFetch(
  async () => new Response(JSON.stringify({
    detail: [{
      type: 'greater_than_equal',
      loc: ['body', 'max_days'],
      msg: 'Input should be greater than or equal to 1',
      input: 0
    }],
    error: {
      code: 'validation_error',
      message: 'Request validation failed',
      diagnostics: [{
        type: 'greater_than_equal',
        loc: ['body', 'max_days'],
        msg: 'Input should be greater than or equal to 1',
        input: 0
      }]
    }
  }), {
    status: 422,
    headers: { 'content-type': 'application/json' }
  }),
  async () => {
    const { apiFetch } = createGameApi('/api')
    await assert.rejects(
      apiFetch('/benchmark', { method: 'POST', body: JSON.stringify({ max_days: 0 }) }),
      (error) => {
        assert.equal(error instanceof ApiError, true)
        assert.equal(error.status, 422)
        assert.equal(error.code, 'validation_error')
        assert.equal(error.message, 'Request validation failed')
        assert.deepEqual(error.detail, [{
          type: 'greater_than_equal',
          loc: ['body', 'max_days'],
          msg: 'Input should be greater than or equal to 1',
          input: 0
        }])
        assert.deepEqual(error.diagnostics, error.detail)
        assert.equal(error.requestId, null)
        return true
      }
    )
  }
))

test('apiFetch turns plain text failures into structured ApiError', () => withFetch(
  async () => new Response('upstream unavailable', {
    status: 503,
    headers: { 'x-correlation-id': 'corr-503' }
  }),
  async () => {
    const { apiFetch } = createGameApi('/api')
    await assert.rejects(
      apiFetch('/health'),
      (error) => {
        assert.equal(error instanceof ApiError, true)
        assert.equal(error.status, 503)
        assert.equal(error.code, 'service_unavailable')
        assert.equal(error.message, 'upstream unavailable')
        assert.equal(error.detail, 'upstream unavailable')
        assert.deepEqual(error.diagnostics, [])
        assert.equal(error.requestId, 'corr-503')
        assert.equal(error.payload, null)
        assert.equal(error.body, 'upstream unavailable')
        return true
      }
    )
  }
))

test('normalizeApiError supports unwrapped validation payloads', () => {
  const detail = [{ loc: ['query', 'limit'], msg: 'Input should be less than or equal to 100' }]
  const error = normalizeApiError({
    response: new Response(JSON.stringify({ detail }), { status: 422 }),
    payload: { detail },
    text: JSON.stringify({ detail })
  })

  assert.equal(error instanceof ApiError, true)
  assert.equal(error.status, 422)
  assert.equal(error.code, 'validation_error')
  assert.equal(error.message, 'Input should be less than or equal to 100')
  assert.equal(error.detail, detail)
  assert.equal(error.diagnostics, detail)
})
