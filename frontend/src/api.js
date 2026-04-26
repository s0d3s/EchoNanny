const ENV_API_BASE = String(import.meta.env.VITE_API_BASE || '').trim()
const ENV_WS_BASE = String(import.meta.env.VITE_WS_BASE || '').trim()
const ALLOW_ENV_BASE_FALLBACK = String(import.meta.env.VITE_ALLOW_ENV_BASE_FALLBACK ?? 'true').toLowerCase() !== 'false'

function discoverBaseFromWindow() {
  if (typeof window === 'undefined' || !window.location) {
    return { apiBase: null, wsBase: null }
  }

  const { protocol, origin } = window.location
  if (!origin || (protocol !== 'http:' && protocol !== 'https:')) {
    return { apiBase: null, wsBase: null }
  }

  const wsProtocol = protocol === 'https:' ? 'wss:' : 'ws:'
  const wsOrigin = `${wsProtocol}//${window.location.host}`
  return {
    apiBase: `${origin}/api`,
    wsBase: wsOrigin,
  }
}

function resolveBasesOrThrow() {
  const isDev = Boolean(import.meta.env?.DEV)
  const discovered = discoverBaseFromWindow()
  const discoveredApiBase = discovered.apiBase || ''
  const discoveredWsBase = discovered.wsBase || ''
  const fallbackApiBase = ALLOW_ENV_BASE_FALLBACK ? ENV_API_BASE : ''
  const fallbackWsBase = ALLOW_ENV_BASE_FALLBACK ? ENV_WS_BASE : ''

  const hasDiscovered = Boolean(discoveredApiBase && discoveredWsBase)
  const hasFallback = Boolean(fallbackApiBase && fallbackWsBase)

  if (!hasDiscovered && !hasFallback) {
    throw new Error(
      'Unable to resolve API/WS base URLs from loaded Web UI origin. '
      + 'Set VITE_ALLOW_ENV_BASE_FALLBACK=true and provide VITE_API_BASE/VITE_WS_BASE fallback values.',
    )
  }

  const useFallbackInDev = isDev && hasFallback
  const shouldUseDiscovered = hasDiscovered && !useFallbackInDev

  return {
    discoveredApiBase,
    discoveredWsBase,
    fallbackApiBase,
    fallbackWsBase,
    activeApiBase: shouldUseDiscovered ? discoveredApiBase : fallbackApiBase,
    activeWsBase: shouldUseDiscovered ? discoveredWsBase : fallbackWsBase,
    usingDiscovered: shouldUseDiscovered,
  }
}

const BASES = resolveBasesOrThrow()

let currentApiBase = BASES.activeApiBase
let currentWsBase = BASES.activeWsBase
let discoveryProbeDone = !BASES.usingDiscovered
let discoveryProbePromise = null

function switchToFallbackBase() {
  if (!BASES.fallbackApiBase || !BASES.fallbackWsBase) return false
  currentApiBase = BASES.fallbackApiBase
  currentWsBase = BASES.fallbackWsBase
  discoveryProbeDone = true
  return true
}

async function ensureDiscoveredBaseReady() {
  if (discoveryProbeDone) return

  if (discoveryProbePromise) {
    await discoveryProbePromise
    return
  }

  const healthUrl = new URL('/health', `${currentApiBase}/`).toString()
  discoveryProbePromise = fetch(healthUrl)
    .then((resp) => {
      if (!resp.ok) {
        switchToFallbackBase()
      }
    })
    .catch(() => {
      switchToFallbackBase()
    })
    .finally(() => {
      discoveryProbeDone = true
      discoveryProbePromise = null
    })

  await discoveryProbePromise
}

export function getAccessToken() {
  return localStorage.getItem('access_token') || ''
}

export function setTokens(tokens) {
  localStorage.setItem('access_token', tokens.access_token)
  localStorage.setItem('refresh_token', tokens.refresh_token)
}

export function clearTokens() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
}

let refreshInFlight = null

async function refreshTokensOrThrow() {
  if (refreshInFlight) return refreshInFlight

  await ensureDiscoveredBaseReady()

  const refresh_token = localStorage.getItem('refresh_token')
  if (!refresh_token) {
    throw new Error('No refresh token')
  }

  refreshInFlight = fetch(`${currentApiBase}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token }),
  })
    .then(async (resp) => {
      if (!resp.ok) throw new Error('Refresh failed')
      const data = await resp.json()
      setTokens(data)
      return data
    })
    .finally(() => {
      refreshInFlight = null
    })

  return refreshInFlight
}

function forceLoginRedirect() {
  clearTokens()
  if (window.location.pathname !== '/login') {
    window.location.assign('/login')
  }
}

async function executeRequestWithBase(apiBase, path, options = {}, meta = { retryOn401: true }) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  const token = getAccessToken()
  if (token) headers.Authorization = `Bearer ${token}`

  const resp = await fetch(`${apiBase}${path}`, { ...options, headers })
  if (resp.status === 401 && meta.retryOn401) {
    try {
      await refreshTokensOrThrow()
      return executeRequestWithBase(apiBase, path, options, { retryOn401: false })
    } catch {
      forceLoginRedirect()
      throw new Error('Unauthorized')
    }
  }

  return resp
}

async function request(path, options = {}, meta = { retryOn401: true }) {
  await ensureDiscoveredBaseReady()

  let resp
  try {
    resp = await executeRequestWithBase(currentApiBase, path, options, meta)
  } catch (err) {
    const switched = switchToFallbackBase()
    if (!switched) {
      throw err
    }
    resp = await executeRequestWithBase(currentApiBase, path, options, meta)
  }

  // If auto-discovered base points to non-API origin (e.g. Vite dev origin),
  // fail over once to configured env fallback and retry.
  if (resp.status === 404 && BASES.usingDiscovered && switchToFallbackBase()) {
    resp = await executeRequestWithBase(currentApiBase, path, options, meta)
  }

  if (!resp.ok) {
    let detail = 'Request failed'
    try {
      const body = await resp.json()
      if (Array.isArray(body.detail)) {
        detail = body.detail
          .map((item) => item?.msg || JSON.stringify(item))
          .join('; ')
      } else if (typeof body.detail === 'object' && body.detail !== null) {
        detail = JSON.stringify(body.detail)
      } else if (body.detail) {
        detail = String(body.detail)
      }
    } catch {
      // ignore
    }
    throw new Error(detail)
  }

  const type = resp.headers.get('content-type') || ''
  if (type.includes('application/json')) return resp.json()
  return resp
}

export const api = {
  login(payload) {
    return request('/auth/login', { method: 'POST', body: JSON.stringify(payload) })
  },
  me() {
    return request('/auth/me')
  },
  startLive() {
    return request('/live/start', { method: 'POST' })
  },
  stopLive() {
    return request('/live/stop', { method: 'POST' })
  },
  liveStatus() {
    return request('/live/status')
  },
  devices() {
    return request('/live/devices')
  },
  configureLive(device_id) {
    return request('/live/configure', { method: 'POST', body: JSON.stringify({ device_id }) })
  },
  recordings(params = {}) {
    const search = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && `${v}`.length > 0) search.append(k, v)
    })
    return request(`/recordings?${search.toString()}`)
  },
  recording(id) {
    return request(`/recordings/${id}`)
  },
  deleteRecording(id) {
    return request(`/recordings/${id}`, { method: 'DELETE' })
  },
  activeRecording() {
    return request('/recordings/active')
  },
  labels(id) {
    return request(`/recordings/${id}/labels`)
  },
  timeline(id) {
    return request(`/recordings/${id}/timeline`)
  },
  async recordingFileBlob(id) {
    const resp = await request(`/recordings/${id}/stream`)
    return resp.blob()
  },
  wsLiveUrl() {
    const token = getAccessToken()
    const url = new URL(`${currentWsBase}/api/live/ws`)
    url.searchParams.set('token', token)
    return url.toString()
  },
}
