import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { mkdtemp, rm } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { inflateSync } from 'node:zlib'
import { chromium } from 'playwright'

const frontendRoot = path.resolve(fileURLToPath(new URL('..', import.meta.url)))
const repoRoot = path.resolve(frontendRoot, '../..')
const matchPageSourceUrl = new URL('../src/pages/MatchPage.vue', import.meta.url)
const mobileTaskShellSourceUrl = new URL('../src/components/MobileTaskShell.vue', import.meta.url)
const apiErrorPanelSourceUrl = new URL('../src/components/ApiErrorPanel.vue', import.meta.url)
const trustBundleDrawerSourceUrl = new URL('../src/components/evolution/TrustBundleDrawer.vue', import.meta.url)
const evolutionConsolePanelSourceUrl = new URL('../src/components/evolution/EvolutionConsolePanel.vue', import.meta.url)
const evolutionProposalReviewPanelSourceUrl = new URL('../src/components/evolution/EvolutionProposalReviewPanel.vue', import.meta.url)
const evolutionWorkbenchSourceUrl = new URL('../src/composables/useEvolutionWorkbench.js', import.meta.url)
const reviewReportPanelSourceUrl = new URL('../src/components/history/ReviewReportPanel.vue', import.meta.url)
const logsPageSourceUrl = new URL('../src/pages/LogsPage.vue', import.meta.url)

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = createServer()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      server.close(() => resolve(address.port))
    })
  })
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function fetchWithTimeout(url, timeoutMs = 1000) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  return fetch(url, { signal: controller.signal }).finally(() => clearTimeout(timeout))
}

async function waitForHttp(url, { label, timeoutMs = 30000 } = {}) {
  const deadline = Date.now() + timeoutMs
  let lastError = null
  while (Date.now() < deadline) {
    try {
      const response = await fetchWithTimeout(url)
      if (response.ok) return response
      lastError = new Error(`HTTP ${response.status}`)
    } catch (err) {
      lastError = err
    }
    await delay(250)
  }
  throw new Error(`${label || url} was not ready: ${lastError?.message || 'timeout'}`)
}

function startService(name, command, args, options = {}) {
  const output = []
  const child = spawn(command, args, {
    ...options,
    env: { ...process.env, ...(options.env || {}) },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  })

  const record = (stream, chunk) => {
    const text = chunk.toString()
    output.push(`[${stream}] ${text}`)
    if (output.length > 80) output.splice(0, output.length - 80)
  }
  child.stdout.on('data', (chunk) => record('stdout', chunk))
  child.stderr.on('data', (chunk) => record('stderr', chunk))
  child.on('error', (err) => record('error', String(err?.message || err)))

  return {
    name,
    child,
    tail() {
      return output.join('').trim()
    },
  }
}

async function stopService(service) {
  if (!service?.child || service.child.exitCode !== null || service.child.killed) return
  const child = service.child
  const exited = new Promise((resolve) => child.once('exit', resolve))

  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
  } else {
    child.kill('SIGTERM')
  }

  await Promise.race([exited, delay(3000)])
  if (child.exitCode === null && !child.killed) {
    child.kill('SIGKILL')
    await Promise.race([exited, delay(1000)])
  }
}

function chromiumIsInstalled() {
  try {
    return existsSync(chromium.executablePath())
  } catch {
    return false
  }
}

function readSource(url) {
  return readFileSync(url, 'utf8')
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function firstCssBlock(source, selector) {
  const match = source.match(new RegExp(`${escapeRegExp(selector)}\\s*\\{([\\s\\S]*?)\\n\\}`, 'm'))
  assert.ok(match, `${selector} CSS block should exist`)
  return match[1]
}

function serviceLogs(backend, frontend) {
  return [
    backend ? `\n--- ${backend.name} log ---\n${backend.tail() || '(empty)'}` : '',
    frontend ? `\n--- ${frontend.name} log ---\n${frontend.tail() || '(empty)'}` : '',
  ].join('')
}

function parsePngPixelStats(buffer) {
  const signature = '89504e470d0a1a0a'
  assert.equal(buffer.subarray(0, 8).toString('hex'), signature)

  let offset = 8
  let width = 0
  let height = 0
  let bitDepth = 0
  let colorType = 0
  const idat = []

  while (offset < buffer.length) {
    const length = buffer.readUInt32BE(offset)
    const type = buffer.subarray(offset + 4, offset + 8).toString('ascii')
    const data = buffer.subarray(offset + 8, offset + 8 + length)
    offset += 12 + length

    if (type === 'IHDR') {
      width = data.readUInt32BE(0)
      height = data.readUInt32BE(4)
      bitDepth = data[8]
      colorType = data[9]
      const interlace = data[12]
      assert.equal(bitDepth, 8)
      assert.equal(interlace, 0)
      assert.ok(colorType === 2 || colorType === 6)
    } else if (type === 'IDAT') {
      idat.push(data)
    } else if (type === 'IEND') {
      break
    }
  }

  const channels = colorType === 6 ? 4 : 3
  const rowLength = width * channels
  const raw = inflateSync(Buffer.concat(idat))
  const previous = Buffer.alloc(rowLength)
  const current = Buffer.alloc(rowLength)
  let rawOffset = 0
  let litSamples = 0
  let maxChannel = 0
  const colorBuckets = new Set()
  const sampleEvery = Math.max(1, Math.floor((width * height) / 800))
  let pixelIndex = 0

  for (let y = 0; y < height; y += 1) {
    const filter = raw[rawOffset]
    rawOffset += 1
    raw.copy(current, 0, rawOffset, rawOffset + rowLength)
    rawOffset += rowLength

    for (let x = 0; x < rowLength; x += 1) {
      const left = x >= channels ? current[x - channels] : 0
      const up = previous[x]
      const upLeft = x >= channels ? previous[x - channels] : 0
      if (filter === 1) current[x] = (current[x] + left) & 0xff
      else if (filter === 2) current[x] = (current[x] + up) & 0xff
      else if (filter === 3) current[x] = (current[x] + Math.floor((left + up) / 2)) & 0xff
      else if (filter === 4) {
        const p = left + up - upLeft
        const pa = Math.abs(p - left)
        const pb = Math.abs(p - up)
        const pc = Math.abs(p - upLeft)
        current[x] = (current[x] + (pa <= pb && pa <= pc ? left : (pb <= pc ? up : upLeft))) & 0xff
      } else {
        assert.equal(filter, 0)
      }
    }

    for (let x = 0; x < width; x += 1) {
      if (pixelIndex % sampleEvery === 0) {
        const base = x * channels
        const red = current[base]
        const green = current[base + 1]
        const blue = current[base + 2]
        const alpha = channels === 4 ? current[base + 3] : 255
        maxChannel = Math.max(maxChannel, red, green, blue)
        if (alpha > 0 && red + green + blue > 24) litSamples += 1
        colorBuckets.add(`${red >> 4}:${green >> 4}:${blue >> 4}:${alpha >> 4}`)
      }
      pixelIndex += 1
    }

    previous.set(current)
  }

  return { width, height, litSamples, maxChannel, distinctColorBuckets: colorBuckets.size }
}

async function waitForNonEmptyCanvas(page, selector, { timeoutMs = 20000 } = {}) {
  const deadline = Date.now() + timeoutMs
  let lastProbe = null
  const canvas = page.locator(selector)

  while (Date.now() < deadline) {
    const box = await canvas.boundingBox().catch(() => null)
    if (!box || box.width < 32 || box.height < 32) {
      lastProbe = { nonEmpty: false, reason: 'canvas_not_visible', rect: box }
      await delay(250)
      continue
    }

    try {
      const viewport = page.viewportSize() || { width: 1280, height: 800 }
      const left = Math.max(0, Math.floor(box.x))
      const top = Math.max(0, Math.floor(box.y))
      const right = Math.min(viewport.width, Math.ceil(box.x + box.width))
      const bottom = Math.min(viewport.height, Math.ceil(box.y + box.height))
      const clip = {
        x: left,
        y: top,
        width: Math.max(1, right - left),
        height: Math.max(1, bottom - top),
      }
      const screenshot = await page.screenshot({ clip, timeout: 3000 })
      const stats = parsePngPixelStats(screenshot)
      lastProbe = {
        ...stats,
        nonEmpty: stats.litSamples >= 2 && stats.maxChannel >= 18 && stats.distinctColorBuckets >= 2,
        reason: 'sampled_canvas_clip',
      }
    } catch (err) {
      lastProbe = { nonEmpty: false, reason: err?.message || 'canvas_screenshot_failed' }
    }

    if (lastProbe?.nonEmpty) return lastProbe
    await delay(250)
  }

  throw new Error(`3D canvas stayed blank: ${JSON.stringify(lastProbe)}`)
}

async function pageDomSummary(page) {
  return page.evaluate(() => ({
    hash: window.location.hash,
    mainClass: document.querySelector('main.lycan-app')?.className || '',
    bodyText: document.body.innerText.slice(0, 800),
    hasLobby: Boolean(document.querySelector('main.lycan-app .lobby')),
    hasMatchControl: Boolean(document.querySelector('main.lycan-app .match-control-strip')),
    hasCouncilScene: Boolean(document.querySelector('main.lycan-app .council-scene')),
    canvasCount: document.querySelectorAll('main.lycan-app .council-scene canvas').length,
  }))
}

test('MatchPage mobile safe-area source contract keeps errors on ApiErrorPanel', () => {
  const matchPage = readSource(matchPageSourceUrl)
  const mobileTaskShell = readSource(mobileTaskShellSourceUrl)
  const apiErrorPanel = readSource(apiErrorPanelSourceUrl)
  const errorNoticeBlock = firstCssBlock(matchPage, '.match-error-notice')
  const toastNoticeBlock = firstCssBlock(matchPage, '.match-action-notice')

  assert.match(matchPage, /import ApiErrorPanel from '\.\.\/components\/ApiErrorPanel\.vue'/)
  assert.match(matchPage, /import MobileTaskShell from '\.\.\/components\/MobileTaskShell\.vue'/)
  assert.match(matchPage, /import \{ inlineNoticeForDisplay, noticeErrorForPanel \} from '\.\.\/composables\/apiErrorDisplay\.js'/)
  assert.match(matchPage, /<MobileTaskShell\s+mode="match"\s+:has-task="hasMobileTask"\s+:replay="isReplayMode">/)
  assert.match(matchPage, /inlineMatchNotice = computed\(\(\) => inlineNoticeForDisplay\(props\.matchNotice\)\)/)
  assert.match(matchPage, /matchErrorNotice = computed\(\(\) => matchPanelErrorForNotice\(props\.matchNotice\)\)/)
  assert.match(matchPage, /requestId:\s*error\.request_id/)
  assert.match(matchPage, /<ApiErrorPanel[\s\S]*v-if="matchErrorNotice"[\s\S]*class="match-error-notice"[\s\S]*title="对局操作失败"[\s\S]*compact/)
  assert.match(matchPage, /<aside[\s\S]*v-if="matchNoticeMessage"[\s\S]*:class="\['match-action-notice', matchNoticeType\]"/)
  assert.equal(matchPage.includes('.match-action-notice.error'), false)

  assert.match(errorNoticeBlock, /--match-error-bottom-clearance:\s*calc\(288px \+ var\(--match-safe-bottom,\s*0px\)\)/)
  assert.match(errorNoticeBlock, /top:\s*var\(--match-toast-top,\s*calc\(158px \+ var\(--match-safe-top,\s*0px\)\)\)/)
  assert.match(errorNoticeBlock, /width:\s*min\(520px,\s*calc\(100vw - var\(--match-toast-gutter,\s*32px\) - var\(--match-safe-left,\s*0px\) - var\(--match-safe-right,\s*0px\)\)\)/)
  assert.match(errorNoticeBlock, /max-height:\s*clamp\(144px,\s*calc\(100dvh - var\(--match-toast-top,\s*158px\) - var\(--match-error-bottom-clearance\)\),\s*340px\)/)
  assert.match(errorNoticeBlock, /overflow-y:\s*auto/)
  assert.match(errorNoticeBlock, /pointer-events:\s*auto/)
  assert.match(toastNoticeBlock, /pointer-events:\s*none/)
  assert.match(matchPage, /@media \(max-width: 760px\)[\s\S]*\.match-error-notice[\s\S]*--match-error-bottom-clearance:\s*calc\(306px \+ var\(--match-safe-bottom,\s*0px\)\)/)
  assert.match(matchPage, /@media \(max-width: 760px\)[\s\S]*\.match-error-notice[\s\S]*max-height:\s*clamp\(144px,\s*calc\(100dvh - var\(--match-toast-top,\s*146px\) - var\(--match-error-bottom-clearance\)\),\s*260px\)/)

  for (const edge of ['top', 'right', 'bottom', 'left']) {
    assert.match(mobileTaskShell, new RegExp(`--match-safe-${edge}: env\\(safe-area-inset-${edge}, 0px\\)`))
  }
  assert.match(mobileTaskShell, /display:\s*contents/)
  assert.match(mobileTaskShell, /@media \(max-width: 760px\)[\s\S]*--match-action-bottom:\s*max\(12px,\s*calc\(12px \+ var\(--match-safe-bottom\)\)\)/)
  assert.match(mobileTaskShell, /@media \(max-width: 760px\)[\s\S]*--match-toast-top:\s*calc\(146px \+ var\(--match-safe-top\)\)/)
  assert.match(apiErrorPanel, /<section :class="rootClass" role="alert" aria-live="polite">/)
})

test('EvidenceContextBar source contract stays in history detail and is absent from replay', () => {
  const matchPage = readSource(matchPageSourceUrl)
  const reviewPanel = readSource(reviewReportPanelSourceUrl)
  const logsPage = readSource(logsPageSourceUrl)

  assert.doesNotMatch(matchPage, /import EvidenceContextBar from '\.\.\/components\/history\/EvidenceContextBar\.vue'/)
  assert.doesNotMatch(matchPage, /<EvidenceContextBar[\s\S]*class="match-replay-evidence-context"/)
  assert.doesNotMatch(matchPage, /\.match-replay-evidence-context/)
  assert.match(matchPage, /<ReplayControls[\s\S]*v-if="isReplayMode"[\s\S]*class="match-replay-controls"/)

  assert.match(logsPage, /import EvidenceContextBar from '\.\.\/components\/history\/EvidenceContextBar\.vue'/)
  assert.match(logsPage, /<div v-if="selectedHistoryGame" :class="\['detail-topbar', 'workspace-' \+ workspaceTab\]">[\s\S]*<EvidenceContextBar v-if="workspaceTab === 'phase'" :game="selectedHistoryGame" \/>/)
  assert.doesNotMatch(reviewPanel, /import EvidenceContextBar from '\.\/EvidenceContextBar\.vue'/)
  assert.doesNotMatch(reviewPanel, /review-evidence-context/)
})

test('History phase summary and Evolution publish policy avoid misleading evidence or auto-promote controls', () => {
  const logsPage = readSource(logsPageSourceUrl)
  const consolePanel = readSource(evolutionConsolePanelSourceUrl)
  const workbench = readSource(evolutionWorkbenchSourceUrl)

  assert.match(logsPage, /class="phase-evidence-title">阶段摘要<\/span>/)
  assert.doesNotMatch(logsPage, /class="phase-evidence-title">关键证据<\/span>/)

  assert.match(consolePanel, /class="evo-policy-note"[\s\S]*<small>发布策略<\/small>[\s\S]*<b>评审门禁<\/b>[\s\S]*提案审核、门禁与信任包/)
  assert.match(consolePanel, /<small>发布策略<\/small><b>\{\{ evo\.selectedRun\.value\.config\?\.auto_promote \? '评审门禁' : '仅训练记录' \}\}<\/b>/)
  assert.doesNotMatch(consolePanel, /<select v-model="evo\.form\.value\.auto_promote">/)
  assert.match(workbench, /function autoPromoteField\(\)[\s\S]*return Boolean\(form\.value\.auto_promote\)/)
  assert.match(workbench, /auto_promote:\s*autoPromoteField\(\)/)
  assert.doesNotMatch(workbench, /body:\s*JSON\.stringify\([\s\S]*auto_promote:\s*true/)
})

test('mobile viewport Match error panel fixture renders non-empty when Chromium is available', { timeout: 30000 }, async (t) => {
  if (!chromiumIsInstalled()) {
    t.skip('Playwright Chromium is not installed; source-level mobile Match error panel contract is still covered.')
    return
  }

  let browser = null
  try {
    browser = await chromium.launch()
    const page = await browser.newPage({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      deviceScaleFactor: 2,
    })

    await page.setContent(`
      <!doctype html>
      <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <style>
            body {
              min-height: 100vh;
              margin: 0;
              color: #fff0c6;
              background:
                linear-gradient(180deg, #080503, #1f1208 52%, #090604),
                repeating-linear-gradient(90deg, rgba(255, 238, 196, 0.08) 0 1px, transparent 1px 18px);
              font-family: system-ui, sans-serif;
            }
            .mobile-task-shell {
              --match-safe-top: 24px;
              --match-safe-right: 10px;
              --match-safe-bottom: 34px;
              --match-safe-left: 6px;
              --match-toast-gutter: 22px;
              --match-toast-top: calc(146px + var(--match-safe-top));
              display: contents;
            }
            .council-scene {
              min-height: 100dvh;
              display: grid;
              place-items: center;
              background: radial-gradient(circle at 50% 45%, rgba(242, 202, 80, 0.18), transparent 36%);
            }
            .api-error-panel {
              display: grid;
              gap: 6px;
              min-width: 0;
              padding: 10px 11px;
              border: 2px solid var(--status-danger, #9a2e21);
              border-radius: 8px;
              color: var(--text-main, #3f2714);
            }
            .api-error-panel header {
              display: flex;
              align-items: flex-start;
              justify-content: space-between;
              gap: 12px;
            }
            .api-error-panel strong,
            .api-error-panel code,
            .api-error-panel p {
              overflow-wrap: anywhere;
            }
            .match-error-notice {
              --status-danger: #9a2e21;
              --text-main: #3f2714;
              --text-muted: rgba(63, 39, 20, 0.72);
              --match-error-bottom-clearance: calc(306px + var(--match-safe-bottom, 0px));
              position: fixed;
              top: var(--match-toast-top, calc(146px + var(--match-safe-top, 0px)));
              left: 50%;
              z-index: 92;
              box-sizing: border-box;
              width: calc(100vw - var(--match-toast-gutter, 22px) - var(--match-safe-left, 0px) - var(--match-safe-right, 0px));
              max-height: clamp(144px, calc(100dvh - var(--match-toast-top, 146px) - var(--match-error-bottom-clearance)), 260px);
              overflow-y: auto;
              background:
                linear-gradient(180deg, rgba(255, 239, 194, 0.98), rgba(245, 218, 164, 0.98)),
                repeating-linear-gradient(90deg, rgba(88, 42, 14, 0.08) 0 1px, transparent 1px 18px);
              box-shadow: 0 14px 30px rgba(0, 0, 0, 0.36);
              transform: translateX(-50%);
              pointer-events: auto;
            }
            .match-action-notice {
              position: fixed;
              top: var(--match-toast-top, 146px);
              left: 50%;
              width: calc(100vw - var(--match-toast-gutter, 22px) - var(--match-safe-left, 0px) - var(--match-safe-right, 0px));
              transform: translateX(-50%);
              pointer-events: none;
            }
          </style>
        </head>
        <body>
          <section class="mobile-task-shell" data-mode="match">
            <main class="council-scene">mobile match fixture</main>
            <section class="api-error-panel api-error-panel--compact match-error-notice" role="alert" aria-live="polite">
              <header>
                <div>
                  <strong>提交行动失败</strong>
                  <small><span>match_action_invalid</span><span>HTTP 409</span></small>
                </div>
                <code>request req-mobile-409</code>
              </header>
              <p>目标已出局，等待重新选择。</p>
            </section>
            <aside class="match-action-notice success" role="status" aria-live="polite">行动已提交</aside>
          </section>
        </body>
      </html>
    `, { waitUntil: 'load' })

    const summary = await page.evaluate(() => {
      const alert = document.querySelector('.match-error-notice')
      const toast = document.querySelector('.match-action-notice')
      const rect = alert.getBoundingClientRect()
      const style = getComputedStyle(alert)
      return {
        mode: document.querySelector('.mobile-task-shell')?.dataset.mode,
        alertRole: alert?.getAttribute('role') || '',
        alertText: alert?.innerText || '',
        toastClass: toast?.className || '',
        toastErrorCount: document.querySelectorAll('.match-action-notice.error').length,
        bodyTextLength: document.body.innerText.trim().length,
        pointerEvents: style.pointerEvents,
        overflowY: style.overflowY,
        maxHeightPx: Number.parseFloat(style.maxHeight),
        topPx: Number.parseFloat(style.top),
        rect: {
          left: rect.left,
          right: rect.right,
          width: rect.width,
          height: rect.height,
        },
        viewport: {
          width: window.innerWidth,
          height: window.innerHeight,
        },
      }
    })

    assert.equal(summary.mode, 'match')
    assert.equal(summary.alertRole, 'alert')
    assert.match(summary.alertText, /request req-mobile-409/)
    assert.equal(summary.toastClass.includes('success'), true)
    assert.equal(summary.toastErrorCount, 0)
    assert.ok(summary.bodyTextLength > 40)
    assert.equal(summary.pointerEvents, 'auto')
    assert.equal(summary.overflowY, 'auto')
    assert.ok(summary.topPx >= 160, `expected safe-area top offset, got ${summary.topPx}`)
    assert.ok(summary.maxHeightPx >= 144 && summary.maxHeightPx <= 260)
    assert.ok(summary.rect.width >= 320)
    assert.ok(summary.rect.left >= 0)
    assert.ok(summary.rect.right <= summary.viewport.width)

    const screenshot = await page.screenshot({ scale: 'css', timeout: 3000 })
    const stats = parsePngPixelStats(screenshot)
    assert.equal(stats.width, summary.viewport.width)
    assert.equal(stats.height, summary.viewport.height)
    assert.ok(stats.litSamples >= 5)
    assert.ok(stats.distinctColorBuckets >= 3)
    t.diagnostic(`mobile screenshot ${stats.width}x${stats.height}; colors=${stats.distinctColorBuckets}; alertTop=${summary.topPx}`)
  } finally {
    await browser?.close()
  }
})

test('EvolutionProposalReviewPanel source contract highlights proposal and gate deep link targets', () => {
  const panel = readSource(evolutionProposalReviewPanelSourceUrl)
  const gateTargetBlock = firstCssBlock(panel, '.evo-gate-strip--deep-link-target')
  const proposalTargetBlock = firstCssBlock(panel, '.evo-proposal-row--deep-link-target')
  const inlineBlock = firstCssBlock(panel, '.evo-deep-link-inline')

  assert.match(panel, /const deepLinkTarget = computed\(\(\) => props\.evo\.evolutionDeepLinkTarget\?\.value \|\| null\)/)
  assert.match(panel, /const deepLinkProposalId = computed\(\(\) => textValue\(deepLinkTarget\.value\?\.proposal_id\)\)/)
  assert.match(panel, /const deepLinkGateReportId = computed\(\(\) => textValue\(deepLinkTarget\.value\?\.gate_report_id\)\)/)
  assert.match(panel, /function deepLinkState\(scope, matched, hasTarget\)/)
  assert.match(panel, /matched:\s*'链接目标'/)
  assert.match(panel, /pending:\s*'待恢复'/)
  assert.match(panel, /unmatched:\s*'未匹配'/)

  assert.match(panel, /:class="\['evo-gate-strip', \.\.\.gateDeepLinkClass\]"/)
  assert.match(panel, /:data-gate-report-id="gateReportId \|\| null"/)
  assert.match(panel, /:data-deep-link-target="deepLinkGateReportId \? 'gate' : null"/)
  assert.match(panel, /:data-deep-link-gate-id="deepLinkGateReportId \|\| null"/)
  assert.match(panel, /data-deep-link-marker="gate"/)
  assert.match(panel, /class="evo-deep-link-badge evo-gate-deep-link-marker"/)

  assert.match(panel, /:class="\['evo-proposal-row', \.\.\.proposalDeepLinkClass\(proposal\)\]"/)
  assert.match(panel, /:data-proposal-id="proposalId\(proposal\) \|\| null"/)
  assert.match(panel, /:data-deep-link-target="proposalDeepLinkMatched\(proposal\) \? 'proposal' : null"/)
  assert.match(panel, /:data-deep-link-proposal-id="proposalDeepLinkMatched\(proposal\) \? deepLinkProposalId : null"/)
  assert.match(panel, /data-deep-link-marker="proposal"/)
  assert.match(panel, /class="evo-deep-link-inline"/)
  assert.match(panel, /提案 \$\{deepLinkStateLabel\(proposalDeepLinkState\.value\)\}: \$\{deepLinkProposalId\.value\}/)
  assert.match(panel, /门禁 \$\{deepLinkStateLabel\(gateDeepLinkState\.value\)\}: \$\{deepLinkGateReportId\.value\}/)

  assert.match(gateTargetBlock, /border:\s*1px solid rgba\(139,\s*108,\s*50,\s*0\.26\)/)
  assert.match(gateTargetBlock, /background:\s*rgba\(139,\s*108,\s*50,\s*0\.045\)/)
  assert.match(proposalTargetBlock, /box-shadow:\s*inset 3px 0 0 rgba\(139,\s*108,\s*50,\s*0\.36\)/)
  assert.match(inlineBlock, /flex-wrap:\s*wrap/)
  assert.match(panel, /\.evo-deep-link-inline\[data-deep-link-state="unmatched"\] span/)
  assert.match(panel, /\.evo-deep-link-badge\[data-deep-link-state="pending"\]/)
})

test('EvolutionProposalReviewPanel source contract supports bulk proposal review without new APIs', () => {
  const panel = readSource(evolutionProposalReviewPanelSourceUrl)
  const bulkToolsBlock = firstCssBlock(panel, '.evo-proposal-bulk-tools')
  const bulkCountsBlock = firstCssBlock(panel, '.evo-proposal-bulk-counts')
  const bulkActionsBlock = firstCssBlock(panel, '.evo-proposal-bulk-actions')

  assert.match(panel, /import \{ computed, reactive, ref \} from 'vue'/)
  assert.match(panel, /const bulkRejectReason = ref\(''\)/)
  assert.match(panel, /const bulkReviewAction = ref\(''\)/)
  assert.match(panel, /import RejectDialog from '\.\/RejectDialog\.vue'/)
  assert.match(panel, /const rejectDialogOpen = ref\(false\)/)
  assert.match(panel, /const rejectReviewMetadata = reactive\(\{\}\)/)
  assert.match(panel, /const pendingReviewProposals = computed\(\(\) => proposals\.value\.filter\(isPendingReviewProposal\)\)/)
  assert.match(panel, /const acceptableProposals = computed\(\(\) => pendingReviewProposals\.value\.filter\(canBulkAcceptProposal\)\)/)
  assert.match(panel, /const rejectableProposals = computed\(\(\) => pendingReviewProposals\.value\.filter\(canBulkRejectProposal\)\)/)
  assert.match(panel, /const canBulkAccept = computed\(\(\) => acceptableCount\.value > 0 && !isProposalActionBusy\.value\)/)
  assert.match(panel, /const bulkRejectReasonText = computed\(\(\) => textValue\(bulkRejectReason\.value\)\)/)
  assert.match(panel, /const bulkRejectDisabledReason = computed\(\(\) =>/)
  assert.match(panel, /const canBulkReject = computed\(\(\) => \([\s\S]*rejectableCount\.value > 0 && !isProposalActionBusy\.value && !bulkRejectDisabledReason\.value/)

  assert.match(panel, /function isPendingReviewProposal\(proposal\)[\s\S]*!isAccepted\(proposal\) && !isRejected\(proposal\)/)
  assert.match(panel, /function rowActionDisabled\(proposal, action\)[\s\S]*if \(isBulkReviewing\.value\) return true[\s\S]*if \(actionLoading\.value && !rowActionLoading\(proposal, action\)\) return true/)
  assert.match(panel, /function rejectDialogActionDisabled\(proposal\)[\s\S]*if \(actionLoading\.value && !rowActionLoading\(proposal, 'reject'\)\) return true/)
  assert.match(panel, /function confirmRejectDialog\(payload\)[\s\S]*const reason = textValue\(payload\?\.reason\)[\s\S]*await props\.evo\.rejectProposal\(proposal, props\.evo\.selectedRunId\.value, reason, \{ tags \}\)/)
  assert.match(panel, /function hasBlockingReviewError\(\)[\s\S]*notice\.type === 'error' \|\| Boolean\(props\.evo\.error\?\.value\)/)
  assert.match(panel, /async function runBulkReview\(action, items\)[\s\S]*if \(action === 'reject' && !bulkRejectReasonText\.value\) return[\s\S]*for \(const proposal of items\)[\s\S]*await props\.evo\.acceptProposal\(proposal, runId\)[\s\S]*await props\.evo\.rejectProposal\(proposal, runId, bulkRejectReasonText\.value\)[\s\S]*if \(hasBlockingReviewError\(\)\) break/)
  assert.match(panel, /async function bulkAcceptProposals\(\)[\s\S]*runBulkReview\('accept', \[\.\.\.acceptableProposals\.value\]\)/)
  assert.match(panel, /async function bulkRejectProposals\(\)[\s\S]*runBulkReview\('reject', \[\.\.\.rejectableProposals\.value\]\)/)
  assert.doesNotMatch(panel, /\/proposals\/bulk|bulkProposal|acceptProposals|rejectProposals/)

  assert.match(panel, /class="evo-proposal-bulk-tools"[\s\S]*data-bulk-review-tools/)
  assert.match(panel, /<small>待处理<\/small><b>\{\{ pendingReviewCount \}\}<\/b>/)
  assert.match(panel, /<small>可接受<\/small><b>\{\{ acceptableCount \}\}<\/b>/)
  assert.match(panel, /<small>可拒绝<\/small><b>\{\{ rejectableCount \}\}<\/b>/)
  assert.match(panel, /v-model="bulkRejectReason"[\s\S]*placeholder="批量拒绝原因"[\s\S]*:disabled="isProposalActionBusy"/)
  assert.match(panel, /:disabled="!canBulkAccept"[\s\S]*@click="bulkAcceptProposals"[\s\S]*接受全部可处理/)
  assert.match(panel, /:disabled="!canBulkReject"[\s\S]*@click="bulkRejectProposals"[\s\S]*拒绝全部可处理/)
  assert.match(panel, /:disabled="rowActionDisabled\(proposal, 'accept'\)"/)
  assert.match(panel, /data-open-reject-dialog/)
  assert.match(panel, /@click="openRejectDialog\(proposal, index\)"/)
  assert.match(panel, /:disabled="rowActionDisabled\(proposal, 'reject'\)"/)
  assert.match(panel, /<RejectDialog[\s\S]*:reject-buffer="rejectDialogProposal\?\.rejectBuffer \|\| \{\}"[\s\S]*@confirm="confirmRejectDialog"/)
  assert.doesNotMatch(panel, /placeholder="拒绝原因"/)

  assert.match(bulkToolsBlock, /grid-template-columns:\s*minmax\(190px,\s*0\.8fr\) minmax\(180px,\s*1fr\) auto/)
  assert.match(bulkToolsBlock, /border:\s*1px solid rgba\(58,\s*42,\s*24,\s*0\.12\)/)
  assert.match(bulkCountsBlock, /grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/)
  assert.match(bulkActionsBlock, /justify-content:\s*flex-end/)
})

test('TrustBundleDrawer mobile source contract keeps authority and evidence deep links', () => {
  const drawer = readSource(trustBundleDrawerSourceUrl)
  const drawerBlock = firstCssBlock(drawer, '.evo-trust-drawer')
  const authorityBlock = firstCssBlock(drawer, '.evo-trust-authority')

  assert.match(drawer, /<Teleport to="body">/)
  assert.match(drawer, /class="evo-trust-drawer"[\s\S]*role="dialog"[\s\S]*aria-modal="true"[\s\S]*aria-label="信任包审计"/)
  assert.match(drawer, /const authorityClass = computed\(\(\) => `status-\$\{audit\.value\.authorityStatus \|\| 'cached'\}`\)/)
  assert.match(drawer, /cached:\s*'缓存'/)
  assert.match(drawer, /loading:\s*'读取中'/)
  assert.match(drawer, /verified:\s*'已校验'/)
  assert.match(drawer, /mismatch:\s*'不一致'/)
  assert.match(drawer, /unavailable:\s*'不可用'/)
  assert.match(drawer, /<div :class="\['evo-trust-authority', authorityClass\]">/)
  assert.match(drawer, /<em v-if="mismatchLabels\.length">\{\{ mismatchLabels\.join\(' \/ '\) \}\}<\/em>/)
  assert.match(drawer, /<button type="button" class="evo-ghost-action" :disabled="loading" @click="refresh">/)

  for (const hrefField of ['gate_report_href', 'source_run_href', 'version_href']) {
    assert.match(drawer, new RegExp(`<a v-if="audit\\.${hrefField}" :href="audit\\.${hrefField}">`))
  }
  assert.equal((drawer.match(/<a v-if="row\.href" :href="row\.href">\{\{ row\.id \}\}<\/a>/g) || []).length, 2)
  assert.match(drawer, /训练证据/)
  assert.match(drawer, /提案证据/)
  assert.match(drawer, /配对种子/)

  assert.match(drawerBlock, /width:\s*min\(540px,\s*100vw\)/)
  assert.match(drawerBlock, /max-height:\s*100vh/)
  assert.match(drawerBlock, /overflow:\s*auto/)
  assert.match(authorityBlock, /grid-template-columns:\s*auto minmax\(0,\s*1fr\)/)
  assert.match(authorityBlock, /min-width:\s*0/)
  assert.match(drawer, /\.evo-trust-field-grid a,\s*\.evo-trust-id-grid a,\s*\.evo-trust-seed-table a\s*\{[\s\S]*text-decoration:\s*none/)
  assert.match(drawer, /\.evo-trust-chip-row span,[\s\S]*\.evo-trust-id-grid a,[\s\S]*padding:\s*3px 7px[\s\S]*border-radius:\s*6px[\s\S]*text-overflow:\s*ellipsis/)
  assert.match(drawer, /\.evo-trust-seed-table > \*\s*\{[\s\S]*padding:\s*6px 7px[\s\S]*text-overflow:\s*ellipsis[\s\S]*white-space:\s*nowrap/)
  assert.match(drawer, /@media \(max-width: 760px\)[\s\S]*\.evo-trust-drawer[\s\S]*width:\s*100vw[\s\S]*min-height:\s*100vh/)
  assert.match(drawer, /@media \(max-width: 760px\)[\s\S]*\.evo-trust-field-grid,[\s\S]*\.evo-trust-completeness,[\s\S]*\.evo-trust-authority[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\)/)
  assert.match(drawer, /@media \(max-width: 760px\)[\s\S]*\.evo-trust-seed-table[\s\S]*overflow-x:\s*auto/)
})

test('mobile viewport TrustBundleDrawer fixture renders authority and evidence links non-empty when Chromium is available', { timeout: 30000 }, async (t) => {
  if (!chromiumIsInstalled()) {
    t.skip('Playwright Chromium is not installed; source-level mobile TrustBundleDrawer contract is still covered.')
    return
  }

  let browser = null
  try {
    browser = await chromium.launch()
    const page = await browser.newPage({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      deviceScaleFactor: 2,
    })

    await page.setContent(`
      <!doctype html>
      <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <style>
            body {
              min-height: 100vh;
              margin: 0;
              background:
                linear-gradient(180deg, #2f261c, #15100b),
                repeating-linear-gradient(90deg, rgba(255, 253, 250, 0.1) 0 1px, transparent 1px 18px);
              font-family: system-ui, sans-serif;
            }
            .evo-trust-drawer-backdrop {
              position: fixed;
              inset: 0;
              z-index: 1200;
              display: flex;
              justify-content: flex-end;
              background: rgba(38, 29, 19, 0.34);
            }
            .evo-trust-drawer {
              box-sizing: border-box;
              display: grid;
              align-content: start;
              gap: 14px;
              width: min(540px, 100vw);
              max-height: 100vh;
              overflow: auto;
              padding: 18px;
              border-left: 1px solid rgba(58, 42, 24, 0.16);
              background: #fffdfa;
              box-shadow: -18px 0 42px rgba(38, 29, 19, 0.2);
            }
            .evo-trust-drawer-head,
            .evo-trust-section header {
              display: flex;
              align-items: center;
              justify-content: space-between;
              gap: 12px;
              min-width: 0;
            }
            .evo-trust-drawer-head span,
            .evo-trust-field-grid span,
            .evo-trust-completeness > span,
            .evo-trust-completeness > div {
              min-width: 0;
            }
            .evo-trust-drawer-actions {
              display: flex;
              flex: 0 0 auto;
              align-items: center;
              gap: 8px;
            }
            .evo-ghost-action {
              padding: 6px 9px;
              border: 1px solid rgba(58, 42, 24, 0.18);
              border-radius: 7px;
              background: rgba(255, 255, 250, 0.76);
              color: #2f261c;
              font-weight: 800;
            }
            .evo-trust-drawer-head small,
            .evo-trust-field-grid small,
            .evo-trust-completeness small,
            .evo-trust-section header b {
              color: #756957;
              font-size: 10px;
              font-weight: 800;
              letter-spacing: 0;
              text-transform: uppercase;
            }
            .evo-trust-drawer-head h2,
            .evo-trust-section h3 {
              margin: 0;
              color: #2f261c;
              font-size: 16px;
              font-weight: 850;
            }
            .evo-trust-section h3 {
              font-size: 12px;
            }
            .evo-trust-authority {
              display: grid;
              grid-template-columns: auto minmax(0, 1fr);
              gap: 4px 8px;
              align-items: center;
              min-width: 0;
              padding: 8px 10px;
              border: 1px solid rgba(139, 108, 50, 0.22);
              border-radius: 8px;
              background: rgba(139, 108, 50, 0.055);
            }
            .evo-trust-authority.status-mismatch {
              border-color: rgba(139, 58, 42, 0.24);
              background: rgba(139, 58, 42, 0.055);
            }
            .evo-trust-authority b {
              color: #7b4d1f;
              font-size: 11px;
              font-weight: 850;
            }
            .evo-trust-authority span,
            .evo-trust-authority em {
              min-width: 0;
              overflow-wrap: anywhere;
              color: #756957;
              font-size: 12px;
              font-style: normal;
            }
            .evo-trust-authority em {
              grid-column: 2;
              font-size: 11px;
              font-weight: 800;
            }
            .evo-trust-field-grid {
              display: grid;
              grid-template-columns: repeat(2, minmax(0, 1fr));
              gap: 8px;
            }
            .evo-trust-field-grid span,
            .evo-trust-completeness,
            .evo-trust-section {
              min-width: 0;
              padding: 10px;
              border: 1px solid rgba(58, 42, 24, 0.14);
              border-radius: 8px;
              background: rgba(255, 255, 250, 0.68);
            }
            .evo-trust-field-grid span,
            .evo-trust-section {
              display: grid;
              gap: 9px;
            }
            .evo-trust-completeness {
              display: grid;
              grid-template-columns: 0.55fr 0.45fr minmax(0, 1fr);
              gap: 10px;
              border-color: rgba(74, 124, 68, 0.28);
              background: rgba(74, 124, 68, 0.06);
            }
            .evo-trust-field-grid code,
            .evo-trust-field-grid a,
            .evo-trust-id-grid code,
            .evo-trust-id-grid a,
            .evo-trust-seed-table code {
              min-width: 0;
              overflow: hidden;
              color: #2f261c;
              font-family: "Cascadia Code", Consolas, monospace;
              font-size: 11px;
              font-weight: 800;
              text-overflow: ellipsis;
              white-space: nowrap;
            }
            .evo-trust-field-grid a,
            .evo-trust-id-grid a {
              text-decoration: none;
            }
            .evo-trust-chip-row,
            .evo-trust-id-grid {
              display: flex;
              flex-wrap: wrap;
              gap: 6px;
              min-width: 0;
            }
            .evo-trust-chip-row span,
            .evo-trust-id-grid code,
            .evo-trust-id-grid a,
            .evo-trust-id-grid span {
              max-width: 100%;
              overflow: hidden;
              padding: 3px 7px;
              border-radius: 6px;
              background: rgba(58, 42, 24, 0.07);
              color: #756957;
              font-size: 10px;
              font-weight: 800;
              text-overflow: ellipsis;
              white-space: nowrap;
            }
            .evo-trust-seed-table {
              display: grid;
              grid-template-columns: repeat(5, minmax(72px, 1fr));
              gap: 1px;
              overflow-x: auto;
              border: 1px solid rgba(58, 42, 24, 0.14);
              border-radius: 7px;
              background: rgba(58, 42, 24, 0.14);
            }
            .evo-trust-seed-table > * {
              min-width: 0;
              overflow: hidden;
              padding: 6px 7px;
              background: #fffdfa;
              color: #756957;
              font-size: 11px;
              text-overflow: ellipsis;
              white-space: nowrap;
            }
            @media (max-width: 760px) {
              .evo-trust-drawer {
                width: 100vw;
                min-height: 100vh;
                padding: 14px;
                border-left: 0;
              }
              .evo-trust-field-grid,
              .evo-trust-completeness,
              .evo-trust-authority {
                grid-template-columns: minmax(0, 1fr);
              }
              .evo-trust-authority em {
                grid-column: auto;
              }
              .evo-trust-seed-table {
                grid-template-columns: repeat(5, minmax(72px, 1fr));
                overflow-x: auto;
              }
            }
          </style>
        </head>
        <body>
          <div class="evo-trust-drawer-backdrop">
            <aside class="evo-trust-drawer" role="dialog" aria-modal="true" aria-label="信任包审计">
              <header class="evo-trust-drawer-head">
                <span>
                  <small>权威信任包</small>
                  <h2>信任包</h2>
                </span>
                <div class="evo-trust-drawer-actions">
                  <button type="button" class="evo-ghost-action">刷新</button>
                  <button type="button" class="evo-ghost-action">关闭</button>
                </div>
              </header>
              <div class="evo-trust-authority status-mismatch">
                <b>不一致</b>
                <span>权威信任包与页面缓存不一致。</span>
                <em>trust_bundle_id / bundle_hash / gate_report_id</em>
              </div>
              <section class="evo-trust-field-grid">
                <span><small>trust_bundle_id</small><code>tb_mobile_authority</code></span>
                <span><small>bundle_hash</small><code>sha256:authority-mobile-hash</code></span>
                <span><small>gate_report_id</small><a href="#evolution?run_id=evo_mobile&gate_report_id=gate_mobile">gate_mobile</a></span>
                <span><small>rollback_target</small><code>baseline_mobile</code></span>
                <span><small>source_run_id</small><a href="#evolution?run_id=evo_mobile">evo_mobile</a></span>
                <span><small>version_id</small><a href="#evolution?role=seer&version_id=version_mobile">version_mobile</a></span>
              </section>
              <section class="evo-trust-completeness" data-status="complete">
                <span><small>完整度</small><b>完整</b></span>
                <span><small>分数</small><b>98%</b></span>
                <div><small>缺失项</small><b>—</b></div>
              </section>
              <section class="evo-trust-section">
                <header><h3>训练证据</h3><b>2</b></header>
                <div class="evo-trust-id-grid">
                  <a href="#logs?game_id=train_mobile_a&workspace=archive">train_mobile_a</a>
                  <a href="#logs?game_id=train_mobile_b&workspace=archive">train_mobile_b</a>
                </div>
              </section>
              <section class="evo-trust-section">
                <header><h3>提案证据</h3><b>2</b></header>
                <div class="evo-trust-id-grid">
                  <a href="#evolution?run_id=evo_mobile&proposal_id=proposal_mobile_a">proposal_mobile_a</a>
                  <a href="#evolution?run_id=evo_mobile&proposal_id=proposal_mobile_b">proposal_mobile_b</a>
                </div>
              </section>
              <section class="evo-trust-section">
                <header><h3>配对种子</h3><b>1</b></header>
                <div class="evo-trust-seed-table">
                  <span>种子</span><span>基线</span><span>候选</span><span>差值</span><span>胜方</span>
                  <code>260607</code><span>0.48</span><span>0.57</span><b>0.09</b><span>candidate</span>
                </div>
              </section>
            </aside>
          </div>
        </body>
      </html>
    `, { waitUntil: 'load' })

    const summary = await page.evaluate(() => {
      const drawer = document.querySelector('.evo-trust-drawer')
      const authority = document.querySelector('.evo-trust-authority')
      const firstEvidenceLink = document.querySelector('.evo-trust-id-grid a')
      const fieldLinks = [...document.querySelectorAll('.evo-trust-field-grid a')].map((link) => ({
        text: link.textContent.trim(),
        href: link.getAttribute('href'),
        rect: link.getBoundingClientRect().toJSON(),
      }))
      const evidenceLinks = [...document.querySelectorAll('.evo-trust-id-grid a')].map((link) => ({
        text: link.textContent.trim(),
        href: link.getAttribute('href'),
        rect: link.getBoundingClientRect().toJSON(),
      }))
      const drawerRect = drawer.getBoundingClientRect()
      const authorityRect = authority.getBoundingClientRect()
      const evidenceStyle = getComputedStyle(firstEvidenceLink)
      const drawerStyle = getComputedStyle(drawer)

      return {
        role: drawer?.getAttribute('role') || '',
        modal: drawer?.getAttribute('aria-modal') || '',
        label: drawer?.getAttribute('aria-label') || '',
        authorityText: authority?.innerText || '',
        bodyTextLength: document.body.innerText.trim().length,
        fieldLinks,
        evidenceLinks,
        chipStyle: {
          backgroundColor: evidenceStyle.backgroundColor,
          borderRadius: evidenceStyle.borderRadius,
          textOverflow: evidenceStyle.textOverflow,
          whiteSpace: evidenceStyle.whiteSpace,
        },
        overflowY: drawerStyle.overflowY,
        rect: {
          left: drawerRect.left,
          right: drawerRect.right,
          width: drawerRect.width,
          height: drawerRect.height,
        },
        authorityRect: {
          top: authorityRect.top,
          width: authorityRect.width,
          height: authorityRect.height,
        },
        viewport: {
          width: window.innerWidth,
          height: window.innerHeight,
        },
      }
    })

    const hrefs = [...summary.fieldLinks, ...summary.evidenceLinks].map((link) => link.href)
    assert.equal(summary.role, 'dialog')
    assert.equal(summary.modal, 'true')
    assert.equal(summary.label, '信任包审计')
    assert.match(summary.authorityText, /不一致/)
    assert.match(summary.authorityText, /trust_bundle_id \/ bundle_hash \/ gate_report_id/)
    assert.ok(summary.bodyTextLength > 260)
    assert.equal(summary.fieldLinks.length, 3)
    assert.equal(summary.evidenceLinks.length, 4)
    assert.ok(hrefs.includes('#evolution?run_id=evo_mobile&gate_report_id=gate_mobile'))
    assert.ok(hrefs.includes('#evolution?run_id=evo_mobile'))
    assert.ok(hrefs.includes('#evolution?role=seer&version_id=version_mobile'))
    assert.ok(hrefs.includes('#logs?game_id=train_mobile_a&workspace=archive'))
    assert.ok(hrefs.includes('#evolution?run_id=evo_mobile&proposal_id=proposal_mobile_a'))
    assert.equal(summary.chipStyle.textOverflow, 'ellipsis')
    assert.equal(summary.chipStyle.whiteSpace, 'nowrap')
    assert.notEqual(summary.chipStyle.backgroundColor, 'rgba(0, 0, 0, 0)')
    assert.ok(Number.parseFloat(summary.chipStyle.borderRadius) >= 6)
    assert.equal(summary.overflowY, 'auto')
    assert.ok(summary.rect.width >= 360)
    assert.ok(summary.rect.left >= 0)
    assert.ok(summary.rect.right <= summary.viewport.width)
    assert.ok(summary.rect.height >= summary.viewport.height)
    assert.ok(summary.authorityRect.top > 40)
    assert.ok(summary.authorityRect.width >= 340)
    for (const link of [...summary.fieldLinks, ...summary.evidenceLinks]) {
      assert.ok(link.text, 'link text should not be blank')
      assert.ok(link.href?.startsWith('#'), `expected hash href, got ${link.href}`)
      assert.ok(link.rect.width > 20, `${link.text} should have visible width`)
      assert.ok(link.rect.height > 10, `${link.text} should have visible height`)
      assert.ok(link.rect.left >= 0, `${link.text} should not overflow left`)
      assert.ok(link.rect.right <= summary.viewport.width, `${link.text} should not overflow right`)
    }

    const screenshot = await page.screenshot({ scale: 'css', timeout: 3000 })
    const stats = parsePngPixelStats(screenshot)
    assert.equal(stats.width, summary.viewport.width)
    assert.equal(stats.height, summary.viewport.height)
    assert.ok(stats.litSamples >= 5)
    assert.ok(stats.distinctColorBuckets >= 3)
    t.diagnostic(`trust drawer mobile screenshot ${stats.width}x${stats.height}; colors=${stats.distinctColorBuckets}; links=${hrefs.length}`)
  } finally {
    await browser?.close()
  }
})

test('frontend creates a fake LLM game and renders a non-empty 3D canvas through the Vite proxy', { timeout: 120000 }, async (t) => {
  if (process.env.RUN_FRONTEND_BACKEND_SMOKE !== '1') {
    t.skip('set RUN_FRONTEND_BACKEND_SMOKE=1 to run the frontend-backend browser smoke')
    return
  }

  if (!chromiumIsInstalled()) {
    t.skip('Playwright Chromium is not installed; run `npx playwright install chromium` in ui/frontend.')
    return
  }

  const backendPort = await getFreePort()
  const frontendPort = await getFreePort()
  const backendRoot = await mkdtemp(path.join(tmpdir(), '521wolf-ui-smoke-'))
  const frontendEnvRoot = await mkdtemp(path.join(tmpdir(), '521wolf-ui-env-'))
  let backend = null
  let frontend = null
  let browser = null
  let page = null

  try {
    backend = startService(
      'ui backend',
      'uv',
      ['run', 'uvicorn', 'ui.backend.main:app', '--host', '127.0.0.1', '--port', String(backendPort)],
      {
        cwd: repoRoot,
        env: {
          UI_BACKEND_ROOT: backendRoot,
          UI_BACKEND_USE_FAKE_LLM: '1',
          LANGFUSE_TRACING_ENABLED: 'false',
          LANGFUSE_PUBLIC_KEY: '',
          LANGFUSE_SECRET_KEY: '',
          LANGFUSE_BASE_URL: '',
          OTEL_SDK_DISABLED: 'true',
          OTEL_TRACES_EXPORTER: 'none',
        },
      },
    )
    await waitForHttp(`http://127.0.0.1:${backendPort}/api/health`, { label: 'ui backend' })

    frontend = startService(
      'vite',
      process.execPath,
      [
        path.join(frontendRoot, 'node_modules', 'vite', 'bin', 'vite.js'),
        '--host',
        '127.0.0.1',
        '--port',
        String(frontendPort),
        '--strictPort',
      ],
      {
        cwd: frontendRoot,
        env: {
          UI_FRONTEND_ENV_DIR: frontendEnvRoot,
          UI_FRONTEND_API_PROXY_TARGET: `http://127.0.0.1:${backendPort}`,
          VITE_USE_FRONTEND_MOCK: 'false',
          VITE_TTS_ENABLED: 'false',
        },
      },
    )
    await waitForHttp(`http://127.0.0.1:${frontendPort}/`, { label: 'vite' })

    browser = await chromium.launch()
    page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
    const pageErrors = []
    const failedApiResponses = []
    page.on('pageerror', (err) => pageErrors.push(err.message))
    page.on('response', (response) => {
      if (response.url().includes('/api/') && response.status() >= 400) {
        failedApiResponses.push(`${response.status()} ${response.url()}`)
      }
    })

    await page.route('**/api/games', async (route) => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.pathname !== '/api/games' || request.method() !== 'POST') {
        await route.continue()
        return
      }
      const body = JSON.parse(request.postData() || '{}')
      await route.continue({
        headers: { ...request.headers(), 'content-type': 'application/json' },
        postData: JSON.stringify({
          ...body,
          max_days: 1,
          enable_sheriff: false,
        }),
      })
    })

    const healthResponse = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return url.pathname === '/api/health' && response.status() === 200
    })
    const rolesResponse = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return url.pathname === '/api/roles' && response.status() === 200
    })
    const gamesResponse = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return url.pathname === '/api/games' && response.status() === 200
    })

    await page.goto(`http://127.0.0.1:${frontendPort}/`, { waitUntil: 'domcontentloaded' })
    await Promise.all([healthResponse, rolesResponse, gamesResponse])

    await page.locator('main.lycan-app .lobby').waitFor({ state: 'visible' })
    await page.getByRole('button', { name: /真实后端|连接本地后端对局/ }).waitFor({ state: 'visible' })

    const apiChecks = await page.evaluate(async () => {
      const [health, roles, games] = await Promise.all([
        fetch('/api/health').then((response) => response.json()),
        fetch('/api/roles').then((response) => response.json()),
        fetch('/api/games').then((response) => response.json()),
      ])
      return { health, roles, games }
    })

    assert.equal(apiChecks.health.ok, true)
    assert.equal(apiChecks.health.mode, 'api')
    assert.equal(apiChecks.health.external?.supports_sse, true)
    assert.ok(apiChecks.roles.roles.includes('villager'))
    assert.ok(Array.isArray(apiChecks.games.games))

    const createGameResponse = page.waitForResponse((response) => {
      const request = response.request()
      const url = new URL(response.url())
      return url.pathname === '/api/games' && request.method() === 'POST' && response.status() === 200
    })
    await page.getByRole('button', { name: /真实后端|连接本地后端对局/ }).click()
    const createdGame = await (await createGameResponse).json()

    assert.ok(createdGame.game_id)
    assert.equal(createdGame.mode, 'watch')
    assert.ok(Array.isArray(createdGame.players))
    assert.equal(createdGame.players.length, 12)
    assert.equal(createdGame.max_days, 1)

    await page.waitForFunction(() => (
      window.location.hash === '#match'
      && Boolean(document.querySelector('main.lycan-app .match-control-strip'))
      && Boolean(document.querySelector('main.lycan-app .council-scene canvas'))
    ), null, { timeout: 60000 })
    const canvasProbe = await waitForNonEmptyCanvas(page, 'main.lycan-app .council-scene canvas')

    assert.equal(canvasProbe.nonEmpty, true)
    assert.deepEqual(pageErrors, [])
    assert.deepEqual(failedApiResponses, [])
  } catch (err) {
    const summary = page ? await pageDomSummary(page).catch(() => null) : null
    throw new Error(`${err?.stack || err}\n--- page summary ---\n${JSON.stringify(summary, null, 2)}${serviceLogs(backend, frontend)}`)
  } finally {
    await browser?.close()
    await stopService(frontend)
    await stopService(backend)
    await rm(frontendEnvRoot, { recursive: true, force: true })
    await rm(backendRoot, { recursive: true, force: true })
  }
})
