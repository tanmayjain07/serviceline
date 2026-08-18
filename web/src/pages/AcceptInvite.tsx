import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import AuthShell from '../components/AuthShell'
import { Alert, Button, Field, Spinner } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import {
  ROLE_DESCRIPTIONS,
  ROLE_LABELS,
  type InvitationPreview,
  type TokenPair,
} from '../lib/types'

export default function AcceptInvite() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const { signIn } = useAuth()
  const navigate = useNavigate()

  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const {
    data: preview,
    isPending,
    isError,
  } = useQuery({
    queryKey: ['invite-preview', token],
    queryFn: () =>
      api.get<InvitationPreview>(
        `/invitations/preview?token=${encodeURIComponent(token)}`,
      ),
    enabled: token.length > 0,
    retry: false,
  })

  if (!token) {
    return (
      <AuthShell title="Invitation link is incomplete">
        <Alert>
          This link is missing its token. Ask whoever invited you to send it
          again.
        </Alert>
      </AuthShell>
    )
  }

  if (isPending) {
    return (
      <AuthShell title="Checking your invitation">
        <div className="grid place-items-center py-6 text-slate-400">
          <Spinner className="h-6 w-6" />
        </div>
      </AuthShell>
    )
  }

  if (isError || !preview) {
    // Expired, revoked, already used, or simply wrong. The API deliberately
    // does not distinguish between these, so neither does this screen.
    return (
      <AuthShell
        title="This invitation is no longer valid"
        footer={
          <Link to="/login" className="font-medium text-brand-700 hover:underline">
            Go to sign in
          </Link>
        }
      >
        <Alert tone="warning">
          It may have expired, been revoked, or already been used. Ask the
          company owner to send you a new one.
        </Alert>
      </AuthShell>
    )
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const body = preview!.requires_signup
        ? { token, full_name: fullName, password }
        : { token, password }
      const pair = await api.post<TokenPair>('/invitations/accept', body, true)
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
      title={`Join ${preview.tenant_name}`}
      subtitle={`You have been invited as a ${ROLE_LABELS[preview.role].toLowerCase()}.`}
    >
      <div className="mb-5 rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-600 ring-1 ring-slate-200">
        <p className="font-medium text-slate-800">
          {ROLE_LABELS[preview.role]}
        </p>
        <p className="mt-0.5">{ROLE_DESCRIPTIONS[preview.role]}</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        {error && <Alert>{error}</Alert>}

        <Field label="Email" value={preview.email} readOnly disabled />

        {preview.requires_signup ? (
          <>
            <Field
              label="Your name"
              required
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
            />
            <Field
              label="Choose a password"
              type="password"
              autoComplete="new-password"
              required
              minLength={10}
              hint="At least 10 characters."
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </>
        ) : (
          <Field
            label="Your existing ServiceLine password"
            type="password"
            autoComplete="current-password"
            required
            hint="This email already has an account, so we need its password to add you to this company."
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        )}

        <Button type="submit" loading={busy} className="w-full">
          Join {preview.tenant_name}
        </Button>
      </form>
    </AuthShell>
  )
}
