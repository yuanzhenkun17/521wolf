import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdtemp, rm } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
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

test('frontend opens against the real UI backend through the Vite proxy', { timeout: 70000 }, async (t) => {
  if (!chromiumIsInstalled()) {
    t.skip('Playwright Chromium is not installed; run `npx playwright install chromium` in ui/frontend.')
    return
  }

  const backendPort = await getFreePort()
  const frontendPort = await getFreePort()
  const backendRoot = await mkdtemp(path.join(tmpdir(), '521wolf-ui-smoke-'))
  let backend = null
  let frontend = null
  let browser = null

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
          UI_FRONTEND_API_PROXY_TARGET: `http://127.0.0.1:${backendPort}`,
          VITE_USE_FRONTEND_MOCK: 'false',
          VITE_TTS_ENABLED: 'false',
        },
      },
    )
    await waitForHttp(`http://127.0.0.1:${frontendPort}/`, { label: 'vite' })

    browser = await chromium.launch()
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
    const pageErrors = []
    const failedApiResponses = []
    page.on('pageerror', (err) => pageErrors.push(err.message))
    page.on('response', (response) => {
      if (response.url().includes('/api/') && response.status() >= 400) {
        failedApiResponses.push(`${response.status()} ${response.url()}`)
      }
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
    assert.deepEqual(pageErrors, [])
    assert.deepEqual(failedApiResponses, [])
  } catch (err) {
    throw new Error(`${err?.stack || err}${serviceLogs(backend, frontend)}`)
  } finally {
    await browser?.close()
    await stopService(frontend)
    await stopService(backend)
    await rm(backendRoot, { recursive: true, force: true })
  }
})
