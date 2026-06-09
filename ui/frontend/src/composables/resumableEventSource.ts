// @ts-nocheck
function eventIdFrom(event, payload = {}) {
  const rawId = event?.lastEventId || event?.id || event?.eventId || payload?.event_id || payload?.id
  const eventId = String(rawId || '').trim()
  return !eventId || eventId === '0' ? '' : eventId
}

function createResumableEventSource({
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
}) {
  const sources = new Map()
  const retryTimers = new Map()
  const retryDelays = new Map()
  let lastEventIds = {}

  function urlFor(id) {
    return makeUrl(id, lastEventIds[id] || '')
  }

  function rememberEventId(id, event, payload = {}) {
    const eventId = eventIdFrom(event, payload)
    if (!id || !eventId) return
    lastEventIds = {
      ...lastEventIds,
      [id]: eventId
    }
  }

  function resetEventId(id) {
    if (!id || !lastEventIds[id]) return
    const next = { ...lastEventIds }
    delete next[id]
    lastEventIds = next
  }

  function resetAllEventIds() {
    lastEventIds = {}
  }

  function clearRetryTimer(id) {
    const timer = retryTimers.get(id)
    if (!timer) return
    if (typeof window !== 'undefined') window.clearTimeout(timer)
    retryTimers.delete(id)
  }

  function clearAllRetryTimers() {
    for (const id of [...retryTimers.keys()]) clearRetryTimer(id)
  }

  function close(id) {
    clearRetryTimer(id)
    const source = sources.get(id)
    if (!source) return
    source.close?.()
    sources.delete(id)
  }

  function closeAll() {
    clearAllRetryTimers()
    for (const id of [...sources.keys()]) close(id)
  }

  function has(id) {
    return sources.has(id)
  }

  function ids() {
    return [...sources.keys()]
  }

  function scheduleReconnect(id) {
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

  function connect(id) {
    if (!id || typeof EventSource === 'undefined') return null
    if (sources.has(id)) return sources.get(id)
    clearRetryTimer(id)
    const source = new EventSource(urlFor(id))
    sources.set(id, source)
    let done = false

    source.addEventListener('open', (event) => {
      if (backoff) retryDelays.set(id, retryDelay)
      onOpen?.({ id, event, source })
    })

    const handle = async (event) => {
      clearRetryTimer(id)
      if (backoff) retryDelays.set(id, retryDelay)
      const rawData = event.data || ''
      let payload = {}
      let parseError = null
      try {
        payload = JSON.parse(rawData || '{}')
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
      source.addEventListener(name, handle)
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
