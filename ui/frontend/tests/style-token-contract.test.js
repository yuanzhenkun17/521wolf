import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'vitest'

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

function assertOrder(source, earlier, later) {
  const earlierIndex = source.indexOf(earlier)
  const laterIndex = source.indexOf(later)

  assert.notEqual(earlierIndex, -1, `Missing import: ${earlier}`)
  assert.notEqual(laterIndex, -1, `Missing import: ${later}`)
  assert.ok(earlierIndex < laterIndex, `${earlier} must be loaded before ${later}`)
}

function cssBlock(source, selector) {
  const index = source.indexOf(selector)
  assert.notEqual(index, -1, `Missing CSS selector: ${selector}`)
  const start = source.indexOf('{', index)
  let depth = 0

  for (let i = start; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1
    if (source[i] === '}') {
      depth -= 1
      if (depth === 0) return source.slice(start + 1, i)
    }
  }

  throw new Error(`Unclosed CSS selector: ${selector}`)
}

test('Global styles load foundation tokens before legacy and workbench aliases', () => {
  const source = readSource('../src/style.css')

  assertOrder(source, '@import "./styles/foundation/index.css";', '@import "./styles/base.css";')
  assertOrder(source, '@import "./styles/base.css";', '@import "./styles/workbenches.css";')
  assertOrder(source, '@import "./styles/workbenches.css";', '@import "./styles/cascade-overrides.css";')
})

test('Foundation tokens keep semantic aliases for legacy root variables', () => {
  const tokens = readSource('../src/styles/foundation/tokens.css')
  const motion = readSource('../src/styles/foundation/motion.css')
  const zIndex = readSource('../src/styles/foundation/z-index.css')

  assert.match(tokens, /--color-bg-app:\s*var\(--bg,\s*#16130b\)/)
  assert.match(tokens, /--color-text-primary:\s*var\(--text,\s*#eae1d4\)/)
  assert.match(tokens, /--color-border-default:\s*var\(--outline,\s*rgba\(242, 202, 80, 0\.16\)\)/)
  assert.match(tokens, /--shadow-panel:\s*0 8px 32px rgba\(0, 0, 0, 0\.55\)/)
  assert.match(tokens, /--layout-side-panel-width:\s*var\(--panel-width,\s*320px\)/)

  assert.match(motion, /--duration-scene:\s*1100ms/)
  assert.match(motion, /--ease-emphasized:\s*cubic-bezier\(0\.22, 1, 0\.36, 1\)/)

  assert.match(zIndex, /--z-background:\s*0/)
  assert.match(zIndex, /--z-base:\s*1/)
  assert.match(zIndex, /--z-topbar:\s*50/)
})

test('Base shell consumes foundation tokens for stable non-layout primitives', () => {
  const source = readSource('../src/styles/part-01.css')
  const lycanApp = cssBlock(source, '.lycan-app {')
  const atmosphere = cssBlock(source, '.atmosphere {')
  const noise = cssBlock(source, '.noise {')
  const glass = cssBlock(source, '.glass {')
  const topbar = cssBlock(source, '.topbar {')

  assert.match(source, /html,\s*body\s*\{[\s\S]*background:\s*var\(--color-bg-app\)/)
  assert.match(source, /html,\s*body\s*\{[\s\S]*color:\s*var\(--color-text-primary\)/)
  assert.match(lycanApp, /background:\s*var\(--color-bg-app\)/)
  assert.match(lycanApp, /color:\s*var\(--color-text-primary\)/)
  assert.match(atmosphere, /z-index:\s*var\(--z-background\)/)
  assert.match(atmosphere, /transition:\s*background var\(--duration-scene\) var\(--ease-emphasized\)/)
  assert.match(noise, /z-index:\s*var\(--z-base\)/)
  assert.match(glass, /box-shadow:\s*var\(--shadow-panel\)/)
  assert.match(topbar, /z-index:\s*var\(--z-topbar\)/)
  assert.doesNotMatch(lycanApp, /background:\s*#16130b/)
  assert.doesNotMatch(glass, /box-shadow:\s*0 8px 32px rgba\(0, 0, 0, 0\.55\)/)
})
