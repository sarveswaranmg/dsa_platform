import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { setSessionLostHandler } from '../api/examiner/client'
import { login as loginRequest, logout as logoutRequest } from '../api/examiner/endpoints'
import type { ExaminerRole } from '../api/examiner/types'
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  readClaims,
  setTokens,
} from './examinerTokens'

interface ExaminerAuthValue {
  role: ExaminerRole | null
  orgId: string | null
  isAuthenticated: boolean
  signIn: (email: string, password: string, totpCode: string) => Promise<void>
  signOut: () => Promise<void>
}

export const ExaminerAuthContext = createContext<ExaminerAuthValue | null>(null)

export function ExaminerAuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => getAccessToken())

  // A failed refresh (expired or rotated-away) drops us back to signed-out.
  useEffect(() => {
    setSessionLostHandler(() => setToken(null))
    return () => setSessionLostHandler(null)
  }, [])

  const signIn = useCallback(
    async (email: string, password: string, totpCode: string) => {
      const tokens = await loginRequest(email, password, totpCode)
      setTokens(tokens.access_token, tokens.refresh_token)
      setToken(tokens.access_token)
    },
    [],
  )

  const signOut = useCallback(async () => {
    const refresh = getRefreshToken()
    if (refresh) {
      // Best effort: revoke server-side, but always clear locally.
      try {
        await logoutRequest(refresh)
      } catch {
        // ignore — the local session is being dropped regardless
      }
    }
    clearTokens()
    setToken(null)
  }, [])

  const value = useMemo<ExaminerAuthValue>(() => {
    const claims = readClaims(token)
    return {
      role: claims?.role ?? null,
      orgId: claims?.org_id ?? null,
      isAuthenticated: claims !== null,
      signIn,
      signOut,
    }
  }, [token, signIn, signOut])

  return (
    <ExaminerAuthContext.Provider value={value}>
      {children}
    </ExaminerAuthContext.Provider>
  )
}
