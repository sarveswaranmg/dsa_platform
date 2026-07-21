import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import type { ExaminerRole } from '../../api/examiner/types'
import { useExaminerAuth } from '../../auth/useExaminerAuth'

import './ConsoleLayout.css'

const LINKS: { to: string; label: string; roles?: ExaminerRole[] }[] = [
  { to: '/console/questions', label: 'Question bank' },
  { to: '/console/blueprints', label: 'Blueprints', roles: ['admin', 'author'] },
  { to: '/console/schedule', label: 'Schedule', roles: ['admin', 'author'] },
  {
    to: '/console/results',
    label: 'Results',
    roles: ['admin', 'reviewer', 'proctor'],
  },
]

export function ConsoleLayout() {
  const { role, signOut } = useExaminerAuth()
  const navigate = useNavigate()

  const visible = LINKS.filter(
    (link) => !link.roles || (role && link.roles.includes(role)),
  )

  return (
    <div className="console">
      <header className="console__bar">
        <span className="console__brand">Examiner console</span>
        <nav className="console__nav">
          {visible.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              className={({ isActive }) =>
                `console__link${isActive ? ' console__link--active' : ''}`
              }
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
        <div className="console__account">
          <span className="console__role">{role}</span>
          <button
            type="button"
            className="console__signout"
            onClick={async () => {
              await signOut()
              navigate('/console/login', { replace: true })
            }}
          >
            Sign out
          </button>
        </div>
      </header>
      <main className="console__content">
        <Outlet />
      </main>
    </div>
  )
}
