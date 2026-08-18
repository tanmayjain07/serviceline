import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'

import AuthShell from '../components/AuthShell'
import { Button, Spinner } from '../components/ui'
import { useAuth } from '../lib/auth'
import { ROLE_LABELS } from '../lib/types'

/**
 * Shown when one person belongs to more than one company.
 *
 * Two of the client's contractors share a bookkeeper, so this is a real case.
 * Until a company is chosen the access token carries no tenant, and no company
 * data is reachable at all.
 */
export default function ChooseCompany() {
  const { me, isAuthenticated, isLoading, switchCompany, signOut } = useAuth()
  const navigate = useNavigate()
  const [busyId, setBusyId] = useState<string | null>(null)

  if (isLoading) {
    return (
      <div className="grid min-h-screen place-items-center text-slate-400">
        <Spinner className="h-8 w-8" />
      </div>
    )
  }
  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (me && me.active_tenant_id) return <Navigate to="/" replace />

  async function choose(tenantId: string) {
    setBusyId(tenantId)
    try {
      await switchCompany(tenantId)
      navigate('/', { replace: true })
    } finally {
      setBusyId(null)
    }
  }

  return (
    <AuthShell
      title="Choose a company"
      subtitle="Your account belongs to more than one."
      footer={
        <button onClick={signOut} className="text-slate-500 hover:underline">
          Sign out
        </button>
      }
    >
      <ul className="space-y-2">
        {me?.memberships.map((membership) => (
          <li key={membership.tenant_id}>
            <button
              onClick={() => void choose(membership.tenant_id)}
              disabled={busyId !== null}
              className="flex w-full items-center justify-between gap-3 rounded-lg px-4 py-3 text-left ring-1 ring-slate-200 transition-colors hover:bg-slate-50 disabled:opacity-60"
            >
              <span>
                <span className="block text-sm font-medium text-slate-900">
                  {membership.tenant_name}
                </span>
                <span className="block text-xs text-slate-500">
                  {ROLE_LABELS[membership.role]}
                </span>
              </span>
              {busyId === membership.tenant_id ? (
                <Spinner className="h-4 w-4 text-slate-400" />
              ) : (
                <span aria-hidden className="text-slate-400">
                  &rarr;
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-4">
        <Button variant="ghost" className="w-full" onClick={signOut}>
          Use a different account
        </Button>
      </div>
    </AuthShell>
  )
}
