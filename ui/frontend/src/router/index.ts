import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { installLegacyHashBridge, syncInitialRouteToLegacyHash } from './legacyHashRedirect'
import { registerLegacyViewRouter } from './legacyViewNavigation'

const LobbyPage = () => import('../pages/LobbyPage.vue')
const MatchPage = () => import('../pages/MatchPage.vue')
const LogsPage = () => import('../pages/LogsPage.vue')
const BenchmarkPage = () => import('../pages/BenchmarkPage.vue')
const EvolutionPage = () => import('../pages/EvolutionPage.vue')

export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'lobby', component: LobbyPage },
  { path: '/match', name: 'match', component: MatchPage },
  { path: '/logs', name: 'logs', component: LogsPage },
  { path: '/benchmark', name: 'benchmark', component: BenchmarkPage },
  { path: '/evolution', name: 'evolution', component: EvolutionPage }
]

if (typeof window !== 'undefined') {
  syncInitialRouteToLegacyHash()
}

export const router = createRouter({
  history: createWebHistory(),
  routes
})

registerLegacyViewRouter(router)
installLegacyHashBridge(router)
