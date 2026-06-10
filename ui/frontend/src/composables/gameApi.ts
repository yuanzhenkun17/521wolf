import type { ApiErrorPayload } from '../types/api'

const viteEnv = import.meta.env
const API = viteEnv.VITE_API_BASE || '/api'
const USE_FRONTEND_MOCK = viteEnv.VITE_USE_FRONTEND_MOCK === 'true'
type LegacyRequestOptions = RequestInit & Record<string, any>

let mockApiFetchPromise: Promise<(path: string, options?: LegacyRequestOptions) => Promise<unknown>> | null = null

const REQUEST_ID_HEADERS = ['x-request-id', 'x-correlation-id', 'x-trace-id']
const STATUS_ERROR_CODES = {
  400: 'bad_request',
  401: 'unauthorized',
  403: 'forbidden',
  404: 'not_found',
  409: 'conflict',
  422: 'validation_error',
  500: 'internal_error',
  502: 'bad_gateway',
  503: 'service_unavailable'
}

class ApiError extends Error {
  status: number
  code: string
  detail: unknown
  diagnostics: unknown[]
  requestId: string | null
  payload: unknown
  body: string

  constructor({
    status = 0,
    code = '',
    message = '',
    detail = null,
    diagnostics = [],
    requestId = null,
    payload = null,
    body = ''
  }: {
    status?: number
    code?: string
    message?: string
    detail?: unknown
    diagnostics?: unknown[]
    requestId?: string | null
    payload?: unknown
    body?: string
  } = {}) {
    super(message || (status ? `HTTP ${status}` : 'API request failed'))
    this.name = 'ApiError'
    this.status = status
    this.code = code || httpErrorCode(status)
    this.detail = detail
    this.diagnostics = diagnostics == null ? [] : diagnostics
    this.requestId = requestId || null
    this.payload = payload
    this.body = body
  }
}

async function apiFetchMock(path: string, options: LegacyRequestOptions = {}) {
  if (!mockApiFetchPromise) {
    mockApiFetchPromise = import('../mockAgentGame.ts').then((module) => module.mockApiFetch)
  }
  const mockApiFetch = await mockApiFetchPromise
  return mockApiFetch(path, options)
}

function isObject(value: unknown): value is Record<string, any> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function hasOwn(value: unknown, key: string) {
  return Object.prototype.hasOwnProperty.call(value, key)
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value
    if (value != null && typeof value !== 'object') {
      const text = String(value).trim()
      if (text) return text
    }
  }
  return ''
}

function httpErrorCode(status: unknown): string {
  const normalized = Number(status)
  if (STATUS_ERROR_CODES[normalized]) return STATUS_ERROR_CODES[normalized]
  return normalized ? `http_${normalized}` : 'api_error'
}

function requestIdFromHeaders(headers: Headers | null | undefined): string | null {
  if (!headers || typeof headers.get !== 'function') return null
  for (const header of REQUEST_ID_HEADERS) {
    const value = headers.get(header)
    if (value) return value
  }
  return null
}

function requestIdFromPayload(payload: unknown): string | null {
  if (!isObject(payload)) return null
  const error = isObject(payload.error) ? payload.error : {}
  return firstText(
    payload.requestId,
    payload.request_id,
    payload.requestID,
    error.requestId,
    error.request_id,
    error.requestID
  ) || null
}

function stringifyFallback(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (typeof value !== 'object') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function messageFromDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (isObject(item)) {
          return firstText(item.msg, item.message, item.detail) || stringifyFallback(item)
        }
        return stringifyFallback(item)
      })
      .filter(Boolean)
      .join('; ')
  }
  if (isObject(detail)) {
    return firstText(detail.message, detail.detail, detail.msg) || stringifyFallback(detail)
  }
  return stringifyFallback(detail)
}

async function readErrorPayload(response: Response): Promise<{ payload: ApiErrorPayload | null; text: string; requestId: string | null }> {
  const text = await response.text().catch(() => '')
  if (!text) {
    return {
      payload: null,
      text: '',
      requestId: requestIdFromHeaders(response.headers)
    }
  }
  try {
    return {
      payload: JSON.parse(text),
      text,
      requestId: requestIdFromHeaders(response.headers)
    }
  } catch {
    return {
      payload: null,
      text,
      requestId: requestIdFromHeaders(response.headers)
    }
  }
}

function normalizeApiError({
  response = null,
  payload = null,
  text = '',
  requestId = null
}: {
  response?: Response | null
  payload?: ApiErrorPayload | null
  text?: string
  requestId?: string | null
} = {}) {
  const status = Number(response?.status || 0)
  const error = isObject(payload?.error) ? payload.error : {}
  const detail = isObject(payload) && hasOwn(payload, 'detail')
    ? payload.detail
    : (text ? text : null)
  const diagnostics = hasOwn(error, 'diagnostics')
    ? error.diagnostics
    : (isObject(payload) && hasOwn(payload, 'diagnostics') ? payload.diagnostics : (Array.isArray(detail) ? detail : []))
  const message = firstText(
    error.message,
    isObject(payload) ? payload.message : '',
    messageFromDetail(detail),
    text,
    status ? `HTTP ${status}` : ''
  )
  const code = firstText(
    error.code,
    isObject(payload) ? payload.code : '',
    httpErrorCode(status)
  )
  return new ApiError({
    status,
    code,
    message,
    detail,
    diagnostics,
    requestId: firstText(requestId, requestIdFromPayload(payload), requestIdFromHeaders(response?.headers)) || null,
    payload,
    body: text
  })
}

function createGameApi(apiBase = API) {
  async function apiFetch(path: string, options: LegacyRequestOptions = {}) {
    if (USE_FRONTEND_MOCK) {
      return apiFetchMock(path, options)
    }

    const headers = {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {})
    }
    const response = await fetch(`${apiBase}${path}`, {
      ...options,
      headers
    })
    if (!response.ok) {
      throw normalizeApiError({ response, ...(await readErrorPayload(response)) })
    }
    if (response.status === 204) return null
    const text = await response.text()
    return text ? JSON.parse(text) : null
  }

  return { apiFetch, apiBase }
}

export { API, ApiError, createGameApi, normalizeApiError, readErrorPayload }
