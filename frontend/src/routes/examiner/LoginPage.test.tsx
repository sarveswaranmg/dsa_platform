import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ExaminerAuthProvider } from '../../auth/ExaminerAuthContext'
import { clearTokens, getAccessToken } from '../../auth/examinerTokens'
import { LoginPage } from './LoginPage'

function mockFetchOnce(status: number, body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    })) as unknown as typeof fetch,
  )
}

async function signIn() {
  await userEvent.type(screen.getByLabelText(/email/i), 'a@example.com')
  await userEvent.type(screen.getByLabelText(/password/i), 'hunter2hunter2')
  await userEvent.type(screen.getByLabelText(/authenticator code/i), '123456')
  await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
}

beforeEach(() => {
  render(
    <MemoryRouter>
      <ExaminerAuthProvider>
        <LoginPage />
      </ExaminerAuthProvider>
    </MemoryRouter>,
  )
})

afterEach(() => {
  clearTokens()
  vi.unstubAllGlobals()
})

describe('LoginPage', () => {
  it('stores tokens after a successful sign-in', async () => {
    mockFetchOnce(200, {
      access_token: 'access-1',
      refresh_token: 'refresh-1',
      token_type: 'bearer',
      expires_in: 900,
    })
    await signIn()
    expect(getAccessToken()).toBe('access-1')
  })

  it('surfaces a rejected credential or TOTP code', async () => {
    mockFetchOnce(401, { detail: 'Invalid TOTP code' })
    await signIn()
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid TOTP code')
    expect(getAccessToken()).toBeNull()
  })

  it('tells an examiner who has not enrolled TOTP what to do', async () => {
    mockFetchOnce(403, {
      detail: 'TOTP enrollment must be verified before login',
    })
    await signIn()
    expect(await screen.findByRole('alert')).toHaveTextContent(/enrollment/i)
  })
})
