import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

function diagnosticsSource() {
  return readFileSync(new URL('../src/components/benchmark/BenchmarkDiagnosticsExplorer.vue', import.meta.url), 'utf8')
}

test('BenchmarkDiagnosticsExplorer localizes backend diagnostic keys for visible grouping', () => {
  const source = diagnosticsSource()

  assert.match(source, /const diagnosticKindLabels = \{/)
  assert.match(source, /rankable_failed:\s*'入榜失败'/)
  assert.match(source, /llm_error:\s*'LLM 错误'/)
  assert.match(source, /const diagnosticLevelLabels = \{/)
  assert.match(source, /info:\s*'信息'/)
  assert.match(source, /warning:\s*'警告'/)
  assert.match(source, /const byKind = countRows\(summary\.by_kind, diagnosticKindLabel\)/)
  assert.match(source, /const byOrigin = countRows\(summary\.by_origin, originLabel\)/)
  assert.match(source, /displayDiagnosticKind\(item\)/)
  assert.match(source, /displayDiagnosticLevel\(item\)/)
  assert.doesNotMatch(source, /item\.kindLabel \|\| item\.kind \|\| 'diagnostic'/)
  assert.doesNotMatch(source, /item\.levelLabel \|\| item\.level \|\| 'info'/)
})

test('BenchmarkDiagnosticsExplorer SFC compiles after diagnostic label mapping', () => {
  const filename = new URL('../src/components/benchmark/BenchmarkDiagnosticsExplorer.vue', import.meta.url).pathname
  const source = diagnosticsSource()
  const { descriptor, errors } = parse(source, { filename })
  assert.deepEqual(errors, [])
  const script = compileScript(descriptor, { id: 'benchmark-diagnostics-explorer-test' })
  assert.match(script.content, /diagnosticKindLabel/)
  const template = compileTemplate({
    source: descriptor.template.content,
    filename,
    id: 'benchmark-diagnostics-explorer-test'
  })
  assert.deepEqual(template.errors, [])
})
