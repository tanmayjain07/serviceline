import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
  Spinner,
} from '../components/ui'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import {
  PRIORITY_TONE,
  STATUS_TONE,
  formatDate,
  formatMoney,
  windowLabel,
  zoneHint,
} from '../lib/jobFormat'
import {
  JOB_PRIORITY_LABELS,
  JOB_STATUS_LABELS,
  JOB_STATUS_NEXT,
  JOB_TYPE_LABELS,
  type JobDetail as Job,
  type JobStatus,
} from '../lib/types'

/** Statuses a technician is allowed to set. The API enforces this too. */
const TECH_ALLOWED: JobStatus[] = ['en_route', 'in_progress', 'complete']

export default function JobDetail() {
  const { jobId = '' } = useParams()
  const { role } = useAuth()
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)

  const { data: job, isPending } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.get<Job>(`/jobs/${jobId}`),
  })

  const changeStatus = useMutation({
    mutationFn: (status: JobStatus) =>
      api.post<Job>(`/jobs/${jobId}/status`, { status }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['job', jobId], updated)
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      queryClient.invalidateQueries({ queryKey: ['board'] })
      setError(null)
    },
    onError: (caught) =>
      setError(
        caught instanceof ApiError ? caught.detail : 'Could not change the status.',
      ),
  })

  if (isPending) {
    return (
      <div className="grid place-items-center py-24 text-slate-400">
        <Spinner className="h-8 w-8" />
      </div>
    )
  }
  if (!job) return <EmptyState title="Job not found" />

  const nextStatuses = JOB_STATUS_NEXT[job.status].filter((s) =>
    role === 'technician' ? TECH_ALLOWED.includes(s) : true,
  )
  const lead = job.assignments.find((a) => a.is_lead)
  const helpers = job.assignments.filter((a) => !a.is_lead)
  // Technicians receive a response with no price fields at all, so this is a
  // check for absence rather than for null.
  const showsMoney = 'total_cents' in job

  return (
    <>
      <PageHeader
        title={job.title}
        description={`${job.job_number} · ${JOB_TYPE_LABELS[job.job_type]} · ${job.customer_name ?? ''}`}
        actions={
          <Link to="/jobs">
            <Button variant="ghost">Back to jobs</Button>
          </Link>
        }
      />

      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}

      <div className="mb-6 flex flex-wrap items-center gap-2">
        <Badge tone={STATUS_TONE[job.status]}>{JOB_STATUS_LABELS[job.status]}</Badge>
        <Badge tone={PRIORITY_TONE[job.priority]}>
          {JOB_PRIORITY_LABELS[job.priority]} priority
        </Badge>
        {nextStatuses.map((status) => (
          <Button
            key={status}
            variant="secondary"
            loading={changeStatus.isPending && changeStatus.variables === status}
            onClick={() => changeStatus.mutate(status)}
          >
            Mark {JOB_STATUS_LABELS[status].toLowerCase()}
          </Button>
        ))}
        {!nextStatuses.length && (
          <span className="text-sm text-slate-400">This job is finished.</span>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <div className="space-y-6">
          <Card title="Schedule">
            <dl className="grid gap-4 p-5 sm:grid-cols-2">
              <div>
                <dt className="text-xs font-medium text-slate-500">Date</dt>
                <dd className="text-sm text-slate-900">
                  {formatDate(job.scheduled_date)}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-medium text-slate-500">
                  Arrival window
                </dt>
                <dd className="text-sm text-slate-900">
                  {windowLabel(job.arrival_window_start, job.arrival_window_end)}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-slate-500">
                  Service address
                </dt>
                <dd className="text-sm text-slate-900">{job.address_one_line}</dd>
                {job.address_timezone && (
                  <dd className="mt-0.5 font-mono text-[11px] text-slate-400">
                    Times shown in {zoneHint(job.address_timezone)} —{' '}
                    {job.address_timezone}
                  </dd>
                )}
              </div>
            </dl>
          </Card>

          {(job.description || job.customer_notes || job.internal_notes) && (
            <Card title="Notes">
              <div className="space-y-4 p-5">
                {job.description && (
                  <div>
                    <p className="text-xs font-medium text-slate-500">Description</p>
                    <p className="text-sm whitespace-pre-wrap text-slate-800">
                      {job.description}
                    </p>
                  </div>
                )}
                {job.customer_notes && (
                  <div>
                    <p className="text-xs font-medium text-slate-500">
                      Customer notes
                    </p>
                    <p className="text-sm whitespace-pre-wrap text-slate-800">
                      {job.customer_notes}
                    </p>
                  </div>
                )}
                {job.internal_notes && (
                  <div className="rounded-lg bg-amber-50 p-3 ring-1 ring-amber-200">
                    <p className="text-xs font-medium text-amber-800">
                      Internal — never shown to the customer
                    </p>
                    <p className="text-sm whitespace-pre-wrap text-amber-900">
                      {job.internal_notes}
                    </p>
                  </div>
                )}
              </div>
            </Card>
          )}

          <Card
            title="Labour and parts"
            description={
              showsMoney ? undefined : 'Pricing is not shown to technicians.'
            }
          >
            {!job.line_items.length ? (
              <EmptyState title="Nothing logged yet" />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-left text-xs text-slate-500 uppercase">
                      <th className="px-5 py-2 font-medium">Item</th>
                      <th className="px-5 py-2 font-medium">Qty</th>
                      {showsMoney && (
                        <th className="px-5 py-2 text-right font-medium">Total</th>
                      )}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {job.line_items.map((item) => (
                      <tr key={item.id}>
                        <td className="px-5 py-2">
                          <span className="text-slate-900">{item.description}</span>
                          <span className="ml-2 text-xs text-slate-400">
                            {item.kind === 'labor' ? 'Labour' : 'Part'}
                          </span>
                        </td>
                        <td className="px-5 py-2 tabular-nums text-slate-600">
                          {item.quantity}
                        </td>
                        {showsMoney && (
                          <td className="px-5 py-2 text-right tabular-nums text-slate-900">
                            {formatMoney(item.total_cents)}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                  {showsMoney && (
                    <tfoot>
                      <tr className="border-t border-slate-200">
                        <td className="px-5 py-2 font-medium text-slate-900" colSpan={2}>
                          Total
                        </td>
                        <td className="px-5 py-2 text-right font-medium tabular-nums text-slate-900">
                          {formatMoney(job.total_cents)}
                        </td>
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
            )}
          </Card>
        </div>

        <Card title="Crew">
          {!job.assignments.length ? (
            <EmptyState
              title="Nobody assigned"
              description="Assign a lead from the dispatch board."
            />
          ) : (
            <ul className="divide-y divide-slate-100">
              {lead && (
                <li className="flex items-center justify-between px-5 py-3">
                  <span className="text-sm text-slate-900">{lead.full_name}</span>
                  <Badge tone="info">Lead</Badge>
                </li>
              )}
              {helpers.map((helper) => (
                <li
                  key={helper.membership_id}
                  className="flex items-center justify-between px-5 py-3"
                >
                  <span className="text-sm text-slate-700">{helper.full_name}</span>
                  <Badge tone="neutral">Helper</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  )
}
