import type { LocationQueryRaw, Router } from 'vue-router'
import type { AppView } from '../types/ui'
import { appViewFromLegacyHash, appViewHash, appViewPath } from './appViews'

let activeRouter: Pick<Router, 'replace'> | null = null

export function registerLegacyViewRouter(router: Pick<Router, 'replace'> | null): void {
  activeRouter = router
}

export function routePathForView(view: AppView): string {
  return appViewPath(view)
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

export function viewFromHash(hash = globalThis.window?.location?.hash || ''): AppView {
  return appViewFromLegacyHash(hash)
}

export function hashForView(view: AppView = 'lobby'): string {
  return appViewHash(view)
}

export function currentLegacyHash(): string {
  return typeof window === 'undefined' ? '' : String(window.location.hash || '')
}

export function currentLegacyView(fallback: AppView = 'lobby'): AppView {
  if (typeof window === 'undefined') return fallback
  return viewFromHash(currentLegacyHash())
}

export function addLegacyHashChangeListener(handler: (event: HashChangeEvent) => void): () => void {
  if (typeof window === 'undefined') return () => {}
  window.addEventListener('hashchange', handler)
  return () => window.removeEventListener('hashchange', handler)
}

export function routeHashFromLegacyHash(hash = ''): string {
  return String(hash || '').split('?')[0]
}

export function isLegacyHashForView(view: AppView, hash = currentLegacyHash()): boolean {
  const viewHash = hashForView(view)
  const routeHash = routeHashFromLegacyHash(hash)
  return viewHash ? routeHash === `#${viewHash}` : !routeHash
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

export function writeLegacyHashForView(view: AppView, hash = ''): void {
  if (typeof window === 'undefined') return
  const legacyHash = String(hash || '')
  window.location.hash = legacyHash
  syncRouterToLegacyView(view, legacyHash)
}

export function syncCurrentLegacyHashForView(view: AppView): boolean {
  const hash = currentLegacyHash()
  if (!isLegacyHashForView(view, hash)) return false
  syncRouterToLegacyView(view, hash)
  return true
}

export function writeViewHash(view: AppView = 'lobby'): void {
  if (typeof window === 'undefined') return
  const hash = hashForView(view)
  const nextHash = hash ? `#${hash}` : ''
  writeLegacyHashForView(view, nextHash)
}
