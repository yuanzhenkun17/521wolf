import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'vitest'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

test('TasksPage is rebuilt on the self-evolution logbook layout instead of the old Lab shell', () => {
  const source = readSource('../src/pages/TasksPage.vue')

  assert.doesNotMatch(source, /import LabWorkbenchShell/)
  assert.doesNotMatch(source, /<LabWorkbenchShell/)
  assert.match(source, /class="tasks-shell parchment-logbook"/)
  assert.match(source, /class="tasks-command-bar"/)
  assert.doesNotMatch(source, /class="tasks-detail-topbar"/)
  assert.doesNotMatch(source, /detail-workspace-tabs/)
  assert.match(source, /class="tasks-control-rail"/)
  assert.match(source, /class="tasks-main-pane"/)
  assert.match(source, /class="tasks-context-rail"[\s\S]*data-tasks-context-rail/)
  assert.match(source, /grid-template-areas:[\s\S]*"rail command context"[\s\S]*"rail pane context"/)
  assert.match(source, /@media \(min-width: 961px\)[\s\S]*\.tasks-shell,[\s\S]*\.tasks-shell\.parchment-logbook\s*\{[\s\S]*grid-template-columns:\s*252px minmax\(0, 1fr\) 300px/)
})

test('TasksPage keeps the event timeline inline and collapsed by default', () => {
  const source = readSource('../src/pages/TasksPage.vue')

  assert.match(source, /const eventsExpanded = ref\(false\)/)
  assert.match(source, /class="task-events-toggle"[\s\S]*:aria-expanded="eventsExpanded"/)
  assert.match(source, /v-show="eventsExpanded"[\s\S]*id="task-events-content"/)
  assert.match(source, /\.task-events-panel\.expanded/)
  assert.match(source, /\.task-events-panel\s*\{[\s\S]*overflow:\s*hidden;[\s\S]*var\(--tasks-panel-solid\)/)
  assert.match(source, /\.task-events-content\s*\{[\s\S]*max-height:\s*clamp\(220px,\s*42vh,\s*430px\);[\s\S]*overflow-y:\s*auto;/)
  assert.match(source, /@media \(max-width: 960px\)[\s\S]*\.task-events-content\s*\{[\s\S]*max-height:\s*none;[\s\S]*overflow:\s*visible;/)
  assert.doesNotMatch(source, /activeWorkspace|selectWorkspace|queueSectionRef|eventsSectionRef/)
})

test('TasksPage shares the self-evolution parchment palette and context treatment', () => {
  const source = readSource('../src/pages/TasksPage.vue')

  assert.match(source, /--logbook-bg:\s*#f2dfae/)
  assert.match(source, /--evo-bg:\s*var\(--logbook-bg\)/)
  assert.match(source, /--tasks-bg-texture:\s*var\(--evo-bg-texture\)/)
  assert.match(source, /\.tasks-shell\.parchment-logbook\s*\{[\s\S]*background:\s*var\(--tasks-bg-texture\)/)
  assert.match(source, /\.tasks-context-head,[\s\S]*\.tasks-context-section,[\s\S]*\.tasks-context-scroll :deep\(\.task-artifact-panel\)[\s\S]*border-radius:\s*0/)
  assert.match(source, /<TaskArtifactPanel[\s\S]*:task-id="selectedTaskId"[\s\S]*class="tasks-artifact-panel"[\s\S]*show-actions/)
})
