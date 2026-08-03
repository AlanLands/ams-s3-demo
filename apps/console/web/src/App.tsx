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
import { canSeeStage, fallbackStagePath, type S3StageId } from './pages/s3/stageAccess'

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

// A stage the current role does not see is also not reachable by typing its
// URL. The stage rail already filters itself from the same map (see
// stageAccess.ts); this closes the gap between "not offered" and "not
// reachable", which is otherwise the first thing anyone notices.
//
// Redirects to the board rather than home: the person is still working this
// pipeline, and ejecting them from it reads as a fault rather than a redirect.
// Presentation only — the API does not enforce this split.
function RequireStage({ id, children }: { id: S3StageId; children: React.ReactNode }) {
  const { identity } = useAuth()
  if (!canSeeStage(identity?.role, id)) return <Navigate to={fallbackStagePath()} replace />
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
          <Route
            path="target"
            element={
              <RequireStage id="target">
                <TargetStage />
              </RequireStage>
            }
          />
          <Route
            path="generate"
            element={
              <RequireStage id="generate">
                <GenerateStage />
              </RequireStage>
            }
          />
          <Route
            path="design-doc"
            element={
              <RequireStage id="design-doc">
                <DesignDocStage />
              </RequireStage>
            }
          />
          <Route
            path="tests"
            element={
              <RequireStage id="tests">
                <TestsStage />
              </RequireStage>
            }
          />
          <Route
            path="release"
            element={
              <RequireStage id="release">
                <ReleaseStage />
              </RequireStage>
            }
          />
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
