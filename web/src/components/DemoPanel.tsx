/**
 * The published demo logins, shown on the sign-in page of the public demo.
 *
 * Two deliberate choices here.
 *
 * First, both companies are listed rather than one. The interesting claim this
 * project makes is that a tenant cannot reach another tenant's data, and a
 * claim like that is worth far more if the reader can test it. Handing over
 * credentials for both sides is the invitation to try.
 *
 * Second, the free-tier cold start is stated up front instead of being hidden.
 * A visitor who clicks "sign in" and waits fifty seconds with no explanation
 * concludes the app is broken. A visitor who was told to expect it concludes
 * the developer knew what they were shipping.
 */

import { Badge } from './ui'

interface DemoAccount {
  label: string
  email: string
  role: string
  note?: string
}

const PASSWORD = 'demo-password'

const ACCOUNTS: DemoAccount[] = [
  {
    label: 'Northline Mechanical',
    email: 'owner@northline.demo',
    role: 'Owner',
    note: 'Full access: team, settings, audit log',
  },
  {
    label: 'Northline Mechanical',
    email: 'tech@northline.demo',
    role: 'Technician',
    note: 'Restricted: cannot see the team or settings',
  },
  {
    label: 'Buckeye Plumbing',
    email: 'owner@buckeye.demo',
    role: 'Owner',
    note: 'A different company. Try to reach Northline data from here.',
  },
  {
    label: 'Both companies',
    email: 'books@shared.demo',
    role: 'Accountant',
    note: 'One person, two companies -- shows the company switcher',
  },
]

export default function DemoPanel({
  onPick,
}: {
  onPick: (email: string, password: string) => void
}) {
  if (import.meta.env.VITE_DEMO_MODE !== 'true') return null

  return (
    <div className="mb-6 rounded-xl bg-slate-50 p-4 ring-1 ring-slate-200">
      <div className="flex items-center gap-2">
        <Badge tone="info">Demo</Badge>
        <p className="text-sm font-semibold text-slate-900">
          Sign in with a sample account
        </p>
      </div>

      <p className="mt-2 text-xs leading-relaxed text-slate-600">
        Two separate companies share this demo. Sign in to one, then the other,
        and confirm neither can see the other&rsquo;s data &mdash; including by
        editing IDs in the API requests.
      </p>

      <ul className="mt-3 space-y-1.5">
        {ACCOUNTS.map((account) => (
          <li key={account.email}>
            <button
              type="button"
              onClick={() => onPick(account.email, PASSWORD)}
              className="w-full rounded-lg bg-white px-3 py-2 text-left ring-1 ring-slate-200 transition-colors hover:bg-brand-50 hover:ring-brand-200"
            >
              <span className="flex items-baseline justify-between gap-2">
                <span className="text-xs font-medium text-slate-900">
                  {account.label}
                </span>
                <span className="text-[11px] uppercase tracking-wide text-slate-500">
                  {account.role}
                </span>
              </span>
              <span className="mt-0.5 block font-mono text-[11px] text-slate-500">
                {account.email}
              </span>
              {account.note && (
                <span className="mt-0.5 block text-[11px] text-slate-500">
                  {account.note}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>

      <p className="mt-3 text-[11px] text-slate-500">
        Password for every account:{' '}
        <span className="font-mono text-slate-700">{PASSWORD}</span>
      </p>
    </div>
  )
}
