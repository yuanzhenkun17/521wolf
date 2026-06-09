import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

const shell = readSource('../src/components/evolution/EvolutionWorkbenchShell.vue')
const page = readSource('../src/pages/EvolutionPage.vue')
const workbench = readSource('../src/composables/useEvolutionWorkbench.js')

test('Evolution workbench shell exposes the persistent right context rail', () => {
  assert.match(shell, /runRows:\s*\{\s*type:\s*Array,\s*default:\s*\(\) => \[\]\s*\}/)
  assert.match(shell, /selectedRun:\s*\{\s*type:\s*Object,\s*default:\s*null\s*\}/)
  assert.match(shell, /selectedProposalReview:\s*\{\s*type:\s*Object,\s*default:\s*null\s*\}/)
  assert.match(shell, /selectedCanPromote:\s*\{\s*type:\s*Boolean,\s*default:\s*false\s*\}/)
  assert.match(shell, /selectedPromoteDisabledReason:\s*\{\s*type:\s*String,\s*default:\s*''\s*\}/)
  assert.match(shell, /selectedCanReject:\s*\{\s*type:\s*Boolean,\s*default:\s*false\s*\}/)
  assert.match(shell, /selectedRejectDisabledReason:\s*\{\s*type:\s*String,\s*default:\s*''\s*\}/)
  assert.match(shell, /selectedCanTerminate:\s*\{\s*type:\s*Boolean,\s*default:\s*false\s*\}/)
  assert.match(shell, /selectedTerminateDisabledReason:\s*\{\s*type:\s*String,\s*default:\s*''\s*\}/)
  assert.match(shell, /selectedRollbackDisabledReason:\s*\{\s*type:\s*String,\s*default:\s*''\s*\}/)

  assert.match(shell, /<aside class="evo-context-rail" aria-label="当前上下文" data-evolution-context-rail>/)
  assert.match(shell, /运行摘要/)
  assert.match(shell, /发布审计/)
  assert.match(shell, /高风险动作/)
  assert.match(shell, /诊断/)
  assert.match(shell, /const riskActionRows = computed\(\(\) => \[/)
  assert.match(shell, /label:\s*'晋升'/)
  assert.match(shell, /label:\s*'拒绝运行'/)
  assert.match(shell, /label:\s*'终止'/)
  assert.match(shell, /label:\s*'回滚'/)
  assert.match(shell, /const contextGateLabel = computed/)
  assert.match(shell, /const contextTrustLabel = computed/)
  assert.match(shell, /const contextEvidenceLabel = computed/)
})

test('EvolutionPage wires desktop context props without changing the seven work areas', () => {
  assert.match(page, /const navTabs = \[[\s\S]*key: 'console'[\s\S]*key: 'review'[\s\S]*key: 'runs'[\s\S]*key: 'leaderboard'[\s\S]*key: 'versions'[\s\S]*key: 'events'[\s\S]*key: 'samples'/)
  assert.doesNotMatch(page, /icon:\s*['"]/)
  assert.match(page, /const selectedCanReview = computed\(\(\) => evo\.selectedCanReject\.value\)/)
  assert.match(page, /const selectedCanTerminate = computed\(\(\) => evo\.selectedCanTerminate\.value\)/)
  assert.match(page, /:run-rows="evo\.runRows\.value"/)
  assert.match(page, /:selected-run="evo\.selectedRun\.value"/)
  assert.match(page, /:selected-proposal-review="evo\.selectedProposalReview\.value"/)
  assert.match(page, /:selected-can-promote="selectedCanPromote"/)
  assert.match(page, /:selected-reject-disabled-reason="evo\.selectedRejectDisabledReason\.value"/)
  assert.match(page, /:selected-terminate-disabled-reason="evo\.selectedTerminateDisabledReason\.value"/)
  assert.match(page, /:selected-rollback-disabled-reason="evo\.selectedRollbackDisabledReason\.value"/)
  assert.match(page, /grid-template-columns:\s*248px minmax\(0, 1fr\) 292px/)
  assert.match(page, /"rail command context"[\s\S]*"rail topbar context"[\s\S]*"rail pane context"/)
  assert.match(page, /\.evo-context-rail\s*\{[\s\S]*grid-area:\s*context[\s\S]*overflow:\s*hidden/)
})

test('Evolution composable exports high-risk action disabled reasons for visible UI', () => {
  assert.match(workbench, /selectedPromoteDisabledReason/)
  assert.match(workbench, /const selectedRejectDisabledReason = computed\(\(\) =>/)
  assert.match(workbench, /批量任务不能直接拒绝，请选择子运行。/)
  assert.match(workbench, /只有待评审运行可以拒绝。/)
  assert.match(workbench, /const selectedTerminateDisabledReason = computed\(\(\) =>/)
  assert.match(workbench, /运行已结束，不能终止。/)
  assert.match(workbench, /const selectedRollbackDisabledReason = computed\(\(\) =>/)
  assert.match(workbench, /selectedCanReject/)
  assert.match(workbench, /selectedCanTerminate/)
  assert.match(workbench, /selectedRollbackDisabledReason/)
  assert.match(workbench, /recommendationLabel/)
  assert.match(workbench, /trainingGameCompleted/)
  assert.match(workbench, /battleGameRequested/)
  assert.match(workbench, /diagnosticCount/)
})
