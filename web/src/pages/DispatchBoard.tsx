import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Alert, Badge, Button, PageHeader, Spinner, cx } from '../components/ui'
import { api, ApiError } from '../lib/api'
import {
  PRIORITY_TONE,
  STATUS_TONE,
  dateRange,
  startOfWeek,
  windowLabel,
  zoneHint,
} from '../lib/jobFormat'
import {
  JOB_STATUS_LABELS,
  type JobStatus,
  type JobSummary,
  type Membership,
  type Page,
  type ScheduleConflict,
} from '../lib/types'

const DAYS = 7
const ASSIGNABLE = new Set(['owner', 'dispatcher', 'technician'])

interface PendingMove {
  jobId: string
  jobNumber: string
  membershipId: string | null
  date: string | null
  conflict: ScheduleConflict
}

function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate(),
  ).padStart(2, '0')}`
}

export default function DispatchBoard() {
  const queryClient = useQueryClient()
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()))
  const [dragging, setDragging] = useState<string | null>(null)
  const [hover, setHover] = useState<string | null>(null)
  const [pending, setPending] = useState<PendingMove | null>(null)
  const [error, setError] = useState<string | null>(null)

  const weekOf = isoDate(weekStart)
  const days = useMemo(() => dateRange(weekStart, DAYS), [weekStart])

  const { data: jobs, isPending } = useQuery({
    queryKey: ['board', weekOf],
    queryFn: () =>
      api.get<JobSummary[]>(`/jobs/board?week_of=${weekOf}&days=${DAYS}`),
  })

  const { data: team } = useQuery({
    queryKey: ['memberships'],
    queryFn: () => api.get<Page<Membership>>('/memberships?limit=200'),
  })

  const crew = useMemo(
    () =>
      (team?.items ?? []).filter((m) => m.is_active && ASSIGNABLE.has(m.role)),
    [team],
  )

  const schedule = useMutation({
    mutationFn: (vars: {
      jobId: string
      membershipId: string | null
      date: string | null
      allowConflicts?: boolean
    }) =>
      api.post(`/jobs/${vars.jobId}/schedule`, {
        lead_membership_id: vars.membershipId,
        scheduled_date: vars.date,
        allow_conflicts: vars.allowConflicts ?? false,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['board'] })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      setPending(null)
      setError(null)
    },
    onError: (caught, vars) => {
      // A 409 is not a failure — it is the server reporting a clash and waiting
      // for the dispatcher to confirm. Squeezing a callback between two installs
      // is normal work, so this offers to proceed rather than refusing.
      if (caught instanceof ApiError && caught.status === 409) {
        const body = caught.body as ScheduleConflict | undefined
        const job = jobs?.find((j) => j.id === vars.jobId)
        if (body?.conflicts) {
          setPending({
            jobId: vars.jobId,
            jobNumber: job?.job_number ?? '',
            membershipId: vars.membershipId,
            date: vars.date,
            conflict: body,
          })
          return
        }
      }
      setError(
        caught instanceof ApiError ? caught.detail : 'Could not move that job.',
      )
    },
  })

  // Bucket once per render rather than filtering inside every cell: 25 crew by
  // 7 days is 175 cells, and filtering 200 jobs in each would be 35,000 passes.
  const buckets = useMemo(() => {
    const map = new Map<string, JobSummary[]>()
    for (const job of jobs ?? []) {
      const key = `${job.lead_membership_id ?? 'none'}|${job.scheduled_date ?? 'none'}`
      const list = map.get(key)
      if (list) list.push(job)
      else map.set(key, [job])
    }
    return map
  }, [jobs])

  const tray = buckets.get('none|none') ?? []

  function drop(membershipId: string | null, date: string | null) {
    if (!dragging) return
    setHover(null)
    schedule.mutate({ jobId: dragging, membershipId, date })
    setDragging(null)
  }

  return (
    <>
      <PageHeader
        title="Dispatch board"
        description={`Week of ${weekStart.toLocaleDateString(undefined, { day: 'numeric', month: 'long' })} · ${crew.length} crew · ${jobs?.length ?? 0} open jobs`}
        actions={
          <div className="flex gap-2">
            <Button
              variant="secondary"
              onClick={() => {
                const d = new Date(weekStart)
                d.setDate(d.getDate() - DAYS)
                setWeekStart(d)
              }}
            >
              &larr; Previous
            </Button>
            <Button variant="secondary" onClick={() => setWeekStart(startOfWeek(new Date()))}>
              This week
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                const d = new Date(weekStart)
                d.setDate(d.getDate() + DAYS)
                setWeekStart(d)
              }}
            >
              Next &rarr;
            </Button>
          </div>
        }
      />

      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}

      {pending && (
        <div className="mb-4">
          <Alert tone="warning" title="That would double-book them">
            <p>{pending.conflict.detail}</p>
            <ul className="mt-2 space-y-0.5 text-xs">
              {pending.conflict.conflicts.map((c) => (
                <li key={c.id}>
                  <span className="font-mono">{c.job_number}</span> {c.title} —{' '}
                  {windowLabel(c.arrival_window_start, c.arrival_window_end)}
                </li>
              ))}
            </ul>
            <div className="mt-3 flex gap-2">
              <Button
                variant="secondary"
                loading={schedule.isPending}
                onClick={() =>
                  schedule.mutate({
                    jobId: pending.jobId,
                    membershipId: pending.membershipId,
                    date: pending.date,
                    allowConflicts: true,
                  })
                }
              >
                Book it anyway
              </Button>
              <Button variant="ghost" onClick={() => setPending(null)}>
                Leave it
              </Button>
            </div>
          </Alert>
        </div>
      )}

      {isPending ? (
        <div className="grid place-items-center py-24 text-slate-400">
          <Spinner className="h-8 w-8" />
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_16rem]">
          {/* The board itself scrolls sideways; the page never does. */}
          <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-slate-200">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <th className="sticky left-0 z-10 w-28 bg-slate-50 px-3 py-2 text-left text-xs font-medium text-slate-500">
                    Day
                  </th>
                  {crew.map((member) => (
                    <th
                      key={member.id}
                      className="min-w-52 border-l border-slate-100 bg-slate-50 px-3 py-2 text-left"
                    >
                      <span className="block truncate text-sm font-medium text-slate-800">
                        {member.full_name}
                      </span>
                      <span className="block text-[11px] text-slate-400 capitalize">
                        {member.role}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {days.map((day) => {
                  const [, m, d] = day.split('-')
                  const label = new Date(day + 'T00:00:00').toLocaleDateString(
                    undefined,
                    { weekday: 'short' },
                  )
                  return (
                    <tr key={day} className="border-t border-slate-100">
                      <th className="sticky left-0 z-10 bg-white px-3 py-2 text-left align-top">
                        <span className="block text-sm font-medium text-slate-800">
                          {label}
                        </span>
                        <span className="block text-xs text-slate-400">
                          {d}/{m}
                        </span>
                      </th>
                      {crew.map((member) => {
                        const key = `${member.id}|${day}`
                        const cell = buckets.get(key) ?? []
                        return (
                          <td
                            key={key}
                            onDragOver={(e) => {
                              e.preventDefault()
                              setHover(key)
                            }}
                            onDragLeave={() => setHover((h) => (h === key ? null : h))}
                            onDrop={() => drop(member.id, day)}
                            className={cx(
                              'min-w-52 border-l border-slate-100 p-1.5 align-top transition-colors',
                              hover === key && 'bg-brand-50',
                            )}
                          >
                            <div className="space-y-1.5">
                              {cell.map((job) => (
                                <JobCard
                                  key={job.id}
                                  job={job}
                                  onDragStart={() => setDragging(job.id)}
                                  onDragEnd={() => setDragging(null)}
                                />
                              ))}
                            </div>
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Unassigned tray */}
          <div
            onDragOver={(e) => {
              e.preventDefault()
              setHover('tray')
            }}
            onDragLeave={() => setHover((h) => (h === 'tray' ? null : h))}
            onDrop={() => drop(null, null)}
            className={cx(
              'rounded-xl bg-white p-3 ring-1 ring-slate-200 transition-colors',
              hover === 'tray' && 'bg-brand-50 ring-brand-300',
            )}
          >
            <p className="mb-2 text-sm font-semibold text-slate-900">Unassigned</p>
            <p className="mb-3 text-xs text-slate-500">
              Drag onto the board to assign. Drag back here to unschedule.
            </p>
            <div className="space-y-1.5">
              {tray.length === 0 ? (
                <p className="py-6 text-center text-xs text-slate-400">
                  Everything is assigned.
                </p>
              ) : (
                tray.map((job) => (
                  <JobCard
                    key={job.id}
                    job={job}
                    onDragStart={() => setDragging(job.id)}
                    onDragEnd={() => setDragging(null)}
                  />
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function JobCard({
  job,
  onDragStart,
  onDragEnd,
}: {
  job: JobSummary
  onDragStart: () => void
  onDragEnd: () => void
}) {
  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className="cursor-grab rounded-lg bg-white p-2 text-left ring-1 ring-slate-200 transition-shadow hover:shadow-sm active:cursor-grabbing"
    >
      <div className="flex items-start justify-between gap-1">
        <Link
          to={`/jobs/${job.id}`}
          className="truncate text-xs font-medium text-slate-900 hover:underline"
        >
          {job.title}
        </Link>
        <Badge tone={STATUS_TONE[job.status as JobStatus]}>
          {JOB_STATUS_LABELS[job.status]}
        </Badge>
      </div>
      <p className="mt-0.5 truncate text-[11px] text-slate-500">
        {job.customer_name}
      </p>
      <p className="mt-0.5 text-[11px] text-slate-400">
        {job.arrival_window_start
          ? windowLabel(job.arrival_window_start, job.arrival_window_end)
          : 'No time set'}
        {/* The zone is shown on every card, not just the odd ones: a dispatcher
            covering two timezones needs it visible without having to remember
            which addresses are unusual. */}
        {job.address_timezone && ` · ${zoneHint(job.address_timezone)}`}
      </p>
      {job.priority !== 'normal' && job.priority !== 'low' && (
        <span className="mt-1 inline-block">
          <Badge tone={PRIORITY_TONE[job.priority]}>{job.priority}</Badge>
        </span>
      )}
    </div>
  )
}
