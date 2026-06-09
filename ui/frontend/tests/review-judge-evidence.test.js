import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'vitest'

function reviewSource() {
  return readFileSync(new URL('../src/components/history/ReviewReportPanel.vue', import.meta.url), 'utf8')
}

function judgeEvidenceSource() {
  return readFileSync(new URL('../src/components/history/JudgeEvidencePanel.vue', import.meta.url), 'utf8')
}

test('ReviewReportPanel delegates per-judgment evidence rendering to JudgeEvidencePanel', () => {
  const source = reviewSource()

  assert.match(source, /import JudgeEvidencePanel from '\.\/JudgeEvidencePanel\.vue'/)
  assert.match(source, /const decisionJudgeCards = computed/)
  assert.match(source, /evidence: buildJudgeEvidenceDetails\(item\)/)
  assert.match(source, /v-for="row in decisionJudgeCards"/)
  assert.match(source, /<JudgeEvidencePanel :evidence="row\.evidence" :row-key="row\.key" :format-json="formatJson" \/>/)
})

test('JudgeEvidencePanel renders decision judge evidence as per-judgment details', () => {
  const source = judgeEvidenceSource()

  assert.match(source, /const props = defineProps\(\{[\s\S]*evidence: \{ type: Object, default: null \}[\s\S]*rowKey: \{ type: \[String, Number\], default: '' \}[\s\S]*formatJson: \{ type: Function, default: null \}/)
  assert.match(source, /const evidenceGroups = computed/)
  assert.match(source, /const hasEvidence = computed\(\(\) => evidenceTotal\.value > 0\)/)
  assert.match(source, /<details v-if="hasEvidence" class="review-judge-evidence">/)
  assert.match(source, /<summary>[\s\S]*证据展开[\s\S]*evidenceTotal[\s\S]*<\/summary>/)
})

test('JudgeEvidencePanel only renders populated judge evidence blocks', () => {
  const source = judgeEvidenceSource()

  assert.match(source, /v-if="evidenceGroups\.evidenceRefs\.length"[\s\S]*证据引用/)
  assert.match(source, /v-if="evidenceGroups\.counterfactuals\.length"[\s\S]*反事实/)
  assert.match(source, /v-if="evidenceGroups\.rubricMisses\.length"[\s\S]*评分规则未命中/)
  assert.match(source, /v-if="evidenceGroups\.degradedReasons\.length"[\s\S]*降级\/失败原因/)
  assert.match(source, /v-if="evidenceGroups\.warnings\.length"[\s\S]*警告/)
  assert.match(source, /v-if="evidenceGroups\.diagnostics\.length"[\s\S]*诊断/)
  assert.match(reviewSource(), /details\.hasAny = details\.total > 0/)
})

test('ReviewReportPanel scopes report-level judge diagnostics and warnings by decision id', () => {
  const source = reviewSource()

  assert.match(source, /function rowMatchesDecision\(row, item\)/)
  assert.match(source, /const id = judgeDecisionId\(item\)/)
  assert.match(source, /String\(rowId\) === id/)
  assert.match(source, /String\(value\)\.includes\(id\)/)
  assert.match(source, /function decisionJudgeScopedRows\(field, item\)/)
  assert.match(source, /valueRows\(decisionJudgeData\.value\?\.\[field\]\)[\s\S]*\.filter\(\(row\) => rowMatchesDecision\(row, item\)\)/)
  assert.match(source, /decisionJudgeScopedRows\('degraded_reasons', item\)/)
  assert.match(source, /diagnostics\.map\(diagnosticReason\)\.filter\(Boolean\)/)
})

test('ReviewReportPanel judge evidence styles are dense and mobile-safe', () => {
  const source = judgeEvidenceSource()

  assert.match(source, /\.review-judge-evidence\s*\{[\s\S]*min-width:\s*0/)
  assert.match(source, /\.review-judge-evidence-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)[\s\S]*min-width:\s*0/)
  assert.match(source, /\.review-judge-evidence-block\s*\{[\s\S]*min-width:\s*0/)
  assert.match(source, /\.review-judge-evidence-block p,[\s\S]*\.review-judge-evidence-list li\s*\{[\s\S]*overflow-wrap:\s*anywhere/)
  assert.match(source, /@media \(max-width: 720px\)[\s\S]*\.review-judge-evidence-grid\s*\{[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/)
  assert.doesNotMatch(reviewSource(), /\.review-judge-evidence-grid\s*\{/)
})
