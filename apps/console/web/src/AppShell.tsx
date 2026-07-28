import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from './AuthContext'

interface NavItem {
  code: string
  path: string
  title: string
}

const SCENARIOS: NavItem[] = [
  { code: 'S3', path: '/s3', title: 'Enhancement Delivery' },
]

// Minimal 16x16 line icons (no icon library — keeps the frontend
// dependency-free) matching the sidebar's icon+label rows.
function HomeIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M2 7.5 8 2l6 5.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M3.5 6.5V14h9V6.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function ScenarioIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
      <rect x="2" y="2.5" width="12" height="11" rx="1.5" strokeLinejoin="round" />
      <path d="M2 6h12" strokeLinecap="round" />
    </svg>
  )
}

export default function AppShell() {
  const { identity, logout } = useAuth()
  const navigate = useNavigate()
  const initial = identity?.name?.trim().charAt(0).toUpperCase() ?? '?'

  return (
    <div className="ams-shell">
      <header className="ams-topbar">
        <div className="ams-topbar-brand">
          <span className="ams-topbar-brand-name">MapleSure AMS Console</span>
          <span className="ams-topbar-brand-caption">S3 · one process, one port.</span>
        </div>
        <div className="ams-topbar-identity">
          <div className="ams-topbar-identity-text">
            <div className="ams-topbar-identity-name">{identity?.name}</div>
            <div className="ams-topbar-identity-role">{identity?.role}</div>
          </div>
          <div className="ams-topbar-avatar">{initial}</div>
          <button
            className="ams-button ams-button-secondary"
            style={{ fontSize: '0.82rem', padding: '0.35rem 0.7rem' }}
            onClick={async () => {
              await logout()
              navigate('/login')
            }}
          >
            Log out
          </button>
        </div>
      </header>

      <div className="ams-shell-body">
        <aside className="ams-shell-sidebar">
          <nav className="ams-sidebar-nav">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                isActive ? 'ams-sidebar-link ams-sidebar-link-active' : 'ams-sidebar-link'
              }
            >
              <span className="ams-sidebar-link-icon">
                <HomeIcon />
              </span>
              Home
            </NavLink>
          </nav>

          <div className="ams-sidebar-divider" />

          <nav className="ams-sidebar-nav">
            {SCENARIOS.map((item) => (
              <NavLink
                key={item.code}
                to={item.path}
                className={({ isActive }) =>
                  isActive ? 'ams-sidebar-link ams-sidebar-link-active' : 'ams-sidebar-link'
                }
              >
                <span className="ams-sidebar-link-icon">
                  <ScenarioIcon />
                </span>
                <span>
                  {item.code} · {item.title.split(' ')[0]}
                  <span className="ams-sidebar-link-desc">{item.title}</span>
                </span>
              </NavLink>
            ))}
            {identity?.role === 'manager' && (
              <div className="ams-sidebar-subnav">
                <a href="/s3#quick-question" className="ams-sidebar-sublink">
                  Quick question
                </a>
                <a href="/s3#ticket-dashboard" className="ams-sidebar-sublink">
                  Ticket dashboard
                </a>
              </div>
            )}
            {identity?.role === 'engineer' && (
              <div className="ams-sidebar-subnav">
                <a href="/s3#board" className="ams-sidebar-sublink">
                  Jira board
                </a>
                <a href="/s3#codegen" className="ams-sidebar-sublink">
                  Codegen &amp; release
                </a>
              </div>
            )}
          </nav>
        </aside>
        <main className="ams-shell-main">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
