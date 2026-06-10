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

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function customPropertyValue(source, propertyName) {
  const match = source.match(new RegExp(`${escapeRegExp(propertyName)}\\s*:\\s*([^;]+);`))
  assert.ok(match, `Missing CSS custom property: ${propertyName}`)
  return match[1].trim()
}

function numericCustomProperty(source, propertyName) {
  const value = Number(customPropertyValue(source, propertyName))
  assert.ok(Number.isFinite(value), `${propertyName} must be numeric`)
  return value
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
  assert.equal(customPropertyValue(tokens, '--color-accent-primary-soft'), 'rgba(242, 202, 80, 0.16)')
  assert.equal(customPropertyValue(tokens, '--color-status-danger-strong'), '#993026')
  assert.equal(customPropertyValue(tokens, '--color-status-warning-strong'), '#76510e')
  assert.equal(customPropertyValue(tokens, '--color-status-warning-muted'), '#8b5e34')
  assert.equal(customPropertyValue(tokens, '--color-status-success'), '#8dffac')
  assert.equal(customPropertyValue(tokens, '--color-status-info'), 'var(--blue, #bfcdff)')
  assert.match(tokens, /--shadow-panel:\s*0 8px 32px rgba\(0, 0, 0, 0\.55\)/)
  assert.match(tokens, /--layout-side-panel-width:\s*var\(--panel-width,\s*320px\)/)

  assert.match(motion, /--duration-scene:\s*1100ms/)
  assert.match(motion, /--ease-emphasized:\s*cubic-bezier\(0\.22, 1, 0\.36, 1\)/)
  assert.equal(customPropertyValue(motion, '--duration-atmosphere'), 'var(--duration-scene)')
  assert.equal(customPropertyValue(motion, '--ease-atmosphere'), 'var(--ease-emphasized)')

  assert.match(zIndex, /--z-underlay-deep:\s*-2/)
  assert.match(zIndex, /--z-underlay:\s*-1/)
  assert.match(zIndex, /--z-background:\s*0/)
  assert.match(zIndex, /--z-base:\s*1/)
  assert.match(zIndex, /--z-raised:\s*2/)
  assert.match(zIndex, /--z-topbar:\s*50/)
})

test('Foundation z-index and motion contracts stay ordered and reduced-motion safe', () => {
  const motion = readSource('../src/styles/foundation/motion.css')
  const zIndex = readSource('../src/styles/foundation/z-index.css')
  const reducedMotion = cssBlock(motion, '@media (prefers-reduced-motion: reduce) {')
  const zScale = [
    '--z-underlay-deep',
    '--z-underlay',
    '--z-background',
    '--z-base',
    '--z-raised',
    '--z-scene',
    '--z-scene-overlay',
    '--z-panel',
    '--z-panel-raised',
    '--z-hud',
    '--z-topbar',
    '--z-dropdown',
    '--z-overlay',
    '--z-toast',
    '--z-modal',
    '--z-debug',
  ]

  for (let index = 1; index < zScale.length; index += 1) {
    const previous = numericCustomProperty(zIndex, zScale[index - 1])
    const current = numericCustomProperty(zIndex, zScale[index])
    assert.ok(previous < current, `${zScale[index - 1]} must be lower than ${zScale[index]}`)
  }

  for (const duration of ['--duration-fast', '--duration-standard', '--duration-slow', '--duration-scene']) {
    assert.equal(customPropertyValue(reducedMotion, duration), '0ms')
  }
})

test('Workbench semantic aliases consume foundation status tokens', () => {
  const source = readSource('../src/styles/workbenches.css')
  const statusBridge = [
    '--workbench-logbook-danger',
    '--workbench-logbook-warning',
    '--workbench-logbook-warning-benchmark',
  ]
    .map((propertyName) => `${propertyName}: ${customPropertyValue(source, propertyName)};`)
    .join('\n')

  assert.equal(customPropertyValue(source, '--workbench-logbook-danger'), 'var(--color-status-danger-strong)')
  assert.equal(customPropertyValue(source, '--workbench-logbook-warning'), 'var(--color-status-warning-strong)')
  assert.equal(customPropertyValue(source, '--workbench-logbook-warning-benchmark'), 'var(--color-status-warning-muted)')
  assert.equal(customPropertyValue(source, '--logbook-danger'), 'var(--workbench-logbook-danger)')
  assert.equal(customPropertyValue(source, '--logbook-warning'), 'var(--workbench-logbook-warning)')
  assert.equal(customPropertyValue(source, '--logbook-warning-benchmark'), 'var(--workbench-logbook-warning-benchmark)')
  assert.doesNotMatch(statusBridge, /#[0-9a-fA-F]{3,8}/)
})

test('Base shell consumes foundation tokens for stable non-layout primitives', () => {
  const source = readSource('../src/styles/base.css')
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
  assert.match(atmosphere, /transition:\s*background var\(--duration-atmosphere\) var\(--ease-atmosphere\)/)
  assert.match(noise, /z-index:\s*var\(--z-base\)/)
  assert.match(glass, /box-shadow:\s*var\(--shadow-panel\)/)
  assert.match(topbar, /z-index:\s*var\(--z-topbar\)/)
  assert.doesNotMatch(lycanApp, /background:\s*#16130b/)
  assert.doesNotMatch(glass, /box-shadow:\s*0 8px 32px rgba\(0, 0, 0, 0\.55\)/)
})
