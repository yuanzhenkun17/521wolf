function createLatestOnlyTracker() {
  let currentId = 0

  function next() {
    const id = currentId + 1
    currentId = id
    return {
      id,
      isLatest: () => id === currentId
    }
  }

  function invalidate() {
    currentId += 1
  }

  return {
    next,
    invalidate,
    isLatest: (token) => Boolean(token?.isLatest?.())
  }
}

function createLatestOnlyMap() {
  const trackers = new Map()

  function trackerFor(key) {
    const normalized = String(key ?? '')
    if (!trackers.has(normalized)) trackers.set(normalized, createLatestOnlyTracker())
    return trackers.get(normalized)
  }

  return {
    next: (key) => trackerFor(key).next(),
    invalidate: (key) => trackerFor(key).invalidate(),
    isLatest: (key, token) => trackerFor(key).isLatest(token)
  }
}

function isLatestRequest(token) {
  return !token || token.isLatest()
}

function allLatestRequests(...tokens) {
  return tokens.every(isLatestRequest)
}

export {
  allLatestRequests,
  createLatestOnlyMap,
  createLatestOnlyTracker,
  isLatestRequest
}
