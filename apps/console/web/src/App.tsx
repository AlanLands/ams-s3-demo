import { Navigate, Route, Routes, BrowserRouter } from 'react-router-dom'
import { AuthProvider, useAuth } from './AuthContext'
import AppShell from './AppShell'
import Login from './pages/Login'
import Home from './pages/Home'
import S3 from './pages/S3'
import BoardStage from './pages/s3/BoardStage'
import TargetStage from './pages/s3/TargetStage'
import GenerateStage from './pages/s3/GenerateStage'
import DesignDocStage from './pages/s3/DesignDocStage'
import TestsStage from './pages/s3/TestsStage'
import ReleaseStage from './pages/s3/ReleaseStage'
import Admin from './pages/Admin'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { identity, loading } = useAuth()
  if (loading) return <p style={{ padding: '2rem' }}>Loading…</p>
  if (!identity) return <Navigate to="/login" replace />
  return <>{children}</>
}

// Admin is manager-only. The API enforces this itself (every /api/admin route
// 403s a non-manager), so this guard is about not showing an engineer a page
// whose every control would fail — hence a redirect home rather than a "you
// are not allowed" screen for a page they were never offered. It sits inside
// RequireAuth, so `identity` is non-null by the time it runs.
function RequireManager({ children }: { children: React.ReactNode }) {
  const { identity } = useAuth()
  if (identity?.role !== 'manager') return <Navigate to="/" replace />
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
        <Route path="/s3" element={<S3 />}>
          <Route index element={<Navigate to="board" replace />} />
          <Route path="board" element={<BoardStage />} />
          <Route path="target" element={<TargetStage />} />
          <Route path="generate" element={<GenerateStage />} />
          <Route path="design-doc" element={<DesignDocStage />} />
          <Route path="tests" element={<TestsStage />} />
          <Route path="release" element={<ReleaseStage />} />
        </Route>
        <Route
          path="/admin"
          element={
            <RequireManager>
              <Admin />
            </RequireManager>
          }
        />
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
