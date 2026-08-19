/**
 * Types mirroring the API's schemas.
 *
 * These are hand-written for milestone 1. From milestone 2 they should be
 * generated from the OpenAPI document that FastAPI already serves at
 * /openapi.json, so the frontend and backend cannot silently drift apart.
 */

export type Role = 'owner' | 'dispatcher' | 'technician' | 'accountant'
export type Plan = 'trial' | 'starter' | 'pro' | 'business'
export type TenantStatus =
  | 'trialing'
  | 'active'
  | 'past_due'
  | 'canceled'
  | 'suspended'
export type TradeType =
  | 'hvac'
  | 'plumbing'
  | 'electrical'
  | 'multi_trade'
  | 'other'

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  tenant_id: string | null
  role: Role | null
}

export interface MembershipSummary {
  tenant_id: string
  tenant_name: string
  tenant_slug: string
  role: Role
  is_active: boolean
}

export interface Me {
  id: string
  email: string
  full_name: string
  is_superadmin: boolean
  active_tenant_id: string | null
  active_role: Role | null
  memberships: MembershipSummary[]
}

export interface Tenant {
  id: string
  name: string
  slug: string
  trade_type: TradeType
  timezone: string
  plan: Plan
  status: TenantStatus
  trial_ends_at: string | null
  created_at: string
  seat_limit: number | null
  seats_used: number
}

export interface Membership {
  id: string
  tenant_id: string
  user_id: string
  role: Role
  is_active: boolean
  created_at: string
  email: string
  full_name: string
  last_login_at: string | null
}

export interface Invitation {
  id: string
  tenant_id: string
  email: string
  role: Role
  expires_at: string
  accepted_at: string | null
  revoked_at: string | null
  created_at: string
  status: 'pending' | 'accepted' | 'revoked' | 'expired'
}

export interface InvitationCreated extends Invitation {
  accept_url: string
}

export interface InvitationPreview {
  tenant_name: string
  email: string
  role: Role
  expires_at: string
  requires_signup: boolean
}

/**
 * A single field in an audit entry.
 *
 * Two shapes reach the client, because two different things are being
 * recorded. An update carries a before/after pair; a creation carries the
 * value the row started with, where "before" would be meaningless. Modelling
 * only the diff shape is what produced entries rendering as "role: — → —".
 */
export type AuditDiff = { from: unknown; to: unknown }
export type AuditChange = AuditDiff | string | number | boolean | null

export function isAuditDiff(change: AuditChange): change is AuditDiff {
  return (
    typeof change === 'object' &&
    change !== null &&
    ('from' in change || 'to' in change)
  )
}

export interface AuditEntry {
  id: string
  action: string
  entity_type: string
  entity_id: string | null
  entity_label: string | null
  actor_user_id: string | null
  actor_email: string | null
  changes: Record<string, AuditChange> | null
  ip_address: string | null
  created_at: string
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export const ROLE_LABELS: Record<Role, string> = {
  owner: 'Owner',
  dispatcher: 'Dispatcher',
  technician: 'Technician',
  accountant: 'Accountant',
}

export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  owner: 'Full access, including billing and team management.',
  dispatcher: 'Schedules jobs and manages customers. No billing access.',
  technician: 'Sees only their own jobs. Cannot see pricing.',
  accountant: 'Read-only access to reports and exports.',
}

export const TRADE_LABELS: Record<TradeType, string> = {
  hvac: 'HVAC',
  plumbing: 'Plumbing',
  electrical: 'Electrical',
  multi_trade: 'Multi-trade',
  other: 'Other',
}
