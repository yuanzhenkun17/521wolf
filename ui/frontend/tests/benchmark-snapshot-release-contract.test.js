import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

function snapshotReleaseSource() {
  return readSource('../src/components/benchmark/BenchmarkSnapshotReleasePanel.vue')
}

test('BenchmarkSnapshotReleasePanel exposes release readiness and disabled reasons near freeze action', () => {
  const source = snapshotReleaseSource()

  assert.match(source, /const currentReleaseAudit = computed\(\(\) =>/)
  assert.match(source, /const currentUnrankableRows = computed\(\(\) =>/)
  assert.match(source, /const releaseReadinessChecks = computed\(\(\) =>/)
  assert.match(source, /const releaseBlockingReasons = computed\(\(\) =>/)
  assert.match(source, /const releaseGateDetail = computed\(\(\) =>/)
  assert.match(source, /const selectedSnapshotReleaseGate = computed\(\(\) =>/)
  assert.match(source, /const selectedSnapshotEvidenceRows = computed\(\(\) =>/)
  assert.match(source, /const selectedSnapshotGateIssues = computed\(\(\) =>/)
  assert.match(source, /const boundaryWarningSummary = computed\(\(\) =>/)
  assert.match(source, /:aria-label="'冻结快照：' \+ releaseGateLabel"/)
  assert.match(source, /:aria-disabled="String\(!canCreate\)"/)
  assert.match(source, /:title="releaseGateDetail"/)
  assert.match(source, /aria-label="发布门禁"/)
  assert.match(source, /aria-label="禁用原因"/)
  assert.match(source, /冻结按钮已开放/)
  assert.match(source, /冻结按钮已禁用/)
  assert.match(source, /可冻结/)
  assert.match(source, /不可冻结/)
  assert.doesNotMatch(source, /snapshot-freeze-reason|snapshot-gate-check|snapshot-secondary-button|refreshSnapshots/)
})

test('BenchmarkSnapshotReleasePanel shows compact server release evidence after snapshot selection', () => {
  const source = snapshotReleaseSource()

  assert.match(source, /const selectedSnapshotExportArtifact = ref\(null\)/)
  assert.match(source, /const selectedSnapshotExportHash = computed/)
  assert.match(source, /selectedSnapshotExportArtifact\.value\?\.export_content_hash/)
  assert.match(source, /props\.benchmark\.loadBenchmarkSnapshotExport/)
  assert.match(source, /snapshotExportPayload/)
  assert.match(source, /Evaluation Set/)
  assert.match(source, /缺少 Evaluation Set，无法冻结正式快照/)
  assert.match(source, /缺少 Seed Set，无法证明种子边界/)
  assert.match(source, /缺少 Config Hash，无法证明配置边界/)
  assert.match(source, /存在评测边界告警，需先处理后再冻结/)
  assert.match(source, /不可排名证据/)
  assert.match(source, /随快照保留/)
  assert.match(source, /不会进入正式排名/)
  assert.match(source, /scope/)
  assert.match(source, /aria-label="发布证据"/)
  assert.match(source, /服务端门禁/)
  assert.match(source, /门禁阈值/)
  assert.match(source, /Content Hash/)
  assert.match(source, /Export Hash/)
  assert.match(source, /export_content_hash/)
  assert.match(source, /来源运行/)
  assert.match(source, /来源报告/)
  assert.match(source, /结果批次/)
  assert.match(source, /aria-label="服务端门禁问题"/)
  assert.match(source, /snapshot-evidence-grid/)
  assert.doesNotMatch(source, /snapshot-audit|snapshot-list-meta|snapshot-source-line|compare-boundary|snapshot-code-value/)
  assert.doesNotMatch(source, />Readiness</)
  assert.doesNotMatch(source, />Release Gate</)
})

test('BenchmarkSnapshotReleasePanel keeps release identity and boundary warnings as hard blockers', () => {
  const source = snapshotReleaseSource()

  assert.match(source, /key: 'seed'[\s\S]*required: true[\s\S]*blockedReason: '缺少 Seed Set/)
  assert.match(source, /key: 'config'[\s\S]*required: true[\s\S]*blockedReason: '缺少 Config Hash/)
  assert.match(source, /key: 'boundary-warning'[\s\S]*required: true[\s\S]*blockedReason: '存在评测边界告警/)
  assert.match(source, /key: 'unrankable'[\s\S]*required: false[\s\S]*attentionReason: '不可排名证据会保留，但不进入正式排名'/)
  assert.doesNotMatch(source, /key: 'source-run'|key: 'source-report'|key: 'source-result'/)
  assert.match(source, /release_gate/)
  assert.match(source, /release_manifest/)
})

test('BenchmarkSnapshotReleasePanel keeps warm snapshot release styling', () => {
  const source = snapshotReleaseSource()

  assert.match(source, /--snapshot-bg:\s*var\(--bench-bg,\s*var\(--logbook-bg,\s*#f2dfae\)\)/)
  assert.match(source, /--snapshot-surface:\s*var\(--bench-surface,\s*var\(--logbook-surface,\s*rgba\(255, 252, 245, 0\.7\)\)\)/)
  assert.match(source, /--snapshot-border:\s*var\(--bench-border,\s*var\(--logbook-border,\s*rgba\(139, 94, 52, 0\.15\)\)\)/)
  assert.match(source, /--snapshot-ink:\s*var\(--bench-text,\s*var\(--logbook-text,\s*#3a2a18\)\)/)
  assert.match(source, /--snapshot-muted:\s*var\(--bench-text-secondary,\s*var\(--logbook-muted,\s*#8b6b4a\)\)/)
  assert.match(source, /--snapshot-accent:\s*var\(--bench-accent,\s*var\(--logbook-accent,\s*#8b5e34\)\)/)
  assert.match(source, /--snapshot-strong:\s*var\(--bench-accent-strong,\s*var\(--logbook-accent-strong,\s*#5a3319\)\)/)
  assert.match(source, /--snapshot-danger:\s*var\(--bench-danger,\s*var\(--logbook-danger,\s*#5a3319\)\)/)
  assert.doesNotMatch(source, /snapshot-green|snapshot-blue|snapshot-red|snapshot-amber/)
  assert.match(source, /\.snapshot-release-gate--ready/)
  assert.match(source, /\.snapshot-release-gate--blocked/)
  assert.doesNotMatch(source, /\.snapshot-gate-check\.blocked/)
})

test('BenchmarkSnapshotReleasePanel SFC compiles after release gate wiring', () => {
  const filename = new URL('../src/components/benchmark/BenchmarkSnapshotReleasePanel.vue', import.meta.url).pathname
  const source = snapshotReleaseSource()
  const { descriptor, errors } = parse(source, { filename })
  assert.deepEqual(errors, [])
  const script = compileScript(descriptor, { id: 'benchmark-snapshot-release-test' })
  assert.match(script.content, /releaseReadinessChecks/)
  assert.match(script.content, /selectedSnapshotEvidenceRows/)
  assert.doesNotMatch(script.content, /currentRowSourceAudit/)
  const template = compileTemplate({
    source: descriptor.template.content,
    filename,
    id: 'benchmark-snapshot-release-test'
  })
  assert.deepEqual(template.errors, [])
})

test('Workbench loads benchmark snapshot export artifacts with hashes', () => {
  const source = readSource('../src/composables/useEvaluationWorkbench.js')

  assert.match(source, /function normalizeBenchmarkSnapshotExport\(data\)/)
  assert.match(source, /data\.kind !== 'benchmark_leaderboard_snapshot_export'/)
  assert.match(source, /const benchmarkSnapshotExports = ref\(\{\}\)/)
  assert.match(source, /const snapshotExportRequests = createLatestOnlyMap\(\)/)
  assert.match(source, /function benchmarkSnapshotExportCacheKey\(snapshotId, format\)/)
  assert.match(source, /function benchmarkSnapshotExportPath\(snapshotId, format = 'json'\)/)
  assert.match(source, /async function loadBenchmarkSnapshotExport\(format = 'json', snapshotId = selectedBenchmarkSnapshotId\.value\)/)
  assert.match(source, /apiFetch\(benchmarkSnapshotExportPath\(id, normalized\)\)/)
  assert.match(source, /export_content_hash: String\(data\.export_content_hash \|\| data\.artifact_hash \|\| ''\)/)
  assert.match(source, /artifact_hash: String\(data\.artifact_hash \|\| data\.export_content_hash \|\| ''\)/)
  assert.match(source, /benchmarkSnapshotExports,/)
  assert.match(source, /loadBenchmarkSnapshotExport,/)
})
