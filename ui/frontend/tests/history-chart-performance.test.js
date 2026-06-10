import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { test } from 'vitest'
import { fileURLToPath } from 'node:url'

const frontendRoot = path.resolve(fileURLToPath(new URL('..', import.meta.url)))

function source(relativePath) {
  return readFileSync(path.join(frontendRoot, relativePath), 'utf8')
}

test('review vote-flow chart keeps the ECharts flow and heatmap implementation', () => {
  const packageJson = JSON.parse(source('package.json'))
  const voteFlowSource = source('src/components/history/VoteFlowSankey.vue')

  assert.ok(packageJson.dependencies?.echarts)
  assert.match(voteFlowSource, /import\s+\*\s+as\s+echarts/)
  assert.match(voteFlowSource, /SankeyChart/)
  assert.match(voteFlowSource, /HeatmapChart/)
  assert.match(voteFlowSource, /echarts\.init/)
  assert.match(voteFlowSource, /class="vote-flow-chart"/)
})

test('review report auto requests flow data before mounting vote-flow charts', () => {
  const reviewSource = source('src/components/history/ReviewReportPanel.vue')

  assert.match(reviewSource, /const showFlowCharts = computed\(\(\) => hasFlowChartData\.value\)/)
  assert.match(reviewSource, /class="review-flow-status"/)
  assert.match(reviewSource, /requestFlowCharts/)
  assert.match(reviewSource, /flowData/)
  assert.match(reviewSource, /loadFlowData/)
  assert.doesNotMatch(reviewSource, /IntersectionObserver/)
  assert.doesNotMatch(reviewSource, /展开图表/)
  assert.match(reviewSource, /props\.game\?\.decisions/)
  assert.doesNotMatch(reviewSource, /class="review-flow-gate"/)
  assert.match(reviewSource, /<VoteFlowSankey\s+v-if="showFlowCharts"/)
})

test('review score stacked bars keep the target branch alignment contract', () => {
  const scoreSource = source('src/components/history/ReviewScoreStackedBar.vue')
  const logsPageSource = source('src/pages/LogsPage.vue')

  assert.doesNotMatch(scoreSource, /class="rsb-rank"|\.rsb-rank/)
  assert.doesNotMatch(scoreSource, /<small>综合<\/small>/)
  assert.match(scoreSource, /\.rsb-row\s*\{[\s\S]*grid-template-columns:\s*92px minmax\(360px,\s*1fr\) 34px[\s\S]*gap:\s*4px/)
  assert.match(scoreSource, /\.rsb-legend\s*\{[\s\S]*padding:\s*0 0 9px;/)
  assert.match(logsPageSource, /\.history-detail-panel \.detail-topbar :deep\(\.history-phase-tabs\)\s*\{[\s\S]*height:\s*82px[\s\S]*padding:\s*11px 10px 17px 0/)
})

test('history phase detail keeps target branch phase workbench structure', () => {
  const logsPageSource = source('src/pages/LogsPage.vue')

  assert.match(logsPageSource, /function isSetupHistoryPage\(page: any\)/)
  assert.match(logsPageSource, /const allHistoryPages = computed<any\[\]>\(\(\) => hasStoreSelection\.value \? historyStore\.pages : props\.historyPages\)/)
  assert.match(logsPageSource, /const historyPagesForTabs = computed<any\[\]>\(\(\) => allHistoryPages\.value\.filter\(\(page\) => !isSetupHistoryPage\(page\)\)\)/)
  assert.match(logsPageSource, /const selectedPhaseTabKey = computed\(\(\) => \{/)
  assert.match(logsPageSource, /:selected-page-key="selectedPhaseTabKey"/)
  assert.doesNotMatch(logsPageSource, /<header class="phase-overview"/)
  assert.doesNotMatch(logsPageSource, /\{\{ phaseDecisionPanelMeta \}\}/)
  assert.match(logsPageSource, /<section v-if="canShowPhaseDecisionPanel" class="phase-decision-panel">\s*<header class="phase-section-head">\s*<h4>决策明细<\/h4>\s*<\/header>/)
  assert.match(logsPageSource, /\.phase-evidence-panel\s*\{[\s\S]*padding:\s*14px 14px 12px/)
  assert.match(logsPageSource, /\.phase-decision-panel\s*\{[\s\S]*margin-top:\s*12px;[\s\S]*padding:\s*10px 14px 12px;[\s\S]*border-top:\s*0;[\s\S]*background:\s*rgba\(255,\s*252,\s*245,\s*0\.34\)/)
  assert.match(logsPageSource, /\.phase-decision-panel :deep\(\.night-two-col\)\s*\{[\s\S]*border:\s*0;[\s\S]*background:\s*transparent;[\s\S]*gap:\s*12px/)
  assert.match(logsPageSource, /\.history-page-detail details\.history-raw-section\s*\{[\s\S]*margin-top:\s*12px;[\s\S]*border-top:\s*0;[\s\S]*background:\s*rgba\(255,\s*252,\s*245,\s*0\.34\)/)
  assert.match(logsPageSource, /\.history-page-detail details\.history-raw-section > summary\s*\{[\s\S]*background:\s*transparent;/)
})

test('history review and evidence deletion expose trust boundaries', () => {
  const reviewSource = source('src/components/history/ReviewReportPanel.vue')
  const historyListSource = source('src/components/HistoryGameList.vue')
  const logsPageSource = source('src/pages/LogsPage.vue')

  assert.match(reviewSource, /local_estimate/)
  assert.match(reviewSource, /本地推算，仅供浏览/)
  assert.match(reviewSource, /class="\['review-score-source', reviewScoreSourceClass\]"/)

  assert.match(historyListSource, /function isEvidenceGame/)
  assert.match(historyListSource, /sourceKey\(game\) !== 'normal'/)
  assert.match(historyListSource, /:disabled="isEvidenceGame\(item\)"/)
  assert.match(historyListSource, /普通删除不可用/)
  assert.match(logsPageSource, /history-game-delete:disabled/)
})
