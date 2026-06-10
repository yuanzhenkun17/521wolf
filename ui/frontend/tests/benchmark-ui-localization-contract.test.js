import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'vitest'
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

function suiteRailSource() {
  return readSource('../src/components/benchmark/BenchmarkSuiteRail.vue')
}

function targetSelectorSource() {
  return readSource('../src/components/benchmark/BenchmarkTargetSelector.vue')
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
  assert.match(source, /\.bench-runs-layout\s*\{[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\) minmax\(260px,\s*300px\);[\s\S]*max-width:\s*100%;[\s\S]*min-width:\s*0;/)
  assert.match(source, /\.bench-card\s*\{[\s\S]*min-width:\s*0;/)
  assert.match(source, /\.bench-table\s*\{[\s\S]*max-width:\s*100%;[\s\S]*min-width:\s*0;[\s\S]*overflow-x:\s*auto;/)
  assert.match(source, /\.bench-runs-side\s*\{[\s\S]*max-width:\s*100%;[\s\S]*min-width:\s*0;/)
  assert.match(source, /\.bench-detail-kv\s*\{[\s\S]*grid-template-columns:\s*72px minmax\(0,\s*1fr\)/)
  assert.match(source, /\.diagnostic-filters\s*\{[\s\S]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/)
  assert.match(source, /\.diagnostic-filters \.bench-filter-clear\s*\{[\s\S]*grid-column:\s*1 \/ -1;[\s\S]*width:\s*100%/)
  assert.match(source, /\.bench-diagnostic-row\s*\{[\s\S]*grid-template-columns:\s*70px minmax\(0,\s*1fr\)/)
  assert.match(source, /\.bench-diagnostic-row span,\s*[\s\S]*\.bench-diagnostic-row em\s*\{[\s\S]*white-space:\s*normal;[\s\S]*overflow-wrap:\s*anywhere/)
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
  assert.match(source, /预计成本/)
  assert.match(source, /临时评测不绑定版本化套件/)
  assert.match(source, /label: '裁判判定'/)
  assert.match(source, /<dt>裁判判定<\/dt>/)
  assert.doesNotMatch(source, /Judge 判定单位|判定 Judge 未启用|<small>Judge 判定<\/small>|<dt>Judge 判定<\/dt>|over budget reason|Dry Run|预算与停止线提示|预计 Token|预计 token|预检模式/)
})

test('Benchmark page keeps boundary metadata in the right context rail only', () => {
  const source = pageSource()

  assert.match(source, /bench-context-section--boundary/)
  assert.match(source, /bench-context-section--suite/)
  assert.match(source, /bench-context-section--gate/)
  assert.match(source, /<small>当前套件<\/small>/)
  assert.match(source, /<small>评测边界<\/small>/)
  assert.match(source, /<small>入榜门禁<\/small>/)
  assert.match(source, /label: '比较边界'/)
  assert.match(source, /label: '评测集'/)
  assert.match(source, /label: '种子集'/)
  assert.match(source, /label: 'Config Hash'/)
  assert.match(source, /<span>门禁规则<\/span>/)
  assert.match(source, /<span>套件详情<\/span>/)
  assert.match(source, /<span>种子集<\/span>/)
  assert.match(source, /<span>指标<\/span>/)
  assert.match(source, /<span>裁判配置<\/span>/)
  assert.match(source, /const benchmarkCommandMetaRows = computed\(\(\) => \[/)
  assert.match(source, /:meta="benchmarkCommandMetaRows"/)
  assert.match(source, /action-label="刷新"/)
  assert.match(source, /@action="refresh"/)
  assert.match(source, /const planSummaryRows = computed\(\(\) => \[/)
  assert.match(source, /class="bench-plan-summary" aria-label="启动计划摘要"/)
  assert.match(source, /\.bench-context-panel\s*\{[\s\S]*border-left:\s*1px solid rgba\(93,\s*48,\s*17,\s*0\.22\);[\s\S]*padding-left:\s*14px/)
  assert.match(source, /\.bench-context-run-detail\s*\{[\s\S]*max-width:\s*calc\(100% - 24px\)/)
  assert.doesNotMatch(source, /import BenchmarkBoundaryBar/)
  assert.doesNotMatch(source, /const labHeaderMeta/)
  assert.doesNotMatch(source, /:meta="labHeaderMeta"/)
  assert.doesNotMatch(source, /<template #boundary>/)
  assert.doesNotMatch(source, /boundary-label=/)
  assert.doesNotMatch(source, /:show-header="false"|<template #tabs-actions>|bench-tabs-refresh/)
  assert.doesNotMatch(source, /<small>评测口径<\/small>|contextBudgetRows|label: '预算状态'|bench-plan-grid|bench-cost-breakdown|bench-policy-breakdown|scope=model/)
})

test('Benchmark suite rail stays focused on suite selection', () => {
  const source = suiteRailSource()

  assert.match(source, /aria-label="评测套件库"/)
  assert.match(source, /<span class="suite-row-main">/)
  assert.doesNotMatch(source, /suite-rail-summary|suite-row-tags|suite-row-meta|suite-row-foot|suite-row-activity|suite-rail-selected/)
  assert.doesNotMatch(source, /selectedSpecRows|selectedSeedRows|selectedMetricRows|selectedGateRows|selectedJudgeRows/)
})

test('Benchmark target selector keeps overview focused on editable inputs', () => {
  const source = targetSelectorSource()

  assert.match(source, /<small>目标<\/small>/)
  assert.match(source, /<h2>被测对象<\/h2>/)
  assert.match(source, /v-model\.trim="benchmark\.form\.value\.model_id"/)
  assert.match(source, /v-model\.trim="benchmark\.form\.value\.model_config_hash"/)
  assert.match(source, /v-model\.trim="benchmark\.form\.value\.target_version_id"/)
  assert.doesNotMatch(source, /targetModeLabel|subjectLabel|selectedRoleLabel|target-note|模型评测写入|角色版本评测写入/)
})

test('Benchmark boundary and page keep the warm logbook palette', () => {
  const boundary = boundarySource()
  const page = pageSource()
  const workbenches = readSource('../src/styles/workbenches.css')
  const combined = `${boundary}\n${page}`

  assert.match(boundary, /--boundary-bg:\s*var\(--bench-bg-texture,\s*var\(--logbook-bg-texture,\s*#f2dfae\)\)/)
  assert.match(boundary, /--boundary-surface:\s*var\(--bench-surface,\s*var\(--logbook-surface,\s*rgba\(255, 252, 245, 0\.7\)\)\)/)
  assert.match(boundary, /--boundary-border:\s*var\(--bench-border,\s*var\(--logbook-border,\s*rgba\(139, 94, 52, 0\.15\)\)\)/)
  assert.match(boundary, /--boundary-text:\s*var\(--bench-text,\s*var\(--logbook-text,\s*#3a2a18\)\)/)
  assert.match(boundary, /--boundary-muted:\s*var\(--bench-text-secondary,\s*var\(--logbook-muted,\s*#8b6b4a\)\)/)
  assert.match(boundary, /--boundary-accent:\s*var\(--bench-accent,\s*var\(--logbook-accent,\s*#8b5e34\)\)/)
  assert.match(boundary, /--boundary-accent-strong:\s*var\(--bench-accent-strong,\s*var\(--logbook-accent-strong,\s*#5a3319\)\)/)
  assert.match(boundary, /box-shadow:\s*0 1px 3px rgba\(91, 47, 18, 0\.04\)/)
  assert.match(boundary, /\.benchmark-boundary-bar\s*\{[\s\S]*overflow-x:\s*auto[\s\S]*overflow-y:\s*hidden/)
  assert.match(boundary, /\.boundary-cell small,[\s\S]*\.boundary-cell em\s*\{[\s\S]*text-overflow:\s*ellipsis[\s\S]*white-space:\s*nowrap/)
  assert.doesNotMatch(boundary, /grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/)

  assert.match(workbenches, /--workbench-logbook-bg:\s*#f2dfae/)
  assert.match(workbenches, /--logbook-bg:\s*var\(--workbench-logbook-bg,\s*#f2dfae\)/)
  assert.match(workbenches, /--logbook-bg-texture:\s*var\(--workbench-logbook-bg-texture\)/)
  assert.doesNotMatch(page, /--logbook-bg:\s*var\(--workbench-logbook-bg/)
  assert.match(page, /--bench-bg:\s*var\(--logbook-bg\)/)
  assert.match(page, /--bench-bg-texture:\s*var\(--logbook-bg-texture\)/)
  assert.match(page, /--bench-surface:\s*var\(--logbook-surface\)/)
  assert.match(page, /--bench-panel:\s*var\(--logbook-panel\)/)
  assert.match(page, /--bench-border:\s*var\(--logbook-border\)/)
  assert.match(page, /--bench-text:\s*var\(--logbook-text\)/)
  assert.match(page, /--bench-text-secondary:\s*var\(--logbook-muted\)/)
  assert.match(page, /--bench-accent:\s*var\(--logbook-accent\)/)
  assert.match(page, /--bench-accent-strong:\s*var\(--logbook-accent-strong\)/)
  assert.match(page, /--bench-warning:\s*var\(--logbook-warning-benchmark,\s*var\(--logbook-warning\)\)/)
  assert.match(page, /--bench-danger-border:\s*rgba\(153, 48, 38, 0\.28\)/)
  assert.match(page, /--bench-warning-border:\s*rgba\(139, 100, 31, 0\.3\)/)
  assert.match(page, /\.bench-page\s*\{[\s\S]*background:\s*var\(--bench-bg-texture\)/)
  assert.doesNotMatch(combined, /snapshot-green|snapshot-blue|snapshot-red|snapshot-amber|report-blue|report-warn/)
  assert.doesNotMatch(combined, /#4a9eff|#0f6b72|#2e7d32|#c62828|#f9a825|#f5a623/)
})

test('Benchmark UI localization SFCs compile', () => {
  assertSfcCompiles('../src/components/benchmark/BenchmarkBatchRunsTable.vue', 'benchmark-batch-runs-localization-test')
  assertSfcCompiles('../src/components/benchmark/BenchmarkBoundaryBar.vue', 'benchmark-boundary-localization-test')
  assertSfcCompiles('../src/components/benchmark/BenchmarkSuiteRail.vue', 'benchmark-suite-rail-localization-test')
  assertSfcCompiles('../src/components/benchmark/BenchmarkTargetSelector.vue', 'benchmark-target-selector-localization-test')
  assertSfcCompiles('../src/pages/BenchmarkPage.vue', 'benchmark-page-localization-test')
})
