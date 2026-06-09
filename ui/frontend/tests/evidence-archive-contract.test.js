import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

function assertSourceContract(source, contracts) {
  for (const [label, pattern] of contracts) {
    assert.match(source, pattern, label)
  }
}

function assertAnySourceContract(source, label, patterns) {
  assert.ok(
    patterns.some((pattern) => pattern.test(source)),
    label
  )
}

test('Evidence Archive is a first-class app route and TopNav Lab entry', () => {
  const app = readSource('../src/App.vue')
  const gameSession = readSource('../src/composables/gameSession.js')
  const liveState = readSource('../src/composables/useLiveGameState.js')
  const history = readSource('../src/composables/useGameHistory.js')
  const topNav = readSource('../src/components/TopNav.vue')

  assert.match(gameSession, /evidence:\s*'evidence'/)
  assert.match(liveState, /computedState\.inEvidence = computed\(\(\) => currentView\.value === 'evidence'\)/)
  assert.match(app, /const EvidencePage = defineAsyncComponent\(\(\) => import\('\.\/pages\/EvidencePage\.vue'\)\)/)
  assert.match(app, /const evidenceProps = computed\(\(\) => pickRuntime\(logsPropKeys\)\)/)
  assert.match(app, /inEvidence/)
  assert.match(app, /@open-evidence="openEvidencePage\(\)"/)
  assert.match(app, /<EvidencePage[\s\S]*v-if="inEvidence"[\s\S]*@open-logs="openLogPage\(\$event\)"/)
  assert.match(history, /async function openEvidencePage\(gameId = null, \{ rememberOrigin = true \} = \{\}\)/)
  assert.match(history, /const targetGameId = gameId == null \? '' : String\(gameId\)/)
  assert.match(history, /state\.currentView\.value = 'evidence'/)
  assert.match(history, /writeViewHash\('evidence'\)/)
  assert.match(history, /loadArchive\(activeGameId, \{ clearNotice: false \}\)/)
  assert.match(history, /loadReview\(activeGameId, \{ clearNotice: false \}\)/)
  assert.match(history, /params\.get\('game_id'\) \|\| params\.get\('game'\) \|\| ''/)
  assert.match(history, /route\.routeHash === '#evidence'/)
  assert.match(history, /openEvidencePage\(route\.gameId \|\| null, \{ rememberOrigin \}\)/)
  assert.match(topNav, /key: 'evidence'[\s\S]*line: 'lab'[\s\S]*event: 'open-evidence'/)
})

test('#evidence?game_id=... keeps selected archive and review preloaded', () => {
  const history = readSource('../src/composables/useGameHistory.js')

  assertSourceContract(history, [
    ['hash routing parses the evidence game_id query parameter', /function hashRouteInfo\(\)[\s\S]*const params = new URLSearchParams\(queryString\)[\s\S]*gameId: params\.get\('game_id'\) \|\| params\.get\('game'\) \|\| ''/],
    ['evidence route forwards the query game id into openEvidencePage', /if \(route\.routeHash === '#evidence'\) \{[\s\S]*void openEvidencePage\(route\.gameId \|\| null, \{ rememberOrigin \}\)[\s\S]*return/],
    ['openEvidencePage selects the explicit game before preloading assets', /async function openEvidencePage[\s\S]*const selectedGameId = targetGameId \|\| String\(state\.selectedHistoryGameId\.value \|\| ''\)[\s\S]*await selectHistoryGame\(selectedGameId, \{ fromOpenPage: true \}\)[\s\S]*const activeGameId = String\(state\.selectedHistoryGame\.value\?\.game_id \|\| state\.selectedHistoryGameId\.value \|\| ''\)/],
    ['archive and review are preloaded together without replacing the evidence route hash', /await Promise\.allSettled\(\[[\s\S]*loadArchive\(activeGameId, \{ clearNotice: false \}\),[\s\S]*loadReview\(activeGameId, \{ clearNotice: false \}\)[\s\S]*\]\)/],
  ])
})

test('EvidenceLink game targets point to the formal Evidence Archive route', () => {
  const links = readSource('../src/components/history/evidenceLinks.js')

  assert.match(links, /buildHashLink\('evidence', \{ game_id: gameId \}\)/)
  assert.doesNotMatch(links, /buildHashLink\('logs', \{ game_id: gameId \}\)/)
})

test('EvidencePage reuses archive and review evidence surfaces without delete actions', () => {
  const page = readSource('../src/pages/EvidencePage.vue')

  assertSourceContract(page, [
    ['Evidence Archive page exposes a stable test hook', /data-evidence-archive-page/],
    ['Evidence Archive imports the shared evidence context', /import EvidenceContextBar from '\.\.\/components\/history\/EvidenceContextBar\.vue'/],
    ['Evidence Archive imports shared evidence links', /import EvidenceLink from '\.\.\/components\/history\/EvidenceLink\.vue'/],
    ['Evidence Archive reuses the archive panel', /const GameArchivePanel = defineAsyncComponent\(\(\) => import\('\.\.\/components\/history\/GameArchivePanel\.vue'\)\)/],
    ['Evidence Archive reuses the review panel', /const ReviewReportPanel = defineAsyncComponent\(\(\) => import\('\.\.\/components\/history\/ReviewReportPanel\.vue'\)\)/],
    ['Evidence Archive summarizes asset authority state', /const selectedAssetRows = computed/],
    ['Evidence Archive renders the shared context bar', /<EvidenceContextBar/],
    ['Evidence Archive renders the formal archive link', /<EvidenceLink :target="selectedEvidenceSource" kind="game" label="Archive" \/>/],
    ['Evidence Archive renders archived game evidence', /<GameArchivePanel/],
    ['Evidence Archive renders review evidence', /<ReviewReportPanel/],
    ['Evidence Archive declares the read-only boundary in empty state copy', /Evidence Archive 只提供只读索引、来源跳转和审计上下文，不提供删除入口。/],
  ])

  const actionableSource = page.replace(/Evidence Archive 只提供只读索引、来源跳转和审计上下文，不提供删除入口。/g, '')
  assert.doesNotMatch(actionableSource, /deleteHistoryGame|forceDelete|deleteEvidence|removeEvidence|destroyEvidence|@delete|@remove/i)
  assert.doesNotMatch(actionableSource, /@click="[^"]*(delete|remove|destroy)[^"]*"/i)
  assert.doesNotMatch(actionableSource, /\b(method|verb):\s*['"]DELETE['"]/i)
  assert.doesNotMatch(actionableSource, /删除对局|删除证据|移除证据|清空档案/)
})

test('EvidencePage exposes global search, source/status filters, and pagination controls', () => {
  const page = readSource('../src/pages/EvidencePage.vue')

  assertSourceContract(page, [
    ['filtering starts from normalized evidence rows', /const evidenceRows = computed\(\(\) =>[\s\S]*props\.gameHistory[\s\S]*normalizeEvidenceRow/],
    ['search filtering produces a filtered evidence row collection', /const (filteredEvidenceRows|visibleEvidenceRows) = computed\(\(\) =>[\s\S]*(evidenceSearch|searchQuery|globalSearch)/],
    ['pagination produces a sliced evidence row collection', /const (paginatedEvidenceRows|pagedEvidenceRows|visibleEvidencePageRows) = computed\(\(\) =>[\s\S]*\.slice\(/],
    ['index renders paginated rows rather than the raw full collection', /v-for="row in (paginatedEvidenceRows|pagedEvidenceRows|visibleEvidencePageRows)"/],
    ['page size is bounded in component state', /(const evidencePageSize|pageSize:|EVIDENCE_PAGE_SIZE)\s*=?\s*\d+/],
  ])

  assertAnySourceContract(page, 'global search input is rendered with search semantics', [
    /<input[\s\S]*type="search"[\s\S]*(aria-label|placeholder)="[^"]*(全局搜索|搜索|Search)[^"]*"/,
    /<(label|div|section)[\s\S]*(全局搜索|搜索|Search)[\s\S]*<input[\s\S]*type="search"/,
  ])
  assertAnySourceContract(page, 'source filter is rendered as an explicit control', [
    /<(select|button|label)[\s\S]*(aria-label="[^"]*(来源|Source)[^"]*"|来源筛选|Source)[\s\S]*(v-model|@change|@click)/,
    /<(select|button)[\s\S]*(v-model="[^"]*(source|Source)[^"]*"|data-filter="source")/,
  ])
  assertAnySourceContract(page, 'status filter is rendered as an explicit control', [
    /<(select|button|label)[\s\S]*(aria-label="[^"]*(状态|资产|Status)[^"]*"|状态筛选|资产状态|Status)[\s\S]*(v-model|@change|@click)/,
    /<(select|button)[\s\S]*(v-model="[^"]*(status|Status|asset|Asset)[^"]*"|data-filter="status")/,
  ])
  assertAnySourceContract(page, 'pagination has previous and next buttons', [
    /<button[\s\S]*(上一页|Previous|Prev)[\s\S]*<\/button>[\s\S]*<button[\s\S]*(下一页|Next)[\s\S]*<\/button>/,
    /aria-label="[^"]*(上一页|Previous|Prev)[^"]*"[\s\S]*aria-label="[^"]*(下一页|Next)[^"]*"/,
  ])
})

test('EvidencePage keeps archive layout dense and mobile-safe', () => {
  const page = readSource('../src/pages/EvidencePage.vue')

  assertSourceContract(page, [
    ['desktop workbench uses a shrinkable detail column', /\.evidence-workbench\s*\{[\s\S]*grid-template-columns:\s*minmax\(260px, 0\.33fr\) minmax\(0, 1fr\)/],
    ['index owns vertical overflow instead of expanding the viewport', /\.evidence-index\s*\{[\s\S]*max-height:\s*calc\(100vh - 164px\)[\s\S]*overflow:\s*auto/],
    ['authority strip uses shrinkable columns', /\.evidence-authority-strip\s*\{[\s\S]*grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\)/],
    ['tablet layout collapses to one workbench column', /@media \(max-width: 1040px\)[\s\S]*\.evidence-workbench\s*\{[\s\S]*grid-template-columns:\s*1fr/],
    ['phone layout accounts for safe-area insets', /@media \(max-width: 720px\)[\s\S]*env\(safe-area-inset-top, 0px\)[\s\S]*env\(safe-area-inset-bottom, 0px\)/],
    ['small phone summary and authority strips collapse to one column', /@media \(max-width: 460px\)[\s\S]*\.evidence-summary-grid,[\s\S]*\.evidence-authority-strip\s*\{[\s\S]*grid-template-columns:\s*1fr/],
  ])

  assertAnySourceContract(page, 'filter controls are in a shrinkable wrapping toolbar', [
    /\.evidence-(filter-bar|index-controls|archive-controls)\s*\{[\s\S]*min-width:\s*0[\s\S]*(flex-wrap:\s*wrap|grid-template-columns:[\s\S]*minmax\(0, 1fr\))/,
    /\.evidence-(filter-bar|index-controls|archive-controls)\s*\{[\s\S]*(flex-wrap:\s*wrap|grid-template-columns:[\s\S]*minmax\(0, 1fr\))[\s\S]*min-width:\s*0/,
  ])
  assertAnySourceContract(page, 'pagination controls wrap on mobile instead of widening the page', [
    /\.evidence-pagination\s*\{[\s\S]*min-width:\s*0[\s\S]*flex-wrap:\s*wrap/,
    /\.evidence-pagination\s*\{[\s\S]*flex-wrap:\s*wrap[\s\S]*min-width:\s*0/,
    /@media \(max-width: 720px\)[\s\S]*\.evidence-pagination\s*\{[\s\S]*(grid-template-columns:\s*1fr|flex-wrap:\s*wrap)/,
  ])
})
