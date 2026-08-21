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

/* -------------------------------------------------------------------------- */
/* Milestone 2: customers, addresses, jobs                                     */
/* -------------------------------------------------------------------------- */

export type CustomerKind = 'residential' | 'company'

export type JobType =
  | 'install'
  | 'repair'
  | 'maintenance'
  | 'inspection'
  | 'emergency'
  | 'other'

export type JobPriority = 'low' | 'normal' | 'high' | 'emergency'

export type JobStatus =
  | 'unscheduled'
  | 'scheduled'
  | 'en_route'
  | 'in_progress'
  | 'complete'
  | 'invoiced'
  | 'closed'
  | 'canceled'

export type LineItemKind = 'labor' | 'part'

export interface ServiceAddress {
  id: string
  customer_id: string
  label: string | null
  line1: string
  line2: string | null
  city: string
  state: string
  postal_code: string
  /** Authoritative for scheduling at this address — not the company's zone. */
  timezone: string
  notes: string | null
  is_primary: boolean
  is_active: boolean
  one_line: string
  created_at: string
}

export interface Customer {
  id: string
  kind: CustomerKind
  name: string
  contact_name: string | null
  phone: string | null
  email: string | null
  notes: string | null
  is_active: boolean
  created_at: string
}

export interface CustomerDetail extends Customer {
  addresses: ServiceAddress[]
  open_job_count: number
}

export interface JobAssignment {
  membership_id: string
  is_lead: boolean
  full_name: string | null
  role: Role | null
}

export interface JobLineItem {
  id: string
  kind: LineItemKind
  description: string
  quantity: string
  sort_order: number
  /** Absent entirely for technicians — the API omits the field, not just the value. */
  unit_price_cents?: number | null
  total_cents?: number | null
}

export interface JobSummary {
  id: string
  job_number: string
  title: string
  status: JobStatus
  priority: JobPriority
  job_type: JobType
  customer_id: string
  customer_name: string | null
  address_one_line: string | null
  address_timezone: string | null
  scheduled_date: string | null
  arrival_window_start: string | null
  arrival_window_end: string | null
  window_start_utc: string | null
  window_end_utc: string | null
  lead_membership_id: string | null
  lead_name: string | null
  helper_count: number
}

export interface JobDetail extends JobSummary {
  description: string | null
  customer_notes: string | null
  internal_notes: string | null
  service_address_id: string
  assignments: JobAssignment[]
  line_items: JobLineItem[]
  completed_at: string | null
  canceled_at: string | null
  created_at: string
  /** Present only for roles allowed to see money. */
  total_cents?: number | null
}

export interface ScheduleConflict {
  detail: string
  conflicts: Array<{
    id: string
    job_number: string
    title: string
    scheduled_date: string | null
    arrival_window_start: string | null
    arrival_window_end: string | null
  }>
}

export const JOB_STATUS_LABELS: Record<JobStatus, string> = {
  unscheduled: 'Unscheduled',
  scheduled: 'Scheduled',
  en_route: 'En route',
  in_progress: 'In progress',
  complete: 'Complete',
  invoiced: 'Invoiced',
  closed: 'Closed',
  canceled: 'Canceled',
}

/** Which statuses a job may move to. Mirrors JOB_STATUS_TRANSITIONS on the
 *  server, which is the authority — this only decides which buttons to draw. */
export const JOB_STATUS_NEXT: Record<JobStatus, JobStatus[]> = {
  unscheduled: ['scheduled', 'canceled'],
  scheduled: ['unscheduled', 'en_route', 'canceled'],
  en_route: ['in_progress', 'scheduled', 'canceled'],
  in_progress: ['complete', 'canceled'],
  complete: ['invoiced', 'in_progress'],
  invoiced: ['closed'],
  closed: [],
  canceled: ['unscheduled'],
}

export const JOB_TYPE_LABELS: Record<JobType, string> = {
  install: 'Install',
  repair: 'Repair',
  maintenance: 'Maintenance',
  inspection: 'Inspection',
  emergency: 'Emergency',
  other: 'Other',
}

export const JOB_PRIORITY_LABELS: Record<JobPriority, string> = {
  low: 'Low',
  normal: 'Normal',
  high: 'High',
  emergency: 'Emergency',
}
