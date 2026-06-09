import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

test('TopNav derives StreamStatusBadge from existing activeSession stream fields', () => {
  const source = readSource('../src/components/TopNav.vue')

  assert.match(source, /import \{ computed, onBeforeUnmount, ref, watch \} from 'vue'/)
  assert.match(source, /const streamStatusBadge = computed\(\(\) => \{/)
  assert.match(source, /const session = props\.activeSession \|\| \{\}/)
  assert.match(source, /session\.running/)
  assert.match(source, /session\.sseConnected/)
  assert.match(source, /session\.sse_connected/)
  assert.match(source, /session\.streamStatus/)
  assert.match(source, /session\.stream_status/)
  assert.match(source, /POLLING_STREAM_STATUSES/)
  assert.match(source, /RECONNECTING_STREAM_STATUSES/)
  assert.match(source, /running && !connected && !background/)
})

test('TopNav StreamStatusBadge exposes the required user-visible states', () => {
  const source = readSource('../src/components/TopNav.vue')

  for (const label of ['实时流', '重连中', '轮询降级', '后台运行', '已停止', '可查看']) {
    assert.match(source, new RegExp(`label = '${label}'`))
  }

  assert.match(source, /status = 'live'/)
  assert.match(source, /status = 'reconnecting'/)
  assert.match(source, /status = 'polling'/)
  assert.match(source, /status = 'background'/)
  assert.match(source, /status = 'stopped'/)
  assert.match(source, /最近恢复/)
})

test('TopNav stream badge has title and aria labels on the active session control', () => {
  const source = readSource('../src/components/TopNav.vue')

  assert.match(source, /class="active-session-pill"[\s\S]*:title="streamStatusBadge\.title"[\s\S]*:aria-label="streamStatusBadge\.ariaLabel"/)
  assert.match(source, /class="session-dot"[\s\S]*:data-stream-status="streamStatusBadge\.status"/)
  assert.match(source, /class="stream-status-badge"[\s\S]*:data-stream-status="streamStatusBadge\.status"[\s\S]*:title="streamStatusBadge\.title"[\s\S]*:aria-label="streamStatusBadge\.ariaLabel"/)
  assert.match(source, /\{\{ streamStatusBadge\.label \}\}/)
})

test('TopNav stream badge stays compact on narrow viewports', () => {
  const source = readSource('../src/components/TopNav.vue')

  assert.match(source, /\.stream-status-badge\s*\{[\s\S]*max-width:\s*100%[\s\S]*overflow:\s*hidden[\s\S]*text-overflow:\s*ellipsis[\s\S]*white-space:\s*nowrap/)
  assert.match(source, /\.session-dot\[data-stream-status="live"\]/)
  assert.match(source, /\.session-dot\[data-stream-status="reconnecting"\]/)
  assert.match(source, /\.session-dot\[data-stream-status="polling"\]/)
  assert.match(source, /@media \(max-width: 760px\)[\s\S]*\.active-session-pill\s*\{[\s\S]*min-width:\s*38px[\s\S]*width:\s*38px/)
  assert.match(source, /@media \(max-width: 760px\)[\s\S]*\.session-copy\s*\{[\s\S]*display:\s*none/)
})
