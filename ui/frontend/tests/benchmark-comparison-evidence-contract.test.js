import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'vitest'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

function comparisonSource() {
  return readSource('../src/components/benchmark/BenchmarkComparisonView.vue')
}

function leaderboardSource() {
  return readSource('../src/components/benchmark/BenchmarkLeaderboardTable.vue')
}

function workbenchSource() {
  return readSource('../src/composables/useEvaluationWorkbench.ts')
}

test('BenchmarkComparisonView keeps unrankable evidence separate from formal ranking rows', () => {
  const source = comparisonSource()
  const workbench = workbenchSource()

  assert.match(source, /const comparePayload = computed\(\(\) =>/)
  assert.match(source, /benchmarkLeaderboardCompareLoading/)
  assert.match(source, /benchmarkLeaderboardCompareError/)
  assert.match(source, /const compareSourceTone = computed\(\(\) =>/)
  assert.match(source, /const compareSourceLabel = computed\(\(\) =>/)
  assert.match(source, /const apiCompareRows = computed\(\(\) =>/)
  assert.match(source, /const hasApiCompareRows = computed\(\(\) => apiCompareRows\.value\.length > 0\)/)
  assert.match(source, /hasApiCompareRows\.value\s*\?\s*apiCompareRows\.value/)
  assert.match(source, /服务端比较为空，保留本地榜单/)
  assert.match(source, /compare\?\.unrankable_evidence/)
  assert.match(source, /compare\?\.unrankableEvidence/)
  assert.match(source, /compare\?\.evidence\?\.unrankable/)
  assert.match(source, /const fallbackUnrankableEvidenceRows = computed/)
  assert.match(source, /const unrankableEvidenceRows = computed/)
  assert.match(source, /const boundaryMismatchRows = computed/)
  assert.match(source, /<section class="unrankable-panel" aria-label="未入榜证据">/)
  assert.match(source, /<section v-if="boundaryMismatchRows\.length" class="boundary-mismatch-alert" aria-label="边界不一致警告">/)
  assert.match(source, /<span>未入榜证据<\/span>/)
  assert.match(source, /<dt>有效局率<\/dt>/)
  assert.match(source, /<dt>batch_id<\/dt>/)
  assert.doesNotMatch(source, /compareSummaryPayload|compareAuditRows|compare-audit-strip|正式比较口径|正式行|变化分布/)
  assert.doesNotMatch(source, /boundary-strip|mode-badge|confidence-panel|baseline-panel|row-detail-panel/)
  assert.match(source, /class="\['compare-source-chip', 'compare-source-chip--' \+ compareSourceTone\]"/)
  assert.match(source, /aria-label="比较来源"/)
  assert.match(source, /aria-live="polite"/)
  assert.match(source, /:role="compareLoading \? 'status' : undefined"/)
  assert.match(source, /aria-label="比较来源提示"/)
  assert.match(source, /服务端比较不可用/)
  assert.match(source, /正在加载服务端比较/)
  assert.match(source, /服务端标准比较/)
  assert.match(source, /本地兜底比较/)
  assert.match(source, /本地当前榜单/)
  assert.match(source, /const WARNING_LABELS = \{/)
  assert.match(source, /low_sample:\s*'小样本'/)
  assert.match(source, /unpaired_seeds:\s*'未配对种子'/)
  assert.match(source, /insufficient_overlap:\s*'配对重叠不足'/)
  assert.match(source, /sampleSize/)
  assert.match(source, /pairedSampleSize/)
  assert.match(source, /standardErrorValue/)
  assert.match(source, /pairedDeltaValue/)
  assert.match(source, /normalizeWinRateInterval/)
  assert.match(source, /normalizeSignificanceLabel/)
  assert.match(source, /normalizeWarnings/)
  assert.match(workbench, /const statistics = \{/)
  assert.match(workbench, /sample_size:\s*score\?\.sample_size/)
  assert.match(workbench, /paired_sample_size:\s*score\?\.paired_sample_size/)
  assert.match(workbench, /win_rate_ci:\s*score\?\.win_rate_ci/)
  assert.match(workbench, /paired_delta:\s*score\?\.paired_delta/)
  assert.match(workbench, /significance_label:\s*score\?\.significance_label/)
  assert.match(workbench, /warnings:\s*score\?\.warnings/)
  assert.match(workbench, /\.\.\.statistics/)
})

test('BenchmarkComparisonView uses warm benchmark colors and Chinese visible labels', () => {
  const source = comparisonSource()
  const leaderboard = leaderboardSource()

  assert.match(source, /--comparison-bg:\s*var\(--bench-bg-texture,\s*var\(--logbook-bg-texture,\s*#f2dfae\)\)/)
  assert.match(source, /--comparison-positive:\s*var\(--bench-accent,\s*var\(--logbook-accent,\s*#8b5e34\)\)/)
  assert.match(source, /--comparison-model:\s*var\(--bench-accent-strong,\s*var\(--logbook-accent-strong,\s*#5a3319\)\)/)
  assert.match(source, /--comparison-danger-border:\s*var\(--bench-danger-border,\s*rgba\(153, 48, 38, 0\.28\)\)/)
  assert.doesNotMatch(source, /--comparison-green/)
  assert.doesNotMatch(source, /--comparison-blue/)
  assert.doesNotMatch(source, /后端 unrankable_evidence/)
  assert.doesNotMatch(source, /95% CI/)
  assert.doesNotMatch(source, /CI 正常/)
  assert.match(source, /置信证据/)
  assert.match(source, /置信区间正常/)
  assert.match(source, /样本量/)
  assert.match(source, /formatInterval/)
  assert.match(source, /formatStandardError/)
  assert.match(source, /paired delta/)
  assert.match(source, /差异不显著/)
  assert.match(source, /未配对种子/)
  assert.match(source, /配对重叠不足/)

  assert.match(leaderboard, /样本量/)
  assert.match(leaderboard, /置信证据/)
  assert.match(leaderboard, /paired delta/)
  assert.match(leaderboard, /差异不显著/)
  assert.match(leaderboard, /小样本/)
  assert.match(leaderboard, /未配对种子/)
  assert.match(leaderboard, /配对重叠不足/)
  assert.doesNotMatch(leaderboard, /#3a7a3a/)
  assert.match(leaderboard, /color:\s*var\(--bench-accent-strong,\s*#8b5e34\)/)
  assert.match(leaderboard, /color:\s*var\(--bench-danger,\s*var\(--logbook-danger,\s*#993026\)\)/)
})

test('BenchmarkComparisonView SFC compiles after unrankable evidence wiring', () => {
  const filename = new URL('../src/components/benchmark/BenchmarkComparisonView.vue', import.meta.url).pathname
  const source = comparisonSource()
  const { descriptor, errors } = parse(source, { filename })
  assert.deepEqual(errors, [])
  const script = compileScript(descriptor, { id: 'benchmark-comparison-evidence-test' })
  assert.match(script.content, /unrankableEvidenceRows/)
  const template = compileTemplate({
    source: descriptor.template.content,
    filename,
    id: 'benchmark-comparison-evidence-test'
  })
  assert.deepEqual(template.errors, [])

  const leaderboardFilename = new URL('../src/components/benchmark/BenchmarkLeaderboardTable.vue', import.meta.url).pathname
  const leaderboardParsed = parse(leaderboardSource(), { filename: leaderboardFilename })
  assert.deepEqual(leaderboardParsed.errors, [])
  compileScript(leaderboardParsed.descriptor, { id: 'benchmark-leaderboard-statistics-test' })
  const leaderboardTemplate = compileTemplate({
    source: leaderboardParsed.descriptor.template.content,
    filename: leaderboardFilename,
    id: 'benchmark-leaderboard-statistics-test'
  })
  assert.deepEqual(leaderboardTemplate.errors, [])
})
