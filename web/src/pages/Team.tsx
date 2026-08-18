import { useState, type FormEvent } from 'react'
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
  ROLE_DESCRIPTIONS,
  ROLE_LABELS,
  type Invitation,
  type InvitationCreated,
  type Membership,
  type Page,
  type Role,
  type Tenant,
} from '../lib/types'

const ASSIGNABLE_ROLES: Role[] = ['owner', 'dispatcher', 'technician', 'accountant']

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export default function Team() {
  const queryClient = useQueryClient()
  const { me, can } = useAuth()
  const isOwner = can('owner')

  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<Role>('technician')
  const [banner, setBanner] = useState<{ tone: 'success' | 'warning'; text: string } | null>(
    null,
  )
  const [error, setError] = useState<string | null>(null)
  const [lastInviteUrl, setLastInviteUrl] = useState<string | null>(null)

  const members = useQuery({
    queryKey: ['memberships'],
    queryFn: () => api.get<Page<Membership>>('/memberships'),
  })

  const tenant = useQuery({
    queryKey: ['tenant'],
    queryFn: () => api.get<Tenant>('/tenants/current'),
  })

  const invitations = useQuery({
    queryKey: ['invitations'],
    queryFn: () => api.get<Invitation[]>('/invitations'),
    enabled: isOwner,
  })

  const invite = useMutation({
    mutationFn: (body: { email: string; role: Role }) =>
      api.post<InvitationCreated>('/invitations', body),
    onSuccess: (created) => {
      setError(null)
      setInviteEmail('')
      setLastInviteUrl(created.accept_url)
      setBanner({
        tone: 'success',
        text: `Invitation created for ${created.email}.`,
      })
      void queryClient.invalidateQueries({ queryKey: ['invitations'] })
      void queryClient.invalidateQueries({ queryKey: ['tenant'] })
    },
    onError: (caught) => {
      setLastInviteUrl(null)
      setError(caught instanceof ApiError ? caught.detail : 'Could not send that invite.')
    },
  })

  const revoke = useMutation({
    mutationFn: (id: string) => api.delete(`/invitations/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['invitations'] })
      void queryClient.invalidateQueries({ queryKey: ['tenant'] })
    },
  })

  const updateMember = useMutation({
    mutationFn: ({ id, ...body }: { id: string; role?: Role; is_active?: boolean }) =>
      api.patch<Membership>(`/memberships/${id}`, body),
    onSuccess: () => {
      setError(null)
      void queryClient.invalidateQueries({ queryKey: ['memberships'] })
      void queryClient.invalidateQueries({ queryKey: ['tenant'] })
    },
    onError: (caught) => {
      setError(caught instanceof ApiError ? caught.detail : 'Could not save that change.')
    },
  })

  function handleInvite(event: FormEvent) {
    event.preventDefault()
    invite.mutate({ email: inviteEmail, role: inviteRole })
  }

  const seatsFull =
    tenant.data?.seat_limit !== null &&
    tenant.data !== undefined &&
    tenant.data.seats_used >= (tenant.data.seat_limit ?? Infinity)

  return (
    <>
      <PageHeader
        title="Team"
        description={
          tenant.data
            ? tenant.data.seat_limit === null
              ? `${tenant.data.seats_used} active members · unlimited seats`
              : `${tenant.data.seats_used} of ${tenant.data.seat_limit} seats used on the ${tenant.data.plan} plan`
            : undefined
        }
      />

      {banner && (
        <div className="mb-4">
          <Alert tone={banner.tone}>{banner.text}</Alert>
        </div>
      )}
      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}

      {lastInviteUrl && (
        <div className="mb-4">
          <Alert tone="info" title="Send this link to your colleague">
            <p className="mt-1 text-xs text-slate-600">
              Email delivery arrives in milestone 3. Until then the invite link is
              shown once, here — it is not stored and cannot be retrieved again.
            </p>
            <code className="mt-2 block overflow-x-auto rounded bg-white/70 px-2 py-1.5 font-mono text-xs break-all">
              {lastInviteUrl}
            </code>
          </Alert>
        </div>
      )}

      {isOwner && (
        <Card
          className="mb-6"
          title="Invite someone"
          description="They will receive a link that expires in 7 days."
        >
          <form onSubmit={handleInvite} className="grid gap-4 px-5 py-4 sm:grid-cols-[1fr_200px_auto] sm:items-end">
            <Field
              label="Email"
              type="email"
              required
              value={inviteEmail}
              onChange={(event) => setInviteEmail(event.target.value)}
              placeholder="mike@example.com"
            />
            <SelectField
              label="Role"
              value={inviteRole}
              hint={ROLE_DESCRIPTIONS[inviteRole]}
              onChange={(event) => setInviteRole(event.target.value as Role)}
            >
              {ASSIGNABLE_ROLES.map((role) => (
                <option key={role} value={role}>
                  {ROLE_LABELS[role]}
                </option>
              ))}
            </SelectField>
            <Button type="submit" loading={invite.isPending} disabled={seatsFull}>
              Send invite
            </Button>
          </form>
          {seatsFull && (
            <div className="border-t border-slate-100 px-5 py-3">
              <Alert tone="warning">
                All seats on your plan are in use. Deactivate someone or upgrade to
                add more.
              </Alert>
            </div>
          )}
        </Card>
      )}

      <Card title="Members">
        {members.isPending ? (
          <div className="grid place-items-center py-10 text-slate-400">
            <Spinner className="h-6 w-6" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-100 text-xs tracking-wide text-slate-500 uppercase">
                <tr>
                  <th className="px-5 py-2.5 font-medium">Name</th>
                  <th className="px-5 py-2.5 font-medium">Role</th>
                  <th className="px-5 py-2.5 font-medium">Last sign-in</th>
                  <th className="px-5 py-2.5 font-medium">Status</th>
                  {isOwner && <th className="px-5 py-2.5" />}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {members.data?.items.map((member) => {
                  const isSelf = member.user_id === me?.id
                  return (
                    <tr key={member.id} className={member.is_active ? '' : 'bg-slate-50'}>
                      <td className="px-5 py-3">
                        <div className="font-medium text-slate-900">
                          {member.full_name}
                          {isSelf && <span className="ml-1.5 text-xs text-slate-400">(you)</span>}
                        </div>
                        <div className="text-xs text-slate-500">{member.email}</div>
                      </td>
                      <td className="px-5 py-3">
                        {isOwner ? (
                          <select
                            value={member.role}
                            disabled={updateMember.isPending}
                            onChange={(event) =>
                              updateMember.mutate({
                                id: member.id,
                                role: event.target.value as Role,
                              })
                            }
                            className="rounded-md bg-white px-2 py-1 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-brand-500"
                          >
                            {ASSIGNABLE_ROLES.map((role) => (
                              <option key={role} value={role}>
                                {ROLE_LABELS[role]}
                              </option>
                            ))}
                          </select>
                        ) : (
                          ROLE_LABELS[member.role]
                        )}
                      </td>
                      <td className="px-5 py-3 text-slate-500">
                        {formatDate(member.last_login_at)}
                      </td>
                      <td className="px-5 py-3">
                        <Badge tone={member.is_active ? 'success' : 'neutral'}>
                          {member.is_active ? 'Active' : 'Deactivated'}
                        </Badge>
                      </td>
                      {isOwner && (
                        <td className="px-5 py-3 text-right">
                          <Button
                            variant={member.is_active ? 'danger' : 'secondary'}
                            onClick={() =>
                              updateMember.mutate({
                                id: member.id,
                                is_active: !member.is_active,
                              })
                            }
                          >
                            {member.is_active ? 'Deactivate' : 'Reactivate'}
                          </Button>
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {isOwner && (
        <Card className="mt-6" title="Invitations">
          {invitations.isPending ? (
            <div className="grid place-items-center py-10 text-slate-400">
              <Spinner className="h-6 w-6" />
            </div>
          ) : invitations.data?.length === 0 ? (
            <EmptyState
              title="No invitations yet"
              description="Invite a dispatcher or technician to get started."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-100 text-xs tracking-wide text-slate-500 uppercase">
                  <tr>
                    <th className="px-5 py-2.5 font-medium">Email</th>
                    <th className="px-5 py-2.5 font-medium">Role</th>
                    <th className="px-5 py-2.5 font-medium">Expires</th>
                    <th className="px-5 py-2.5 font-medium">Status</th>
                    <th className="px-5 py-2.5" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {invitations.data?.map((invitation) => (
                    <tr key={invitation.id}>
                      <td className="px-5 py-3 text-slate-900">{invitation.email}</td>
                      <td className="px-5 py-3">{ROLE_LABELS[invitation.role]}</td>
                      <td className="px-5 py-3 text-slate-500">
                        {formatDate(invitation.expires_at)}
                      </td>
                      <td className="px-5 py-3">
                        <Badge
                          tone={
                            invitation.status === 'pending'
                              ? 'info'
                              : invitation.status === 'accepted'
                                ? 'success'
                                : 'neutral'
                          }
                        >
                          {invitation.status}
                        </Badge>
                      </td>
                      <td className="px-5 py-3 text-right">
                        {invitation.status === 'pending' && (
                          <Button
                            variant="ghost"
                            onClick={() => revoke.mutate(invitation.id)}
                          >
                            Revoke
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </>
  )
}
