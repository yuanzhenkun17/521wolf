type ObjectRecord = Record<string, unknown>
type NoticeType = 'success' | 'warning' | 'error' | 'info'
type InlineNoticeType = Exclude<NoticeType, 'error'>

interface DiagnosticDisplayRow {
  key: string
  label: string
  message: string
  meta: string[]
  raw: unknown
}

interface ApiErrorDisplayView {
  title: string
  status: number | null
  code: string
  message: string
  detail: string
  requestId: string
  diagnostics: DiagnosticDisplayRow[]
  hasDiagnostics: boolean
  raw: unknown
}

interface InlineNotice extends ObjectRecord {
  type: InlineNoticeType
  message: string
}

const NOTICE_TYPES: readonly NoticeType[] = ['success', 'warning', 'error', 'info']

function isObject(value: unknown): value is ObjectRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function propertyBag(value: unknown): ObjectRecord {
  if (value !== null && (typeof value === 'object' || typeof value === 'function')) {
    return value as ObjectRecord
  }
  return {}
}

function isNoticeType(value: string): value is NoticeType {
  return NOTICE_TYPES.includes(value as NoticeType)
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

function detailText(value: unknown): string {
  if (value == null || value === '') return ''
  if (typeof value === 'string') return value
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === 'string') return item
        if (isObject(item)) return firstText(item.msg, item.message, item.detail) || JSON.stringify(item)
        return String(item)
      })
      .filter(Boolean)
      .join('; ')
  }
  if (isObject(value)) {
    return firstText(value.message, value.detail, value.msg) || JSON.stringify(value)
  }
  return String(value)
}

function diagnosticLabel(row: unknown, index: number): string {
  if (!isObject(row)) return String(row || `diagnostic-${index + 1}`)
  return firstText(row.kind, row.type, row.code, row.stage, row.field, `diagnostic-${index + 1}`)
}

function diagnosticMessage(row: unknown): string {
  if (!isObject(row)) return ''
  return firstText(
    row.message,
    row.msg,
    row.detail,
    row.reason,
    row.role && row.version_id ? `${row.role}/${row.version_id}` : ''
  )
}

function diagnosticMeta(row: unknown): string[] {
  if (!isObject(row)) return []
  return [
    row.level ? `level=${row.level}` : '',
    row.role ? `role=${row.role}` : '',
    row.version_id ? `version=${row.version_id}` : '',
    row.release_stage ? `release_stage=${row.release_stage}` : '',
    row.allowed_flow ? `allowed_flow=${row.allowed_flow}` : '',
    row.run_id ? `run=${row.run_id}` : '',
    row.seed ? `seed=${row.seed}` : ''
  ].filter(Boolean)
}

function normalizeDiagnostics(value: unknown): DiagnosticDisplayRow[] {
  if (!Array.isArray(value)) return []
  return value.map((row, index) => ({
    key: `${diagnosticLabel(row, index)}:${index}`,
    label: diagnosticLabel(row, index),
    message: diagnosticMessage(row),
    meta: diagnosticMeta(row),
    raw: row
  }))
}

function formatApiErrorForDisplay(error: unknown, fallback = '操作失败'): ApiErrorDisplayView {
  const errorData = propertyBag(error)
  const payload = isObject(errorData.payload) ? errorData.payload : {}
  const payloadError = isObject(payload.error) ? payload.error : {}
  const diagnostics = Array.isArray(errorData.diagnostics)
    ? errorData.diagnostics
    : (Array.isArray(payloadError.diagnostics) ? payloadError.diagnostics : [])
  const code = firstText(errorData.code, payloadError.code)
  const message = firstText(
    errorData.message,
    payloadError.message,
    payload.message,
    detailText(errorData.detail),
    detailText(payload.detail),
    fallback
  )
  const detail = detailText(errorData.detail ?? payload.detail)
  return {
    title: code ? `${fallback} · ${code}` : fallback,
    status: Number(errorData.status || 0) || null,
    code,
    message,
    detail,
    requestId: firstText(errorData.requestId, payload.request_id, payload.requestId, payloadError.request_id, payloadError.requestId),
    diagnostics: normalizeDiagnostics(diagnostics),
    hasDiagnostics: diagnostics.length > 0,
    raw: error
  }
}

function normalizedNoticeType(notice: unknown): NoticeType {
  const type = firstText(propertyBag(notice).type).toLowerCase()
  return isNoticeType(type) ? type : 'info'
}

function inlineNoticeForDisplay(notice: unknown): InlineNotice | null {
  const message = firstText(propertyBag(notice).message)
  if (!message || normalizedNoticeType(notice) === 'error') return null
  return {
    ...(isObject(notice) ? notice : {}),
    type: normalizedNoticeType(notice) as InlineNoticeType,
    message
  }
}

function noticeErrorForPanel(notice: unknown): unknown | null {
  const noticeData = propertyBag(notice)
  const message = firstText(noticeData.message)
  if (!message || normalizedNoticeType(notice) !== 'error') return null
  const source = noticeData.error || noticeData.apiError || noticeData.cause
  if (source instanceof Error) return source
  if (isObject(source)) {
    return {
      ...propertyBag(notice),
      ...source,
      message: firstText(source.message, message),
      detail: source.detail ?? noticeData.detail,
      diagnostics: source.diagnostics ?? noticeData.diagnostics,
      requestId: firstText(source.requestId, source.request_id, noticeData.requestId, noticeData.request_id),
      payload: source.payload ?? noticeData.payload
    }
  }
  return notice
}

export {
  formatApiErrorForDisplay,
  inlineNoticeForDisplay,
  normalizeDiagnostics,
  noticeErrorForPanel
}
