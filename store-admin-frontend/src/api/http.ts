const configuredApiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '')
// Localhost fallback exists only in Vite development mode. Production uses
// the deployment-provided value, or a same-origin /api path as the safe
// default; a production bundle can therefore never silently call a laptop.
export const API_BASE = configuredApiBase || (import.meta.env.DEV ? 'http://localhost:8000/api' : '/api')

const ACCESS_KEY = 'sa_access_token'
const REFRESH_KEY = 'sa_refresh_token'

// Session tokens are read sessionStorage-first, localStorage-second, so two
// tabs can hold two different accounts at once (e.g. admin + a branch login).
// A plain new tab has no sessionStorage, so it inherits the localStorage
// session — the normal single-account flow ("log in once, works everywhere")
// is unchanged. A tab only gets its own isolated session by logging in there
// (setTokens) or by being duplicated from one that had one.
function tabHasOwnSession() {
  return !!sessionStorage.getItem(ACCESS_KEY)
}

export function getAccessToken() {
  return sessionStorage.getItem(ACCESS_KEY) ?? localStorage.getItem(ACCESS_KEY)
}

export function getRefreshToken() {
  return sessionStorage.getItem(REFRESH_KEY) ?? localStorage.getItem(REFRESH_KEY)
}

export function setTokens(access: string, refresh: string) {
  // this tab: its own session; also become the default for future new tabs
  sessionStorage.setItem(ACCESS_KEY, access)
  sessionStorage.setItem(REFRESH_KEY, refresh)
  localStorage.setItem(ACCESS_KEY, access)
  localStorage.setItem(REFRESH_KEY, refresh)
}

function storeRefreshedAccess(access: string) {
  ;(tabHasOwnSession() ? sessionStorage : localStorage).setItem(ACCESS_KEY, access)
}

export function clearTokens() {
  sessionStorage.removeItem(ACCESS_KEY)
  sessionStorage.removeItem(REFRESH_KEY)
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

export class ApiError extends Error {
  status: number
  // DRF error bodies vary by shape: a plain array for view-level
  // ValidationError('msg'), or {field: [msg, ...]} for serializer field
  // errors — never assume one or the other, use messages() below.
  body: unknown

  constructor(status: number, body: unknown) {
    super(`API error ${status}`)
    this.status = status
    this.body = body
  }

  /** Flattens either DRF error shape into a plain list of message strings. */
  messages(): string[] {
    if (Array.isArray(this.body)) return this.body.map(String)
    if (this.body && typeof this.body === 'object') {
      return Object.values(this.body as Record<string, unknown>).flatMap((v) =>
        Array.isArray(v) ? v.map(String) : [String(v)],
      )
    }
    return []
  }
}

// Concurrent 401s during a burst of requests should trigger exactly one
// refresh call, not one per request — everyone awaits the same promise.
let refreshPromise: Promise<boolean> | null = null

async function tryRefresh(): Promise<boolean> {
  const refresh = getRefreshToken()
  if (!refresh) return false
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE}/token/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    })
      .then(async (res) => {
        if (!res.ok) return false
        const data = await res.json()
        storeRefreshedAccess(data.access)
        return true
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

async function request<T>(path: string, options: RequestInit = {}, allowRetry = true): Promise<T> {
  const token = getAccessToken()
  const headers: Record<string, string> = {
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers as Record<string, string>),
  }
  if (token) headers.Authorization = `Bearer ${token}`

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })

  if (res.status === 401 && allowRetry) {
    const refreshed = await tryRefresh()
    if (refreshed) return request<T>(path, options, false)
    clearTokens()
  }

  if (!res.ok) {
    const body: unknown = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body)
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export const http = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
