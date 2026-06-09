// @ts-nocheck
import { watch } from 'vue'

const NOTICE_DISMISS_DELAYS = {
  success: 2500,
  warning: 5000
}

function emptyNotice() {
  return { type: '', message: '' }
}

function noticeDismissDelay(type) {
  return NOTICE_DISMISS_DELAYS[type] || 0
}

function createNoticeAutoDismiss(noticeRef, { enabled = true, onDismiss = null } = {}) {
  let timer = 0

  function clearTimer() {
    if (timer && typeof window !== 'undefined') window.clearTimeout(timer)
    timer = 0
  }

  function schedule(notice) {
    clearTimer()
    if (!enabled || typeof window === 'undefined') return
    const message = String(notice?.message || '')
    const type = String(notice?.type || '')
    const delay = noticeDismissDelay(type)
    if (!message || !delay) return

    const expected = { type, message }
    timer = window.setTimeout(() => {
      timer = 0
      const current = noticeRef.value || {}
      if (current.type !== expected.type || current.message !== expected.message) return
      noticeRef.value = emptyNotice()
      onDismiss?.(expected)
    }, delay)
  }

  if (!enabled) {
    return { dispose() {}, clearTimer() {} }
  }

  const stop = watch(noticeRef, schedule, { flush: 'sync' })

  function dispose() {
    clearTimer()
    stop()
  }

  return { dispose, clearTimer }
}

export { createNoticeAutoDismiss, emptyNotice, noticeDismissDelay }
