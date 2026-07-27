import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { registerOrg, verifyTotpEnrollment } from '../../api/examiner/endpoints'
import { ApiError } from '../../api/client'
import type { RegisterResponse } from '../../api/examiner/types'

type Step = 'register' | 'enroll'

export function RegisterPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState<Step>('register')
  const [orgName, setOrgName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [enrollment, setEnrollment] = useState<RegisterResponse | null>(null)
  const [totpCode, setTotpCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleRegister(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const response = await registerOrg({ org_name: orgName, email, password })
      setEnrollment(response)
      setStep('enroll')
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.detail
          : 'Registration failed. Please try again.',
      )
    } finally {
      setBusy(false)
    }
  }

  async function handleEnroll(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await verifyTotpEnrollment(email, password, totpCode)
      navigate('/console/login', { replace: true })
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.detail
          : 'Could not verify that code. Please try again.',
      )
    } finally {
      setBusy(false)
    }
  }

  if (step === 'enroll' && enrollment) {
    return (
      <main className="console__content">
        <h1>Set up your authenticator</h1>
        <p>
          Add this account to an authenticator app (Google Authenticator, 1Password,
          Authy…), then enter the 6-digit code it shows to finish setting up
          your profile.
        </p>
        <form className="console-form" onSubmit={handleEnroll}>
          <label>
            <span>Secret key (manual entry)</span>
            <input type="text" readOnly value={enrollment.totp_secret} onFocus={(e) => e.target.select()} />
          </label>
          <label>
            <span>Provisioning URI</span>
            <input
              type="text"
              readOnly
              value={enrollment.totp_provisioning_uri}
              onFocus={(e) => e.target.select()}
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
            {busy ? 'Verifying…' : 'Verify & finish'}
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

  return (
    <main className="console__content">
      <h1>Create your organization</h1>
      <p>This creates your org and an admin profile. You can invite other examiners afterwards.</p>
      <form className="console-form" onSubmit={handleRegister}>
        <label>
          <span>Organization name</span>
          <input
            type="text"
            value={orgName}
            onChange={(event) => setOrgName(event.target.value)}
            required
          />
        </label>
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
            autoComplete="new-password"
            minLength={12}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        <button type="submit" className="console-button" disabled={busy}>
          {busy ? 'Creating…' : 'Create account'}
        </button>
        {error && (
          <p className="console-error" role="alert">
            {error}
          </p>
        )}
      </form>
      <p>
        Already have an account? <Link to="/console/login">Sign in</Link>
      </p>
    </main>
  )
}
