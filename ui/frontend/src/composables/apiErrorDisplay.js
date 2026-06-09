function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function firstText(...values) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (value != null && typeof value !== 'object') {
      const text = String(value).trim()
      if (text) return text
    }
  }
  return ''
}

function detailText(value) {
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

function diagnosticLabel(row, index) {
  if (!isObject(row)) return String(row || `diagnostic-${index + 1}`)
  return firstText(row.kind, row.type, row.code, row.stage, row.field, `diagnostic-${index + 1}`)
}

function diagnosticMessage(row) {
  if (!isObject(row)) return ''
  return firstText(
    row.message,
    row.msg,
    row.detail,
    row.reason,
    row.role && row.version_id ? `${row.role}/${row.version_id}` : ''
  )
}

function diagnosticMeta(row) {
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

function normalizeDiagnostics(value) {
  if (!Array.isArray(value)) return []
  return value.map((row, index) => ({
    key: `${diagnosticLabel(row, index)}:${index}`,
    label: diagnosticLabel(row, index),
    message: diagnosticMessage(row),
    meta: diagnosticMeta(row),
    raw: row
  }))
}

function formatApiErrorForDisplay(error, fallback = '操作失败') {
  const payload = isObject(error?.payload) ? error.payload : {}
  const payloadError = isObject(payload.error) ? payload.error : {}
  const diagnostics = Array.isArray(error?.diagnostics)
    ? error.diagnostics
    : (Array.isArray(payloadError.diagnostics) ? payloadError.diagnostics : [])
  const code = firstText(error?.code, payloadError.code)
  const message = firstText(
    error?.message,
    payloadError.message,
    payload.message,
    detailText(error?.detail),
    detailText(payload.detail),
    fallback
  )
  const detail = detailText(error?.detail ?? payload.detail)
  return {
    title: code ? `${fallback} · ${code}` : fallback,
    status: Number(error?.status || 0) || null,
    code,
    message,
    detail,
    requestId: firstText(error?.requestId, payload.request_id, payload.requestId, payloadError.request_id, payloadError.requestId),
    diagnostics: normalizeDiagnostics(diagnostics),
    hasDiagnostics: diagnostics.length > 0,
    raw: error
  }
}

function normalizedNoticeType(notice) {
  const type = firstText(notice?.type).toLowerCase()
  return ['success', 'warning', 'error', 'info'].includes(type) ? type : 'info'
}

function inlineNoticeForDisplay(notice) {
  const message = firstText(notice?.message)
  if (!message || normalizedNoticeType(notice) === 'error') return null
  return {
    ...(isObject(notice) ? notice : {}),
    type: normalizedNoticeType(notice),
    message
  }
}

function noticeErrorForPanel(notice) {
  const message = firstText(notice?.message)
  if (!message || normalizedNoticeType(notice) !== 'error') return null
  const source = notice?.error || notice?.apiError || notice?.cause
  if (source instanceof Error) return source
  if (isObject(source)) {
    return {
      ...notice,
      ...source,
      message: firstText(source.message, message),
      detail: source.detail ?? notice.detail,
      diagnostics: source.diagnostics ?? notice.diagnostics,
      requestId: firstText(source.requestId, source.request_id, notice.requestId, notice.request_id),
      payload: source.payload ?? notice.payload
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
