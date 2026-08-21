import { useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  PageHeader,
  SelectField,
  Spinner,
} from '../components/ui'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import {
  PRIORITY_TONE,
  STATUS_TONE,
  formatDate,
  windowLabel,
  zoneHint,
} from '../lib/jobFormat'
import {
  JOB_PRIORITY_LABELS,
  JOB_STATUS_LABELS,
  JOB_TYPE_LABELS,
  type Customer,
  type CustomerDetail,
  type JobDetail,
  type JobStatus,
  type JobSummary,
  type Page,
} from '../lib/types'

const OPEN: JobStatus[] = ['unscheduled', 'scheduled', 'en_route', 'in_progress']

export default function Jobs() {
  const { can, role } = useAuth()
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<'open' | 'all'>('open')
  const [showForm, setShowForm] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [customerId, setCustomerId] = useState('')

  const canDispatch = can('owner', 'dispatcher')

  const { data, isPending } = useQuery({
    queryKey: ['jobs', filter],
    queryFn: () => {
      const params = new URLSearchParams({ limit: '100' })
      if (filter === 'open') OPEN.forEach((s) => params.append('status', s))
      return api.get<Page<JobSummary>>(`/jobs?${params}`)
    },
  })

  // Only loaded when the form is open — a technician never sees this at all.
  const { data: customers } = useQuery({
    queryKey: ['customers', ''],
    queryFn: () => api.get<Page<Customer>>('/customers?limit=200'),
    enabled: showForm && canDispatch,
  })

  const { data: chosen } = useQuery({
    queryKey: ['customer', customerId],
    queryFn: () => api.get<CustomerDetail>(`/customers/${customerId}`),
    enabled: Boolean(customerId),
  })

  const create = useMutation({
    mutationFn: (body: unknown) => api.post<JobDetail>('/jobs', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      setShowForm(false)
      setCustomerId('')
      setError(null)
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.detail : 'Could not create the job.'),
  })

  const grouped = useMemo(() => {
    const map = new Map<string, JobSummary[]>()
    for (const job of data?.items ?? []) {
      const key = job.scheduled_date ?? 'unscheduled'
      map.set(key, [...(map.get(key) ?? []), job])
    }
    return [...map.entries()].sort(([a], [b]) =>
      a === 'unscheduled' ? -1 : b === 'unscheduled' ? 1 : a.localeCompare(b),
    )
  }, [data])

  function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const start = String(form.get('arrival_window_start') ?? '')
    const end = String(form.get('arrival_window_end') ?? '')
    const date = String(form.get('scheduled_date') ?? '')

    create.mutate({
      customer_id: form.get('customer_id'),
      service_address_id: form.get('service_address_id'),
      title: String(form.get('title') ?? '').trim(),
      job_type: form.get('job_type'),
      priority: form.get('priority'),
      description: String(form.get('description') ?? '').trim() || null,
      scheduled_date: date || null,
      arrival_window_start: date && start ? `${start}:00` : null,
      arrival_window_end: date && end ? `${end}:00` : null,
    })
  }

  return (
    <>
      <PageHeader
        title="Jobs"
        description={
          role === 'technician'
            ? 'Work assigned to you'
            : data
              ? `${data.total} ${filter === 'open' ? 'open' : 'total'}`
              : undefined
        }
        actions={
          <div className="flex gap-2">
            <SelectField
              label=""
              aria-label="Filter"
              value={filter}
              onChange={(e) => setFilter(e.target.value as 'open' | 'all')}
            >
              <option value="open">Open only</option>
              <option value="all">Everything</option>
            </SelectField>
            {canDispatch && (
              <Button onClick={() => setShowForm((v) => !v)}>
                {showForm ? 'Cancel' : 'New job'}
              </Button>
            )}
          </div>
        }
      />

      {showForm && (
        <Card title="New job" className="mb-6">
          <form onSubmit={handleCreate} className="space-y-4 p-5">
            {error && <Alert>{error}</Alert>}

            <div className="grid gap-4 sm:grid-cols-2">
              <SelectField
                label="Customer"
                name="customer_id"
                required
                value={customerId}
                onChange={(e) => setCustomerId(e.target.value)}
              >
                <option value="">Choose…</option>
                {customers?.items.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </SelectField>

              <SelectField
                label="Service address"
                name="service_address_id"
                required
                disabled={!chosen}
              >
                <option value="">
                  {chosen ? 'Choose…' : 'Pick a customer first'}
                </option>
                {chosen?.addresses.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.one_line} — {zoneHint(a.timezone)}
                  </option>
                ))}
              </SelectField>

              <Field label="Title" name="title" required placeholder="Furnace not igniting" />

              <SelectField label="Type" name="job_type" defaultValue="repair">
                {Object.entries(JOB_TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </SelectField>

              <SelectField label="Priority" name="priority" defaultValue="normal">
                {Object.entries(JOB_PRIORITY_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </SelectField>

              <Field label="Date" name="scheduled_date" type="date" />
              <Field label="Window from" name="arrival_window_start" type="time" />
              <Field
                label="Window to"
                name="arrival_window_end"
                type="time"
                hint="Interpreted in the service address's timezone."
              />
            </div>

            <Field label="Description" name="description" />

            <Button type="submit" loading={create.isPending}>
              Create job
            </Button>
          </form>
        </Card>
      )}

      {isPending ? (
        <div className="grid place-items-center py-16 text-slate-400">
          <Spinner />
        </div>
      ) : !data?.items.length ? (
        <Card>
          <EmptyState
            title="Nothing here"
            description={
              role === 'technician'
                ? 'No work assigned to you yet.'
                : 'Create a job to get started.'
            }
          />
        </Card>
      ) : (
        <div className="space-y-6">
          {grouped.map(([day, list]) => (
            <Card
              key={day}
              title={day === 'unscheduled' ? 'Unscheduled' : formatDate(day)}
              description={`${list.length} job${list.length === 1 ? '' : 's'}`}
            >
              <ul className="divide-y divide-slate-100">
                {list.map((job) => (
                  <li key={job.id}>
                    <Link
                      to={`/jobs/${job.id}`}
                      className="block px-5 py-3 transition-colors hover:bg-slate-50"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs text-slate-400">
                          {job.job_number}
                        </span>
                        <span className="text-sm font-medium text-slate-900">
                          {job.title}
                        </span>
                        <Badge tone={STATUS_TONE[job.status]}>
                          {JOB_STATUS_LABELS[job.status]}
                        </Badge>
                        {job.priority !== 'normal' && job.priority !== 'low' && (
                          <Badge tone={PRIORITY_TONE[job.priority]}>
                            {JOB_PRIORITY_LABELS[job.priority]}
                          </Badge>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-slate-500">
                        {job.customer_name}
                        {job.address_one_line && ` · ${job.address_one_line}`}
                      </p>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {job.arrival_window_start
                          ? windowLabel(job.arrival_window_start, job.arrival_window_end)
                          : 'No time set'}
                        {job.address_timezone && (
                          <span className="text-slate-400">
                            {' '}
                            ({zoneHint(job.address_timezone)})
                          </span>
                        )}
                        {job.lead_name ? ` · ${job.lead_name}` : ' · Unassigned'}
                        {job.helper_count > 0 && ` +${job.helper_count}`}
                      </p>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      )}
    </>
  )
}
