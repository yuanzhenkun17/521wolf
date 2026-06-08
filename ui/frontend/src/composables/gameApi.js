import { mockApiFetch } from '../mockAgentGame.js'

const viteEnv = import.meta.env || {}
const API = viteEnv.VITE_API_BASE || '/api'
const USE_FRONTEND_MOCK = viteEnv.VITE_USE_FRONTEND_MOCK === 'true'

async function readErrorMessage(response) {
  const text = await response.text().catch(() => '')
  if (!text) return `HTTP ${response.status}`
  try {
    const payload = JSON.parse(text)
    if (typeof payload?.detail === 'string') return payload.detail
    if (Array.isArray(payload?.detail)) return payload.detail.map((item) => item.msg || item.detail || String(item)).join('; ')
    if (payload?.message) return String(payload.message)
  } catch {}
  return text
}

function createGameApi(apiBase = API) {
  async function apiFetch(path, options = {}) {
    if (USE_FRONTEND_MOCK) {
      return mockApiFetch(path, options)
    }

    const headers = {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {})
    }
    const response = await fetch(`${apiBase}${path}`, {
      ...options,
      headers
    })
    if (!response.ok) {
      throw new Error(await readErrorMessage(response))
    }
    if (response.status === 204) return null
    const text = await response.text()
    return text ? JSON.parse(text) : null
  }

  return { apiFetch, apiBase }
}

export { API, createGameApi }
