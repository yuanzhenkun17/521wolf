import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

const samplesPanel = readSource('../src/components/evolution/EvolutionSamplesPanel.vue')
const workbench = readSource('../src/composables/useEvolutionWorkbench.ts')

test('Evolution samples workspace keeps the three review-evidence buckets', () => {
  assert.match(workbench, /const SAMPLE_GAME_BUCKETS = \['training', 'baseline', 'candidate'\]/)
  assert.match(samplesPanel, /v-for="bucket in evo\.sampleBuckets\.value"/)
  assert.match(samplesPanel, /@click="evo\.selectSampleGame\(bucket\.key\)"/)
  assert.match(samplesPanel, /@click="evo\.selectSampleGame\(game\.bucket, game\.id\)"/)
})

test('Evolution sample detail exposes evidence traceability fields and existing actions', () => {
  for (const required of [
    '证据追溯',
    '历史 ID',
    '样本 ID',
    '阶段',
    '样本桶',
    '胜方',
    '天数',
    '种子',
    '事件数',
    '决策数',
    '打开日志',
    '回放样本局'
  ]) {
    assert.match(samplesPanel, new RegExp(required))
  }

  assert.match(samplesPanel, /data-evolution-sample-evidence-trace/)
  assert.match(samplesPanel, /const emit = defineEmits\(\['open-sample-log', 'replay-sample-game'\]\)/)
  assert.match(samplesPanel, /emit\('open-sample-log', historyId\)/)
  assert.match(samplesPanel, /emit\('replay-sample-game', historyId\)/)
  assert.match(samplesPanel, /:disabled="Boolean\(evo\.selectedSampleHistoryUnavailableReason\.value\)"/)
})

test('Evolution sample decision and event previews stay compact and point overflow to logs', () => {
  assert.match(samplesPanel, /const DECISION_PREVIEW_LIMIT = 8/)
  assert.match(samplesPanel, /const EVENT_PREVIEW_LIMIT = 10/)
  assert.match(samplesPanel, /data-evolution-sample-compact-evidence/)
  assert.match(samplesPanel, /决策预览/)
  assert.match(samplesPanel, /事件预览/)
  assert.match(samplesPanel, /detailDecisions\(evo\)\.slice\(0, DECISION_PREVIEW_LIMIT\)/)
  assert.match(samplesPanel, /detailEvents\(evo\)\.slice\(0, EVENT_PREVIEW_LIMIT\)/)
  assert.match(samplesPanel, /还有 \{\{ decisionOverflowCount\(evo\) \}\} 条决策未显示，请打开日志查看完整记录。/)
  assert.match(samplesPanel, /还有 \{\{ eventOverflowCount\(evo\) \}\} 条事件未显示，请打开日志查看完整记录。/)
})
