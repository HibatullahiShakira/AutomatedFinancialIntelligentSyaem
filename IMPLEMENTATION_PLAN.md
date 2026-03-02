# AMSS Enterprise — Full Implementation Order from Scratch
Autonomous Financial Intelligence Platform
 Designed & Architected by Shakira Hibatullahi
 Software & Data Engineer | Financial Systems | ML Architecture
 February 2026

The Golden Rule: Every phase is designed so the system is always in a working state. At any point you can demo, onboard early users, and gather real data that makes later ML models better. You never have a "we need everything before we can launch" problem.

TABLE OF CONTENTS
Phase 0 — Foundation
Phase 1 — Identity & Security Layer
Phase 2 — Core Accounting Engine
Phase 3 — Billing, Sales & Debt Management
Phase 4 — Customer Risk Flagging Engine
Phase 5 — Liability & Asset Modules
Phase 6 — Insurance Intelligence Module
Phase 7 — Reminder & Notification Engine
Phase 8 — Tax Engine
Phase 9 — Data Platform & Event Store
Phase 10 — Machine Learning Models
Phase 11 — Uncertainty Engine
Phase 12 — Business Intelligence Agent
Phase 13 — MLOps & Production Hardening
Module Dependency Map
Events Registry — Full System

PHASE 0 — Foundation
Nothing else can start until this is solid. This is your ground floor.

Step 1 — Project Structure & Standards
Define your folder structure, coding standards, naming conventions, and branching strategy before writing a single line of business logic. Use a monorepo structure so all services share one repository but stay independently deployable.
Principles to enforce from day one:
Single responsibility per module
Dependency direction: higher-level modules depend on lower-level, never the reverse
All configuration in environment variables, never hardcoded
Every public function must have a contract (typed inputs and outputs)
Branch naming convention: feature/, fix/, infra/, ml/
Why first: Every developer and every future decision depends on knowing where everything lives and how everything is named. Retrofitting structure is painful and disruptive.

Step 2 — Infrastructure as Code (Terraform)
Provision your cloud environment before building anything. Set up AWS account structure, VPC, subnets, security groups, and IAM roles using Terraform. Everything infrastructure-related must be code, never manual clicks.
What to provision at this stage:
VPC with public and private subnets across two availability zones
NAT Gateway for private subnet outbound access
Security groups with least-privilege rules
IAM roles for each service with minimum required permissions
S3 buckets for event store, ML artefacts, and document storage
RDS PostgreSQL instance (Multi-AZ in production, single in dev)
ElastiCache Redis cluster
SQS FIFO queues for event bus
ECR repositories for Docker images
Secrets Manager entries for all credentials
Why before business logic: Your environments (local, dev, staging, production) must be reproducible from day one. Manual infrastructure created by clicking is infrastructure that cannot be version-controlled, reviewed, or recreated reliably.

Step 3 — Local Development Environment (Docker Compose)
Before any AWS costs accumulate, define a Docker Compose file that spins up every service locally. Every developer must be able to run the entire system on their laptop with one command.
Services in Docker Compose:
PostgreSQL (matching RDS version exactly)
Redis (matching ElastiCache version exactly)
LocalStack (AWS service emulation: SQS, S3, SageMaker)
Celery worker
The Django API service
A mock SMTP server for email testing
Why this matters: "Works on my machine" is a project killer. A reproducible local environment means every test, every feature, and every bug fix is validated before it ever touches AWS.

Step 4 — CI/CD Pipeline (GitHub Actions)
Set up automated testing and deployment pipelines before writing business logic. From the very first commit, every push should trigger linting, testing, and a build check.
Pipeline stages:
Lint & Type Check (parallel, ~2 min): ruff + mypy + bandit for Python; ESLint + TypeScript for frontend; terraform fmt + tflint for infrastructure
Unit & Integration Tests (~5 min): pytest with PostgreSQL and Redis containers; coverage gate must be above 80% to proceed
ML Model Validation (on PR to main, ~10 min): run validation suite on latest model versions; fail if MAPE > 15%
Docker Build & Push to ECR (~5 min): multi-stage build; image vulnerability scanning
Staging Deploy (auto, ~10 min): Terraform plan; database migration; ECS rolling update; smoke tests
Production Deploy (manual approval gate): blue-green deployment; automatic rollback if error rate exceeds 1% in first 5 minutes
Why before business logic: You build the safety net before you start walking the tightrope. Every feature built after this is automatically validated.

Step 5 — Database Schema Strategy
Design your PostgreSQL schema with multi-tenancy as the absolute foundation. Every table must have a tenant_id column from day one.
Non-negotiable rules:
Every business data table has tenant_id UUID NOT NULL as its first non-primary-key column
Row-level security policies enforced at the database level, not only at the application level
All timestamps stored in UTC as TIMESTAMPTZ, never TIMESTAMP
All monetary values stored as DECIMAL(18,2) or as integers in the smallest currency unit — never FLOAT
Migration strategy defined: every schema change goes through a numbered migration file, never direct ALTER TABLE in production
Index strategy defined before any table is created: what queries will be run, what columns need indexes
Why multi-tenancy first: Retrofitting multi-tenancy into an existing schema is one of the most expensive engineering mistakes possible. A tenant isolation bug in a financial system is a catastrophic data breach.

PHASE 1 — Identity & Security Layer
This is the gate. Nothing is accessible without this working correctly.

Step 6 — Authentication System
Build user registration, login, JWT token generation, and token refresh. Use AWS Cognito for token management but implement your own permission layer on top.
What to build:
User registration with email verification
Login with JWT access token (1-hour expiry) and refresh token (7-day expiry)
Token refresh endpoint
Password reset flow
MFA enforcement for OWNER role (TOTP)
Role hierarchy definition: OWNER, ACCOUNTANT, VIEWER, SALESPERSON
Security requirements:
Passwords hashed with bcrypt (minimum cost factor 12)
All tokens validated on every request
Failed login attempts rate-limited and logged
Token revocation on logout stored in Redis
Why before everything else: Every other module depends on knowing who is making a request and what they are allowed to do.

Step 7 — Tenant Management
Build the ability to create a business (tenant), assign users to it, and enforce that all data queries are scoped to the tenant.
What to build:
Business registration (tenant creation)
User-to-tenant assignment with role
Tenant context injection middleware (every authenticated request carries tenant_id automatically)
Row-level security verification — write integration tests proving Tenant A cannot read Tenant B's data
Critical test: Before building any financial module, write a test that creates two tenants, inserts data for each, and proves that querying as Tenant A returns zero rows from Tenant B's data. This test must pass and must never be deleted.
Why this order: Once you have real financial data in the system, discovering a tenant isolation bug is catastrophic. Prove isolation works before financial data exists.

Step 8 — API Gateway & Middleware Layer
Build the middleware that sits in front of every API endpoint — request validation, JWT verification, tenant context injection, rate limiting, and request logging.
Middleware chain (in order):
SSL termination (handled at CloudFront/ALB)
Rate limiting (per tenant, per IP)
JWT verification
Tenant context injection (attaches tenant_id to request)
Permission check (does this role have access to this endpoint?)
Request logging (correlation ID assigned, logged to CloudWatch)
Response logging (status code, latency logged)
Why build this as middleware: Every future endpoint passes through this layer automatically. Getting it right once means you never think about authentication, logging, or rate limiting again when building business features.

PHASE 2 — Core Accounting Engine
This is the heart. All financial intelligence depends on accurate financial records.

Step 9 — Chart of Accounts
Build the foundational data model for accounts — assets, liabilities, equity, income, and expenses. This is the skeleton that all transactions attach to.
Account hierarchy:
Account Type (Asset, Liability, Equity, Income, Expense)
Account Category (Current Assets, Fixed Assets, Current Liabilities, Long-term Liabilities, etc.)
Individual Account (Cash, Accounts Receivable, Inventory, Equipment, etc.)
Rules enforced at the database level:
Every account belongs to exactly one account type
Account codes follow a defined numbering scheme (1xxx = Assets, 2xxx = Liabilities, 3xxx = Equity, 4xxx = Income, 5xxx = Expenses)
Accounts can be deactivated but never deleted if they have journal entries
A default chart of accounts is seeded for new Nigerian SME tenants
Why before transactions: You cannot post a journal entry without knowing which accounts to debit and credit. The chart of accounts is the vocabulary; transactions are the sentences.

Step 10 — Journal Entry & Transaction Engine
Build the ability to record financial transactions with proper double-entry posting. This is the most critical module in the entire system.
Core rules — enforced at the database level, not just application level:
Every journal entry must have at least two lines (one debit, one credit)
Total debits must equal total credits — this is a database constraint, not just a validation
Journal entries are immutable once posted — errors are corrected by reversal entries, never by editing
Every journal entry has a unique reference number, a posting date, a description, and a source (manual, invoice, payment, depreciation, etc.)
All amounts stored as DECIMAL(18,2) — no floating point arithmetic in financial calculations
Transaction types:
Manual journal entry
Invoice posting (accounts receivable debit, income credit)
Payment received (cash debit, accounts receivable credit)
Expense payment (expense debit, cash credit)
Depreciation (depreciation expense debit, accumulated depreciation credit)
Insurance premium (insurance expense debit, cash or payables credit)
Tax payment (tax liability debit, cash credit)
Why immutability: In accounting, you never delete or edit history. You reverse and repost. This is both a legal requirement and what makes event sourcing work correctly.

Step 11 — Account Balance Computation
Build the engine that computes account balances by aggregating journal entries. Do not store balances as a cached number that gets updated — derive them from journal entries on query.
The core principle: The journal IS the truth. Balances are derived from it. This prevents balance corruption bugs permanently.
What to build:
Balance computation function: sum all debits minus sum all credits for any account, for any date range
Trial balance generator: all accounts with their computed balances as of a date
Period-end closing logic: transfer income and expense balances to retained earnings at financial year end
Balance caching strategy: compute and cache balances in Redis, invalidate cache when new journal entries are posted
Performance consideration: For tenants with years of transaction history, computing balances from scratch on every request becomes slow. Implement a balance snapshot table that stores the balance at the end of each month, so queries only need to replay entries since the last snapshot.

Step 12 — Event Publisher Integration
Every time a transaction is created, the system publishes a structured event to the SQS queue. At this point, nobody is listening — that is fine. Build the publisher first.
What to build:
Event publisher service: a typed function that constructs the canonical event envelope and publishes to SQS
Event schema validation: every event published must conform to the canonical schema before it is sent
Idempotency: every event has a UUID; duplicate events (from retries) must be safely ignored by consumers
Dead letter queue: events that fail processing after 3 attempts go to a DLQ with an alert
Canonical event envelope (all events use this):
event_id: uuid-v4
event_type: string (from EventTypes registry)
schema_version: "2.0"
tenant_id: uuid-v4
user_id: uuid-v4
timestamp: ISO-8601 UTC
correlation_id: uuid-v4
causation_id: uuid-v4
source_service: string
payload: object (event-specific data)
metadata: object (ip, user_agent, request_id)

Why publish before anyone listens: The event bus is the backbone of the entire system. Testing that events are published correctly, with the right schema, from the very first module means every subsequent module that consumes these events has reliable, well-formed input.

PHASE 3 — Billing, Sales & Debt Management
Built directly on top of accounting. Sales create invoices; invoices trigger collection intelligence.

Step 13 — Customer Registry
Build the ability to create and manage customers. This is the foundation that invoicing, risk scoring, and collection management all depend on.
Customer data model:
Identity: name, trading name, registration number (CAC), tax identification number (TIN)
Contact: primary email, WhatsApp number, secondary contact, physical address
Financial terms: default payment terms (Net 7, 15, 30, 60), credit limit, currency
Classification: customer type (individual, SME, corporate, government), industry, acquisition channel
Status: active, suspended (Amber/Red flagged), blocked (Black flagged)
Relationship: assigned salesperson, account manager, date of first transaction
Why a separate customer registry before invoicing: Invoices, risk scores, payment history, and collection actions all belong to a customer. The customer record is the anchor point for all of these. Building it first means every subsequent module has a clean foreign key relationship to attach to.

Step 14A — Enhanced Invoice Engine with Sales Lifecycle
Build the full order-to-cash lifecycle. An invoice is not just a document — it is the start of a collection lifecycle.
Sales lifecycle stages: Quotation → Sales Order → Invoice → Partial Payment → Full Payment → Receipt → Journal Entry
Invoice data model (enhanced):
Core: invoice number, customer, issue date, due date, line items, subtotal, VAT (7.5%), total
Sales context: sales channel, salesperson, linked quotation, linked sales order
Payment terms: standard terms, early payment discount (percentage and deadline), late payment penalty (percentage per month overdue)
Collection tracking: reminder count, last reminder date, last reminder channel, customer response, promise-to-pay date
Dispute tracking: dispute flag, dispute nature, dispute opened date, resolution status
Status: draft, issued, partially-paid, paid, overdue, disputed, written-off
Rules:
An invoice in "draft" status does not trigger accounting entries
When an invoice is "issued," post the accounts receivable journal entry
When a payment is received against an invoice, post the cash receipt journal entry
A payment cannot exceed the outstanding balance on an invoice
If a customer is Black-flagged, new invoice creation is blocked at this layer
PDF generation: Every issued invoice generates a professional PDF stored in S3 with a signed URL for delivery. The PDF includes company branding, Nigerian VAT registration number, bank account details for payment, and a QR code linking to an online payment page.

Step 14B — Customer Debt Notification Sequence
This is a structured communication escalation ladder, not ad-hoc reminders. For each overdue invoice, the system runs through defined escalation levels automatically.
Escalation ladder:
Level 1 — Gentle Reminder (Day 1 after due date)
Tone: Friendly, assumes oversight
Channels: Email only
Content: Invoice number, amount, due date, payment instructions
Action tracked: Email delivery status
Level 2 — Firm Reminder (Day 7 overdue)
Tone: Professional, references original due date explicitly
Channels: Email + WhatsApp
Content: Invoice PDF attached, payment terms restated, late penalty notice if applicable
Action tracked: Email delivery + WhatsApp delivery and read status
Level 3 — Urgent Notice (Day 14 overdue)
Tone: Urgent, account under review
Channels: Email + WhatsApp + in-app owner alert
Content: States that failure to respond within 48 hours will escalate the account status
Action tracked: Response received or not; if no response, raises customer risk score immediately
Level 4 — Final Notice (Day 30 overdue)
Tone: Formal, legal action implied
Channels: Email + WhatsApp + owner escalation alert
Content: Formal notice of overdue status, request for payment plan agreement if unable to pay in full
Action tracked: Response; promise-to-pay date if customer negotiates
Level 5 — Internal Escalation (Day 45+ overdue)
No further automated customer-facing messages
Owner receives a decision brief from the agent: payment probability, recommended action (payment plan, collection, write-off consideration)
Collection status marked as "escalated" — requires human decision
WhatsApp message design principles:
First line: purpose (payment reminder for invoice #INV-XXXX)
Second line: amount and due date
Third line: clear call to action (pay now link or contact number)
Sign-off: professional, leaves door open for response
Message length: under 160 words
Delivery tracking: sent → delivered → read statuses all recorded

Step 14C — Promise-to-Pay Tracking
When a customer responds and commits to a payment date, the system manages that commitment.
Promise-to-pay workflow:
Owner or system records the customer's committed payment date
Automated reminders pause (no point sending reminders if a payment is promised)
A watch is set on the promised date
If payment arrives before the promised date: promise fulfilled, record positive signal, resume normal status
If promised date passes without payment: PROMISE_TO_PAY_BROKEN event fires, escalation ladder resumes from where it left off, risk score recalculates immediately
A customer who breaks two or more promises triggers Red-flag rule regardless of days overdue

PHASE 4 — Customer Risk Flagging Engine
Rules as configuration, not code. Each organisation defines their own risk tolerance.

Step 15A — Risk Rule Configuration Engine
Every risk rule is stored as data in the database, not hardcoded in the application. This is the most important design decision in this module.
Risk rule data model:
Rule identity: rule name, description, category (payment behaviour, credit limit, collection pattern)
Trigger condition: field being evaluated, comparison operator (>, <, =, between, percentage), threshold value
Risk level assigned: Green, Amber, Red, Black
Automatic actions on trigger: notification template to fire, invoice creation block flag, owner approval required flag, salesperson notification flag
Rule active flag and effective date
Tenant scope: belongs to one organisation, fully customisable per tenant
Default rule set (seeded for all new tenants, fully modifiable):
Rule
Condition
Risk Level Assigned
Early Watch
Any invoice overdue > 15 days
Amber
Credit Limit Breach
Total outstanding > credit limit
Amber + invoice block
Consistent Late Payer
> 40% of last 10 invoices paid late
Amber
High Risk — Overdue
Any invoice overdue > 30 days
Red
Promise Breaker
2+ broken promise-to-pay commitments
Red
Severe Overdue
Any invoice overdue > 60 days
Black + invoice block
Concentration Risk
Single customer > 30% of total AR
Amber (no block)

All threshold values (15 days, 40%, 30 days, 60 days, 30%) are configuration values editable by the business owner through the settings interface. No code change required to adjust them.

Step 15B — Customer Risk Score Computation Engine
Beyond binary flags, each customer receives a continuous risk score from 0 to 100 computed from weighted signals. Weights are configurable per organisation.
Scoring signals:
Signal
What It Measures
Default Weight
Payment timeliness score
% of historical invoices paid on or before due date
35%
Days-to-pay trend
Is average payment time improving or deteriorating?
20%
Balance coverage ratio
Outstanding balance relative to average monthly payment
20%
Promise reliability score
% of payment promises honoured on promised date
15%
Communication responsiveness
Response rate and speed to reminders
5%
Invoice dispute rate
Frequency of disputes raised to delay payment
5%

Score interpretation:
75–100: Green (low risk, good payment behaviour)
50–74: Amber (watch, some risk signals present)
25–49: Red (high risk, collection action required)
0–24: Black (severe risk, no new credit)
ML enhancement (Phase 10): Once the Invoice Payment Predictor ML model is live (Step 31), its payment probability output is fed back into this score as an additional weighted signal, making risk scoring progressively more accurate as data accumulates.

Step 15C — Risk Status Lifecycle Manager
Risk status follows defined transitions with explicit rules for both escalation and recovery.
Escalation transitions:
Green → Amber: triggered by Rule 1, Rule 3, or Rule 7
Amber → Red: triggered by Rule 4, Rule 5, or Amber persisting >30 days without resolution
Red → Black: triggered by Rule 6 or Red persisting >30 days without payment
Recovery transition:
Any status → Green: requires ALL of the following:
All overdue balances cleared
Rolling payment score returns above threshold
Owner manually confirms status reset
Automatic recovery to Green is intentionally disabled. A human must confirm the customer has earned restored trust.
Risk score recalculation triggers:
Payment received (score may improve)
Invoice becomes overdue (immediate recalculation)
Promise-to-pay date passes without payment (immediate)
Reminder delivered, read, but no response after 48 hours
New invoice created for this customer (score checked before creation allowed)

Step 15D — Risk Event Publisher & Invoice Block Integration
When a customer's risk status changes, the system publishes events and enforces consequences.
Events published by Risk Module:
CUSTOMER_RISK_LEVEL_CHANGED
CUSTOMER_FLAGGED_AMBER
CUSTOMER_FLAGGED_RED
CUSTOMER_BLOCKED
CUSTOMER_RISK_CLEARED
CREDIT_LIMIT_BREACHED
PROMISE_TO_PAY_BROKEN
INVOICE_CREATION_BLOCKED
COLLECTION_ESCALATION_TRIGGERED

Invoice creation enforcement: Before allowing invoice creation, the billing module checks the customer's current risk status. If Black-flagged, creation is blocked and the owner is notified with the reason. Owner can override with explicit confirmation, which is logged for audit.
Cash Flow Forecaster integration (Phase 10): The forecaster subscribes to CUSTOMER_RISK_LEVEL_CHANGED events and adjusts expected inflow projections accordingly. An invoice from a Red-flagged customer is weighted lower in the forecast than one from a Green customer.

PHASE 5 — Liability & Asset Modules
Both are independent of each other but both depend on the accounting engine.

Step 16 — Liability Register
Build the ability to register every financial obligation the business has.
Liability types and what each tracks:
Liability Type
Key Fields
Intelligence Layer
Bank Loans
Principal, rate type, tenure, monthly payment, balloon
DSCR monitoring, refinancing recommendation
Trade Payables
Supplier, amount, due date, early payment discount
Opportunity cost of early vs late payment
Rent / Lease
Monthly amount, annual review date, lease end
Inflation-adjusted future rent projection
Staff Salaries
Headcount, payroll total, PAYE, pay date
Wage inflation tracking, payroll compliance
Utility Bills
Electricity, water, diesel, internet
Energy cost trend vs macro FX index
Tax Liabilities
VAT monthly, WHT, CIT, PAYE
Running total updated on every transaction
Informal Loans
Lender, amount, agreed terms
Tracks undocumented obligations for full picture
Equipment Finance
Asset financed, monthly payment, ownership date
Asset-liability linkage, book value vs balance

Payment workflow: When a liability payment is made, it triggers a journal entry in the accounting module. The liability module does not write accounting entries directly — it publishes a PAYMENT_MADE event and the accounting module posts the journal entry.
Events published:
LIABILITY_REGISTERED
PAYMENT_MADE
PAYMENT_OVERDUE
LIABILITY_CLOSED
DSCR_BELOW_THRESHOLD
REFINANCING_RECOMMENDED


Step 17 — Asset Register
Build the ability to register all business assets with depreciation management.
Asset categories and depreciation methods:
Category
Examples
Method
Rate
Property & Buildings
Office, warehouse
Straight-line
2% per year
Machinery & Equipment
Production machinery
Reducing balance
20% per year
Vehicles
Delivery trucks, cars
Reducing balance
25% per year
IT Equipment
Computers, servers, POS
Straight-line
33% per year
Generator & Power
Diesel generator, solar
Straight-line
10% per year
Furniture & Fittings
Office furniture
Straight-line
20% per year
Inventory / Stock
Goods for resale
FIFO or weighted average
—
Intangible Assets
Software licences
Per licence terms
—

Automated depreciation: On the first day of each month, a scheduled job posts depreciation journal entries for every active asset. Depreciation expense debit, accumulated depreciation credit. This is the first fully automated business logic in the system.
Asset lifecycle events:
ASSET_REGISTERED
ASSET_DEPRECIATED
ASSET_REVALUED
ASSET_DISPOSED
ASSET_IMPAIRED
MAINTENANCE_DUE


Step 18 — Asset-Liability Linkage
Connect assets to the liabilities that finance them. This enables mismatch detection.
Asset-liability mismatch detection algorithm:
For each asset-financing pair:
Compute asset's annual contribution to revenue (if traceable)
Compute total annual cost of ownership: depreciation + maintenance + insurance + financing cost
Compare asset book value against outstanding financing balance
If financing balance > book value → NEGATIVE EQUITY ASSET ALERT
If annual cost > annual contribution → DRAG ASSET ALERT
If asset fully depreciated but loan not paid → GHOST ASSET ALERT
Example output from agent: "Your delivery truck (₦1.2M book value) has an outstanding vehicle loan of ₦1.8M. You owe ₦600,000 more than the asset is worth. Monthly loan payment: ₦45,000. Consider refinancing or disposal."

PHASE 6 — Insurance Intelligence Module
Inserts after Asset-Liability Linkage. Depends on Asset Register being live.

Step 18A — Insurance Policy Register
Build the ability to register and manage all insurance policies the business holds.
Policy data model:
Identity: policy number, insurance provider name, provider contact, policy type
Policy types: asset insurance, vehicle, fire and burglary, general liability, goods-in-transit, key-person, marine cargo, business interruption
Coverage: insurable items linked (asset register records or manual description), sum insured (coverage amount), excess/deductible, explicit exclusions
Financial: annual premium, payment frequency (annual, semi-annual, quarterly, monthly), next premium due date, total paid to date
Lifecycle: start date, end date, renewal date, auto-renewal flag, status (active, lapsed, expired, cancelled, under-claim)
Documents: policy document S3 reference, certificate of insurance reference, last renewal document
Insurable item types:
Asset from the asset register (vehicle, equipment, property)
Key person (linked to specific loan liability)
General business liability (not tied to a specific asset)
Goods in transit (inventory coverage)
Business interruption (revenue protection)

Step 18B — Insurance Claim Management
When the business invokes insurance, all claim details are tracked and connected to the affected asset.
Claim data model:
Claim reference number, linked policy, date of incident, date filed
Description of incident, asset damaged or lost (linked to asset register)
Estimated loss, claimed amount, settlement amount, settlement date
Claim status: filed, under-review, approved, partially-approved, rejected, closed
If claim rejected: triggers asset impairment or disposal workflow in asset module
If claim settled: posts income journal entry in accounting module

Step 18C — Insurance Intelligence Layer
Coverage gap detection: Every time a new asset is registered, the insurance module checks whether that asset type has an active policy. If not, it raises a COVERAGE_GAP_DETECTED event and the agent notifies the owner immediately.
Under-insurance detection: As assets depreciate and FX moves, coverage amounts can become dangerously misaligned with actual replacement costs. The system detects when sum insured falls significantly below current replacement cost (adjusted for inflation and FX).
Over-insurance detection: Flags when premium is being paid to cover assets that have been fully depreciated or disposed. Wasted premium is identified and owner is notified.
Premium-to-value ratio analysis: For each insured asset, compute the ratio of annual premium to asset book value. Flag outliers — both unusually high (possible mis-selling) and unusually low (possible undercover).
Renewal intelligence: Calculates renewal urgency based on coverage criticality:
Coverage Type
Reminder Schedule
Critical (vehicles, property, key-person)
90, 60, 30, 14, 7, 1 days before expiry + day of expiry
Standard coverage
30, 14, 7, day of expiry
Monthly/quarterly premium
Same as liability reminders — materiality score determines lead time

Lapse consequence: If a policy lapses without renewal, the system immediately raises POLICY_LAPSED, notifies the owner through all channels, and the agent includes the lapsed coverage in every subsequent financial state context until resolved.

Step 18D — Insurance Event Publisher & Module Connections
Events published by Insurance Module:
POLICY_REGISTERED
POLICY_RENEWED
POLICY_LAPSED
POLICY_EXPIRED
POLICY_CANCELLED
CLAIM_FILED
CLAIM_SETTLED
CLAIM_REJECTED
COVERAGE_GAP_DETECTED
PREMIUM_DUE
UNDER_INSURANCE_DETECTED
OVER_INSURANCE_DETECTED

Cross-module connections:
Asset Module: asset registration triggers coverage check; asset disposal triggers policy update prompt; claim write-off triggers asset disposal workflow
Accounting Module: premium payments post to "Insurance Expense" account; claim settlements post as income; insurance module publishes events, accounting module posts entries
Liability Module: key-person insurance linked to specific loans appears in liability register
Notification Engine: all alerts route through the central notification layer (Step 20)
Agent Module: lapsed policies, coverage gaps, and claim statuses included in every financial state context

PHASE 7 — Reminder & Notification Engine
Consumes events from all other modules. Produces nothing except alerts.

Step 19 — Reminder Scheduling Engine
Build the logic that computes when reminders should fire based on obligation due dates, materiality scores, and coverage ratios.
Materiality score formula:
materiality_score = obligation_amount / monthly_revenue

> 20% of monthly revenue = High materiality
5-20% of monthly revenue = Medium materiality
< 5% of monthly revenue = Low materiality

Coverage ratio check:
coverage_ratio = current_cash / obligation_amount

coverage_ratio < 1.5 AND days_until_due < 14 → URGENT
coverage_ratio < 1.0 → CRITICAL (immediate proactive agent alert)

Lead time by materiality:
Critical (coverage < 1.0): immediate alert
High materiality: 21, 14, 7, 3, 1 days before
Medium materiality: 14, 7, 1 days before
Low materiality: 3 days before only
This engine is called by: the liability module, the tax module, the insurance module, and the billing module. One engine, multiple callers.

Step 20 — Notification Delivery Layer
Build the multi-channel notification system as a general-purpose service that any module can call.
Channels and when each is used:
Channel
Used For
Technology
In-app notification
All alerts, always
WebSocket push to frontend
Email
All alerts above Low materiality
AWS SES
WhatsApp
Urgent and Critical alerts + customer debt reminders
WhatsApp Business API
SMS
If other channels not acknowledged within 2 hours
Termii (Nigerian provider)

Notification template system: Templates are stored in the database, parameterised with variables ({{customer_name}}, {{amount}}, {{due_date}}), and versioned. Different templates for different alert types and escalation levels.
Escalation logic: If an alert is sent and not acknowledged within the defined window, it escalates to the next channel automatically. In-app → Email → WhatsApp → SMS.

Step 21 — Event Consumer — Notification Worker
Build Celery workers that listen to the event bus and trigger reminders when relevant events arrive.
Events consumed and actions triggered:
Event Consumed
Reminder Action
LIABILITY_REGISTERED
Schedule tiered reminder chain
INSURANCE_POLICY_REGISTERED
Schedule renewal reminder chain
INVOICE_OVERDUE
Trigger Level 1 escalation ladder
PROMISE_TO_PAY_BROKEN
Trigger escalation resume
COVERAGE_GAP_DETECTED
Immediate owner alert
POLICY_LAPSED
Immediate critical alert all channels
PAYMENT_OVERDUE
Tiered reminder based on materiality
TAX_DEADLINE_APPROACHING
Filing reminder

PHASE 8 — Tax Engine
Fully independent module. Computes tax from existing transaction data via events.

Step 22 — Tax Constants & Rules Engine
Define all Nigerian tax rules as configuration, not hardcoded logic.
Tax rules as configuration:
Tax Type
Rate
Applicability
Filing Frequency
VAT
7.5%
All taxable goods and services
Monthly (FIRS)
WHT — Services
10%
Professional and consulting services
Monthly
WHT — Rent
10%
Rental payments made
Monthly
WHT — Dividends
10%
Dividend distributions
At payment
CIT
30% (large), 20% (medium), 0% (small)
Annual corporate income
Annual
PAYE
Progressive (7.5%–24%)
Employee salaries
Monthly
NHF
2.5% employee
Housing fund contribution
Monthly

Rules are in configuration files, not code. When FIRS updates rates, you change configuration — no code deployment required.

Step 23 — Real-Time Tax Computation
Build event consumers that listen for TRANSACTION_CREATED events and update running tax liability totals automatically.
Tax computation workflow:
Every transaction event triggers a tax classification check
If taxable: compute applicable tax, update running liability total for that tax type
Tax liability totals stored per tenant per tax type per period
These totals feed directly into the liability register (visible as "Tax Liabilities")
When a tax payment is made, reduce the liability total and post the accounting entry

Step 24 — Tax Calendar & Filing Alerts
Build the filing deadline calendar and connect it to the notification engine.
Filing calendar:
Monthly VAT return: due 21st of following month
Monthly WHT remittance: due 21st of following month
Monthly PAYE remittance: due 10th of following month
Annual CIT filing: due 6 months after financial year end
Alert schedule: 30 days, 14 days, 7 days before each deadline. Alerts include current computed liability amount, what has already been remitted, and what remains outstanding.

PHASE 9 — Data Platform & Event Store
Start this in parallel from Phase 2. The sooner it runs, the more training data ML models have.

Step 25 — S3 Event Store
Build an event consumer that writes every event to S3 in Parquet format, partitioned by tenant and date. This is your append-only audit trail and ML training data source.
Partition structure:
s3://amss-events/
  tenant_id=xxx/
    year=2026/
      month=02/
        day=28/
          events.parquet

S3 Object Lock: All event store files are written with WORM (Write Once Read Many) protection. Financial event history is immutable. No file can be overwritten or deleted. This satisfies the 7-year regulatory retention requirement.
Why start early: You want as much historical event data as possible before ML models need it. Starting this in Phase 9 means you have been collecting data since Phase 2.

Step 26 — Feature Engineering Pipeline
Build the AWS Glue batch jobs that transform raw events from S3 into structured feature vectors.
Features computed per tenant:
47 financial features: cash position, burn rate, receivables aging, liability coverage ratios, payment behaviour patterns, revenue trends, expense ratios, asset-liability ratios
12 macro features: current CBN rate, inflation rate, USD/NGN rate, diesel price index, food inflation index, monetary policy stance, credit market conditions
Output: Parquet files in S3 feature store, partitioned by tenant and date. Refreshed nightly by Glue batch job scheduled via Apache Airflow (MWAA).

Step 27 — Macro Data Ingression
...

## MODULE C — Customer Risk Flagging & Configurable Risk Rules Engine

**Overview**: Allow tenants to configure risk rules for their own thresholds. Rules are data-driven.

### Rule Data Model
- Rule identity, trigger condition, risk level, automatic actions, active flag/effective date.

### Default Risk Rules
Seven default rules provided, all thresholds configurable.

### Risk Score Computation
Continuous score (0–100) from weighted signals; weights configurable.

### Recalculation Triggers
Score recalculated reactively on payments, overdue invoices, promises, reminders, new invoices.

### Risk Status Lifecycle
Green → Amber → Red → Black with explicit triggers and manual recovery to Green.

### Org-Specific Rule Interface
Threshold settings, custom rule builder, risk level actions.

### Published Events
`CUSTOMER_RISK_LEVEL_CHANGED`, `CUSTOMER_FLAGGED_AMBER`, `CUSTOMER_FLAGGED_RED`, `CUSTOMER_BLOCKED`, `CUSTOMER_RISK_CLEARED`, `CREDIT_LIMIT_BREACHED`, `PROMISE_TO_PAY_BROKEN`, `INVOICE_CREATION_BLOCKED`, `COLLECTION_ESCALATION_TRIGGERED`.

### Integrations
- Accounting: invoice creation blocked on CUSTOMER_BLOCKED event.
- Cash Flow Forecaster: adjust projections by risk scores.
- Agent: use risk register in queries.
- ML Predictor: risk score as input/output.

### Implementation Slots
After Step 14, split into 14A–14C; after Step 15, add 15A–15D; after Step 18A, add 18B–18D.

### Bigger Picture Scenario
Explained integrated operation with assets, insurance, claims, overdue invoices, agent brief.

---

This markdown serves as the reference for future development planning. Maintain its contents and update as the project evolves.