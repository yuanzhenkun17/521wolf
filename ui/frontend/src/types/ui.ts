export type AppView = 'lobby' | 'match' | 'logs' | 'benchmark' | 'evolution'
export type NoticeType = '' | 'info' | 'success' | 'warning' | 'error'

export interface NoticeState {
  type: NoticeType
  message: string
  code?: string
  requestId?: string | null
}

export interface ToastState extends NoticeState {
  id: string
  createdAt: number
  timeoutMs?: number
}

export interface AsyncState<T = unknown> {
  loading: boolean
  error: string
  data: T | null
  loadedAt?: number | null
}

export interface SelectOption<T extends string | number = string> {
  value: T
  label: string
  disabled?: boolean
  description?: string
}

export interface TableColumn {
  key: string
  label: string
  visible?: boolean
  sortable?: boolean
  width?: string | number
}

export interface DialogState<T = unknown> {
  open: boolean
  payload: T | null
}
