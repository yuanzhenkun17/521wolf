import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

function batchRunsSource() {
  return readSource('../src/components/benchmark/BenchmarkBatchRunsTable.vue')
}

function boundarySource() {
  return readSource('../src/components/benchmark/BenchmarkBoundaryBar.vue')
}

function pageSource() {
  return readSource('../src/pages/BenchmarkPage.vue')
}

function assertSfcCompiles(relativePath, id) {
  const filename = new URL(relativePath, import.meta.url).pathname
  const source = readSource(relativePath)
  const { descriptor, errors } = parse(source, { filename })
  assert.deepEqual(errors, [])
  compileScript(descriptor, { id })
  const template = compileTemplate({
    source: descriptor.template.content,
    filename,
    id
  })
  assert.deepEqual(template.errors, [])
}

test('Benchmark run table keeps Chinese-first labels and localized backend fallbacks', () => {
  const source = batchRunsSource()

  assert.match(source, /const statusLabels = \{/)
  assert.match(source, /role_version:\s*'角色版本'/)
  assert.match(source, /rankable:\s*'可入榜'/)
  assert.match(source, /unrankable:\s*'未入榜'/)
  assert.match(source, /rankable_failed:\s*'入榜失败'/)
  assert.match(source, /gate_failed:\s*'门禁失败'/)
  assert.match(source, /function displayMappedLabel/)
  assert.match(source, /function displayRankable/)
  assert.match(source, /<small>裁判均分<\/small>/)
  assert.match(source, /<span>裁判<\/span>/)
  assert.match(source, /<span>裁判标签<\/span>/)
  assert.match(source, /run\.evaluationSetId \|\| '临时'/)
  assert.match(source, /label: 'Config Hash'/)
  assert.doesNotMatch(source, /ad-hoc/)
  assert.doesNotMatch(source, /<small>Judge<\/small>|<span>Judge<\/span>|Judge 标签|配置 Hash/)
})

test('Benchmark page maps diagnostics, warnings, and visible judge labels to Chinese copy', () => {
  const source = pageSource()

  assert.match(source, /const diagnosticKindLabels = \{/)
  assert.match(source, /rankable_failed:\s*'入榜失败'/)
  assert.match(source, /llm_error:\s*'LLM 错误'/)
  assert.match(source, /const viewDensityLabels = \{/)
  assert.match(source, /compact:\s*'紧凑'/)
  assert.match(source, /const planWarningLabels = \{/)
  assert.match(source, /budget_exceeded:\s*'预算超限'/)
  assert.match(source, /ad_hoc_benchmark:\s*'临时评测'/)
  assert.match(source, /const planBudgetReasonLabels = \{/)
  assert.match(source, /estimated_units_exceed_limit_units:\s*'预计调用单位超限'/)
  assert.match(source, /estimated_cost_exceed_limit_cost:\s*'预计成本超限'/)
  assert.match(source, /stop_after_budget_units:\s*'达到预算停止线'/)
  assert.match(source, /countSummaryRows\(contextDiagnosticSummary\.value\.by_kind,\s*displayDiagnosticKind\)/)
  assert.match(source, /displayDiagnosticKind\(item\.kindLabel \|\| item\.kind\)/)
  assert.match(source, /densityDisplayLabel\(benchmark\.activeBenchmarkViewConfig\.value\?\.density\)/)
  assert.match(source, /displayPlanWarningKind\(warning\.kind\)/)
  assert.match(source, /displayPlanBudgetReason\(reason\)/)
  assert.match(source, /超预算原因/)
  assert.match(source, /预算与停止线提示/)
  assert.match(source, /预计成本/)
  assert.match(source, /预计 Token|预计 token/)
  assert.match(source, /预检模式/)
  assert.match(source, /临时评测不绑定版本化套件/)
  assert.match(source, /label: '裁判判定单位'/)
  assert.match(source, /裁判判定未启用/)
  assert.match(source, /<small>裁判判定<\/small>/)
  assert.match(source, /<dt>裁判判定<\/dt>/)
  assert.doesNotMatch(source, /Judge 判定单位|判定 Judge 未启用|<small>Judge 判定<\/small>|<dt>Judge 判定<\/dt>|over budget reason|Dry Run/)
})

test('Benchmark boundary and page keep the warm logbook palette', () => {
  const boundary = boundarySource()
  const page = pageSource()
  const combined = `${boundary}\n${page}`

  assert.match(boundary, /--boundary-bg:\s*var\(--bench-bg-texture,\s*var\(--logbook-bg-texture,\s*#f2dfae\)\)/)
  assert.match(boundary, /--boundary-surface:\s*var\(--bench-surface,\s*var\(--logbook-surface,\s*rgba\(255, 252, 245, 0\.7\)\)\)/)
  assert.match(boundary, /--boundary-border:\s*var\(--bench-border,\s*var\(--logbook-border,\s*rgba\(139, 94, 52, 0\.15\)\)\)/)
  assert.match(boundary, /--boundary-text:\s*var\(--bench-text,\s*var\(--logbook-text,\s*#3a2a18\)\)/)
  assert.match(boundary, /--boundary-muted:\s*var\(--bench-text-secondary,\s*var\(--logbook-muted,\s*#8b6b4a\)\)/)
  assert.match(boundary, /--boundary-accent:\s*var\(--bench-accent,\s*var\(--logbook-accent,\s*#8b5e34\)\)/)
  assert.match(boundary, /--boundary-accent-strong:\s*var\(--bench-accent-strong,\s*var\(--logbook-accent-strong,\s*#5a3319\)\)/)
  assert.match(boundary, /box-shadow:\s*0 1px 3px rgba\(91, 47, 18, 0\.04\)/)

  assert.match(page, /--logbook-bg:\s*#f2dfae/)
  assert.match(page, /--logbook-bg-texture:[\s\S]*repeating-linear-gradient\(90deg,\s*rgba\(118, 71, 27, 0\.024\)[\s\S]*var\(--logbook-bg\)/)
  assert.match(page, /--bench-bg:\s*var\(--logbook-bg\)/)
  assert.match(page, /--bench-bg-texture:\s*var\(--logbook-bg-texture\)/)
  assert.match(page, /--bench-surface:\s*var\(--logbook-surface\)/)
  assert.match(page, /--bench-panel:\s*var\(--logbook-panel\)/)
  assert.match(page, /--bench-border:\s*var\(--logbook-border\)/)
  assert.match(page, /--bench-text:\s*var\(--logbook-text\)/)
  assert.match(page, /--bench-text-secondary:\s*var\(--logbook-muted\)/)
  assert.match(page, /--bench-accent:\s*var\(--logbook-accent\)/)
  assert.match(page, /--bench-accent-strong:\s*var\(--logbook-accent-strong\)/)
  assert.match(page, /--bench-danger-border:\s*rgba\(153, 48, 38, 0\.28\)/)
  assert.match(page, /--bench-warning-border:\s*rgba\(139, 100, 31, 0\.3\)/)
  assert.match(page, /\.bench-page\s*\{[\s\S]*background:\s*var\(--bench-bg-texture\)/)
  assert.doesNotMatch(combined, /snapshot-green|snapshot-blue|snapshot-red|snapshot-amber|report-blue|report-warn/)
  assert.doesNotMatch(combined, /#4a9eff|#0f6b72|#2e7d32|#c62828|#f9a825|#f5a623/)
})

test('Benchmark UI localization SFCs compile', () => {
  assertSfcCompiles('../src/components/benchmark/BenchmarkBatchRunsTable.vue', 'benchmark-batch-runs-localization-test')
  assertSfcCompiles('../src/components/benchmark/BenchmarkBoundaryBar.vue', 'benchmark-boundary-localization-test')
  assertSfcCompiles('../src/pages/BenchmarkPage.vue', 'benchmark-page-localization-test')
})
