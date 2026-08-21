import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  PageHeader,
  Spinner,
} from '../components/ui'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatDate, windowLabel, zoneHint } from '../lib/jobFormat'
import type { CustomerDetail as Customer, JobSummary, Page } from '../lib/types'

export default function CustomerDetail() {
  const { customerId = '' } = useParams()
  const { can } = useAuth()
  const queryClient = useQueryClient()
  const [showAddress, setShowAddress] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canManage = can('owner', 'dispatcher')

  const { data: customer, isPending } = useQuery({
    queryKey: ['customer', customerId],
    queryFn: () => api.get<Customer>(`/customers/${customerId}`),
  })

  const { data: jobs } = useQuery({
    queryKey: ['customer-jobs', customerId],
    queryFn: () =>
      api.get<Page<JobSummary>>(`/jobs?customer_id=${customerId}&limit=50`),
    enabled: Boolean(customer),
  })

  const addAddress = useMutation({
    mutationFn: (body: unknown) =>
      api.post(`/customers/${customerId}/addresses`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['customer', customerId] })
      setShowAddress(false)
      setError(null)
    },
    onError: (caught) =>
      setError(
        caught instanceof ApiError ? caught.detail : 'Could not add the address.',
      ),
  })

  if (isPending) {
    return (
      <div className="grid place-items-center py-24 text-slate-400">
        <Spinner className="h-8 w-8" />
      </div>
    )
  }
  if (!customer) {
    return <EmptyState title="Customer not found" />
  }

  function handleAddAddress(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    addAddress.mutate({
      label: String(form.get('label') ?? '').trim() || null,
      line1: String(form.get('line1') ?? '').trim(),
      city: String(form.get('city') ?? '').trim(),
      state: String(form.get('state') ?? '').trim(),
      postal_code: String(form.get('postal_code') ?? '').trim(),
      timezone: String(form.get('timezone') ?? '').trim() || null,
    })
  }

  return (
    <>
      <PageHeader
        title={customer.name}
        description={
          [
            customer.kind === 'company' ? 'Company' : 'Residential',
            customer.contact_name,
            customer.phone,
          ]
            .filter(Boolean)
            .join(' · ')
        }
        actions={
          <Link to="/customers">
            <Button variant="ghost">Back to customers</Button>
          </Link>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <Card
          title="Jobs"
          description={`${jobs?.total ?? 0} recorded, ${customer.open_job_count} still open`}
        >
          {!jobs?.items.length ? (
            <EmptyState
              title="No jobs yet"
              description="Work booked for this customer will appear here."
            />
          ) : (
            <ul className="divide-y divide-slate-100">
              {jobs.items.map((job) => (
                <li key={job.id}>
                  <Link
                    to={`/jobs/${job.id}`}
                    className="block px-5 py-3 transition-colors hover:bg-slate-50"
                  >
                    <span className="flex items-center justify-between gap-3">
                      <span className="truncate text-sm font-medium text-slate-900">
                        {job.title}
                      </span>
                      <span className="shrink-0 font-mono text-xs text-slate-400">
                        {job.job_number}
                      </span>
                    </span>
                    <span className="mt-0.5 block text-xs text-slate-500">
                      {formatDate(job.scheduled_date)}
                      {job.arrival_window_start &&
                        ` · ${windowLabel(job.arrival_window_start, job.arrival_window_end)}`}
                      {job.lead_name && ` · ${job.lead_name}`}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card
          title="Service addresses"
          description="Scheduling uses each address's own timezone"
          actions={
            canManage && (
              <Button
                variant="secondary"
                onClick={() => setShowAddress((v) => !v)}
              >
                {showAddress ? 'Cancel' : 'Add'}
              </Button>
            )
          }
        >
          {showAddress && (
            <form
              onSubmit={handleAddAddress}
              className="space-y-3 border-b border-slate-100 p-5"
            >
              {error && <Alert>{error}</Alert>}
              <Field label="Label" name="label" placeholder="Main office" />
              <Field label="Street" name="line1" required />
              <div className="grid grid-cols-3 gap-3">
                <Field label="City" name="city" required />
                <Field label="State" name="state" required />
                <Field label="ZIP" name="postal_code" required />
              </div>
              <Field
                label="Timezone"
                name="timezone"
                placeholder="America/Indiana/Knox"
                hint="Blank uses the company default."
              />
              <Button type="submit" loading={addAddress.isPending}>
                Add address
              </Button>
            </form>
          )}

          {!customer.addresses.length ? (
            <EmptyState
              title="No address on file"
              description="Add one before booking work."
            />
          ) : (
            <ul className="divide-y divide-slate-100">
              {customer.addresses.map((address) => (
                <li key={address.id} className="px-5 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      {address.label && (
                        <p className="text-xs font-medium text-slate-500">
                          {address.label}
                        </p>
                      )}
                      <p className="text-sm text-slate-900">{address.one_line}</p>
                    </div>
                    {address.is_primary && <Badge tone="info">Primary</Badge>}
                  </div>
                  <p className="mt-1 font-mono text-[11px] text-slate-400">
                    {zoneHint(address.timezone)} · {address.timezone}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  )
}
