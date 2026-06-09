import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

function benchmarkReportSource() {
  return readSource('../src/components/benchmark/BenchmarkRunReportPanel.vue')
}

test('BenchmarkRunReportPanel delegates judge evidence rendering to shared JudgeEvidencePanel', () => {
  const source = benchmarkReportSource()

  assert.match(source, /import JudgeEvidencePanel from '\.\.\/history\/JudgeEvidencePanel\.vue'/)
  assert.match(source, /const benchmarkJudgeEvidenceRows = computed\(\(\) =>/)
  assert.match(source, /<JudgeEvidencePanel :evidence="row\.evidence" :row-key="row\.key" :format-json="jsonText" \/>/)
  assert.match(source, /class="benchmark-judge-evidence-list" aria-label="评测 Judge 证据"/)
  assert.doesNotMatch(source, /<details[^>]+class="benchmark-judge-evidence"/)
})

test('Benchmark judge evidence maps aggregate, lowest decisions, and diagnostics into shared evidence groups', () => {
  const source = benchmarkReportSource()

  assert.match(source, /function benchmarkResultJudgeAggregate\(result\)/)
  assert.match(source, /scoreSummary\.decision_judge_aggregate/)
  assert.match(source, /selectedRun\.value\?\.judgeAggregate/)
  assert.match(source, /canonicalReport\.value\?\.decision_judge_diagnostics/)
  assert.match(source, /canonicalReport\.value\?\.judge_diagnostics/)
  assert.match(source, /source\.aggregate\?\.lowest_decisions/)
  assert.match(source, /diagnosticMatchesJudgeDecision\(row, decision\)/)

  assert.match(source, /evidenceRefs:\s*uniqueRows\(fieldRows\(aggregate, \['evidence_refs', 'evidence_ref', 'evidence'\]\)\)/)
  assert.match(source, /counterfactuals:\s*uniqueRows\(fieldRows\(aggregate, \['counterfactual', 'counterfactuals'\]\)\)/)
  assert.match(source, /rubricMisses:\s*uniqueRows\(\[[\s\S]*top_rubric_misses[\s\S]*top_mistake_tags/)
  assert.match(source, /diagnostics:\s*uniqueRows\(\[\.\.\.fieldRows\(aggregate, \['diagnostics', 'diagnostic'\]\), \.\.\.diagnosticsRows\]\)/)
  assert.match(source, /degradedReasons:\s*uniqueRows\(\[[\s\S]*degraded_reasons[\s\S]*degradedDiagnostics\.map\(diagnosticReason\)/)
  assert.match(source, /warnings:\s*uniqueRows\(\[[\s\S]*fieldRows\(aggregate, \['warnings', 'warning'\]\)[\s\S]*warningDiagnostics\.map\(diagnosticReason\)/)
})

test('Benchmark judge diagnostics keep result scoping without dropping batch-level diagnostics', () => {
  const source = benchmarkReportSource()

  assert.match(source, /function diagnosticMatchesBenchmarkJudgeSource\(row, source\)/)
  assert.match(source, /const rowResultId = String\(row\?\.result_batch_id \|\| ''\)/)
  assert.doesNotMatch(source, /const rowResultId = String\(row\?\.result_batch_id \|\| row\?\.batch_id/)
  assert.match(source, /title: 'Decision Judge 诊断'/)
  assert.match(source, /return haystack\.includes\('judge'\) \|\| hasJudgeEvidenceFields\(row\)/)
})

test('Benchmark judge evidence styles are dense and mobile-safe', () => {
  const source = benchmarkReportSource()

  assert.match(source, /\.benchmark-report-panel\s*\{[\s\S]*--log-text:\s*var\(--report-ink\)[\s\S]*--log-accent:\s*var\(--report-accent\)/)
  assert.match(source, /\.benchmark-judge-evidence-list\s*\{[\s\S]*min-width:\s*0[\s\S]*margin-top:\s*8px/)
  assert.match(source, /\.benchmark-judge-evidence-row\s*\{[\s\S]*min-width:\s*0[\s\S]*overflow:\s*hidden/)
  assert.match(source, /\.benchmark-judge-evidence-head\s*\{[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\) auto[\s\S]*min-width:\s*0/)
  assert.match(source, /\.benchmark-judge-evidence-meta\s*\{[\s\S]*overflow:\s*hidden[\s\S]*text-overflow:\s*ellipsis/)
  assert.match(source, /@media \(max-width: 720px\)[\s\S]*\.benchmark-judge-evidence-head\s*\{[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/)
  assert.match(source, /@media \(max-width: 720px\)[\s\S]*\.benchmark-judge-evidence-row :deep\(\.review-judge-evidence-grid\)\s*\{[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/)
})

test('BenchmarkRunReportPanel SFC still compiles after judge evidence wiring', () => {
  const filename = new URL('../src/components/benchmark/BenchmarkRunReportPanel.vue', import.meta.url).pathname
  const source = benchmarkReportSource()
  const { descriptor, errors } = parse(source, { filename })
  assert.deepEqual(errors, [])
  const script = compileScript(descriptor, { id: 'benchmark-run-report-panel-test' })
  assert.match(script.content, /JudgeEvidencePanel/)
  const template = compileTemplate({
    source: descriptor.template.content,
    filename,
    id: 'benchmark-run-report-panel-test'
  })
  assert.deepEqual(template.errors, [])
})
