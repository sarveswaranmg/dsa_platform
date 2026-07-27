import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RegisterPage } from './RegisterPage'

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

async function registerOrg() {
  await userEvent.type(screen.getByLabelText(/organization name/i), 'Acme')
  await userEvent.type(screen.getByLabelText(/^email$/i), 'a@example.com')
  await userEvent.type(screen.getByLabelText(/^password$/i), 'hunter2hunter2')
  await userEvent.click(screen.getByRole('button', { name: /create account/i }))
}

beforeEach(() => {
  render(
    <MemoryRouter>
      <RegisterPage />
    </MemoryRouter>,
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('RegisterPage', () => {
  it('shows the TOTP enrollment step after a successful registration', async () => {
    mockFetchOnce(201, {
      examiner_id: 'e1',
      org_id: 'o1',
      email: 'a@example.com',
      role: 'admin',
      totp_secret: 'JBSWY3DPEHPK3PXP',
      totp_provisioning_uri: 'otpauth://totp/DSA:a@example.com?secret=JBSWY3DPEHPK3PXP',
    })
    await registerOrg()
    expect(await screen.findByText(/set up your authenticator/i)).toBeInTheDocument()
    expect(screen.getByDisplayValue('JBSWY3DPEHPK3PXP')).toBeInTheDocument()
  })

  it('surfaces a registration error', async () => {
    mockFetchOnce(409, { detail: 'An examiner with this email already exists' })
    await registerOrg()
    expect(await screen.findByRole('alert')).toHaveTextContent(/already exists/i)
  })

  it('surfaces an enrollment verification error', async () => {
    mockFetchOnce(201, {
      examiner_id: 'e1',
      org_id: 'o1',
      email: 'a@example.com',
      role: 'admin',
      totp_secret: 'JBSWY3DPEHPK3PXP',
      totp_provisioning_uri: 'otpauth://totp/DSA:a@example.com?secret=JBSWY3DPEHPK3PXP',
    })
    await registerOrg()
    await screen.findByText(/set up your authenticator/i)

    mockFetchOnce(401, { detail: 'Invalid TOTP code' })
    await userEvent.type(screen.getByLabelText(/authenticator code/i), '000000')
    await userEvent.click(screen.getByRole('button', { name: /verify & finish/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid totp code/i)
  })
})
