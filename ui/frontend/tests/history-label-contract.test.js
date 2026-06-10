import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { test } from 'vitest'
import { fileURLToPath } from 'node:url'

const frontendRoot = path.resolve(fileURLToPath(new URL('..', import.meta.url)))

function source(relativePath) {
  return readFileSync(path.join(frontendRoot, relativePath), 'utf8')
}

test('history replay action is labeled as playback instead of review', () => {
  const historyListSource = source('src/components/HistoryGameList.vue')
  const replayButtonMatch = historyListSource.match(/<button[^>]*class="history-game-replay"[\s\S]*?<\/button>/)

  assert.ok(replayButtonMatch, 'History replay button should exist')

  const replayButtonSource = replayButtonMatch[0]
  assert.match(replayButtonSource, /title="事件回放"/)
  assert.match(replayButtonSource, /aria-label="事件回放"/)
  assert.match(replayButtonSource, />回放<\/button>/)
  assert.doesNotMatch(replayButtonSource, />复盘<\/button>/)
})

test('history review and archive workspace tabs expose lazy load state badges', () => {
  const logsPageSource = source('src/pages/LogsPage.vue')

  assert.match(logsPageSource, /function asyncTabState\(\{ loading = false, loaded = false, error = false, missing = false \} = \{\}\)/)
  assert.match(logsPageSource, /if \(loading\) return \{ state: 'loading', badge: '读取中' \}/)
  assert.match(logsPageSource, /if \(error\) return \{ state: 'error', badge: '错误' \}/)
  assert.match(logsPageSource, /if \(missing\) return \{ state: 'missing', badge: '缺失' \}/)
  assert.match(logsPageSource, /if \(loaded\) return \{ state: 'loaded', badge: '已载入' \}/)
  assert.match(logsPageSource, /return \{ state: 'idle', badge: '未载入' \}/)
  assert.match(logsPageSource, /const reviewTabState = computed\(\(\) => asyncTabState\(\{[\s\S]*loading: reviewLoading\.value[\s\S]*loaded: reviewLoaded\.value[\s\S]*error: Boolean\(selectedReview\.value\?\.error\)/)
  assert.match(logsPageSource, /const archiveTabState = computed\(\(\) => asyncTabState\(\{[\s\S]*loading: archiveLoading\.value[\s\S]*loaded: archiveLoaded\.value[\s\S]*error: Boolean\(selectedArchive\.value\?\.error\)/)
  assert.match(logsPageSource, /<small[\s\S]*class="detail-workspace-badge"[\s\S]*:data-state="item\.state"[\s\S]*\{\{ item\.badge \}\}/)
  assert.match(logsPageSource, /\.detail-workspace-badge\[data-state="idle"\]/)
  assert.match(logsPageSource, /\.detail-workspace-badge\[data-state="loading"\]/)
  assert.match(logsPageSource, /\.detail-workspace-badge\[data-state="loaded"\]/)
  assert.match(logsPageSource, /\.detail-workspace-badge\[data-state="error"\]/)
})
