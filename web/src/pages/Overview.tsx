import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { Alert, Badge, Card, PageHeader, Spinner } from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { ROLE_DESCRIPTIONS, ROLE_LABELS, TRADE_LABELS, type Tenant } from '../lib/types'

function daysUntil(iso: string | null): number | null {
  if (!iso) return null
  const ms = new Date(iso).getTime() - Date.now()
  return Math.ceil(ms / 86_400_000)
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="px-5 py-4">
      <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">
        {label}
      </p>
      <p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

export default function Overview() {
  const { me, role } = useAuth()
  const { data: tenant, isPending } = useQuery({
    queryKey: ['tenant'],
    queryFn: () => api.get<Tenant>('/tenants/current'),
  })

  if (isPending || !tenant) {
    return (
      <div className="grid place-items-center py-20 text-slate-400">
        <Spinner className="h-7 w-7" />
      </div>
    )
  }

  const trialDays = daysUntil(tenant.trial_ends_at)

  return (
    <>
      <PageHeader
        title={tenant.name}
        description={`${TRADE_LABELS[tenant.trade_type]} · ${tenant.timezone.replace('America/', '').replace(/_/g, ' ')}`}
        actions={
          <Badge tone={tenant.status === 'trialing' ? 'info' : 'success'}>
            {tenant.status === 'trialing' ? 'Free trial' : tenant.plan}
          </Badge>
        }
      />

      {tenant.status === 'trialing' && trialDays !== null && (
        <div className="mb-6">
          <Alert tone={trialDays <= 3 ? 'warning' : 'info'}>
            {trialDays > 0
              ? `${trialDays} day${trialDays === 1 ? '' : 's'} left in your free trial.`
              : 'Your free trial has ended.'}{' '}
            Billing arrives in milestone 5.
          </Alert>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <Stat
            label="Team"
            value={
              tenant.seat_limit === null
                ? String(tenant.seats_used)
                : `${tenant.seats_used} / ${tenant.seat_limit}`
            }
            hint={tenant.seat_limit === null ? 'Unlimited seats' : 'Active members'}
          />
        </Card>
        <Card>
          <Stat label="Your role" value={role ? ROLE_LABELS[role] : '—'} />
        </Card>
        <Card>
          <Stat
            label="Companies"
            value={String(me?.memberships.length ?? 1)}
            hint="Accounts you belong to"
          />
        </Card>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card title="What you can do here" description="Enforced by the API, not the UI.">
          <div className="px-5 py-4 text-sm text-slate-600">
            {role && <p>{ROLE_DESCRIPTIONS[role]}</p>}
            {role === 'owner' && (
              <p className="mt-3">
                Start by{' '}
                <Link to="/team" className="font-medium text-brand-700 hover:underline">
                  inviting your team
                </Link>
                .
              </p>
            )}
          </div>
        </Card>

        <Card
          title="Milestone 1 of 5"
          description="Foundations: tenancy, auth, roles, audit."
        >
          <ul className="divide-y divide-slate-100 text-sm">
            {[
              ['Multi-tenancy with database-enforced isolation', true],
              ['Authentication and role-based access', true],
              ['Team invitations and seat limits', true],
              ['Audit log', true],
              ['Customers, jobs, dispatch board', false],
              ['Technician mobile view', false],
              ['Invoicing and reporting', false],
              ['Stripe billing', false],
            ].map(([label, done]) => (
              <li key={label as string} className="flex items-center gap-2.5 px-5 py-2.5">
                <span
                  aria-hidden
                  className={
                    done
                      ? 'grid h-4 w-4 place-items-center rounded-full bg-emerald-100 text-[10px] font-bold text-emerald-700'
                      : 'h-4 w-4 rounded-full ring-1 ring-slate-300'
                  }
                >
                  {done ? '✓' : ''}
                </span>
                <span className={done ? 'text-slate-700' : 'text-slate-400'}>
                  {label as string}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  )
}
