export type JsonPrimitive = string | number | boolean | null
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[]

export interface JsonObject {
  [key: string]: JsonValue
}

export type UnknownRecord = Record<string, unknown>
export type QueryValue = string | number | boolean | null | undefined
export type QueryParams = Record<string, QueryValue | QueryValue[]>

export interface Pagination {
  total: number
  offset: number
  limit: number | null
  returned: number
  has_more: boolean
}

export interface ApiEnvelope<T = unknown> {
  kind?: string
  schema_version?: number
  data?: T
  items?: T[]
  pagination?: Partial<Pagination>
  [key: string]: unknown
}

export interface ApiDiagnostic {
  kind?: string
  code?: string
  level?: 'info' | 'warning' | 'error' | string
  message?: string
  stage?: string
  origin?: string
  [key: string]: unknown
}

export interface ApiErrorPayload {
  error?: {
    code?: string
    message?: string
    diagnostics?: ApiDiagnostic[]
    [key: string]: unknown
  }
  code?: string
  message?: string
  detail?: unknown
  diagnostics?: ApiDiagnostic[]
  requestId?: string
  request_id?: string
  requestID?: string
  [key: string]: unknown
}

export interface ApiErrorShape {
  name: 'ApiError'
  status: number
  code: string
  message: string
  detail: unknown
  diagnostics: ApiDiagnostic[]
  requestId: string | null
  payload: unknown
  body: string
}

export interface ApiRequestOptions extends Omit<RequestInit, 'body'> {
  body?: BodyInit | object | null
  query?: QueryParams
}

export interface ApiClient {
  readonly apiBase: string
  fetch<T = unknown>(path: string, options?: ApiRequestOptions): Promise<T>
  raw(path: string, options?: ApiRequestOptions): Promise<Response>
}

export interface ListResponse<T> {
  items: T[]
  pagination: Pagination
  counts?: Record<string, number>
  facets?: Record<string, unknown>
  raw?: unknown
}

export type ApiFetch = <T = unknown>(path: string, options?: ApiRequestOptions) => Promise<T>

export interface ServiceOptions {
  client?: ApiClient
  apiBase?: string
}

export interface StreamEventPayload<T = unknown> {
  id: string
  event: MessageEvent<string>
  payload: T
  parseError: Error | null
  rawData: string
  source: EventSource
  close: () => void
  resetEventId: () => void
}

export interface StreamConnectionStatus {
  id: string
  connected: boolean
  retrying: boolean
  lastEventId: string
}
