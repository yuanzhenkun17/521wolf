import { watch } from 'vue'
import type { Ref, WatchStopHandle } from 'vue'

type NoticeType = '' | 'success' | 'warning' | 'error' | 'info' | string

interface NoticeMessage {
  type?: NoticeType
  message?: string
}

interface NoticeAutoDismissOptions {
  enabled?: boolean
  onDismiss?: ((notice: Required<Pick<NoticeMessage, 'type' | 'message'>>) => void) | null
}

interface NoticeAutoDismissController {
  dispose: () => void
  clearTimer: () => void
}

const NOTICE_DISMISS_DELAYS = {
  success: 2500,
  warning: 5000
} as const

function emptyNotice(): Required<Pick<NoticeMessage, 'type' | 'message'>> {
  return { type: '', message: '' }
}

function noticeDismissDelay(type: NoticeType): number {
  return NOTICE_DISMISS_DELAYS[type as keyof typeof NOTICE_DISMISS_DELAYS] || 0
}

function createNoticeAutoDismiss(
  noticeRef: Ref<NoticeMessage | null | undefined>,
  { enabled = true, onDismiss = null }: NoticeAutoDismissOptions = {}
): NoticeAutoDismissController {
  let timer: number | null = null

  function clearTimer() {
    if (timer !== null && typeof window !== 'undefined') window.clearTimeout(timer)
    timer = null
  }

  function schedule(notice: NoticeMessage | null | undefined) {
    clearTimer()
    if (!enabled || typeof window === 'undefined') return
    const message = String(notice?.message || '')
    const type = String(notice?.type || '')
    const delay = noticeDismissDelay(type)
    if (!message || !delay) return

    const expected = { type, message }
    timer = window.setTimeout(() => {
      timer = null
      const current = noticeRef.value || {}
      if (current.type !== expected.type || current.message !== expected.message) return
      noticeRef.value = emptyNotice()
      onDismiss?.(expected)
    }, delay)
  }

  if (!enabled) {
    return { dispose() {}, clearTimer() {} }
  }

  const stop: WatchStopHandle = watch(noticeRef, schedule, { flush: 'sync' })

  function dispose() {
    clearTimer()
    stop()
  }

  return { dispose, clearTimer }
}

export { createNoticeAutoDismiss, emptyNotice, noticeDismissDelay }
