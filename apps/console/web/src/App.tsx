import { Navigate, Route, Routes, BrowserRouter } from 'react-router-dom'
import { AuthProvider, useAuth } from './AuthContext'
import AppShell from './AppShell'
import Login from './pages/Login'
import Home from './pages/Home'
import S3 from './pages/S3'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { identity, loading } = useAuth()
  if (loading) return <p style={{ padding: '2rem' }}>Loading…</p>
  if (!identity) return <Navigate to="/login" replace />
  return <>{children}</>
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Home />} />
        <Route path="/s3" element={<S3 />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}
