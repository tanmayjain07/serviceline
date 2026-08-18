import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { Badge, Button, Card, EmptyState, PageHeader, Spinner } from '../components/ui'
import { api } from '../lib/api'
import type { AuditEntry, Page } from '../lib/types'

const PAGE_SIZE = 25

const ACTION_LABELS: Record<string, string> = {
  'tenant.created': 'Company created',
  'tenant.updated': 'Company settings changed',
  'membership.updated': 'Team member changed',
  'invitation.created': 'Invitation sent',
  'invitation.revoked': 'Invitation revoked',
  'invitation.accepted': 'Invitation accepted',
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return String(value)
}

export default function AuditLog() {
  const [offset, setOffset] = useState(0)
  const [action, setAction] = useState('')

  const { data, isPending, isFetching } = useQuery({
    queryKey: ['audit-log', offset, action],
    queryFn: () => {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
      })
      if (action) params.set('action', action)
      return api.get<Page<AuditEntry>>(`/audit-log?${params}`)
    },
    placeholderData: keepPreviousData,
  })

  const total = data?.total ?? 0
  const showing = data?.items.length ?? 0

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Who changed what, and when. Append-only — entries cannot be edited or deleted, including by us."
      />

      <Card
        title={`${total} ${total === 1 ? 'entry' : 'entries'}`}
        actions={
          <select
            value={action}
            onChange={(event) => {
              setAction(event.target.value)
              setOffset(0)
            }}
            className="rounded-lg bg-white px-2.5 py-1.5 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-brand-500"
          >
            <option value="">All actions</option>
            {Object.entries(ACTION_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        }
      >
        {isPending ? (
          <div className="grid place-items-center py-12 text-slate-400">
            <Spinner className="h-6 w-6" />
          </div>
        ) : showing === 0 ? (
          <EmptyState
            title="Nothing here yet"
            description="Actions taken in this company will appear here."
          />
        ) : (
          <ul className={`divide-y divide-slate-100 ${isFetching ? 'opacity-60' : ''}`}>
            {data?.items.map((entry) => (
              <li key={entry.id} className="px-5 py-3.5">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Badge tone="neutral">
                      {ACTION_LABELS[entry.action] ?? entry.action}
                    </Badge>
                    {entry.entity_label && (
                      <span className="text-sm font-medium text-slate-900">
                        {entry.entity_label}
                      </span>
                    )}
                  </div>
                  <time
                    dateTime={entry.created_at}
                    className="text-xs text-slate-500"
                    title={new Date(entry.created_at).toISOString()}
                  >
                    {new Date(entry.created_at).toLocaleString()}
                  </time>
                </div>

                <p className="mt-1 text-xs text-slate-500">
                  {entry.actor_email ?? 'system'}
                  {entry.ip_address && ` · ${entry.ip_address}`}
                </p>

                {entry.changes && (
                  <dl className="mt-2 space-y-0.5 text-xs">
                    {Object.entries(entry.changes).map(([field, change]) => (
                      <div key={field} className="flex flex-wrap gap-1.5">
                        <dt className="font-medium text-slate-600">{field}:</dt>
                        <dd className="text-slate-500">
                          <span className="line-through">{formatValue(change.from)}</span>
                          {' → '}
                          <span className="text-slate-900">{formatValue(change.to)}</span>
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
              </li>
            ))}
          </ul>
        )}

        {total > PAGE_SIZE && (
          <div className="flex items-center justify-between border-t border-slate-100 px-5 py-3">
            <p className="text-xs text-slate-500">
              {offset + 1}–{offset + showing} of {total}
            </p>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </Card>
    </>
  )
}
