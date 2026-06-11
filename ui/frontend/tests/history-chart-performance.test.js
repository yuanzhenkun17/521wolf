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
  assert.match(voteFlowSource, /const heatmapWidth = computed/)
  assert.match(voteFlowSource, /\['speech', 'day_speech', 'pk_speak'\]\.includes\(phase\)/)
  assert.match(voteFlowSource, /\['vote', 'exile_vote', 'pk_vote'\]\.includes\(phase\)/)
  assert.match(voteFlowSource, /overflow-x:\s*auto/)
  assert.doesNotMatch(voteFlowSource, /rounds\.push\(\{ key: 'end', label: '终局' \}\)/)
})

test('review report auto requests flow data before mounting vote-flow charts', () => {
  const reviewSource = source('src/components/history/ReviewReportPanel.vue')

  assert.match(reviewSource, /const showFlowCharts = computed\(\(\) => hasFlowChartData\.value\)/)
  assert.match(reviewSource, /class="review-flow-status"/)
  assert.match(reviewSource, /requestFlowCharts/)
  assert.match(reviewSource, /flowData/)
  assert.match(reviewSource, /loadFlowData/)
  assert.match(reviewSource, /flowDataPayload\.value\?\.rows/)
  assert.match(reviewSource, /const reviewFlowPlayers = computed/)
  assert.doesNotMatch(reviewSource, /IntersectionObserver/)
  assert.doesNotMatch(reviewSource, /展开图表/)
  assert.match(reviewSource, /props\.game\?\.decisions/)
  assert.doesNotMatch(reviewSource, /class="review-flow-gate"/)
  assert.match(reviewSource, /<VoteFlowSankey\s+v-if="showFlowCharts"/)
})

test('history side assessment only uses authoritative review scores', () => {
  const derivedSource = source('src/composables/useHistoryDerivedState.ts')
  const logsPageSource = source('src/pages/LogsPage.vue')

  assert.doesNotMatch(derivedSource, /buildAssessmentScores/)
  assert.match(derivedSource, /const reviewRows = normalizeReviewScoreRows\(reviewPayload\)/)
  assert.match(derivedSource, /if \(!reviewRows\.length\) return \[\]/)
  assert.match(derivedSource, /optionalReviewScorePercent/)
  assert.doesNotMatch(derivedSource, /\['logic_score', 'logic', 'information_score', 'information', 'overall'\]/)
  assert.match(logsPageSource, /runHistoryAction\('loadFlowData', gameId\)/)
})

test('history result phase shows the terminal winner outside raw logs', () => {
  const logsPageSource = source('src/pages/LogsPage.vue')

  assert.match(logsPageSource, /const resultWinnerText = computed/)
  assert.match(logsPageSource, /终局胜方/)
  assert.match(logsPageSource, /class="phase-result-summary"/)
  assert.match(logsPageSource, /selectedHistoryGame\.value\?\.winner/)
  assert.match(logsPageSource, /phaseCategory\.value === 'result' && !collapsedPhaseEvidenceKeys\.value\.has/)
  assert.match(logsPageSource, /collapsedPhaseEvidenceKeys\.value = new Set\(\)/)
})

test('history selection preloads authoritative review scores', () => {
  const logsPageSource = source('src/pages/LogsPage.vue')
  const historySource = source('src/composables/useGameHistory.ts')

  assert.match(logsPageSource, /selectedReview\.value \? 'loaded' : ''/)
  assert.match(logsPageSource, /const hasScores = \[review\.player_evaluations, review\.player_scores, review\.agent_scores\]/)
  assert.match(logsPageSource, /review\.scoring_version !== 'speech_quality_v2'/)
  assert.match(logsPageSource, /refreshedEmptyReviewKeys\.value\.has\(key\)/)
  assert.match(logsPageSource, /\{ force: true, silentSuccess: true, clearNotice: false \}/)
  assert.match(logsPageSource, /runHistoryAction\('loadReview', gameId\)/)
  assert.match(historySource, /\{ silentSuccess = false, clearNotice = true, force = false \}/)
  assert.match(historySource, /!force && state\.reviewByGameId\.value\[gameId\]/)
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

  assert.doesNotMatch(reviewSource, /local_estimate/)
  assert.doesNotMatch(reviewSource, /buildAssessmentScores/)
  assert.match(reviewSource, /复盘报告真实评分/)
  assert.match(reviewSource, /class="\['review-score-source', reviewScoreSourceClass\]"/)

  assert.match(historyListSource, /function isEvidenceGame/)
  assert.match(historyListSource, /sourceKey\(game\) !== 'normal'/)
  assert.match(historyListSource, /:disabled="isEvidenceGame\(item\)"/)
  assert.match(historyListSource, /普通删除不可用/)
  assert.match(logsPageSource, /history-game-delete:disabled/)
})
