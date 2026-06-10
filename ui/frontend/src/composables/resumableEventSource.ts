type ResumablePayload = Record<string, any>

type ResumableEventIdPayload = {
  event_id?: unknown
  id?: unknown
}

type ResumableEventIdSource = {
  lastEventId?: unknown
  id?: unknown
  eventId?: unknown
}

type ResumableMessageEvent = MessageEvent<string> & ResumableEventIdSource

type ResumableOpenContext = {
  id: string
  event: Event
  source: EventSource
}

type ResumableErrorContext = {
  id: string
  source: EventSource
}

type ResumableEventContext<Payload extends ResumablePayload = ResumablePayload> = {
  id: string
  event: ResumableMessageEvent
  payload: Payload
  parseError: unknown | null
  rawData: string
  source: EventSource
  close: () => void
  resetEventId: () => void
}

type ResumableEventSourceOptions<Payload extends ResumablePayload = ResumablePayload> = {
  events: readonly string[]
  makeUrl: (id: string, lastEventId: string) => string
  onOpen?: (context: ResumableOpenContext) => void
  onEvent?: (context: ResumableEventContext<Payload>) => void | Promise<void>
  onError?: (context: ResumableErrorContext) => void
  shouldReconnect?: (id: string) => boolean
  isTerminal?: (event: ResumableMessageEvent, payload: Payload) => boolean
  retryDelay?: number
  maxRetryDelay?: number
  backoff?: boolean
}

type ResumableEventSourceController = {
  clearRetryTimer: (id: string) => void
  close: (id: string) => void
  closeAll: () => void
  connect: (id: string) => EventSource | null
  has: (id: string) => boolean
  ids: () => string[]
  resetAllEventIds: () => void
  resetEventId: (id: string) => void
  scheduleReconnect: (id: string) => void
}

function eventIdFrom(
  event: ResumableEventIdSource | null | undefined,
  payload: ResumableEventIdPayload = {}
): string {
  const rawId = event?.lastEventId || event?.id || event?.eventId || payload?.event_id || payload?.id
  const eventId = String(rawId || '').trim()
  return !eventId || eventId === '0' ? '' : eventId
}

function createResumableEventSource<Payload extends ResumablePayload = ResumablePayload>({
  events,
  makeUrl,
  onOpen,
  onEvent,
  onError,
  shouldReconnect,
  isTerminal,
  retryDelay = 1000,
  maxRetryDelay = 30000,
  backoff = false
}: ResumableEventSourceOptions<Payload>): ResumableEventSourceController {
  const sources = new Map<string, EventSource>()
  const retryTimers = new Map<string, number>()
  const retryDelays = new Map<string, number>()
  let lastEventIds: Record<string, string> = {}

  function urlFor(id: string): string {
    return makeUrl(id, lastEventIds[id] || '')
  }

  function rememberEventId(
    id: string,
    event: ResumableEventIdSource,
    payload: ResumableEventIdPayload = {}
  ): void {
    const eventId = eventIdFrom(event, payload)
    if (!id || !eventId) return
    lastEventIds = {
      ...lastEventIds,
      [id]: eventId
    }
  }

  function resetEventId(id: string): void {
    if (!id || !lastEventIds[id]) return
    const next = { ...lastEventIds }
    delete next[id]
    lastEventIds = next
  }

  function resetAllEventIds(): void {
    lastEventIds = {}
  }

  function clearRetryTimer(id: string): void {
    const timer = retryTimers.get(id)
    if (!timer) return
    if (typeof window !== 'undefined') window.clearTimeout(timer)
    retryTimers.delete(id)
  }

  function clearAllRetryTimers(): void {
    for (const id of [...retryTimers.keys()]) clearRetryTimer(id)
  }

  function close(id: string): void {
    clearRetryTimer(id)
    const source = sources.get(id)
    if (!source) return
    source.close?.()
    sources.delete(id)
  }

  function closeAll(): void {
    clearAllRetryTimers()
    for (const id of [...sources.keys()]) close(id)
  }

  function has(id: string): boolean {
    return sources.has(id)
  }

  function ids(): string[] {
    return [...sources.keys()]
  }

  function scheduleReconnect(id: string): void {
    if (!id || retryTimers.has(id) || typeof window === 'undefined') return
    const currentDelay = retryDelays.get(id) || retryDelay
    const timer = window.setTimeout(() => {
      retryTimers.delete(id)
      if (shouldReconnect?.(id)) {
        if (backoff) retryDelays.set(id, Math.min(currentDelay * 2, maxRetryDelay))
        connect(id)
      }
    }, currentDelay)
    retryTimers.set(id, timer)
  }

  function connect(id: string): EventSource | null {
    if (!id || typeof EventSource === 'undefined') return null
    if (sources.has(id)) return sources.get(id)!
    clearRetryTimer(id)
    const source = new EventSource(urlFor(id))
    sources.set(id, source)
    let done = false

    source.addEventListener('open', (event) => {
      if (backoff) retryDelays.set(id, retryDelay)
      onOpen?.({ id, event, source })
    })

    const handle = async (event: ResumableMessageEvent): Promise<void> => {
      clearRetryTimer(id)
      if (backoff) retryDelays.set(id, retryDelay)
      const rawData = event.data || ''
      let payload = {} as Payload
      let parseError: unknown | null = null
      try {
        payload = JSON.parse(rawData || '{}') as Payload
      } catch (err) {
        parseError = err
      }
      rememberEventId(id, event, payload)
      if (isTerminal?.(event, payload)) {
        done = true
        close(id)
      }
      await onEvent?.({
        id,
        event,
        payload,
        parseError,
        rawData,
        source,
        close: () => close(id),
        resetEventId: () => resetEventId(id)
      })
    }

    events.forEach((name) => {
      source.addEventListener(name, handle as EventListener)
    })

    source.addEventListener('error', () => {
      source.close?.()
      if (sources.get(id) === source) sources.delete(id)
      if (done) return
      onError?.({ id, source })
      if (shouldReconnect?.(id)) scheduleReconnect(id)
    })
    return source
  }

  return {
    clearRetryTimer,
    close,
    closeAll,
    connect,
    has,
    ids,
    resetAllEventIds,
    resetEventId,
    scheduleReconnect
  }
}

export { createResumableEventSource, eventIdFrom }
export type {
  ResumableErrorContext,
  ResumableEventContext,
  ResumableEventSourceController,
  ResumableEventSourceOptions,
  ResumableMessageEvent,
  ResumableOpenContext
}
