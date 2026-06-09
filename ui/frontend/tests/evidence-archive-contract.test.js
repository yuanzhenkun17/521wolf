import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'vitest'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

function assertSourceContract(source, contracts) {
  for (const [label, pattern] of contracts) {
    assert.match(source, pattern, label)
  }
}

test('EvidencePage is removed as a first-class route and TopNav entry', () => {
  const app = readSource('../src/App.vue')
  const gameSession = readSource('../src/composables/gameSession.ts')
  const liveState = readSource('../src/composables/useLiveGameState.ts')
  const history = readSource('../src/composables/useGameHistory.ts')
  const topNav = readSource('../src/components/TopNav.vue')

  assert.doesNotMatch(app, /EvidencePage/)
  assert.doesNotMatch(app, /evidenceProps/)
  assert.doesNotMatch(app, /inEvidence/)
  assert.doesNotMatch(app, /openEvidencePage/)
  assert.doesNotMatch(topNav, /open-evidence/)
  assert.doesNotMatch(topNav, /key: 'evidence'/)
  assert.doesNotMatch(gameSession, /evidence:\s*'evidence'/)
  assert.doesNotMatch(liveState, /computedState\.inEvidence/)
  assert.doesNotMatch(history, /async function openEvidencePage/)
})

test('legacy #evidence links are not routed or recognized', () => {
  const gameSession = readSource('../src/composables/gameSession.ts')
  const history = readSource('../src/composables/useGameHistory.ts')

  assertSourceContract(history, [
    ['logs hashes can carry game id and workspace', /function logsHash\(\{ gameId = '', workspace = '' \} = \{\}\)[\s\S]*query\.set\('game_id', String\(gameId\)\)[\s\S]*query\.set\('workspace', tab\)/],
    ['hash routing parses workspace query parameters', /workspace: normalizeHistoryWorkspaceTab\(params\.get\('workspace'\) \|\| params\.get\('tab'\) \|\| '', ''\)/],
    ['openLogPage stores the requested workspace', /state\.historyWorkspaceTab\.value = targetWorkspace/],
  ])
  assert.doesNotMatch(gameSession, /#evidence/)
  assert.doesNotMatch(history, /#evidence/)
  assert.doesNotMatch(history, /route\.routeHash === '#evidence'/)
  assert.doesNotMatch(history, /workspace: route\.workspace \|\| 'archive'/)
  assert.doesNotMatch(history, /state\.currentView\.value = 'evidence'/)
  assert.doesNotMatch(history, /writeViewHash\('evidence'\)/)
  assert.doesNotMatch(history, /loadArchive\(activeGameId, \{ clearNotice: false \}\)/)
  assert.doesNotMatch(history, /loadReview\(activeGameId, \{ clearNotice: false \}\)/)
})

test('LogsPage owns archive and review workspaces for evidence details', () => {
  const app = readSource('../src/App.vue')
  const refs = readSource('../src/composables/gameStateShared.ts')
  const logs = readSource('../src/pages/LogsPage.vue')

  assertSourceContract(app, [
    ['App passes the shared logs workspace model', /'historyWorkspaceTab'/],
    ['LogsPage binds history workspace tab through v-model', /v-model:history-workspace-tab="historyWorkspaceTab"/],
  ])
  assertSourceContract(refs, [
    ['runtime stores the selected logs workspace', /historyWorkspaceTab:\s*ref\('phase'\)/],
  ])
  assertSourceContract(logs, [
    ['LogsPage accepts external workspace selection', /historyWorkspaceTab:\s*\{\s*type:\s*String,\s*default:\s*'phase'\s*\}/],
    ['LogsPage emits workspace changes back to runtime', /'update:historyWorkspaceTab'/],
    ['external workspace tab loads matching assets lazily', /function setWorkspaceTab\(tab[\s\S]*next === 'review'[\s\S]*props\.loadReview\?\.[\s\S]*next === 'archive'[\s\S]*props\.loadArchive\?\./],
    ['manual game selection resets back to phase details', /function selectHistoryGameFromList\(gameId\)[\s\S]*setWorkspaceTab\('phase'\)[\s\S]*emit\('select-history-game', gameId\)/],
    ['LogsPage still renders review and archive surfaces', /<ReviewReportPanel[\s\S]*<GameArchivePanel/],
  ])
})

test('EvidenceLink game targets point to Logs archive workspace', () => {
  const links = readSource('../src/components/history/evidenceLinks.ts')

  assert.match(links, /buildHashLink\('logs', \{ game_id: gameId, workspace: 'archive' \}\)/)
  assert.match(links, /params:\s*\{ game_id: gameId, workspace: 'archive' \}/)
  assert.doesNotMatch(links, /buildHashLink\('evidence'/)
})
