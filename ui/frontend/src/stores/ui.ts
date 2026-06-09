import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { NoticeState, ToastState } from '../types/ui'

export interface UiRuntimeHydration {
  error?: string | null
  matchNotice?: NoticeState | null
  historyNotice?: NoticeState | null
}

export const useUiStore = defineStore('ui', () => {
  const notice = ref<NoticeState>({ type: '', message: '' })
  const toasts = ref<ToastState[]>([])

  function setNotice(nextNotice: NoticeState): void {
    notice.value = nextNotice
  }

  function pushToast(toast: Omit<ToastState, 'id' | 'createdAt'>): string {
    const id = crypto.randomUUID?.() || Math.random().toString(36).slice(2)
    toasts.value.push({ ...toast, id, createdAt: Date.now() })
    return id
  }

  function removeToast(id: string): void {
    toasts.value = toasts.value.filter((toast) => toast.id !== id)
  }

  function hydrateFromRuntime(runtime: UiRuntimeHydration): void {
    const sourceNotice: NoticeState = runtime.matchNotice?.message
      ? runtime.matchNotice
      : runtime.historyNotice?.message
        ? runtime.historyNotice
        : runtime.error
          ? { type: 'error' as const, message: runtime.error }
          : { type: '', message: '' }
    notice.value = sourceNotice
  }

  return {
    notice,
    toasts,
    setNotice,
    pushToast,
    removeToast,
    hydrateFromRuntime
  }
})
