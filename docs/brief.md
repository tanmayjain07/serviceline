# The client brief, and what changed after asking

> **This is a simulated engagement.** ServiceLine is a personal project. There is
> no real client, no money changed hands, and "Northline Mechanical" is not a
> real company. The brief below was written as a realistic exercise in scoping a
> multi-tenant SaaS build, and the decisions in it genuinely drive the code — so
> it is kept here rather than discarded. Nothing in this file should be read as a
> record of paid work.

The full exchange it was distilled from — the brief, the reply that questioned
it, the answers, and the revised scope — is in
**[brief-transcript.md](brief-transcript.md)**.

Its purpose is practical: milestone 1 is built, and milestones 2 to 5 depend on
decisions that exist nowhere in the schema. Why scheduling timezones live on the
service address rather than the company, why invoice numbers must be gapless
while job numbers need not be, why a job has one lead technician rather than
several equals — none of that is derivable from the code. It is written down
here so the next person to open this repository, including a future me, does not
have to re-decide it.

---

## 1. The premise

A contractor running a 14-technician HVAC and plumbing company in Ohio has spent
three years running scheduling and dispatch on an Airtable-and-Zapier
arrangement. Three other contractors in their network have asked to buy it. They
want it turned into a product they can sell as a subscription.

Each contractor company is a **tenant**. The stated non-negotiable:

> "I've been burned once already by a developer who built everything in one
> shared database with no separation between customers, and I found out when
> Company A could see Company B's jobs."

That single sentence is why this project exists in the shape it does. Every
architectural decision in [architecture.md](architecture.md) traces back to it.

**Stated budget:** $7,500 fixed price, 10 weeks.
**Actual scope as written:** $14,000–18,000 at senior rates.
That gap is dealt with in section 5.

---

## 2. Roles

Four, inside each tenant:

| Role | May do |
|---|---|
| **Owner** | Everything, including billing and the subscription. One per tenant, transferable. |
| **Dispatcher** | Create and assign jobs, manage the schedule and customers. No billing. |
| **Technician** | Only their own assigned jobs. Update status, log time and parts, upload photos, capture a signature. **Cannot see pricing or other technicians' schedules.** |
| **Accountant** | Reports and exports only. No edits. |

Enforced server-side. From the brief: *"I know enough to check whether hiding a
button is your idea of security."*

---

## 3. Scope as originally stated

**In:** onboarding and tenant provisioning · customers with multiple service
addresses · jobs and work orders · a dispatch board · a technician mobile view ·
light invoicing · reporting · Stripe subscriptions · an audit log.

**Explicitly out of v1:** inventory · GPS and route optimisation · payroll ·
QuickBooks sync · a customer self-service portal · native mobile apps · SMS.

Pricing to launch with:

| Plan | Price | Limits |
|---|---|---|
| Starter | $49/mo | 5 technicians, 200 jobs/mo |
| Pro | $149/mo | 20 technicians, unlimited jobs |
| Business | $349/mo | Unlimited technicians, custom branding |

14-day trial, no card up front.

---

## 4. What the brief got wrong

This is the part worth keeping. A brief is a starting position, not a
specification, and the questions that changed the design were mostly about
things the brief did not mention at all.

### Contradictions and omissions found by reading it

**The Business plan sold API access that section 4 excluded.** The pricing table
had been copied from a competitor. Resolution: pull it from the plan. Do not
sell what does not exist.

**"Multiple technicians per job" conflicted with the dispatch board**, where each
technician is a column. If a two-person job appears in two columns, does dragging
one copy move both? Resolution: **one lead technician** who owns the job and
drives the board, plus optional **helpers** who see it on their schedule. This
constrains the milestone 2 data model directly.

**No mention of migrating three years of existing Airtable data**, despite three
contractors waiting to onboard. Scoped and priced separately, after seeing a real
export.

**No mention of who designs the product.** No mockups, no brand, no reference.
The dispatch board in particular is a dense, opinionated interface. Resolution:
build on a component library and work from a named reference product rather than
inventing a visual language.

### Requirements that were far larger than they sounded

**"Handle bad signal gracefully"** covers three different products:

| | Behaviour | Cost |
|---|---|---|
| (a) | Nothing lost on a failed submit; retry with clear state | ~3 days |
| (b) | (a) plus photos queue and upload in the background | ~1 week |
| (c) | True offline: full read/write with no connection, sync and conflict resolution | 3–4 weeks |

**Agreed: (b).** Crawlspace work means intermittent signal, not a whole shift
without any. (c) is not in this budget and saying so early is what keeps it out.

**Customer "en route" notifications with a "rough ETA"** were requested late. But
GPS and route optimisation are explicitly out of scope, so there is nothing to
compute an ETA *from*. Resolution: the email states the booked arrival window,
not a computed ETA. A live ETA is a phase-2 feature with GPS attached.

**An internal admin surface** — see all tenants, comp an account, extend a trial,
log in as a customer to help them — was mentioned in passing as though it were
small. Cross-tenant access is a deliberate hole in the isolation model, and
impersonation needs its own permission layer, audit trail and tests. Roughly a
week, and reduced to **read-only** view-as: support staff who can write while
impersonating eventually destroy customer data by accident.

---

## 5. Resolved decisions

These are settled. Later milestones should treat them as given.

| # | Question | Decision |
|---|---|---|
| 1 | Can one person belong to several companies? | **Yes.** Many-to-many from the start — two of the target contractors share a bookkeeper. Retrofitting this later is a painful migration. ✅ *built* |
| 2 | API access on the Business plan? | **Removed** from the plan until it exists. |
| 3 | What is "custom branding"? | Logo and colours on invoices and customer emails. **Not** white-label domains. |
| 4 | Several technicians per job? | **One lead** plus optional helpers. |
| 5 | How offline is "offline"? | **Level (b)**: retry on failure, photos queue in the background. |
| 6 | Migrate the Airtable data? | Yes, priced separately after seeing the export. |
| 7 | Who designs it? | Component library, with a named reference product for layout. |
| 8 | Sales tax | One configurable rate per tenant, applied to the whole invoice. Contractor sets it. |
| 9 | Job numbers | `2026-0147`, resetting yearly. **Gaps are acceptable.** Per-tenant counter under a database lock. |
| 10 | Invoice numbers | **Gapless, sequential, never reused** — it has come up in an audit. Allocate at *issue* time, void rather than delete. |
| 11 | Seat limits | Count **active** memberships. Block beyond the limit with a friendly upgrade prompt (HTTP 402). Downgrading requires deactivating down to the new limit first. ✅ *built* |
| 12 | Trial expiry | Read-only for 30 days, then email a full CSV export and delete. Warn clearly and more than once. |
| 13 | The first three contractors | Comped for six months, then Pro at a permanent 30% discount. Needs a manual override. |
| 14 | Timezones | **On the service address, not the company.** One target contractor works both sides of the Ohio/Indiana line, where half of Indiana observes Central time. ⚠️ *milestone 2* |
| 15 | Signatures | **Legally operative.** Capture timestamp, signer name, device and IP alongside the image — a $4,200 dispute was lost for want of this. |
| 16 | Photos | 6–10 per job typically, up to 30 on a large install. Compress, cap at 25, retain 3 years. |
| 17 | Audit log retention | Two years (insurer's requirement), designed so extending to seven is a policy change rather than a rebuild. ✅ *built* |
| 18 | Browser support | Current Chrome, Edge and Safari. Dispatchers on Windows, technicians mostly on iPhone. |

---

## 6. Fitting the scope to the budget

The stated budget did not cover the stated scope. Rather than absorb the
difference or discover it in week seven, the trade was made explicit:

**Added after the original quote** — gapless invoice numbering (2 days),
timezone on service address (2 days), super-admin with view-as (5 days),
customer notifications (2 days), plus invoicing restored to v1 (7 days).

**Removed to pay for it:**

| Cut | What is lost | Saved |
|---|---|---|
| Stripe's hosted Customer Portal instead of a custom billing UI | Plan changes happen on a Stripe-branded page. Proration and dunning come free and correct. | 5 days |
| Reporting: one screen, not five | Jobs per tech, revenue by job type, outstanding invoices. No time-to-complete, no first-time-fix rate. | 4 days |
| CSV export only, no Excel | Excel opens CSV natively. No formatting, no multiple sheets. | 2 days |
| View-as is read-only | Cannot act while impersonating — which is the right call anyway. | 2 days |
| Audit log as a filterable list, not a diff viewer | No side-by-side before/after. | 1 day |

Note what the cuts have in common: every one removes **scope**, none removes
**rigour**. The tests, migrations, isolation suite and deployment pipeline were
never on the table. The Stripe swap is the model case — it saves a week *and*
ships better proration than a hand-rolled billing screen would have.

**Agreed: $9,000 over 12 weeks.**

| # | Weeks | Scope | |
|---|---|---|---|
| **1** | 1–3 | Architecture · schema · RLS isolation · auth · many-to-many users · RBAC · CI · deployment | ✅ **done** |
| 2 | 4–6 | Customers · service addresses with per-address timezone · jobs · dispatch board | next |
| 3 | 7–9 | Technician mobile view · offline-resilient submits · photo queue · signature with audit trail · en-route notification | |
| 4 | 10–11 | Invoicing · gapless numbering · void handling · PDF · one reporting screen · CSV | |
| 5 | 12 | Stripe via hosted portal · seat and job limits · comp overrides · audit log UI · super-admin read-only view-as · handover | |

Deployment and CI were moved from milestone 5 into milestone 1. Deploying at the
end is how a project discovers in week ten that something does not work in
production.

---

## 7. What milestone 2 must honour

Carried forward, because none of it is visible in the current schema:

- **Timezone belongs on the service address.** `tenants.timezone` is only a
  default for new addresses and a display default for company-wide views.
- **One lead technician per job**, plus helpers who see it but do not drive the
  board.
- **Job numbers** are per-tenant, reset yearly, allocated under a lock. Gaps are
  fine.
- **Internal vs customer-visible notes** are different fields on a job.
- The dispatch board must stay usable at **25 technicians and 200 jobs**. That is
  an acceptance criterion, not an aspiration.

And the acceptance test that outranks all of them, unchanged since the first
paragraph of the brief: two tenants, and neither can reach the other's data
through the UI *or* by manipulating IDs in API requests.
