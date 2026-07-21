import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { useExaminerAuth } from '../../auth/useExaminerAuth'

export function LoginPage() {
  const { signIn } = useExaminerAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await signIn(email, password, totpCode)
      navigate('/console/questions', { replace: true })
    } catch (caught) {
      // The server deliberately distinguishes "enrol your authenticator"
      // (403) from bad credentials/TOTP (401), which are kept indistinct.
      setError(
        caught instanceof ApiError
          ? caught.detail
          : 'Sign-in failed. Please try again.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="console__content">
      <h1>Examiner sign in</h1>
      <form className="console-form" onSubmit={handleSubmit}>
        <label>
          <span>Email</span>
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </label>
        <label>
          <span>Password</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        <label>
          <span>Authenticator code</span>
          <input
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={6}
            autoComplete="one-time-code"
            value={totpCode}
            onChange={(event) => setTotpCode(event.target.value)}
            required
          />
        </label>
        <button type="submit" className="console-button" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        {error && (
          <p className="console-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </main>
  )
}
