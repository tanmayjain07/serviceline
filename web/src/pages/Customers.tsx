import { useState, type FormEvent } from 'react'
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
import type { Customer, CustomerDetail, Page } from '../lib/types'

const PAGE_SIZE = 25

export default function Customers() {
  const { can } = useAuth()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canManage = can('owner', 'dispatcher')

  const { data, isPending } = useQuery({
    queryKey: ['customers', query],
    queryFn: () => {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE) })
      if (query) params.set('search', query)
      return api.get<Page<Customer>>(`/customers?${params}`)
    },
  })

  const create = useMutation({
    mutationFn: (body: unknown) => api.post<CustomerDetail>('/customers', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['customers'] })
      setShowForm(false)
      setError(null)
    },
    onError: (caught) =>
      setError(
        caught instanceof ApiError ? caught.detail : 'Could not save the customer.',
      ),
  })

  function handleSearch(event: FormEvent) {
    event.preventDefault()
    setQuery(search.trim())
  }

  function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const line1 = String(form.get('line1') ?? '').trim()

    create.mutate({
      kind: form.get('kind'),
      name: String(form.get('name') ?? '').trim(),
      contact_name: String(form.get('contact_name') ?? '').trim() || null,
      phone: String(form.get('phone') ?? '').trim() || null,
      // An address is optional: a dispatcher taking a call often has the name
      // before the street.
      address: line1
        ? {
            line1,
            city: String(form.get('city') ?? '').trim(),
            state: String(form.get('state') ?? '').trim(),
            postal_code: String(form.get('postal_code') ?? '').trim(),
            timezone: String(form.get('timezone') ?? '').trim() || null,
          }
        : null,
    })
  }

  return (
    <>
      <PageHeader
        title="Customers"
        description={
          data ? `${data.total} on the books` : 'People and companies you work for'
        }
        actions={
          canManage && (
            <Button onClick={() => setShowForm((v) => !v)}>
              {showForm ? 'Cancel' : 'New customer'}
            </Button>
          )
        }
      />

      {showForm && (
        <Card title="New customer" className="mb-6">
          <form onSubmit={handleCreate} className="space-y-4 p-5">
            {error && <Alert>{error}</Alert>}

            <div className="grid gap-4 sm:grid-cols-2">
              <SelectField label="Type" name="kind" defaultValue="residential">
                <option value="residential">Residential</option>
                <option value="company">Company</option>
              </SelectField>
              <Field label="Name" name="name" required placeholder="Whitcomb" />
              <Field label="Contact" name="contact_name" placeholder="Dale Whitcomb" />
              <Field label="Phone" name="phone" placeholder="555-0142" />
            </div>

            <div className="border-t border-slate-100 pt-4">
              <p className="mb-3 text-sm font-medium text-slate-700">
                Service address{' '}
                <span className="font-normal text-slate-400">— optional</span>
              </p>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Street" name="line1" placeholder="88 Elevator Rd" />
                <Field label="City" name="city" placeholder="Knox" />
                <Field label="State" name="state" placeholder="IN" />
                <Field label="ZIP" name="postal_code" placeholder="46534" />
                <Field
                  label="Timezone"
                  name="timezone"
                  placeholder="America/Indiana/Knox"
                  hint="Leave blank to use the company default. Scheduling uses this, not the company's."
                />
              </div>
            </div>

            <Button type="submit" loading={create.isPending}>
              Create customer
            </Button>
          </form>
        </Card>
      )}

      <Card>
        <form onSubmit={handleSearch} className="flex gap-2 border-b border-slate-100 p-4">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name, phone, or street"
            className="w-full rounded-lg px-3 py-2 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-brand-500"
          />
          <Button type="submit" variant="secondary">
            Search
          </Button>
          {query && (
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setSearch('')
                setQuery('')
              }}
            >
              Clear
            </Button>
          )}
        </form>

        {isPending ? (
          <div className="grid place-items-center py-16 text-slate-400">
            <Spinner />
          </div>
        ) : !data?.items.length ? (
          <EmptyState
            title={query ? 'Nothing matched' : 'No customers yet'}
            description={
              query
                ? 'Try a different name, phone number, or street.'
                : 'Add the first one to start booking work.'
            }
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {data.items.map((customer) => (
              <li key={customer.id}>
                <Link
                  to={`/customers/${customer.id}`}
                  className="flex items-center justify-between gap-4 px-5 py-3 transition-colors hover:bg-slate-50"
                >
                  <span className="min-w-0">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium text-slate-900">
                        {customer.name}
                      </span>
                      {customer.kind === 'company' && (
                        <Badge tone="neutral">Company</Badge>
                      )}
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-slate-500">
                      {[customer.contact_name, customer.phone]
                        .filter(Boolean)
                        .join(' · ') || 'No contact details'}
                    </span>
                  </span>
                  <span aria-hidden className="text-slate-300">
                    &rarr;
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  )
}
