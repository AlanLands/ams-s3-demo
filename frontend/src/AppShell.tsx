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

export default function AppShell() {
  const { identity, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="ams-shell">
      <aside className="ams-shell-sidebar">
        <div className="ams-sidebar-title">MapleSure AMS Console</div>
        <div className="ams-sidebar-caption">S3 · one process, one port.</div>

        <div className="ams-sidebar-identity">
          <div className="ams-sidebar-identity-name">{identity?.name}</div>
          <div className="ams-sidebar-identity-role">{identity?.role}</div>
          <button
            className="ams-button ams-button-secondary"
            style={{ width: '100%', fontSize: '0.82rem', padding: '0.35rem 0.6rem' }}
            onClick={async () => {
              await logout()
              navigate('/login')
            }}
          >
            Log out
          </button>
        </div>

        <NavLink
          to="/"
          end
          className={({ isActive }) =>
            isActive ? 'ams-sidebar-link ams-sidebar-link-active' : 'ams-sidebar-link'
          }
        >
          Home
        </NavLink>

        <nav className="ams-sidebar-nav" style={{ marginTop: '0.75rem' }}>
          {SCENARIOS.map((item) => (
            <NavLink
              key={item.code}
              to={item.path}
              className={({ isActive }) =>
                isActive ? 'ams-sidebar-link ams-sidebar-link-active' : 'ams-sidebar-link'
              }
            >
              {item.code} · {item.title.split(' ')[0]}
              <span className="ams-sidebar-link-desc">{item.title}</span>
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="ams-shell-main">
        <Outlet />
      </main>
    </div>
  )
}
