interface LatestOnlyToken {
  readonly id: number
  readonly signal?: AbortSignal
  abort: () => void
  isLatest: () => boolean
}

interface LatestOnlyTracker {
  next: () => LatestOnlyToken
  invalidate: () => void
  isLatest: (token?: LatestOnlyToken | null) => boolean
}

interface LatestOnlyMap {
  next: (key: unknown) => LatestOnlyToken
  invalidate: (key: unknown) => void
  isLatest: (key: unknown, token?: LatestOnlyToken | null) => boolean
}

type MaybeLatestOnlyToken = LatestOnlyToken | null | undefined

function createLatestOnlyTracker(): LatestOnlyTracker {
  let currentId = 0
  let currentController: AbortController | null = null

  function next(): LatestOnlyToken {
    currentController?.abort()
    currentController = typeof AbortController === 'undefined' ? null : new AbortController()
    const id = currentId + 1
    currentId = id
    const controller = currentController
    return {
      id,
      signal: controller?.signal,
      abort: () => {
        if (id === currentId) controller?.abort()
      },
      isLatest: () => id === currentId
    }
  }

  function invalidate(): void {
    currentId += 1
    currentController?.abort()
    currentController = null
  }

  return {
    next,
    invalidate,
    isLatest: (token) => Boolean(token?.isLatest?.())
  }
}

function createLatestOnlyMap(): LatestOnlyMap {
  const trackers = new Map<string, LatestOnlyTracker>()

  function trackerFor(key: unknown): LatestOnlyTracker {
    const normalized = String(key ?? '')
    const existing = trackers.get(normalized)
    if (existing) return existing
    const tracker = createLatestOnlyTracker()
    trackers.set(normalized, tracker)
    return tracker
  }

  return {
    next: (key) => trackerFor(key).next(),
    invalidate: (key) => trackerFor(key).invalidate(),
    isLatest: (key, token) => trackerFor(key).isLatest(token)
  }
}

function isLatestRequest(token?: MaybeLatestOnlyToken): boolean {
  return !token || token.isLatest()
}

function allLatestRequests(...tokens: MaybeLatestOnlyToken[]): boolean {
  return tokens.every(isLatestRequest)
}

export type {
  LatestOnlyMap,
  LatestOnlyToken,
  LatestOnlyTracker
}

export {
  allLatestRequests,
  createLatestOnlyMap,
  createLatestOnlyTracker,
  isLatestRequest
}
