import { getExamToken } from '../auth/examToken'

// Same-origin relative paths work unmodified for local dev and the
// nginx-proxied Docker build (frontend/Dockerfile). Only set at build time
// for the S3/CloudFront deploy, which has no server-side proxy layer.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail)
    this.name = 'ApiError'
  }

  /** The session ended mid-exam and the server refused the write. */
  get isLocked(): boolean {
    return this.status === 409
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST'
  body?: unknown
  /** Omit the bearer header (used by the invite exchange, pre-token). */
  anonymous?: boolean
}

export async function apiFetch<T>(
  path: string,
  { method = 'GET', body, anonymous = false }: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (!anonymous) {
    const token = getExamToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload.detail) detail = payload.detail
    } catch {
      // non-JSON error body; keep the generic message
    }
    throw new ApiError(response.status, detail)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}
