import { API_BASE } from './api'

export interface EventStreamOptions<T = unknown> {
  path: string
  events?: string[]
  onOpen?: (source: EventSource) => void
  onError?: (event: Event, source: EventSource) => void
  onEvent?: (payload: { type: string; data: T; raw: MessageEvent<string>; source: EventSource }) => void
}

export function createEventStream<T = unknown>({
  path,
  events = ['message'],
  onOpen,
  onError,
  onEvent
}: EventStreamOptions<T>) {
  let source: EventSource | null = null

  function connect() {
    if (typeof EventSource === 'undefined') return null
    source = new EventSource(`${API_BASE}${path}`)
    source.onopen = () => onOpen?.(source as EventSource)
    source.onerror = (event) => onError?.(event, source as EventSource)
    for (const type of events) {
      source.addEventListener(type, (event) => {
        const message = event as MessageEvent<string>
        let data: T
        try {
          data = JSON.parse(message.data) as T
        } catch {
          data = message.data as T
        }
        onEvent?.({ type, data, raw: message, source: source as EventSource })
      })
    }
    return source
  }

  function close() {
    source?.close()
    source = null
  }

  return {
    connect,
    close,
    get source() {
      return source
    }
  }
}
