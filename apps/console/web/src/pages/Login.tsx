import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi, ApiError } from '../api'
import { useAuth } from '../AuthContext'

const INSURER_NAME = 'MapleSure Insurance'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [roster, setRoster] = useState<string[]>([])
  const [name, setName] = useState('')
  const [passcode, setPasscode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    authApi.roster().then((names) => {
      setRoster(names)
      setName(names[0] ?? '')
    })
  }, [])

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(name, passcode)
      navigate('/')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Login failed.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{ maxWidth: 640, margin: '4rem auto', padding: '0 1.5rem' }}>
      <span className="ams-eyebrow">{INSURER_NAME} · AMS Console</span>
      <h2 style={{ marginTop: '0.75rem', fontSize: 'var(--ams-text-2xl)' }}>Log in</h2>
      <p style={{ color: 'var(--ams-ink-soft)', marginTop: '0.25rem' }}>
        Pick your name and enter your passcode to see your queue.
      </p>
      <form onSubmit={handleSubmit} className="ams-card" style={{ marginTop: '1.25rem' }}>
        <label style={{ display: 'block', fontSize: 'var(--ams-text-sm)', marginBottom: '0.3rem' }}>
          Name
        </label>
        <select
          className="ams-select"
          value={name}
          onChange={(event) => setName(event.target.value)}
        >
          {roster.map((rosterName) => (
            <option key={rosterName} value={rosterName}>
              {rosterName}
            </option>
          ))}
        </select>

        <label
          style={{
            display: 'block',
            fontSize: 'var(--ams-text-sm)',
            marginTop: '1rem',
            marginBottom: '0.3rem',
          }}
        >
          Passcode
        </label>
        <input
          className="ams-input"
          type="password"
          value={passcode}
          onChange={(event) => setPasscode(event.target.value)}
        />

        {error && (
          <p style={{ color: 'var(--ams-error)', fontSize: 'var(--ams-text-sm)', marginTop: '0.75rem' }}>
            {error}
          </p>
        )}

        <button
          type="submit"
          className="ams-button"
          disabled={submitting || !name}
          style={{ marginTop: '1rem' }}
        >
          Log in
        </button>
      </form>
    </div>
  )
}
