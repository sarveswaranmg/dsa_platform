import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setTokens,
} from '../../auth/examinerTokens'
import { ApiError } from '../client'
import type { TokenResponse } from './types'

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  anonymous?: boolean
}

/** Set by the auth provider so a dead refresh can drop the UI back to login. */
let onSessionLost: (() => void) | null = null
export function setSessionLostHandler(handler: (() => void) | null): void {
  onSessionLost = handler
}

// Single-flight: concurrent 401s share one refresh instead of racing (and
// burning the rotated refresh token, which the server treats as reuse).
let refreshInFlight: Promise<boolean> | null = null

async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return false

  const response = await fetch('/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
  if (!response.ok) {
    clearTokens()
    onSessionLost?.()
    return false
  }
  const tokens = (await response.json()) as TokenResponse
  setTokens(tokens.access_token, tokens.refresh_token)
  return true
}

function ensureRefresh(): Promise<boolean> {
  refreshInFlight ??= refreshAccessToken().finally(() => {
    refreshInFlight = null
  })
  return refreshInFlight
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = {}
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (!options.anonymous) {
    const token = getAccessToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }
  return fetch(path, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
}

export async function examinerFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  let response = await send(path, options)

  // Access tokens are short-lived by design; refresh once and retry.
  if (response.status === 401 && !options.anonymous && getRefreshToken()) {
    if (await ensureRefresh()) {
      response = await send(path, options)
    }
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload.detail) detail = payload.detail
    } catch {
      // non-JSON body; keep the generic message
    }
    if (response.status === 401 && !options.anonymous) onSessionLost?.()
    throw new ApiError(response.status, detail)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}
