import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { authApi, type Identity } from './api'

interface AuthState {
  identity: Identity | null
  loading: boolean
  login: (name: string, passcode: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    authApi
      .me()
      .then(setIdentity)
      .catch(() => setIdentity(null))
      .finally(() => setLoading(false))
  }, [])

  async function login(name: string, passcode: string) {
    const result = await authApi.login(name, passcode)
    setIdentity(result)
  }

  async function logout() {
    await authApi.logout()
    setIdentity(null)
  }

  return (
    <AuthContext.Provider value={{ identity, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (context === null) throw new Error('useAuth must be used within AuthProvider')
  return context
}
