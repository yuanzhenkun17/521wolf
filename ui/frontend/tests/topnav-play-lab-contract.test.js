import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'vitest'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

test('TopNav exposes Play and Lab as primary work lines', () => {
  const source = readSource('../src/components/TopNav.vue')

  assert.match(source, /const navItems = \[[\s\S]*key: 'lobby'[\s\S]*line: 'play'[\s\S]*lineLabel: 'Play'[\s\S]*event: 'go-lobby'/)
  assert.match(source, /key: 'logs'[\s\S]*line: 'play'[\s\S]*lineLabel: 'Play'[\s\S]*event: 'open-logs'/)
  assert.match(source, /key: 'benchmark'[\s\S]*line: 'lab'[\s\S]*lineLabel: 'Lab'[\s\S]*event: 'open-benchmark'/)
  assert.match(source, /key: 'evolution'[\s\S]*line: 'lab'[\s\S]*lineLabel: 'Lab'[\s\S]*event: 'open-evolution'/)
})

test('TopNav buttons show current page state without changing App routing events', () => {
  const source = readSource('../src/components/TopNav.vue')
  const appSource = readSource('../src/App.vue')

  assert.match(source, /function navItemAriaLabel\(item\)[\s\S]*\$\{item\.lineLabel\} 工作线：\$\{item\.label\}[\s\S]*当前页面/)
  assert.match(source, /import \{ useRoute \} from 'vue-router'/)
  assert.match(source, /import \{ useGameStore, useReplayStore, useSessionStore, useUiStore \} from '\.\.\/stores'/)
  assert.match(source, /import \{ appViewFromRouteSource \} from '\.\.\/router\/appViews'/)
  assert.match(source, /const routeActiveView = computed\(\(\) => appViewFromRouteSource\(route\)\)/)
  assert.match(source, /const storeActiveView = computed\(\(\) => sessionStore\.currentView \|\| ''\)/)
  assert.match(source, /const explicitActiveView = computed\(\(\) => hasExplicitTopNavProp\('activeView'\) \? props\.activeView : ''\)/)
  assert.match(source, /if \(routeActiveView\.value\) return routeActiveView\.value/)
  assert.match(source, /return explicitActiveView\.value \|\| storeActiveView\.value \|\| 'lobby'/)
  assert.match(source, /<nav v-if="variant !== 'match'" class="primary-nav" aria-label="主导航">/)
  assert.match(source, /class="nav-button"[\s\S]*:data-work-line="item\.line"[\s\S]*:aria-current="activeNavView === item\.key \? 'page' : undefined"[\s\S]*:aria-label="navItemAriaLabel\(item\)"/)
  assert.match(source, /<span class="nav-line">\{\{ item\.lineLabel \}\}<\/span>[\s\S]*<span class="nav-label">\{\{ item\.label \}\}<\/span>[\s\S]*<span v-if="activeNavView === item\.key" class="nav-state">当前<\/span>/)

  assert.match(appSource, /import \{ useRoute \} from 'vue-router'/)
  assert.match(appSource, /import \{ useAppRuntimeProps \} from '\.\/composables\/appRuntimeProps'/)
  assert.match(appSource, /import \{ appViewFromRouteSource \} from '\.\/router\/appViews'/)
  assert.match(appSource, /const route = useRoute\(\)/)
  assert.match(appSource, /\} = useAppRuntimeProps\(runtime\)/)
  assert.match(source, /const uiStore = useUiStore\(\)/)
  assert.match(source, /function hasExplicitUiProp\(propName: keyof typeof UI_PROP_ALIASES\)/)
  assert.match(source, /const effectiveAudioEnabled = computed\(\(\) => hasExplicitUiProp\('audioEnabled'\) \? props\.audioEnabled : uiStore\.audioEnabled\)/)
  assert.match(source, /const effectiveTtsEnabled = computed\(\(\) => hasExplicitUiProp\('ttsEnabled'\) \? props\.ttsEnabled : uiStore\.ttsEnabled\)/)
  assert.match(source, /const effectiveTtsAvailable = computed\(\(\) => hasExplicitUiProp\('ttsAvailable'\) \? props\.ttsAvailable : uiStore\.ttsAvailable\)/)
  assert.match(appSource, /const routeAppView = computed\(\(\) => appViewFromRouteSource\(route\)\)/)
  assert.match(appSource, /const activeAppView = computed\(\(\) => routeAppView\.value \|\| 'lobby'\)/)
  assert.match(appSource, /const inLogs = computed\(\(\) => activeAppView\.value === 'logs'\)/)
  assert.match(appSource, /const isNight = computed\(\(\) => gameStore\.isNight\)/)
  assert.match(appSource, /const toastError = computed\(\(\) => uiStore\.errorMessage\)/)
  assert.match(appSource, /!gameStore\.roleAssignmentComplete[\s\S]*gameStore\.judgeBoardStarted \|\| gameStore\.judgeBoardStarting/)
  assert.match(source, /const replayStore = useReplayStore\(\)/)
  assert.match(source, /const effectiveHasActiveGame = computed\(\(\) => !replayStore\.isReplayMode && \(propHasActiveGame\.value \|\| storeHasActiveGame\.value\)\)/)
  assert.match(source, /const effectiveShowExitGame = computed\(\(\) => !replayStore\.isReplayMode && \(propShowExitGame\.value \|\| storeShowExitGame\.value\)\)/)
  assert.doesNotMatch(appSource, /:active-view="topNavActiveView"/)
  assert.doesNotMatch(appSource, /:active-session="activeSession"/)
  assert.doesNotMatch(appSource, /:has-active-game="showActiveGamePill"/)
  assert.doesNotMatch(appSource, /:show-exit-game="showTopbarExitGame"/)
  assert.doesNotMatch(appSource, /:exit-disabled="topbarExitDisabled"/)

  assert.match(appSource, /@go-lobby="goLobby"/)
  assert.match(appSource, /@open-logs="openLogPage\(\)"/)
  assert.match(appSource, /@open-benchmark="openBenchmarkPage"/)
  assert.match(appSource, /@open-evolution="openEvolutionPage"/)
})

test('TopNav Play and Lab segment styling stays compact on mobile', () => {
  const source = readSource('../src/components/TopNav.vue')

  assert.match(source, /\.topbar \.primary-nav button\[data-work-line="play"\]\s*\{[\s\S]*--nav-button-accent:\s*var\(--nav-accent\)/)
  assert.match(source, /\.topbar \.primary-nav button\[data-work-line="lab"\]\s*\{[\s\S]*--nav-button-accent:\s*var\(--nav-accent\)/)
  assert.match(source, /\.topbar--lobby \.primary-nav button\[data-work-line="lab"\]\s*\{[\s\S]*color:\s*var\(--nav-accent\)/)
  assert.match(source, /\.topbar--lobby \.primary-nav button\[data-work-line="lab"\]:hover\s*\{[\s\S]*background:\s*rgba\(255,\s*180,\s*168,\s*0\.08\)/)
  assert.match(source, /\.topbar--lobby \.primary-nav button\[data-work-line="lab"\]\.active:hover\s*\{[\s\S]*background:\s*rgba\(255,\s*180,\s*168,\s*0\.08\)/)
  assert.match(source, /\.nav-line\s*\{[\s\S]*display:\s*none/)
  assert.match(source, /\.nav-label\s*\{[\s\S]*text-overflow:\s*ellipsis[\s\S]*white-space:\s*nowrap/)
  assert.match(source, /\.nav-state\s*\{[\s\S]*display:\s*none/)
  assert.match(source, /@media \(max-width: 760px\)[\s\S]*\.topbar \.primary-nav button\s*\{[\s\S]*grid-template-rows:\s*9px 14px/)
  assert.match(source, /@media \(max-width: 760px\)[\s\S]*\.nav-state\s*\{[\s\S]*font-size:\s*0/)
})

test('TopNav Play/Lab contract does not remove existing stream status badge contract', () => {
  const source = readSource('../src/components/TopNav.vue')

  assert.match(source, /const streamStatusBadge = computed\(\(\) => \{/)
  assert.match(source, /class="active-session-pill"[\s\S]*:title="streamStatusBadge\.title"[\s\S]*:aria-label="streamStatusBadge\.ariaLabel"/)
  assert.match(source, /class="stream-status-badge"[\s\S]*:data-stream-status="streamStatusBadge\.status"[\s\S]*\{\{ streamStatusBadge\.label \}\}/)
})
