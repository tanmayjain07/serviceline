# The scoping exchange, in full

> **Simulated.** There is no real client. This is a written exercise in scoping a
> multi-tenant SaaS build: a deliberately realistic brief, the questions that
> should be asked of it, and the negotiation that follows. Both sides were
> written as an exercise. It is kept because the decisions in it drive the code.
>
> The distilled version — decisions only, no dialogue — is
> **[brief.md](brief.md)**. Read that one if you want the answers rather than
> how they were reached.

Four parts: the brief, the reply that questioned it, the answers, and the
revised scope.

---

# Part 1 — The job post

**Title:** Build MVP for Multi-Tenant SaaS — Field Service Scheduling (React + Python + PostgreSQL)

**Budget:** $7,500 fixed-price · **Timeline:** 10 weeks · **Experience level:** Expert

> I run a 14-tech HVAC and plumbing company in Ohio. Over the last three years we
> built our own scheduling and dispatch tool internally (it's currently an
> Airtable + Zapier mess), and three other contractors in my network have asked to
> buy it from me. I want to turn it into a real product I can sell as a
> subscription.
>
> I need someone who has actually shipped a multi-tenant SaaS before — not someone
> learning on my money. I've been burned once already by a developer who built
> everything in one shared database with no separation between customers, and I
> found out when Company A could see Company B's jobs.
>
> Looking for a long-term relationship. If this goes well there's 12+ months of
> follow-on work.

## The detailed brief — "ServiceLine"

### 1. Business context

Sells to HVAC/plumbing contractors with 5–40 technicians. Each contractor is a
**tenant**. Their data must be completely invisible to every other tenant — the
single most important requirement in the document, and one the client says they
will personally test before paying the final milestone.

Launch pricing:

| Plan | Price | Limits |
|---|---|---|
| Starter | $49/mo | up to 5 technicians, 200 jobs/mo |
| Pro | $149/mo | up to 20 technicians, unlimited jobs, customer portal |
| Business | $349/mo | unlimited technicians, API access, custom branding |

14-day free trial, no credit card. Card required to continue.

### 2. Roles inside a tenant

- **Owner** — billing, subscription, invites everyone, sees everything. One per tenant, transferable.
- **Dispatcher** — creates/assigns jobs, manages the schedule and customers. No billing access.
- **Technician** — sees only jobs assigned to them. Updates status, logs time and parts, uploads photos, captures a customer signature. Cannot see pricing or other techs' schedules.
- **Read-only / Accountant** — reports and exports only, no edits.

> Roles must be enforced on the server. I know enough to check whether hiding a
> button is your idea of security.

### 3. Core modules

**3.1 Onboarding & tenant provisioning.** Self-serve signup → company name, trade
type, timezone → tenant created → owner invited to add team members by email.
Invite links expire in 7 days.

**3.2 Customers.** Company or residential. Multiple service addresses per
customer. Contacts, phone, email, notes. Full service history per address. Search
by name, phone, or address.

**3.3 Jobs / work orders.** Job number (per-tenant sequential — `2026-0147`,
restarting each year), customer + service address, job type, priority,
description, scheduled window (date + arrival window like "8am–12pm"), assigned
technician(s), status (`Unscheduled → Scheduled → En Route → In Progress →
Complete → Invoiced → Closed`), line items (labour + parts with quantity and
price), internal notes vs. customer-visible notes, photo attachments, customer
signature capture.

**3.4 Dispatch board.** The screen the dispatcher lives in all day. Week and day
view, technicians as columns, drag-and-drop to assign and reschedule. Must warn
on double-booking. Must remain usable with 25 technicians and 200 jobs in view.

**3.5 Technician mobile view.** Not a native app — a mobile web view that works
well on a phone. Today's job list, tap into a job, update status, log time, add
parts, take photos, get a signature.

> Must handle bad signal gracefully — our techs work in basements and
> crawlspaces. At minimum: don't lose data on a failed submit, queue and retry.

**3.6 Invoicing (light).** Generate an invoice from a completed job, PDF
download, email to customer, mark paid manually. No customer payments in v1.

**3.7 Reporting.** Jobs completed per tech per week · revenue by job type ·
average time-to-complete · first-time fix rate · outstanding invoices. All
exportable to CSV and Excel.

**3.8 Billing & subscriptions.** Stripe. Plan selection, upgrade/downgrade with
proration, failed-payment handling with dunning emails, and the tech-count and
job-count limits actually enforced — blocked with a clear upgrade prompt, not a
crash.

**3.9 Audit log.** Who changed what and when, per tenant, visible to the Owner.
"My insurance carrier asks about this."

### 4. Explicitly NOT in v1

Inventory management · GPS/route optimisation · payroll · QuickBooks sync ·
customer self-service portal · native mobile apps · SMS notifications.

> Do not build these. If you think one is trivial to add, tell me the estimate
> and I'll decide — don't surprise me.

### 5. Technical requirements

- **Frontend:** React with TypeScript. Your choice of tooling, but say what and why.
- **Backend:** Python. FastAPI or Django both fine. Argue for one.
- **Database:** PostgreSQL. **Tenant isolation must be enforced at the database layer**, not only in application code.
- **Hosting:** affordable at 20 customers, scalable to 500. "I don't want AWS if it means I need a DevOps person."
- Email, file storage and background jobs are the developer's call — recommend services and give the monthly cost at 50 tenants.
- Everything runs locally with one command.
- **Timezones:** contractors are in multiple US timezones. Job times must display in the tenant's timezone, always.

### 6. Deliverables

Source in a private GitHub repo the client owns from day one, with commits from
the start · deployed staging · deployed production · database migrations ·
automated tests covering auth, permissions and tenant isolation at minimum ·
README plus a short architecture doc · a 30-minute recorded handover · 30 days of
bug fixes after delivery.

### 7. Acceptance criteria for final payment

- Two tenants created; neither can see the other's data through the UI **or** by manipulating IDs in API requests
- A technician account cannot reach pricing or another tech's jobs by any means
- Full flow works: signup → invite tech → create customer → create job → dispatch → tech completes on phone → invoice → PDF emailed
- Stripe upgrade, downgrade and failed payment behave correctly in test mode
- Dispatch board responsive with 25 techs / 200 jobs seeded
- Tests pass in CI

### 8. Milestones as proposed by the client

| # | Milestone | Amount |
|---|---|---|
| 1 | Architecture doc, schema, auth + tenancy + RBAC | $1,500 |
| 2 | Customers, jobs, dispatch board | $2,000 |
| 3 | Technician mobile view, photos, signatures | $1,500 |
| 4 | Invoicing, reporting, exports | $1,250 |
| 5 | Stripe billing, audit log, deploy, handover | $1,250 |

### 9. What the client wants in a proposal

1. A link to a multi-tenant app you've built, and how you handled isolation
2. Your position on RLS vs. application-level scoping, in plain language
3. Which parts of the brief are underspecified or risky
4. Anything you'd cut from v1 to hit the timeline
5. Weekly availability and timezone overlap with US Eastern

> Please don't send me a generic cover letter. Reference something specific from
> this brief so I know you read it.

---

# Part 2 — The reply

## Leading with the thing that matters

The failure the client described — Company A seeing Company B's jobs — almost
always comes from the same root cause: isolation was a `WHERE tenant_id = ?`
clause that a developer forgot to write on one query. It works for months, then
one endpoint ships without it. You cannot test your way out of that reliably,
because the defect is *an absence*.

### RLS vs. application-level scoping, in plain language

With application-level scoping, every query has to remember to filter by tenant.
Miss one and it silently returns everyone's data. It is **opt-in security** — the
default is "leak."

With Row-Level Security you tell Postgres once: *nobody may see any row that
doesn't belong to their tenant*. Then at the start of every request you stamp the
connection with the current tenant's ID. If a developer writes `SELECT * FROM
jobs` with no filter at all, Postgres returns only that tenant's jobs, because
the database refuses to return anything else. It is **opt-out security**, and
opting out requires deliberately escalating privileges. Human error stops being a
data breach.

The honest trade-offs: it needs care with connection pooling (tenant context must
be set and reset per request, or a pooled connection leaks context to the next
one), background jobs need an explicit tenant context, and a badly written policy
can hurt performance if the tenant column is not indexed properly.

### Stack

React + TypeScript with Vite and TanStack Query. **FastAPI over Django** — the
dispatch board and technician view both want a clean JSON API rather than
server-rendered pages, and Pydantic models give types the TypeScript client can
be generated from, so frontend and backend cannot drift. The cost is Django's
free admin panel; better to build a small purpose-built one than inherit it.

Render or Fly.io for the API, Vercel for the frontend, Neon for Postgres,
S3-compatible storage for photos, Resend for email. Roughly $120–180/month at 50
tenants, no DevOps hire, scales past 500 without re-architecting.

## The questions

### Blocking — these change the schema

1. **Can one person belong to more than one tenant?** The accountant role
   suggests yes eventually — a bookkeeper serving four contractors, or the client
   logging into a customer's account to help. If so, model user↔tenant as
   many-to-many *now*; retrofitting it later is a painful migration and it costs
   almost nothing today.

2. **Section 4 says no API access, but the Business plan sells API access at
   $349/mo.** Which is right? Bolting a public API onto an app not designed for
   one means auth, rate limiting, versioning and docs. Recommendation: keep it
   out of v1 and don't list it on the pricing page until it exists.

3. **What does "custom branding" mean?** Logo and colours on invoices and emails
   is a day's work. Full white-label with the customer's own domain is a
   different product — wildcard certificates, per-tenant domain routing, email
   from their domain.

4. **Multiple technicians per job (3.3) conflicts with the dispatch board
   (3.4)**, where each tech is a column. If a two-person job appears in two
   columns, does dragging one copy move both? Proposal: one **lead technician**
   who owns the job and drives the board, plus optional **helpers** who see it in
   their job list.

### Scope-defining — these change the estimate

5. **"Handle bad signal gracefully" is the biggest risk in the document.** Three
   very different products hide behind that phrase:
   - (a) nothing lost on a failed submit; form retains data, retries, shows a clear "not saved yet" state — **~3 days**
   - (b) the above, plus photos queue and upload in the background — **~1 week**
   - (c) true offline: whole day's schedule cached, full read/write with no connection, sync and conflict resolution — **3–4 weeks, and the hardest thing in the project**

   Recommendation: (b). Crawlspace work means intermittent signal, not a whole
   shift without any. (c) is explicitly not in this budget.

6. **Your existing data.** Three years of jobs and customers in Airtable, and
   three contractors ready to onboard — but migration isn't mentioned anywhere.
   Budget a week for an import tool plus a dry run against the real export, and
   send the export early, because Airtable data is usually messier than expected.

7. **Who is designing this?** No mockups, no brand, no reference product. The
   dispatch board especially is a dense, opinionated interface. Options: build on
   a professional component library and make sensible decisions (no extra cost,
   clean but generic); hire a designer in parallel (+$2–3k, two weeks); or point
   at a competitor whose layout you like. Recommendation: the first — but if you
   hadn't budgeted for design and expected it included, better to say so now than
   in week six.

8. **Sales tax on invoices.** Multi-state contractors, variable rates, labour
   sometimes taxed differently from parts. Can v1 support a per-tenant
   configurable rate, with the contractor responsible for setting it?

### Detail-level

9. **Job numbers.** `2026-0147` resetting yearly is fine, but two dispatchers
   creating jobs simultaneously can collide — needs a per-tenant counter with
   proper database locking. **Are gaps acceptable?**

10. **Do invoice numbers need to be gapless?** Some jurisdictions require it.
    Cheap to build correctly, expensive to fix.

11. **Technician seat limits.** Total accounts or active ones? What happens when
    a Starter tenant deactivates a tech and adds another mid-month — and on
    downgrade from 20 to 5? Suggestion: count active accounts, block beyond the
    limit with an upgrade prompt, and require deactivating down to the limit
    before a downgrade takes effect.

12. **Trial expiry.** Data read-only for 30 days then deleted? Frozen? Exported
    and emailed? A trust and compliance question as much as a technical one.

13. **The three existing contractors** — paying, comped, or grandfathered?
    Determines whether billing needs a manual override in v1.

14. **Timezones.** Do any target contractors operate across a timezone line —
    Ohio to Indiana, for instance? If so, timezone belongs on the *service
    address*, not the tenant, and that must be known before modelling the schema.

15. **Signatures.** Legally operative, or a courtesy? If it matters legally,
    capture a proper audit trail — timestamp, device, IP, signer name — not just
    an image.

16. **Photos.** How many per job, and retained how long? Ten 12MP photos per job
    across 50 tenants adds up, and it is the one line item that grows without
    limit.

17. **Audit log retention** — does the insurer specify a period?

18. **Browser support.** Modern evergreen only?

## The part the client won't enjoy

> Sections 3.1 through 3.9 as written is a $14–18k project at senior rates, not
> $7,500. The dispatch board alone — drag-and-drop, double-booking detection,
> performant at 25 techs and 200 jobs — is two to three weeks by itself. Stripe
> billing with proration, dunning and enforced limits is another two. I'd rather
> tell you now than hit week seven at 45% complete and start asking for more
> money. That's the failure mode you've already lived through once.

Three ways forward:

- **A — Full scope, realistic budget.** $15,000, 14 weeks, everything with offline at level (b).
- **B — Focused v1 at your budget.** $7,500, 10 weeks. Cut invoicing; reporting down to three reports plus CSV; Stripe Checkout without proration or dunning UI; offline at level (a). Photos and signature stay, because the technician view is worthless without them.
- **C — Prove the foundation first.** $2,500, 3 weeks: architecture, schema, auth, tenancy, RBAC, CI, deployment pipeline, tenant-isolation test suite. Then scope the rest with real information.

> I'd recommend B, structured with C's milestone shape — that first milestone is
> already in your plan, and it's the one where isolation gets proven. If it
> doesn't go well, you've spent $1,500 to find out, not $7,500.

One correction to the milestone plan either way: **CI and deployment belong in
milestone 1, not milestone 5.** Deploying at the end is how projects discover in
week ten that something doesn't work in production.

---

# Part 3 — The client's answers

> This is the best response I've gotten by a wide margin, and it's the only one
> that told me my budget was wrong instead of just agreeing with me.
>
> The RLS explanation is the first time anyone has made that concept make sense
> to me. "The default is leak" — that's exactly what happened to me last time.

| # | Answer |
|---|---|
| 1 | **Yes, many-to-many.** "I already know I'll be logging into customer accounts to help them onboard, and two of my three contractors use the same bookkeeper." |
| 2 | "You're right, that's my mistake. I copied that pricing table from a competitor's site. Pull it from the plan." |
| 3 | Logo and colours on invoices and customer emails. No custom domains. Lowest priority. |
| 4 | Lead + helpers is exactly right, and how they actually work — one tech owns the job, sometimes takes an apprentice. |
| 5 | **Level (b).** "The guys take pictures in a basement and then wonder why nothing uploaded." |
| 6 | Migration needed; export to follow. "Fair warning, it's bad. Three years of a system that changed shape twice, half-empty columns, addresses typed into notes fields." Priced separately. |
| 7 | Component library. Reference product: **Jobber**. "I'm not trying to out-design anyone, I just don't want it to look like a spreadsheet with buttons." No design budget. |
| 8 | One configurable rate per tenant, applied to the whole invoice. |
| 9 | Gaps acceptable. "Nobody has ever asked me about a missing job number." |
| 10 | **Gapless, sequential, never reused.** "I asked my accountant, and this one matters. Apparently it's come up in an audit before. Whatever that costs, build it right." |
| 11 | Count active accounts; block with an upgrade prompt; downgrade requires deactivating first. "Make the upgrade prompt friendly, not scolding." |
| 12 | Read-only 30 days, then email a full CSV export and delete. Warn clearly and repeatedly. |
| 13 | Comped six months, then Pro at a permanent 30% discount. Needs a manual override — and an internal admin screen to see all tenants, comp accounts, extend trials, and log in as a customer. "I realize I never mentioned that anywhere. Is that a big lift?" |
| 14 | **Service address, not tenant.** "One of my three contractors is in northwest Ohio with crews working across the Indiana line, and half of Indiana is on Central. I'm glad you asked, because I would have found this out from an angry customer." |
| 15 | **Legally operative.** "I lost a $4,200 dispute two years ago because I had no proof the customer approved the extra work. This is a selling point for me, not a checkbox." |
| 16 | 6–10 per job, occasionally 30 on a big install. Compress, cap at 25, keep three years. |
| 17 | Carrier asked for two years. Design so extending to seven is possible without a rebuild. |
| 18 | Current Chrome, Edge, Safari. |

## On budget

> I appreciate you being straight, and I believe your numbers. I can't do
> $15,000 right now — that's real money for a company my size and this is still a
> bet.
>
> I'll take **Option B, structured with Option C's first milestone**, exactly as
> you suggested.

Two changes to the cut list:

- **Put invoicing back in.** After what the accountant said about numbering, the client doesn't want it bolted on later by someone else.
- **$9,000 and 12 weeks** to cover it. "That's genuinely my ceiling for this phase. If invoicing plus gapless numbering doesn't fit in the extra $1,500, tell me what else comes out to make room — I'd rather cut reporting down to one screen than have you eat the difference and resent the project."

## One thing forgotten

> I need **customer notifications** — when a technician marks a job "En Route,"
> the customer gets an email saying someone's on the way with a name and rough
> ETA. Every one of my contractors has asked for this.
>
> Email only, no SMS. I know I'm adding scope here, so tell me what it costs and
> what it displaces, don't just absorb it.

## Questions back

1. Whose Stripe account, and how is access handled during the build?
2. "What happens if you get hit by a bus — or just get a better offer in week eight? I've been left holding half a codebase before."
3. How are mid-project changes handled? "I'd rather agree the process now than argue about it later."
4. Can we do a call this week?

---

# Part 4 — Revised scope

## Items that landed after the quote

| Added | Why it costs what it costs | Est. |
|---|---|---|
| Gapless invoice numbering | Numbers allocated at *issue* time under a database lock; invoices **voided** rather than deleted; a failed PDF render must not consume a number. Constrains invoice creation for the life of the product. | 2 days |
| Timezone on service address | Every date, every schedule query, the dispatch board and the notification emails resolve against the address's zone. Indiana's DST rules are genuinely nasty. Needs its own tests. | 2 days |
| Super-admin + view-as | Cross-tenant access is a deliberate hole in the isolation model, so it needs its own permission layer, audit trail, and tests proving no regular user can reach it. | 5 days |
| Customer "en route" email | Template, trigger, queue, per-tenant sender identity, unsubscribe handling. | 2 days |

≈ 11 days of new work, plus ≈ 7 for restoring invoicing. The extra $1,500 covers
roughly 5. So ≈ 13 days had to come from somewhere.

## Where they came from

| Cut / changed | What is lost | Saved |
|---|---|---|
| **Stripe's hosted Customer Portal** instead of a custom billing UI | Plan changes, card updates and cancellation happen on a Stripe-branded page. Proration and dunning come free and correct. Slightly less seamless. | 5 days |
| **Reporting: one screen, not five** | Jobs-per-tech, revenue by job type, outstanding invoices on one filterable page. No time-to-complete, no first-time-fix rate. | 4 days |
| **CSV only, no Excel** | Excel opens CSV natively. No formatting, no multiple sheets. | 2 days |
| **View-as is read-only** | Can see a customer's account as they see it, but not click. The right call regardless — write access while impersonating is how support staff accidentally destroy customer data. | 2 days |
| **Audit log is a filterable list, not a diff viewer** | No side-by-side before/after. | 1 day |

14 days recovered, leaving one day of margin held back for the Airtable data
being worse than either side expects.

**Flag on the notification email:** with no GPS and no route optimisation there
is nothing to compute an ETA *from*. What the email can honestly say is *"Mike is
on his way. Your appointment window is 8:00 AM–12:00 PM."* A real live ETA is a
phase-2 feature with GPS attached.

## Answers to the client's questions

**1. Stripe — the client's account, in their company's name.** The developer
never owns it. Test mode with a restricted key during the build; live keys
generated by the client and placed into the hosting environment themselves. Same
for every service: **the client creates the account and invites the developer**.
About 40 minutes on day one, and it means no part of the product is ever hostage
to the developer's credentials.

**2. Bus factor.**

- Repo in the client's GitHub org from day one; developer is a collaborator, not the owner
- Daily pushes — never a week of work living only on one laptop
- Staging deployed and live from week one
- The architecture doc written in **milestone 1**, not at handover, because a doc written at the end only exists if the project reaches the end
- Migrations, tests, typed API, README, one-command local setup. The bar: a competent developer could take over mid-stream without a conversation
- Milestone escrow caps exposure at one unfunded milestone
- **In the contract:** if the developer goes dark for five business days without notice, the engagement terminates, the client keeps everything delivered, and the in-flight milestone is settled pro-rata on what is merged. No dispute, no clawback

**3. Change requests.**

- **Under two hours of work: just done.** No paperwork, no invoice. Small things shouldn't have friction.
- **Anything larger gets a written change note** — cost, schedule impact, and if the budget is fixed, *what it displaces*. Approved in writing before work starts.
- **Nothing changes inside a milestone that has already started.** Changes land in the next one; mid-milestone reshuffling is how projects quietly lose two weeks.
- **Everything that doesn't make v1 goes into a parking-lot document** with a rough estimate. Nothing is lost, and by launch the phase-2 roadmap has written itself.
- **Friday demo on staging plus a short written status:** shipped / next / blocked / decisions needed. The last section is what keeps projects moving.

**4. Call** — 45 minutes, walking the dispatch board and technician flow on
screen, because those are the two places where "obvious" means different things
to different people.

## Final milestone plan

| # | Weeks | Scope | Amount |
|---|---|---|---|
| **1** | 1–3 | Architecture doc · schema · **RLS tenant isolation** · auth · many-to-many users · RBAC · CI · staging + production pipelines · tenant-isolation test suite | **$2,000** |
| **2** | 4–6 | Customers · service addresses with per-address timezone · jobs & work orders · dispatch board (drag/drop, double-booking warning, performant at 25×200) | **$2,250** |
| **3** | 7–9 | Technician mobile view · offline-resilient submits · background photo queue · signature with full legal audit trail · customer en-route notification | **$2,000** |
| **4** | 10–11 | Invoicing · **gapless numbering** · void handling · PDF · email delivery · reporting screen · CSV export | **$1,750** |
| **5** | 12 | Stripe subscriptions via hosted portal · seat & job limits enforced · comp/override support · audit log UI · super-admin with read-only view-as · deploy · handover recording | **$1,000** |
| | | **Total** | **$9,000** |

Airtable migration quoted separately once the export has been seen.

> Milestone 1 is deliberately the largest slice of the calendar for the smallest
> slice of visible product. Three weeks in, you'll have a working staging site
> where you can create two companies and try to break into one from the other —
> and not much else that looks like an app. That's intentional, and I want you
> expecting it so it doesn't read as slow progress. Everything after it moves
> fast *because* of it.

---

# What the exercise is actually demonstrating

Four things, none of which are visible in code:

1. **Reading a brief adversarially.** The strongest moves in Part 2 are about
   things the brief did *not* say: the missing data migration, the missing
   designer, the pricing table contradicting the scope section. Catching what
   isn't written matters more than executing what is.

2. **Pricing honestly, early.** Telling a client their budget is 50% short is
   uncomfortable in week one and catastrophic in week seven. The ledger in Part 4
   — added versus cut, with days attached — turns "you're asking for more than
   you're paying for" into a shared arithmetic problem, and clients choose
   sensibly when they can see the trade.

3. **Cutting scope, never rigour.** Every cut removes features. None removes
   tests, migrations, or the deployment pipeline. The Stripe Customer Portal swap
   is the model: it saves a week *and* ships better proration than a hand-rolled
   billing screen would have.

4. **Volunteering the terms of your own failure.** The five-day termination
   clause is disarming precisely because nobody offers it. To a client who has
   been abandoned before, it is worth more than another portfolio link.
