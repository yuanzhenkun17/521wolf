import { buildQuery } from '../domain/common'
import type { ApiClient, ApiErrorPayload, ApiRequestOptions, QueryParams } from '../types/api'

export const API_BASE = import.meta.env.VITE_API_BASE || '/api'
export const USE_FRONTEND_MOCK = import.meta.env.VITE_USE_FRONTEND_MOCK === 'true'

const REQUEST_ID_HEADERS = ['x-request-id', 'x-correlation-id', 'x-trace-id']
const STATUS_ERROR_CODES: Record<number, string> = {
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

let mockApiFetchPromise: Promise<(path: string, options?: ApiRequestOptions) => Promise<unknown>> | null = null

export class ApiError extends Error {
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
    this.diagnostics = diagnostics
    this.requestId = requestId
    this.payload = payload
    this.body = body
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (value != null && typeof value !== 'object') {
      const text = String(value).trim()
      if (text) return text
    }
  }
  return ''
}

function httpErrorCode(status: number): string {
  return STATUS_ERROR_CODES[status] || (status ? `http_${status}` : 'api_error')
}

function requestIdFromHeaders(headers: Headers | undefined | null): string | null {
  if (!headers || typeof headers.get !== 'function') return null
  for (const header of REQUEST_ID_HEADERS) {
    const value = headers.get(header)
    if (value) return value
  }
  return null
}

function requestIdFromPayload(payload: unknown): string | null {
  if (!isRecord(payload)) return null
  const error = isRecord(payload.error) ? payload.error : {}
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
        if (isRecord(item)) return firstText(item.msg, item.message, item.detail) || stringifyFallback(item)
        return stringifyFallback(item)
      })
      .filter(Boolean)
      .join('; ')
  }
  if (isRecord(detail)) return firstText(detail.message, detail.detail, detail.msg) || stringifyFallback(detail)
  return stringifyFallback(detail)
}

function normalizeBody(body: ApiRequestOptions['body']): BodyInit | null | undefined {
  if (body == null) return body as null | undefined
  if (
    typeof body === 'string' ||
    body instanceof FormData ||
    body instanceof Blob ||
    body instanceof URLSearchParams ||
    body instanceof ArrayBuffer
  ) {
    return body
  }
  return JSON.stringify(body)
}

function normalizeUrl(apiBase: string, path: string, query?: QueryParams): string {
  const separator = path.includes('?') ? '&' : ''
  const queryString = query ? buildQuery(query).replace(/^\?/, '') : ''
  return `${apiBase}${path}${queryString ? `${separator || '?'}${queryString}` : ''}`
}

async function apiFetchMock(path: string, options: ApiRequestOptions = {}): Promise<unknown> {
  if (!mockApiFetchPromise) {
    mockApiFetchPromise = import('../mockAgentGame.ts').then((module) => module.mockApiFetch)
  }
  const mockApiFetch = await mockApiFetchPromise
  return mockApiFetch(path, options)
}

export async function readErrorPayload(response: Response): Promise<{ payload: ApiErrorPayload | null; text: string; requestId: string | null }> {
  const text = await response.text().catch(() => '')
  if (!text) return { payload: null, text: '', requestId: requestIdFromHeaders(response.headers) }
  try {
    return {
      payload: JSON.parse(text) as ApiErrorPayload,
      text,
      requestId: requestIdFromHeaders(response.headers)
    }
  } catch {
    return { payload: null, text, requestId: requestIdFromHeaders(response.headers) }
  }
}

export function normalizeApiError({
  response = null,
  payload = null,
  text = '',
  requestId = null
}: {
  response?: Response | null
  payload?: ApiErrorPayload | null
  text?: string
  requestId?: string | null
} = {}): ApiError {
  const status = Number(response?.status || 0)
  const error = isRecord(payload?.error) ? payload.error : {}
  const detail = isRecord(payload) && Object.prototype.hasOwnProperty.call(payload, 'detail') ? payload.detail : text || null
  const diagnostics = Array.isArray(error.diagnostics)
    ? error.diagnostics
    : isRecord(payload) && Array.isArray(payload.diagnostics)
      ? payload.diagnostics
      : Array.isArray(detail)
        ? detail
        : []
  const message = firstText(error.message, isRecord(payload) ? payload.message : '', messageFromDetail(detail), text, status ? `HTTP ${status}` : '')
  const code = firstText(error.code, isRecord(payload) ? payload.code : '', httpErrorCode(status))
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

export function createApiClient(apiBase = API_BASE): ApiClient {
  async function raw(path: string, options: ApiRequestOptions = {}): Promise<Response> {
    const body = normalizeBody(options.body)
    const headers = {
      ...(body && typeof body === 'string' ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {})
    }
    return fetch(normalizeUrl(apiBase, path, options.query), {
      ...options,
      body,
      headers
    })
  }

  async function fetchJson<T = unknown>(path: string, options: ApiRequestOptions = {}): Promise<T> {
    if (USE_FRONTEND_MOCK) return apiFetchMock(path, options) as Promise<T>
    const response = await raw(path, options)
    if (!response.ok) throw normalizeApiError({ response, ...(await readErrorPayload(response)) })
    if (response.status === 204) return null as T
    const text = await response.text()
    return (text ? JSON.parse(text) : null) as T
  }

  return {
    apiBase,
    raw,
    fetch: fetchJson
  }
}

export const defaultApiClient = createApiClient()
