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
  assert.match(reviewSource, /class="review-flow-gate"/)
  assert.match(reviewSource, /requestFlowCharts/)
  assert.match(reviewSource, /flowData/)
  assert.match(reviewSource, /loadFlowData/)
  assert.doesNotMatch(reviewSource, /IntersectionObserver/)
  assert.doesNotMatch(reviewSource, /展开图表/)
  assert.doesNotMatch(reviewSource, /props\.game\?\.decisions/)
  assert.match(reviewSource, /<VoteFlowSankey\s+v-if="showFlowCharts"/)
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
