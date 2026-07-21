import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { exchangeInvite } from '../api/candidate'
import { ApiError } from '../api/client'
import { setExamToken } from '../auth/examToken'

import './InvitePage.css'

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as
  | string
  | undefined

interface GoogleCredentialResponse {
  credential: string
}

// Minimal shape of the Google Identity Services global.
interface GoogleAccountsId {
  initialize: (config: {
    client_id: string
    callback: (response: GoogleCredentialResponse) => void
  }) => void
  renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void
}

declare global {
  interface Window {
    google?: { accounts: { id: GoogleAccountsId } }
  }
}

export function InvitePage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const inviteToken = params.get('token')
  const buttonRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!inviteToken || !GOOGLE_CLIENT_ID || !buttonRef.current) return
    const google = window.google
    if (!google) {
      setError(
        'Google sign-in could not be loaded. Check your connection and reload.',
      )
      return
    }

    google.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,
      callback: async (response) => {
        setBusy(true)
        setError(null)
        try {
          // The server re-verifies this token and checks the email matches
          // the invite — the browser is never trusted for identity.
          const result = await exchangeInvite(inviteToken, response.credential)
          setExamToken(result.exam_token)
          navigate('/exam/room', { replace: true })
        } catch (caught) {
          setError(
            caught instanceof ApiError
              ? caught.detail
              : 'Sign-in failed. Please try again.',
          )
        } finally {
          setBusy(false)
        }
      },
    })
    google.accounts.id.renderButton(buttonRef.current, {
      theme: 'outline',
      size: 'large',
      text: 'signin_with',
    })
  }, [inviteToken, navigate])

  if (!inviteToken) {
    return (
      <main className="invite">
        <h1>Invalid invite link</h1>
        <p>This link is missing its token. Please use the link from your email.</p>
      </main>
    )
  }

  return (
    <main className="invite">
      <h1>Your DSA assessment</h1>
      <p>
        Sign in with the Google account that received this invitation. The exam
        is bound to that email address.
      </p>
      {!GOOGLE_CLIENT_ID && (
        <p className="invite__error">
          Google sign-in is not configured. Set <code>VITE_GOOGLE_CLIENT_ID</code>{' '}
          to your Google OAuth client ID.
        </p>
      )}
      <div ref={buttonRef} className="invite__google" />
      {busy && <p role="status">Verifying your invitation…</p>}
      {error && (
        <p className="invite__error" role="alert">
          {error}
        </p>
      )}
    </main>
  )
}
