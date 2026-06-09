import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
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

test('BenchmarkComparisonView keeps unrankable evidence separate from formal ranking rows', () => {
  const source = comparisonSource()

  assert.match(source, /const comparePayload = computed\(\(\) =>/)
  assert.match(source, /benchmarkLeaderboardCompareLoading/)
  assert.match(source, /benchmarkLeaderboardCompareError/)
  assert.match(source, /const compareSourceTone = computed\(\(\) =>/)
  assert.match(source, /const compareSourceLabel = computed\(\(\) =>/)
  assert.match(source, /const apiCompareRows = computed\(\(\) =>/)
  assert.match(source, /comparePayload\.value\s*\?\s*apiCompareRows\.value/)
  assert.match(source, /compare\?\.unrankable_evidence/)
  assert.match(source, /compare\?\.unrankableEvidence/)
  assert.match(source, /compare\?\.evidence\?\.unrankable/)
  assert.match(source, /const fallbackUnrankableEvidenceRows = computed/)
  assert.match(source, /const unrankableEvidenceRows = computed/)
  assert.match(source, /const compareSummaryPayload = computed/)
  assert.match(source, /const compareAuditRows = computed/)
  assert.match(source, /summary\.unrankable_evidence_count/)
  assert.match(source, /summary\.boundary_mismatch_count/)
  assert.match(source, /<section class="unrankable-panel" aria-label="未入榜证据">/)
  assert.match(source, /<section class="compare-audit-strip" aria-label="正式比较口径">/)
  assert.match(source, /<small>\{\{ item\.label \}\}<\/small>/)
  assert.match(source, /正式行/)
  assert.match(source, /<span>未入榜证据<\/span>/)
  assert.match(source, /边界告警/)
  assert.match(source, /变化分布/)
  assert.match(source, /<dt>有效局率<\/dt>/)
  assert.match(source, /<dt>batch_id<\/dt>/)
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
  assert.match(source, /95% 置信区间/)
  assert.match(source, /置信区间正常/)
  assert.match(source, /目标角色边界/)

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
})
