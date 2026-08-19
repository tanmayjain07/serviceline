import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import AuthShell from '../components/AuthShell'
import DemoPanel from '../components/DemoPanel'
import { Alert, Button, Field } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { TokenPair } from '../lib/types'

/**
 * How long a sign-in may take before we explain the delay rather than just
 * spinning. The demo runs on a free tier that suspends after inactivity, so the
 * first request of the day genuinely can take the better part of a minute.
 * Four seconds is long enough that a warm server never triggers it.
 */
const SLOW_REQUEST_MS = 4000

export default function Login() {
  const { signIn } = useAuth()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [slow, setSlow] = useState(false)

  const slowTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Clear the timer if the component unmounts mid-request, so a completed
  // navigation cannot leave a setState firing against an unmounted component.
  useEffect(() => {
    return () => {
      if (slowTimer.current) clearTimeout(slowTimer.current)
    }
  }, [])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSlow(false)
    setBusy(true)
    slowTimer.current = setTimeout(() => setSlow(true), SLOW_REQUEST_MS)

    try {
      const pair = await api.post<TokenPair>(
        '/auth/login',
        { email, password },
        true,
      )
      signIn(pair)
      // A user in several companies gets a token with no tenant on it, and has
      // to pick one before any company data is reachable.
      navigate(pair.tenant_id ? '/' : '/choose-company', { replace: true })
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.detail
          : 'Something went wrong. Please try again.',
      )
    } finally {
      if (slowTimer.current) clearTimeout(slowTimer.current)
      setSlow(false)
      setBusy(false)
    }
  }

  return (
    <AuthShell
      title="Sign in"
      subtitle="Welcome back."
      footer={
        <>
          New company?{' '}
          <Link to="/signup" className="font-medium text-brand-700 hover:underline">
            Start a free trial
          </Link>
        </>
      }
    >
      <DemoPanel
        onPick={(demoEmail, demoPassword) => {
          setEmail(demoEmail)
          setPassword(demoPassword)
          setError(null)
        }}
      />

      <form onSubmit={handleSubmit} className="space-y-4">
        {error && <Alert>{error}</Alert>}

        {slow && (
          <Alert tone="warning" title="Waking the server">
            This demo runs on a free tier that sleeps when idle. The first
            request can take up to a minute. Later ones are fast.
          </Alert>
        )}

        <Field
          label="Email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />

        <Button type="submit" loading={busy} className="w-full">
          {busy ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
    </AuthShell>
  )
}
