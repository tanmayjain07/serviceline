/**
 * Formatting helpers for jobs.
 *
 * The important one is `windowLabel`. A booked window is a promise in the
 * *service address's* timezone, so it must be shown exactly as it was recorded
 * — never converted into the viewer's local time. A dispatcher in Ohio looking
 * at an Indiana job needs to see the hour the customer was told, not the hour
 * it happens to be on their own clock.
 *
 * Which is why these format the stored local strings rather than parsing
 * window_start_utc: the UTC pair exists for the server's overlap arithmetic,
 * not for display.
 */

import type { JobPriority, JobStatus } from './types'

/** "08:00:00" -> "8:00 AM". Deliberately does not touch timezones. */
export function formatTime(value: string | null): string {
  if (!value) return ''
  const [h, m] = value.split(':')
  const hour = Number(h)
  const suffix = hour < 12 ? 'AM' : 'PM'
  const display = hour % 12 === 0 ? 12 : hour % 12
  return `${display}:${m} ${suffix}`
}

/** The arrival window as the customer was told it. */
export function windowLabel(
  start: string | null,
  end: string | null,
): string {
  if (!start || !end) return 'No time set'
  return `${formatTime(start)} – ${formatTime(end)}`
}

/** "2026-09-10" -> "Thu 10 Sep". Parsed as a plain date, never as an instant. */
export function formatDate(value: string | null): string {
  if (!value) return 'Unscheduled'
  const [y, m, d] = value.split('-').map(Number)
  const date = new Date(y, m - 1, d)
  return date.toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
}

/** A short timezone hint, shown only when it differs from the company's. */
export function zoneHint(timezone: string | null): string {
  if (!timezone) return ''
  const city = timezone.split('/').pop() ?? timezone
  return city.replace(/_/g, ' ')
}

export function formatMoney(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return '—'
  return (cents / 100).toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
  })
}

type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info'

export const STATUS_TONE: Record<JobStatus, Tone> = {
  unscheduled: 'neutral',
  scheduled: 'info',
  en_route: 'info',
  in_progress: 'warning',
  complete: 'success',
  invoiced: 'success',
  closed: 'neutral',
  canceled: 'danger',
}

export const PRIORITY_TONE: Record<JobPriority, Tone> = {
  low: 'neutral',
  normal: 'neutral',
  high: 'warning',
  emergency: 'danger',
}

/** ISO dates for a run of days starting at `from`. */
export function dateRange(from: Date, days: number): string[] {
  const out: string[] = []
  for (let i = 0; i < days; i += 1) {
    const d = new Date(from)
    d.setDate(from.getDate() + i)
    out.push(
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
        d.getDate(),
      ).padStart(2, '0')}`,
    )
  }
  return out
}

/** The Monday of the week containing `date`. */
export function startOfWeek(date: Date): Date {
  const d = new Date(date)
  const day = (d.getDay() + 6) % 7
  d.setDate(d.getDate() - day)
  d.setHours(0, 0, 0, 0)
  return d
}
