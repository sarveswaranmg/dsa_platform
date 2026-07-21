import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'

import { ExaminerAuthProvider } from './ExaminerAuthContext'
import { RequireRole } from './RequireRole'
import { clearTokens, setTokens } from './examinerTokens'

/** Build an unsigned JWT-shaped token; the client only reads the claims, and
 *  the server is the real authority. */
function fakeAccessToken(role: string): string {
  const payload = btoa(
    JSON.stringify({
      sub: 'e1',
      org_id: 'o1',
      role,
      exp: Math.floor(Date.now() / 1000) + 900,
    }),
  )
  return `header.${payload}.signature`
}

function renderGuarded(roles?: string[]) {
  return render(
    <MemoryRouter initialEntries={['/console/results']}>
      <ExaminerAuthProvider>
        <Routes>
          <Route path="/console/login" element={<p>Login page</p>} />
          <Route
            path="/console/results"
            element={
              <RequireRole roles={roles as never}>
                <p>Secret results</p>
              </RequireRole>
            }
          />
        </Routes>
      </ExaminerAuthProvider>
    </MemoryRouter>,
  )
}

afterEach(() => clearTokens())

describe('RequireRole', () => {
  it('sends an unauthenticated examiner to the login page', () => {
    renderGuarded(['admin'])
    expect(screen.getByText('Login page')).toBeInTheDocument()
    expect(screen.queryByText('Secret results')).not.toBeInTheDocument()
  })

  it('renders the page when the role is allowed', () => {
    setTokens(fakeAccessToken('reviewer'), 'refresh')
    renderGuarded(['admin', 'reviewer', 'proctor'])
    expect(screen.getByText('Secret results')).toBeInTheDocument()
  })

  it('refuses a signed-in examiner whose role is not allowed', () => {
    // Author may write questions but not read candidate results — this
    // mirrors require_role(ADMIN, REVIEWER, PROCTOR) on the backend.
    setTokens(fakeAccessToken('author'), 'refresh')
    renderGuarded(['admin', 'reviewer', 'proctor'])
    expect(screen.queryByText('Secret results')).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(/not permitted/i)
  })

  it('allows any signed-in examiner when no roles are specified', () => {
    setTokens(fakeAccessToken('author'), 'refresh')
    renderGuarded(undefined)
    expect(screen.getByText('Secret results')).toBeInTheDocument()
  })
})
