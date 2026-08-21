/**
 * The HTTP client.
 *
 * Two things here are worth reading before changing anything:
 *
 * 1. Token storage. Access and refresh tokens live in localStorage. The
 *    alternative -- httpOnly cookies -- is more resistant to XSS, at the cost of
 *    needing CSRF protection and a same-site deployment. For milestone 1 the
 *    tradeoff is documented rather than hidden; see docs/architecture.md ADR-005
 *    for the conditions under which we would switch.
 *
 * 2. Refresh is single-flight. If five queries fire at once and all get a 401,
 *    only one refresh request is made and the other four wait on it. Without
 *    this, a page load with several parallel requests produces a burst of
 *    refreshes, and whichever lands last wins -- which shows up as random
 *    logouts that are very hard to reproduce.
 */

import type { TokenPair } from './types'

/**
 * In development this stays '/api/v1' and Vite proxies it to the local API, so
 * the browser only ever talks to one origin and CORS never enters the picture.
 *
 * In production the frontend is a static site on a different host from the API,
 * so the full URL is baked in at build time from VITE_API_BASE_URL. Vite
 * substitutes this at BUILD time, not run time -- changing it therefore needs a
 * redeploy of the frontend, not just a restart.
 */
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

const ACCESS_KEY = 'serviceline.access_token'
const REFRESH_KEY = 'serviceline.refresh_token'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    /**
     * The parsed error body, when there was one.
     *
     * Most failures need only a message, but some carry structure the UI has to
     * act on -- a scheduling conflict returns the jobs that clash so the board
     * can name them and offer to proceed. Flattening every error to a string
     * would throw that away.
     */
    public readonly body?: unknown,
  ) {
    super(detail)
    this.name = 'ApiError'
  }

  /** A plan limit was hit. The UI shows an upgrade prompt rather than an error. */
  get isUpgradeRequired(): boolean {
    return this.status === 402
  }
}

type Listener = () => void
const listeners = new Set<Listener>()

function notify() {
  listeners.forEach((listener) => listener())
}

export function subscribeToAuth(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export const tokens = {
  access: () => localStorage.getItem(ACCESS_KEY),
  refresh: () => localStorage.getItem(REFRESH_KEY),
  set(pair: TokenPair) {
    localStorage.setItem(ACCESS_KEY, pair.access_token)
    localStorage.setItem(REFRESH_KEY, pair.refresh_token)
    notify()
  },
  setAccess(token: string) {
    localStorage.setItem(ACCESS_KEY, token)
    notify()
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
    notify()
  },
}

let refreshInFlight: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = tokens.refresh()
  if (!refreshToken) return null

  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const response = await fetch(`${API_BASE}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        })
        if (!response.ok) {
          tokens.clear()
          return null
        }
        const pair = (await response.json()) as TokenPair
        tokens.set(pair)
        return pair.access_token
      } catch {
        return null
      } finally {
        // Cleared on the next tick so concurrent callers all observe the same
        // promise before it is discarded.
        setTimeout(() => {
          refreshInFlight = null
        }, 0)
      }
    })()
  }

  return refreshInFlight
}

interface RequestOptions {
  method?: string
  body?: unknown
  /** Skip the Authorization header and 401 retry. Used by login and signup. */
  anonymous?: boolean
}

async function send(
  path: string,
  { method = 'GET', body, anonymous = false }: RequestOptions,
  token: string | null,
): Promise<Response> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (!anonymous && token) headers['Authorization'] = `Bearer ${token}`

  return fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  let response = await send(path, options, tokens.access())

  if (response.status === 401 && !options.anonymous && tokens.refresh()) {
    const fresh = await refreshAccessToken()
    if (fresh) {
      response = await send(path, options, fresh)
    }
  }

  if (!response.ok) {
    let detail = response.statusText
    let body: unknown
    try {
      const payload = await response.json()
      body = payload?.detail ?? payload
      if (typeof payload?.detail === 'string') {
        detail = payload.detail
      } else if (Array.isArray(payload?.detail)) {
        // FastAPI validation errors: surface the first message rather than the
        // raw pydantic structure, which is unreadable to a user.
        detail = payload.detail[0]?.msg ?? detail
      } else if (typeof payload?.detail?.detail === 'string') {
        // A structured error: the message sits inside the payload the caller
        // also needs, as with a scheduling conflict.
        detail = payload.detail.detail
      }
    } catch {
      /* body was not JSON; keep the status text */
    }

    if (response.status === 401 && !options.anonymous) tokens.clear()
    throw new ApiError(response.status, detail, body)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown, anonymous = false) =>
    request<T>(path, { method: 'POST', body, anonymous }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
