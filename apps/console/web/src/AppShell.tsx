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
      <a className="ams-skip-link" href="#main-content">
        Skip to main content
      </a>
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
            style={{ fontSize: 'var(--ams-text-xs)', padding: 'var(--ams-space-2) var(--ams-space-3)' }}
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
          </nav>
          <div id="ams-sidebar-slot" />
        </aside>
        <main id="main-content" className="ams-shell-main" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
