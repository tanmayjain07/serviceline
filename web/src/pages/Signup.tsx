import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import AuthShell from '../components/AuthShell'
import { Alert, Button, Field, SelectField } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { TRADE_LABELS, type TokenPair, type TradeType } from '../lib/types'

/**
 * A short list rather than every IANA zone.
 *
 * These are the zones the client's target market actually works in. The full
 * list is 600 entries and would be a worse experience for a contractor in Ohio.
 * The API accepts any valid IANA name, so nothing is lost.
 */
const TIMEZONES = [
  'America/New_York',
  'America/Detroit',
  'America/Indiana/Indianapolis',
  'America/Indiana/Knox',
  'America/Chicago',
  'America/Denver',
  'America/Phoenix',
  'America/Los_Angeles',
]

export default function Signup() {
  const { signIn } = useAuth()
  const navigate = useNavigate()

  const [form, setForm] = useState({
    company_name: '',
    trade_type: 'hvac' as TradeType,
    timezone: 'America/New_York',
    full_name: '',
    email: '',
    password: '',
  })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function update<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((previous) => ({ ...previous, [key]: value }))
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const pair = await api.post<TokenPair>('/auth/signup', form, true)
      signIn(pair)
      navigate('/', { replace: true })
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.detail
          : 'Something went wrong. Please try again.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell
      title="Start your free trial"
      subtitle="14 days, no credit card. You become the owner of the company account."
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" className="font-medium text-brand-700 hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && <Alert>{error}</Alert>}

        <Field
          label="Company name"
          required
          minLength={2}
          value={form.company_name}
          onChange={(event) => update('company_name', event.target.value)}
          placeholder="Northline Mechanical"
        />

        <div className="grid gap-4 sm:grid-cols-2">
          <SelectField
            label="Trade"
            value={form.trade_type}
            onChange={(event) => update('trade_type', event.target.value as TradeType)}
          >
            {(Object.keys(TRADE_LABELS) as TradeType[]).map((trade) => (
              <option key={trade} value={trade}>
                {TRADE_LABELS[trade]}
              </option>
            ))}
          </SelectField>

          <SelectField
            label="Timezone"
            hint="Your company default."
            value={form.timezone}
            onChange={(event) => update('timezone', event.target.value)}
          >
            {TIMEZONES.map((zone) => (
              <option key={zone} value={zone}>
                {zone.replace('America/', '').replace(/_/g, ' ')}
              </option>
            ))}
          </SelectField>
        </div>

        <hr className="border-slate-100" />

        <Field
          label="Your name"
          required
          value={form.full_name}
          onChange={(event) => update('full_name', event.target.value)}
        />
        <Field
          label="Email"
          type="email"
          autoComplete="username"
          required
          value={form.email}
          onChange={(event) => update('email', event.target.value)}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          minLength={10}
          hint="At least 10 characters. Length beats punctuation."
          value={form.password}
          onChange={(event) => update('password', event.target.value)}
        />

        <Button type="submit" loading={busy} className="w-full">
          Create company
        </Button>
      </form>
    </AuthShell>
  )
}
