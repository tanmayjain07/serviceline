import { useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Alert, Badge, Button, Card, Field, PageHeader, SelectField, Spinner } from '../components/ui'
import { api, ApiError } from '../lib/api'
import { TRADE_LABELS, type Tenant, type TradeType } from '../lib/types'

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

export default function Settings() {
  const queryClient = useQueryClient()
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: tenant, isPending } = useQuery({
    queryKey: ['tenant'],
    queryFn: () => api.get<Tenant>('/tenants/current'),
  })

  const [form, setForm] = useState({
    name: '',
    trade_type: 'hvac' as TradeType,
    timezone: 'America/New_York',
  })

  useEffect(() => {
    if (tenant) {
      setForm({
        name: tenant.name,
        trade_type: tenant.trade_type,
        timezone: tenant.timezone,
      })
    }
  }, [tenant])

  const save = useMutation({
    mutationFn: (body: typeof form) => api.patch<Tenant>('/tenants/current', body),
    onSuccess: () => {
      setError(null)
      setSaved(true)
      void queryClient.invalidateQueries({ queryKey: ['tenant'] })
      void queryClient.invalidateQueries({ queryKey: ['me'] })
      setTimeout(() => setSaved(false), 3000)
    },
    onError: (caught) => {
      setError(caught instanceof ApiError ? caught.detail : 'Could not save.')
    },
  })

  if (isPending || !tenant) {
    return (
      <div className="grid place-items-center py-20 text-slate-400">
        <Spinner className="h-7 w-7" />
      </div>
    )
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    save.mutate(form)
  }

  return (
    <>
      <PageHeader
        title="Company settings"
        description="Only owners can change these. Every change is written to the audit log."
      />

      {saved && (
        <div className="mb-4">
          <Alert tone="success">Saved.</Alert>
        </div>
      )}
      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}

      <Card title="Details">
        <form onSubmit={handleSubmit} className="space-y-4 px-5 py-5">
          <Field
            label="Company name"
            required
            minLength={2}
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />

          <div className="grid gap-4 sm:grid-cols-2">
            <SelectField
              label="Trade"
              value={form.trade_type}
              onChange={(event) =>
                setForm({ ...form, trade_type: event.target.value as TradeType })
              }
            >
              {(Object.keys(TRADE_LABELS) as TradeType[]).map((trade) => (
                <option key={trade} value={trade}>
                  {TRADE_LABELS[trade]}
                </option>
              ))}
            </SelectField>

            <SelectField
              label="Default timezone"
              hint="From milestone 2, each service address carries its own timezone. This is only the default."
              value={form.timezone}
              onChange={(event) => setForm({ ...form, timezone: event.target.value })}
            >
              {TIMEZONES.map((zone) => (
                <option key={zone} value={zone}>
                  {zone.replace('America/', '').replace(/_/g, ' ')}
                </option>
              ))}
            </SelectField>
          </div>

          <div className="flex justify-end pt-1">
            <Button type="submit" loading={save.isPending}>
              Save changes
            </Button>
          </div>
        </form>
      </Card>

      <Card className="mt-6" title="Plan">
        <dl className="divide-y divide-slate-100 text-sm">
          <div className="flex items-center justify-between px-5 py-3">
            <dt className="text-slate-600">Current plan</dt>
            <dd>
              <Badge tone="info">{tenant.plan}</Badge>
            </dd>
          </div>
          <div className="flex items-center justify-between px-5 py-3">
            <dt className="text-slate-600">Status</dt>
            <dd className="text-slate-900">{tenant.status}</dd>
          </div>
          <div className="flex items-center justify-between px-5 py-3">
            <dt className="text-slate-600">Seats</dt>
            <dd className="text-slate-900">
              {tenant.seat_limit === null
                ? `${tenant.seats_used} (unlimited)`
                : `${tenant.seats_used} of ${tenant.seat_limit}`}
            </dd>
          </div>
          <div className="flex items-center justify-between px-5 py-3">
            <dt className="text-slate-600">Company URL slug</dt>
            <dd className="font-mono text-xs text-slate-500">{tenant.slug}</dd>
          </div>
        </dl>
        <div className="border-t border-slate-100 px-5 py-3">
          <p className="text-xs text-slate-500">
            Subscription management arrives in milestone 5, through Stripe's hosted
            customer portal.
          </p>
        </div>
      </Card>
    </>
  )
}
