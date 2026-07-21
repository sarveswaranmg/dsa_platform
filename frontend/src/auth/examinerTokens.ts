import type { ExaminerRole } from '../api/examiner/types'

const ACCESS_KEY = 'dsa.examiner.access'
const REFRESH_KEY = 'dsa.examiner.refresh'

/** sessionStorage, not localStorage: examiner sessions die with the tab. */
export function getAccessToken(): string | null {
  return sessionStorage.getItem(ACCESS_KEY)
}

export function getRefreshToken(): string | null {
  return sessionStorage.getItem(REFRESH_KEY)
}

export function setTokens(access: string, refresh: string): void {
  sessionStorage.setItem(ACCESS_KEY, access)
  sessionStorage.setItem(REFRESH_KEY, refresh)
}

export function clearTokens(): void {
  sessionStorage.removeItem(ACCESS_KEY)
  sessionStorage.removeItem(REFRESH_KEY)
}

interface AccessClaims {
  sub: string
  org_id: string
  role: ExaminerRole
  exp: number
}

/**
 * Reads the role out of the access token for navigation only. This is NOT a
 * security boundary — every request is re-authorised by the server; decoding
 * here just avoids showing links the examiner cannot use.
 */
export function readClaims(token: string | null): AccessClaims | null {
  if (!token) return null
  const payload = token.split('.')[1]
  if (!payload) return null
  try {
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(json) as AccessClaims
  } catch {
    return null
  }
}
