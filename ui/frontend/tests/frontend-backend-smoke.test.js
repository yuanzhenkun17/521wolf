import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
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
