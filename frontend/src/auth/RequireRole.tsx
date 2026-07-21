import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import type { ExaminerRole } from '../api/examiner/types'
import { useExaminerAuth } from './useExaminerAuth'

interface RequireRoleProps {
  /** Omit to allow any signed-in examiner. */
  roles?: ExaminerRole[]
  children: ReactNode
}

/**
 * Mirrors the backend's require_role. This is navigation ergonomics only —
 * the server independently authorises every request, so a tampered token
 * buys nothing.
 */
export function RequireRole({ roles, children }: RequireRoleProps) {
  const { isAuthenticated, role } = useExaminerAuth()

  if (!isAuthenticated) {
    return <Navigate to="/console/login" replace />
  }

  if (roles && (!role || !roles.includes(role))) {
    return (
      <main className="console-denied" role="alert">
        <h1>Not permitted</h1>
        <p>
          Your role ({role}) cannot access this page. Required:{' '}
          {roles.join(', ')}.
        </p>
      </main>
    )
  }

  return <>{children}</>
}
