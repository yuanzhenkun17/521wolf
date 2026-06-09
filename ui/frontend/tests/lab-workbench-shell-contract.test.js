import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

test('LabWorkbenchShell exposes shared Lab boundary, tabs, action, and main pane semantics', () => {
  const shell = readSource('../src/components/lab/LabWorkbenchShell.vue')

  assert.match(shell, /workbenchKey:\s*\{\s*type:\s*String,\s*default:\s*'lab'\s*\}/)
  assert.match(shell, /tabs:\s*\{\s*type:\s*Array,\s*default:\s*\(\) => \[\]\s*\}/)
  assert.match(shell, /activeTab:\s*\{\s*type:\s*String,\s*default:\s*''\s*\}/)
  assert.match(shell, /contextLabel:\s*\{\s*type:\s*String,\s*default:\s*'Lab context panel'\s*\}/)
  assert.match(shell, /const emit = defineEmits\(\['update:activeTab', 'action'\]\)/)
  assert.match(shell, /const hasContext = computed\(\(\) => Boolean\(slots\.context\)\)/)
  assert.match(shell, /function selectTab\(tab\)[\s\S]*emit\('update:activeTab', tab\.key\)/)

  assert.match(shell, /class="lab-workbench-action-bar"[\s\S]*:aria-label="`\$\{title\} 操作区`"/)
  assert.match(shell, /class="lab-workbench-boundary-bar"[\s\S]*:aria-label="boundaryLabel"/)
  assert.match(shell, /class="lab-workbench-tabs"[\s\S]*data-lab-tabs/)
  assert.match(shell, /:aria-current="activeTab === tab\.key \? 'page' : undefined"/)
  assert.match(shell, /class="lab-workbench-main-pane"[\s\S]*:aria-label="mainLabel \|\| `\$\{activeTabLabel\} 主面板`"/)
  assert.match(shell, /<aside v-if="hasContext" class="lab-workbench-context" :aria-label="contextLabel">[\s\S]*<slot name="context" \/>[\s\S]*<\/aside>/)
  assert.match(shell, /class="lab-workbench-action-area"[\s\S]*class="lab-workbench-primary-action"[\s\S]*@click="emit\('action'\)"/)
})

test('LabWorkbenchShell keeps dense Lab layout mobile-safe', () => {
  const shell = readSource('../src/components/lab/LabWorkbenchShell.vue')

  assert.match(shell, /\.lab-workbench-bridge\s*\{[\s\S]*display:\s*contents/)
  assert.match(shell, /\.lab-workbench-shell\s*\{[\s\S]*grid-template-columns:\s*var\(--lab-rail-width,\s*316px\) minmax\(0, 1fr\)[\s\S]*overflow:\s*hidden/)
  assert.match(shell, /\.lab-workbench-shell--has-context\s*\{[\s\S]*grid-template-columns:[\s\S]*var\(--lab-rail-width,\s*316px\)[\s\S]*minmax\(0, 1fr\)[\s\S]*var\(--lab-context-width,\s*320px\)/)
  assert.match(shell, /\.lab-workbench-context\s*\{[\s\S]*overflow:\s*hidden/)
  assert.match(shell, /\.lab-workbench-main\s*\{[\s\S]*grid-template-rows:\s*auto auto auto auto minmax\(0, 1fr\)[\s\S]*overflow:\s*hidden/)
  assert.match(shell, /\.lab-workbench-tabs\s*\{[\s\S]*overflow-x:\s*auto/)
  assert.match(shell, /\.lab-workbench-tab span\s*\{[\s\S]*text-overflow:\s*ellipsis[\s\S]*white-space:\s*nowrap/)
  assert.match(shell, /\.lab-workbench-main-pane\s*\{[\s\S]*min-width:\s*0[\s\S]*min-height:\s*0[\s\S]*overflow:\s*hidden/)
  assert.match(shell, /@media \(max-width: 960px\)[\s\S]*\.lab-workbench-shell\s*\{[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)[\s\S]*overflow-x:\s*hidden/)
  assert.match(shell, /@media \(max-width: 640px\)[\s\S]*\.lab-workbench-tabs\s*\{[\s\S]*grid-template-columns:\s*repeat\(auto-fit, minmax\(58px, 1fr\)\)/)
})

test('BenchmarkPage is wired to the shared Lab shell without changing benchmark business panels', () => {
  const benchmark = readSource('../src/pages/BenchmarkPage.vue')

  assert.match(benchmark, /import LabWorkbenchShell from '\.\.\/components\/lab\/LabWorkbenchShell\.vue'/)
  assert.match(benchmark, /const labHeaderMeta = computed\(\(\) => \[[\s\S]*key: 'mode'[\s\S]*key: 'suite'[\s\S]*key: 'budget'/)
  assert.match(benchmark, /<LabWorkbenchShell[\s\S]*v-model:active-tab="activeView"[\s\S]*workbench-key="benchmark"[\s\S]*:tabs="navTabs"[\s\S]*:meta="labHeaderMeta"[\s\S]*@action="refresh"/)
  assert.match(benchmark, /<template #rail>[\s\S]*<BenchmarkSuiteRail :benchmark="benchmark" \/>[\s\S]*<\/template>/)
  assert.match(benchmark, /<template #boundary>[\s\S]*<BenchmarkBoundaryBar :benchmark="benchmark" \/>[\s\S]*selectedBenchmarkUsingLegacyRuns/)
  assert.match(benchmark, /<template #notice>[\s\S]*<ApiErrorPanel[\s\S]*@retry="refresh"[\s\S]*<\/template>/)
  assert.match(benchmark, /<template #context>[\s\S]*class="bench-context-panel"[\s\S]*当前套件[\s\S]*运行上下文[\s\S]*诊断概览[\s\S]*审计边界[\s\S]*发布材料[\s\S]*<\/template>/)
  assert.match(benchmark, /<BenchmarkComparisonView[\s\S]*activeView === 'leaderboards'/)
  assert.match(benchmark, /<BenchmarkBatchRunsTable[\s\S]*activeView === 'runs'/)
  assert.match(benchmark, /<BenchmarkDiagnosticsExplorer[\s\S]*activeView === 'diagnostics'/)
  assert.match(benchmark, /<BenchmarkSnapshotReleasePanel :benchmark="benchmark" \/>[\s\S]*<BenchmarkRunReportPanel :benchmark="benchmark" \/>/)
})

test('EvolutionPage has a low-risk LabWorkbenchShell bridge around the existing evolution shell', () => {
  const evolution = readSource('../src/pages/EvolutionPage.vue')

  assert.match(evolution, /import LabWorkbenchShell from '\.\.\/components\/lab\/LabWorkbenchShell\.vue'/)
  assert.match(evolution, /<LabWorkbenchShell[\s\S]*v-model:active-tab="activeTab"[\s\S]*bridge[\s\S]*class="evo-lab-workbench-bridge"[\s\S]*workbench-key="evolution"[\s\S]*:tabs="navTabs"/)
  assert.match(evolution, /<LabWorkbenchShell[\s\S]*<EvolutionWorkbenchShell[\s\S]*v-model:active-tab="activeTab"[\s\S]*@select-role="evo\.selectRole"[\s\S]*<\/EvolutionWorkbenchShell>[\s\S]*<\/LabWorkbenchShell>/)
  assert.match(evolution, /<EvolutionProposalReviewPanel v-if="activeTab === 'review'" :evo="evo" \/>/)
})
