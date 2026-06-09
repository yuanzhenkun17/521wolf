import type { Pagination, QueryParams, QueryValue, UnknownRecord } from '../types/api'

export function isRecord(value: unknown): value is UnknownRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

export function objectOrEmpty(value: unknown): UnknownRecord {
  return isRecord(value) ? value : {}
}

export function arrayOrEmpty<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : []
}

export function stringValue(value: unknown, fallback = ''): string {
  if (value == null) return fallback
  const text = String(value).trim()
  return text || fallback
}

export function numberValue(value: unknown, fallback = 0): number {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

export function integerValue(value: unknown, fallback = 0): number {
  const number = numberValue(value, fallback)
  return Number.isFinite(number) ? Math.trunc(number) : fallback
}

export function positiveInteger(value: unknown, fallback = 1): number {
  const number = integerValue(value, fallback)
  return number > 0 ? number : fallback
}

export function nullableNumber(value: unknown): number | null {
  if (value == null || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

export function booleanValue(value: unknown, fallback = false): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number' && Number.isFinite(value)) return value !== 0
  if (typeof value === 'string') {
    const key = value.trim().toLowerCase()
    if (['true', 'yes', '1', 'on'].includes(key)) return true
    if (['false', 'no', '0', 'off'].includes(key)) return false
  }
  return fallback
}

export function firstString(...values: unknown[]): string {
  for (const value of values) {
    const text = stringValue(value)
    if (text) return text
  }
  return ''
}

export function firstNumber(...values: unknown[]): number | null {
  for (const value of values) {
    const number = nullableNumber(value)
    if (number != null) return number
  }
  return null
}

export function uniqueStrings(values: unknown[]): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const value of values.flatMap((item) => (Array.isArray(item) ? item : [item]))) {
    const text = stringValue(value)
    if (!text || seen.has(text)) continue
    seen.add(text)
    result.push(text)
  }
  return result
}

export function shortId(value: unknown, length = 8): string {
  const text = stringValue(value)
  if (!text) return ''
  return text.length <= length ? text : text.slice(0, length)
}

export function normalizePagination(raw: unknown, rows: unknown[] = [], fallback: Partial<Pagination> = {}): Pagination {
  const source = objectOrEmpty(raw)
  const returned = integerValue(source.returned, rows.length)
  const offset = Math.max(0, integerValue(source.offset, fallback.offset ?? 0))
  const limitSource = source.limit ?? fallback.limit ?? rows.length
  const limit = limitSource == null ? null : Math.max(0, integerValue(limitSource, rows.length))
  const total = integerValue(source.total, fallback.total ?? offset + returned)
  return {
    total: Math.max(0, total),
    offset,
    limit,
    returned: Math.max(0, returned),
    has_more: booleanValue(source.has_more, false)
  }
}

export function buildQuery(params: QueryParams = {}): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    appendQueryValue(search, key, value)
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

function appendQueryValue(search: URLSearchParams, key: string, value: QueryValue | QueryValue[]): void {
  if (Array.isArray(value)) {
    value.forEach((item) => appendQueryValue(search, key, item))
    return
  }
  if (value == null || value === '') return
  search.append(key, String(value))
}

export function mergeByStableId<T extends UnknownRecord>(existing: T[], incoming: T[], fields: string | string[]): T[] {
  const idFields = Array.isArray(fields) ? fields : [fields]
  const seen = new Set<string>()
  return [...existing, ...incoming].filter((item) => {
    const key = idFields.map((field) => item[field]).find((value) => value != null && value !== '')
    if (key == null || key === '') return true
    const normalized = String(key)
    if (seen.has(normalized)) return false
    seen.add(normalized)
    return true
  })
}
