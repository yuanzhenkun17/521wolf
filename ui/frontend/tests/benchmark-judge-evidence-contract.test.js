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
  assert.match(source, /diagnostics:\s*uniqueRows\(displayEvidenceRows\(\[\.\.\.fieldRows\(aggregate, \['diagnostics', 'diagnostic'\]\), \.\.\.diagnosticsRows\]\)\)/)
  assert.match(source, /degradedReasons:\s*uniqueRows\(\[[\s\S]*degraded_reasons[\s\S]*degradedDiagnostics\.map\(diagnosticReason\)/)
  assert.match(source, /warnings:\s*uniqueRows\(\[[\s\S]*fieldRows\(aggregate, \['warnings', 'warning'\]\)[\s\S]*warningDiagnostics\.map\(diagnosticReason\)/)
})

test('Benchmark judge diagnostics keep result scoping without dropping batch-level diagnostics', () => {
  const source = benchmarkReportSource()

  assert.match(source, /function diagnosticMatchesBenchmarkJudgeSource\(row, source\)/)
  assert.match(source, /const rowResultId = String\(row\?\.result_batch_id \|\| ''\)/)
  assert.doesNotMatch(source, /const rowResultId = String\(row\?\.result_batch_id \|\| row\?\.batch_id/)
  assert.match(source, /title: '决策 Judge 诊断'/)
  assert.match(source, /return haystack\.includes\('judge'\) \|\| hasJudgeEvidenceFields\(row\)/)
})

test('Benchmark report visible judge copy stays Chinese-first', () => {
  const source = benchmarkReportSource()

  assert.match(source, /const STATUS_LABELS = \{[\s\S]*accepted: '通过'[\s\S]*bad: '低分'/)
  assert.match(source, /const DISPLAY_LABELS = \{[\s\S]*'Benchmark ID': '评测 ID'[\s\S]*'Decision Judge': '决策 Judge'[\s\S]*diagnostic: '诊断'/)
  assert.match(source, /reproducibility_manifest_hash: '复现清单 Hash'/)
  assert.match(source, /manifest_hash: 'Manifest Hash'/)
  assert.match(source, /statusDisplayLabel\(canonicalReport\.value\?\.status\)/)
  assert.match(source, /statusLabel: statusDisplayLabel\(game\?\.status_label \|\| game\?\.statusLabel \|\| game\?\.status\)/)
  assert.match(source, /Object\.entries\(reproducibility\)\.map\(\(\[label, value\]\) => \(\{ label: reproducibilityLabel\(label\), value \}\)\)/)
  assert.match(source, /function displayEvidenceRow\(row\)/)
  assert.match(source, /kind: diagnosticDisplayLabel\(row\.kind\)/)
  assert.match(source, /sourceTypeLabel\(source\.type\)/)
  assert.match(source, /`\$\{judgedCount\} 已判定`/)
  assert.match(source, /`低分率 \$\{\(badRate \* 100\)\.toFixed\(0\)\}%`/)
  assert.match(source, /diagnosticDisplayLabel\(decision\?\.quality \|\| '低分决策'\)/)
  assert.doesNotMatch(source, /`\$\{value\} judged`/)
  assert.doesNotMatch(source, /`bad \$\{/)
  assert.doesNotMatch(source, /<small>Decision Judge<\/small>/)
  assert.doesNotMatch(source, /label: 'Benchmark ID'/)
})

test('BenchmarkRunReportPanel surfaces reproducibility manifest and artifact hashes', () => {
  const source = benchmarkReportSource()

  assert.match(source, /const selectedReportExportArtifact = ref\(null\)/)
  assert.match(source, /const reportArtifacts = computed\(\(\) => objectOrEmpty\(canonicalReport\.value\?\.artifacts\)\)/)
  assert.match(source, /const reportManifest = computed\(\(\) => objectOrEmpty\(canonicalReport\.value\?\.reproducibility_manifest\)\)/)
  assert.match(source, /const reportManifestArtifactHashes = computed\(\(\) => objectOrEmpty\(reportManifest\.value\.artifact_hashes\)\)/)
  assert.match(source, /canonicalReport\.value\?\.content_hash/)
  assert.match(source, /reportArtifacts\.value\.content_hash/)
  assert.match(source, /canonicalReport\.value\?\.reproducibility_manifest_hash/)
  assert.match(source, /reportArtifacts\.value\.reproducibility_manifest_hash/)
  assert.match(source, /reportManifest\.value\.manifest_hash/)
  assert.match(source, /reportManifest\.value\.content_hash/)
  assert.match(source, /reportManifestArtifactHashes\.value\.content_hash/)
  assert.match(source, /selectedReportExportArtifact\.value\?\.export_content_hash/)
  assert.match(source, /selectedReportExportArtifact\.value\?\.artifact_hash/)
  assert.match(source, /selectedReportExportArtifact\.value\?\.reproducibility_manifest\?\.artifact_hashes\?\.export_content_hash/)
  assert.match(source, /const reportManifestStatus = computed/)
  assert.match(source, /reportManifestHash\.value === String\(reportManifest\.value\.manifest_hash\)/)
  assert.match(source, /reportContentHash\.value === reportManifestContentHash\.value/)
  assert.match(source, /reportContentHash\.value === artifactContentHash/)
  assert.match(source, /label: '内容 Hash'/)
  assert.match(source, /label: '复现清单 Hash'/)
  assert.match(source, /label: '校验状态'/)
  assert.match(source, /label: '导出 Hash'/)
  assert.match(source, /Manifest Hash/)
  assert.match(source, /aria-label="报告审计证据"/)
  assert.match(source, /class="report-audit-grid"/)
  assert.match(source, /export_content_hash/)
  assert.match(source, /reproducibility_manifest_hash/)
})

test('Workbench preserves benchmark report export artifact hashes', () => {
  const source = readSource('../src/composables/useEvaluationWorkbench.js')

  assert.match(source, /function normalizeBenchmarkBatchReportExport\(data, format = 'markdown'\)/)
  assert.match(source, /data\.kind !== 'benchmark_run_report_export'/)
  assert.match(source, /content_hash: String\(data\.content_hash \|\| data\.report\?\.content_hash \|\| ''\)/)
  assert.match(source, /export_content_hash: String\(data\.export_content_hash \|\| data\.artifact_hash \|\| ''\)/)
  assert.match(source, /artifact_hash: String\(data\.artifact_hash \|\| data\.export_content_hash \|\| ''\)/)
  assert.match(source, /data\.reproducibility_manifest_hash/)
  assert.match(source, /data\.reproducibility_manifest\?\.manifest_hash/)
  assert.match(source, /benchmarkBatchReportExports\.value = \{[\s\S]*\[cacheKey\]: payload/)
  assert.match(source, /return payload/)
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
