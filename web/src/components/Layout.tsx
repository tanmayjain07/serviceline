import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useAuth } from '../lib/auth'
import { ROLE_LABELS, type Role } from '../lib/types'
import { Badge, Button, cx } from './ui'

interface NavItem {
  to: string
  label: string
  /** Roles allowed to SEE this link. The API enforces the same rule again. */
  roles: Role[]
}

const NAV: NavItem[] = [
  { to: '/', label: 'Overview', roles: ['owner', 'dispatcher', 'technician', 'accountant'] },
  { to: '/team', label: 'Team', roles: ['owner', 'dispatcher', 'accountant'] },
  { to: '/settings', label: 'Company settings', roles: ['owner'] },
  { to: '/audit-log', label: 'Audit log', roles: ['owner'] },
]

// Milestone 2 adds Customers, Jobs, and the Dispatch board here. Listing them
// as disabled rather than hiding them keeps the shape of the product visible.
const COMING_SOON = ['Customers', 'Jobs', 'Dispatch board', 'Invoices']

export default function Layout() {
  const { me, role, signOut, switchCompany } = useAuth()
  const navigate = useNavigate()
  const [switching, setSwitching] = useState(false)

  const activeMembership = me?.memberships.find(
    (m) => m.tenant_id === me.active_tenant_id,
  )

  async function handleSwitch(tenantId: string) {
    if (tenantId === me?.active_tenant_id) return
    setSwitching(true)
    try {
      await switchCompany(tenantId)
      navigate('/')
    } finally {
      setSwitching(false)
    }
  }

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <aside className="flex shrink-0 flex-col gap-6 border-b border-slate-200 bg-white px-4 py-5 lg:w-64 lg:border-b-0 lg:border-r">
        <div>
          <div className="flex items-center gap-2">
            <div className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-sm font-bold text-white">
              SL
            </div>
            <span className="text-sm font-semibold text-slate-900">ServiceLine</span>
          </div>

          {me && me.memberships.length > 1 ? (
            <label className="mt-4 block">
              <span className="text-xs font-medium text-slate-500">Company</span>
              <select
                value={me.active_tenant_id ?? ''}
                disabled={switching}
                onChange={(event) => void handleSwitch(event.target.value)}
                className="mt-1 w-full rounded-lg bg-white px-2.5 py-1.5 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-brand-500"
              >
                {me.memberships.map((membership) => (
                  <option key={membership.tenant_id} value={membership.tenant_id}>
                    {membership.tenant_name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            activeMembership && (
              <p className="mt-4 truncate text-sm font-medium text-slate-700">
                {activeMembership.tenant_name}
              </p>
            )
          )}
        </div>

        <nav className="flex-1 space-y-1">
          {NAV.filter((item) => !role || item.roles.includes(role)).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                cx(
                  'block rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-brand-50 text-brand-700'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
                )
              }
            >
              {item.label}
            </NavLink>
          ))}

          <p className="px-3 pt-5 pb-1 text-xs font-medium tracking-wide text-slate-400 uppercase">
            Milestone 2
          </p>
          {COMING_SOON.map((label) => (
            <span
              key={label}
              className="block cursor-not-allowed rounded-lg px-3 py-2 text-sm text-slate-300"
              title="Not built yet — arrives in milestone 2"
            >
              {label}
            </span>
          ))}
        </nav>

        <div className="border-t border-slate-100 pt-4">
          {me && (
            <div className="mb-3">
              <p className="truncate text-sm font-medium text-slate-800">
                {me.full_name}
              </p>
              <p className="truncate text-xs text-slate-500">{me.email}</p>
              {role && (
                <span className="mt-1.5 inline-block">
                  <Badge tone="info">{ROLE_LABELS[role]}</Badge>
                </span>
              )}
            </div>
          )}
          <Button variant="secondary" className="w-full" onClick={signOut}>
            Sign out
          </Button>
        </div>
      </aside>

      <main className="flex-1 px-4 py-6 sm:px-8 sm:py-8">
        <div className="mx-auto max-w-5xl">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
