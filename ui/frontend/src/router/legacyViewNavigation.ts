import type { LocationQueryRaw, Router } from 'vue-router'
import type { AppView } from '../types/ui'

const VIEW_PATHS: Record<AppView, string> = {
  lobby: '/',
  match: '/match',
  logs: '/logs',
  benchmark: '/benchmark',
  evolution: '/evolution'
}

let activeRouter: Pick<Router, 'replace'> | null = null

export function registerLegacyViewRouter(router: Pick<Router, 'replace'> | null): void {
  activeRouter = router
}

export function routePathForView(view: AppView): string {
  return VIEW_PATHS[view] || '/'
}

export function routeQueryFromLegacyHash(hash = ''): LocationQueryRaw {
  const queryString = String(hash || '').split('?')[1] || ''
  const params = new URLSearchParams(queryString)
  const query: LocationQueryRaw = {}

  params.forEach((value, key) => {
    const existing = query[key]
    if (existing === undefined) {
      query[key] = value
    } else if (Array.isArray(existing)) {
      existing.push(value)
    } else {
      query[key] = [existing, value]
    }
  })

  return query
}

export function syncRouterToLegacyView(view: AppView, hash = ''): void {
  if (!activeRouter) return
  const legacyHash = String(hash || '')
  void activeRouter.replace({
    path: routePathForView(view),
    query: routeQueryFromLegacyHash(legacyHash),
    hash: legacyHash
  }).catch(() => {})
}
