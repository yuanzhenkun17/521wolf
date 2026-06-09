import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

const leaderboardPanel = readSource('../src/components/evolution/EvolutionLeaderboardPanel.vue')
const versionsPanel = readSource('../src/components/evolution/EvolutionVersionsPanel.vue')
const eventsPanel = readSource('../src/components/evolution/EvolutionEventsPanel.vue')

test('Evolution leaderboard shows self-evolution validation rows without formal benchmark chrome', () => {
  assert.match(leaderboardPanel, /<h2>验证榜单<\/h2>/)
  assert.match(leaderboardPanel, /aria-label="自进化验证摘要"/)
  assert.match(leaderboardPanel, /aria-label="自进化验证结果"/)
  assert.match(leaderboardPanel, /角色/)
  assert.match(leaderboardPanel, /基线/)
  assert.match(leaderboardPanel, /候选/)
  assert.match(leaderboardPanel, /推荐结论/)
  assert.match(leaderboardPanel, /胜率 \/ 得分/)
  assert.match(leaderboardPanel, /来源运行/)
  assert.match(leaderboardPanel, /#evolution\?run_id=/)
  assert.doesNotMatch(leaderboardPanel, /正式评测|benchmark|评测套件/)
})

test('Evolution versions exposes the release audit chain before strategy patterns', () => {
  assert.match(versionsPanel, /class="evo-version-release-chain" aria-label="版本发布审计链路"/)
  assert.match(versionsPanel, /<h3>发布链路<\/h3>/)
  assert.match(versionsPanel, /当前基线/)
  assert.match(versionsPanel, /候选版本/)
  assert.match(versionsPanel, /发布阶段/)
  assert.match(versionsPanel, /来源运行/)
  assert.match(versionsPanel, /门禁报告/)
  assert.match(versionsPanel, /信任包/)
  assert.match(versionsPanel, /包 Hash/)
  assert.match(versionsPanel, /回滚/)
  assert.match(versionsPanel, /#evolution\?run_id=/)
  assert.match(versionsPanel, /信任包审计/)
})

test('Evolution events workspace is a troubleshooting table with progress fields', () => {
  assert.match(eventsPanel, /class="evo-event-table" role="table" aria-label="运行事件排障"/)
  assert.match(eventsPanel, /事件类型/)
  assert.match(eventsPanel, /目标运行或批次/)
  assert.match(eventsPanel, /当前阶段/)
  assert.match(eventsPanel, /完成数/)
  assert.match(eventsPanel, /进度/)
  assert.match(eventsPanel, /摘要/)
  assert.match(eventsPanel, /function normalizeEventRow\(event\)/)
  assert.match(eventsPanel, /function eventCompletionLabel\(payload = \{\}\)/)
  assert.match(eventsPanel, /function eventProgressPercent\(payload = \{\}\)/)
})
