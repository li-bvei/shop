# store-admin-backend

Django + DRF + MySQL API for the 店铺管理系统 frontend (`../store-admin-frontend`).
Models mirror the frontend's data shapes 1:1 so the frontend's `src/api/*.ts`
layer is a thin DTO conversion, not a redesign.

## Stack

- Django 4.2 (LTS) + Django REST Framework
- MySQL via PyMySQL (pure-Python driver — no native build toolchain required)
- JWT auth via `djangorestframework-simplejwt`
- `django-cors-headers` for the Vite dev server origin

## Setup

```bash
cd store-admin-backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # adjust DB credentials if needed

mysql -u root -e "CREATE DATABASE store_admin CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

python manage.py migrate
python manage.py seed_demo_data   # branches, payment methods, admin + branch demo logins
python manage.py runserver 8071   # must match VITE_API_BASE_URL in the frontend's .env.development.local
```

Demo logins created by `seed_demo_data` (passwords never change — see
`common/test_utils.py:ApiTestCase` and `accounts/tests.py` for the automated
tests that guard this). Actual passwords are not published here — read them
straight from the source of truth, `branches/management/commands/seed_demo_data.py`:

| account | role | branch |
| --- | --- | --- |
| `admin` | admin | — sees/writes every branch **in its own Organization** |
| `shinsaibashi01` | branch | shinsaibashi only |
| `namba01` | branch | namba only |
| `umeda01` | branch | umeda only |

`staff`-role accounts are not seeded by default — only an `admin` account can
create one, from Settings → 账号管理, linked one-to-one to an existing
`StaffMember` row.

## Auth

- `POST /api/token/` `{username, password}` → `{access, refresh}`
- `POST /api/token/refresh/` `{refresh}` → `{access}`
- `GET /api/auth/me/` (bearer token) → `{account, displayName, role, branchId, staffMemberId}`,
  the exact shape `stores/auth.ts` expects.
- `GET/PATCH /api/auth/preference/` — per-user language/theme, lazily created on first read.
- `POST /api/auth/change-password/` — any authenticated account changes its own password.

## Domain apps

| app | model(s) | notes |
| --- | --- | --- |
| `organizations` | `Organization` | the multi-tenant root — every business record ultimately traces back to one Organization; see below |
| `accounts` | `User` (extends `AbstractUser`), `UserPreference` | `role: admin\|branch\|staff`, `organization` FK, `branch` FK (null for admins), `staff_member` nullable 1:1 |
| `branches` | `Branch` | `organization` FK; id = frontend's slug (`shinsaibashi`, `namba`, `umeda`) |
| `staff` | `StaffMember`, `StaffTransfer` | `employment_type: regular_monthly\|hourly\|temporary`, `hire_date`/`leave_date`/`note`; branch-scoped, `?branch=<id>` filter; `StaffTransfer` is the append-only inter-branch move log |
| `paymentmethods` | `PaymentMethodDef` | branch-scoped; `code='cash'` is protected — server rejects rename/delete, but not reordering; `reorder` action for drag-to-reorder |
| `dailyreports` | `DailyReport`, `DailyReportHistory` | see below |
| `purchasing` | `Supplier`, `PurchaseRecord` | `Supplier.organization` FK (shared within one Organization, never across); filtering/pagination/price comparison, see below |
| `dashboard` | (no models — pure aggregation views) | `DashboardSummaryView`, `MonthlyAnalysisView`, both Organization-scoped |
| `scheduling` | `BranchScheduleSetting`, `SchedulePeriod`, `AvailabilityRequest`, `Shift`, `ActualWorkRecord` | monthly auto-period shift planning + attendance confirmation, **not** a time-clock system |
| `wages` | `WageRule`, `WageMonthlyClosing`, `WageEmployeeResult`, `WageDailyDetail` | `v2_simple` hourly/temporary wage calculation engine |
| `promotions` | `Campaign`, `Customer`, `PointsLedger`, `CheckInRecord`, `SpendVerification`, `Prize`, `Milestone`, `LotteryDraw`, `Voucher`, `MilestoneClaim`, `RiskEvent`, `StaffPermission` | customer loyalty card + lottery from 打卡与抽奖实施方案.md — check-in, points, weighted server-side draw, next-visit vouchers, milestones, points spending/expiry, rate limiting, risk flags, monthly report. See below |

### Organization (multi-tenant) scoping

`Organization` is the top-level tenant boundary. `User`, `Branch`, and
`Supplier` each carry an `organization` FK (`on_delete=PROTECT`); every other
business model traces its own Organization transitively through `branch` or
`employee`. **Every query is explicitly filtered by Organization** — never
relying on "it's implicitly scoped because it goes through a branch that
happens to belong to one org" without an explicit filter, since a missed
filter here is a genuine cross-tenant data leak, not just a UX bug.

`common/permissions.py:BranchScopedQuerysetMixin` (applied to every
branch-owned resource — `DailyReportViewSet`, `DailyReportHistoryViewSet`,
`PurchaseRecordViewSet`, `PaymentMethodDefViewSet`, `StaffMemberViewSet`, and
the `scheduling`/`wages` viewsets via their own equivalent scoping) does both
levels in one place:

- Branch-role users only ever see their own branch's rows; the `branch`
  field is optional on create and silently overridden server-side.
- Admin accounts see every branch **within their own Organization** —
  `qs.filter(**{f'{relation_name}__organization_id': user.organization_id})`
  — never the whole system. This was a real gap this round closed: before
  the Organization layer, "admin" implicitly meant "sees everything," which
  stopped being true once a second Organization could exist.

`Supplier` is shared master data *within* one Organization (any branch in the
same Organization can use the same supplier), never across Organizations.

**Platform-level superuser vs. business `admin` role — never conflated.**
Django's own `is_superuser`/`is_staff` (Django admin site access) and this
app's business `role='admin'` are deliberately separate concepts. A
`role='admin'` account is scoped to its Organization everywhere in this
API — but Django's `/admin/` site has zero Organization awareness, so if a
business-admin account also carried `is_staff=True`/`is_superuser=True` (as
the seed script used to set, before this round), it could bypass every
Organization boundary through the Django admin site. Data migration
`accounts/0005_separate_business_admin_from_django_superuser.py` clears
those flags on all existing `role='admin'` rows; `seed_demo_data` never sets
them again. The 4 demo accounts' passwords and login behavior are unaffected
— only the unrelated Django-admin-site flags changed.

Every new Organization gets exactly one seeded via the same data migration
(`default-store-group` / 现有店铺集团 / 既存店舗グループ) that all
pre-existing data was backfilled into, so the 2023–2026 purchase history and
existing branches/accounts kept working unchanged.

### Role model: admin / branch / staff

`common/permissions.py:DenyStaffRole` is registered in
`REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES` alongside `IsAuthenticated`, so
**every endpoint blocks the `staff` role by default** unless it explicitly
opts back in with `permission_classes = [IsAuthenticated]`. This is the
project-wide mechanism that makes new endpoints staff-safe without having to
remember to add a check — the opt-in list is short and auditable:

- `MeView`, `PreferenceView`, `ChangePasswordView` (self-service)
- `SchedulePeriodViewSet`, `AvailabilityRequestViewSet`, `ShiftViewSet`,
  `ActualWorkRecordViewSet` (each internally scopes `staff` to read-only
  access to its own rows — `AvailabilityRequestViewSet` additionally allows
  staff to create/edit its own not-yet-locked wishes)
- `WageEmployeeResultViewSet` (staff sees only rows for its own linked
  `StaffMember`; can edit `manual_addition`/`manual_deduction`/
  `adjustment_reason` only while the parent closing is still `draft`)
- `WageMonthlyClosingViewSet.lock`/`.unlock` (opts back into
  `IsAuthenticated` only to reach a second, explicit
  `role != ADMIN → PermissionDenied` check — lock/unlock is admin-only)

Frontend menu-hiding (`AppSidebar.vue`, `router.beforeEach` role guard) is a
UX convenience only; every one of the checks above is independently
re-verified server-side and is what `accounts/tests.py:StaffRolePermissionBoundaryTests`
exercises against a real request across ~9 endpoints.

**Full matrix:**

| resource | admin | branch | staff |
| --- | --- | --- | --- |
| Dashboard / monthly analysis | ✅ all branches or filtered | ✅ own branch only | ❌ 403 |
| Daily reports / history | ✅ | ✅ own branch | ❌ 403 |
| Purchasing / suppliers | ✅ own Organization | ✅ own branch | ❌ 403 |
| Payment methods (incl. reorder) | ✅ own Organization | ✅ own branch | ❌ 403 |
| Staff list (management) | ✅ own Organization | ✅ own branch only | ❌ 403 |
| Staff transfer (inter-branch) | ✅ admin-only, own Organization | ❌ 403 | ❌ 403 |
| Account management | ✅ create/edit/reset/delete, own Organization | ❌ 403 | ❌ 403 |
| Branch management | ✅ own Organization | ❌ 403 | ❌ 403 |
| Schedule periods / publish | ✅ | ✅ own branch | 🔒 read own published shifts only |
| Availability requests | ✅ read | ✅ own branch read/manage | ✅ own wishes only (create/edit) |
| Shifts | ✅ | ✅ own branch | 🔒 read-only, own rows |
| Actual work records / confirm / lock | ✅ | ✅ own branch | 🔒 read-only, own rows |
| Wage rules | ✅ | ✅ own branch | ❌ 403 |
| Wage monthly closings / generate / confirm | ✅ | ✅ own branch | ❌ 403 |
| Wage closing lock / unlock | ✅ admin-only | ❌ 403 | ❌ 403 |
| Wage employee results | ✅ | ✅ own branch | 🔒 own linked employee only, limited-field write |
| Own password change | ✅ | ✅ | ✅ |

### Server-derived fields (never trust the client for these)

- `PurchaseRecord.amount` = `quantity * unit_price`, recomputed on every save.
- `DailyReport.payment_amounts['cash']` = `total_revenue` − sum of every
  other payment method, recomputed on every save.
- `DailyReportHistory.saved_at` / `edited_by` / `edited_by_name` are always
  set from the authenticated request, never from the request body.
  History rows are append-only (`PATCH`/`DELETE` return 405).
- All wage amounts (`WageDailyDetail.*`, `WageEmployeeResult.estimated_total`)
  are computed server-side in `wages/calculation.py` using `Decimal` only —
  the frontend never performs money math, only displays server-returned figures.

### Purchase item suggestions

`GET /api/purchases/suggestions/?supplier=<id>&q=<keyword>` — ranks by
frequency+recency score (`useCount * 20 + max(0, 60 - daysSinceLatest)`),
scoped to one supplier so `lastUnitPrice` stays comparable. Grouped in Python
from a single flat, capped (`[:500]`), pre-`order_by('-date', '-id')` fetch —
**not** a `GROUP BY` with a per-distinct-item-name correlated subquery, which
was measured at 2.2s against a supplier with ~2,000 records with no supporting
index. The recency bonus already caps out at 60 days back, so capping the
underlying scan at the most recent 500 rows never changes which items rank
highest; it only bounds worst-case cost as the table keeps growing.

### Supplier payable

`Supplier.monthly_payable` (serializer field) = `payable_override` if set,
else the sum of this month's `PurchaseRecord.amount` for that supplier.
The remittance account is split into `bank_name`/`branch_name`/
`account_type`/`account_number` plus three free-text kana readings
(`bank_name_furigana`/`branch_name_furigana`/`account_holder_furigana`) —
kept as separate fields rather than one free-text line since a kanji name
can have more than one plausible reading and only the supplier can confirm
which one their bank has on file (migration `0007_split_bank_account_fields`
replaced the old single `bank_account`/`bank_account_furigana` fields).
`phone` has always been optional server-side (`blank=True`); a frontend-only
required-field rule was removed in the 2026-08-21 round, it was never
enforced by this API.

### Purchasing: filtering, pagination, item-name normalization, price comparison

`GET /api/purchases/` is now server-side paginated (`PurchasePagination`,
50/page, `page_size` up to 200) with filters: `branch`, `supplier`, `month`
(`YYYY-MM`), `date_from`/`date_to`, `item_name` (substring match against the
normalized name), and `ordering` (`date`, `unit_price`, `amount`, `item_name`,
any `-`-prefixed for descending). This replaced the old unpaginated
full-table fetch, which stopped being practical once the real dataset passed
5,000 records.

- **`PurchaseRecord.item_name_normalized`** (`purchasing/utils.py:normalize_item_name`)
  applies Unicode NFKC normalization (full-width → half-width digits/letters/
  parentheses/spaces) plus whitespace collapsing and lowercasing, recomputed
  on every save. Deliberately conservative: it never strips quantity/unit
  descriptors (`1P`, `1ケース`) or an embedded supplier-name suffix, since
  those can genuinely distinguish different SKUs — collapsing them would
  risk comparing unlike products. Backfilled for all pre-existing records via
  data migration `purchasing/migrations/0005_backfill_item_name_normalized.py`.
- **`price_change=up|down` filter** requires `month` to also be set (an
  unbounded price-direction scan over the whole table would be expensive for
  no real benefit — this is a monthly-review feature by design). Direction is
  computed by `purchasing/services.py:compute_price_comparisons()`, comparing
  each record's `unit_price` against the **average unit_price of the same
  (branch, supplier, item_name_normalized) in the calendar month immediately
  before** the record's own month — never a stale older month, never a
  different supplier's price for a similarly-named item. Records with no
  such prior-month data are simply never flagged in either direction.
- **`GET /api/purchases/price_history/?branch=&supplier=&item_name=`** —
  chronological unit-price history (last 100) for one exact
  (branch, supplier, item) combination.
- **`GET /api/purchases/supplier_comparison/?branch=&item_name=`** — the one
  place this feature *does* deliberately mix suppliers: latest/average
  price and record count per supplier for the same item at one branch,
  cheapest first, so the user can compare and pick.

## Scheduling module (`scheduling/`)

Two independent concepts, intentionally kept apart:

1. **Planned** — `BranchScheduleSetting` (per-branch default shift-time
   templates: morning/afternoon/full-day start-end times) →
   `SchedulePeriod` (now created from just `branch` + `month`; start/end
   dates are always server-computed from the calendar month, never
   client-supplied, and the month is immutable once created) →
   `AvailabilityRequest` (a staff member's submitted availability wishes,
   also month-scoped) → `Shift` (the admin/branch's assigned shift,
   validated against availability and against overlapping shifts for the
   same employee via `scheduling/services.py:check_shift()`, which returns
   `(hard_errors, soft_warnings)` — hard errors always block save (including,
   this round, employee-not-in-branch, period-branch mismatch, and
   date-outside-period); soft warnings (e.g. outside submitted availability)
   require an explicit `override=true` resubmission, returned to the
   frontend as `{'code': 'shift-conflict', 'warnings': [...]}`).
   `SchedulePeriod.publish` locks the period's shifts from further plain
   edits and bumps a version number. The frontend renders this as a
   two spreadsheet-style monthly grids (date rows × employee columns), split
   by `StaffMember.work_area` into kitchen and hall. Cell states are
   休/上午/下午/全日. A pure reconciliation function preserves failed/declined
   local edits after partial batch saves. Migration `scheduling.0006` adds an
   ordinary database `UniqueConstraint(branch, month)`; MySQL permits multiple
   NULLs, so legacy `month=NULL` periods remain intact while concurrent current
   month creation is protected at both serializer and database layers.
2. **Actual** — `ActualWorkRecord`, the manager's confirmation of what was
   actually worked (start/end/break). This is **explicitly not a time-clock
   system** — there is no punch-in/punch-out, GPS, or biometric capture
   anywhere in this codebase, and it deliberately does **not** track separate
   late/early/extended-minute figures; a manager enters the confirmed actual
   times, optionally seeded from the published `Shift` via
   `SchedulePeriod.generate_actual_records` (idempotent — keyed on the
   model's own `(employee, work_date)` unique constraint, safe to call
   repeatedly). `ActualWorkRecordSerializer.validate()` requires a non-empty
   `adjustment_reason` whenever the actual times differ from the linked
   shift and the employee wasn't marked absent. `ActualWorkRecord.bulk_confirm`/
   `.lock`/`.unlock` manage the record's status; wage generation only ever
   reads `confirmed`/`locked` rows.

### Employee inter-branch transfer (`staff/models.py:StaffTransfer`)

Admin-only, same-Organization-only, append-only — `POST /api/staff-transfers/`
moves a `StaffMember.branch` and, if the employee has a linked login account,
syncs that account's `branch` too, inside one `transaction.atomic()` block.
If the employee has any `Shift` at the old branch on or after the transfer's
`effective_date`, the request is rejected with
`{'code': 'has-future-shifts-at-old-branch', 'shifts': [...]}` unless resent
with `force: true` — future shifts are never silently dropped. Historical
records (past shifts, past wage results) keep their original branch
reference forever; only the employee's *current* branch changes. Repeat
transfers (including moving back to a previous branch) create a new
`StaffTransfer` row each time — the log is never edited or overwritten.

Midnight-crossing time ranges (a shift or availability window that spans
past midnight) are handled throughout via a uniform minute-offset scale
(`day_offset * 1440 + hour*60 + minute`) rather than wall-clock comparisons,
so a 22:00–02:00 shift is not silently misclassified.

## Wage calculation module (`wages/`) — current `v2_simple` engine

The wage engine was rewritten this round to a deliberately simplified
`v2_simple` calculation (`WageEmployeeResult.calculation_version`). **v1's
historical locked results are never recalculated or overwritten** —
`generate_wage_results()` only ever touches `draft` closings, and all 28
pre-existing v1-era wage tests still pass unmodified against the new engine,
which is what confirms the older E2E scenario was already premium-free by
construction and genuinely unaffected by this rewrite.

Only `StaffMember.employment_type in {hourly, temporary}` are ever paid
through this engine; `regular_monthly` staff only have their hours tracked
(no wage figures are ever generated for them — this is an explicit,
tested rule in `WageEndToEndFlowTests`).

**Formula** (`wages/calculation.py`, all `Decimal`, minute-precision, never `float`):

- `base_amount = actual_paid_minutes / 60 × hourly_rate`. That's it — **no
  night-shift premium, no overtime premium, no statutory-holiday premium**.
  This is an explicit, intentional simplification for this tool, not a claim
  of full labor-law/payroll compliance; see the disclaimer below.
- The wage rule in effect is selected by the **actual work date** falling
  inside a `WageRule`'s `effective_from`/`effective_to` range (validated
  non-overlapping per employee via `select_for_update()` + `check_no_period_overlap()`
  to be race-safe under concurrent edits). The simplified `WageRule` form
  only exposes employee / effective dates / hourly rate / default
  transportation / note — the old night/overtime/statutory-holiday premium
  rate fields still exist on the model (so v1's historical rows keep their
  data) but are never read by `v2_simple` and never shown on this page.
- **Transportation**: `WageEmployeeResult.rule_transportation_amount` always
  tracks the rule-derived default (per-attendance or monthly-fixed, kept
  current on every regenerate). `monthly_transportation_override` is a
  nullable per-employee-per-month override — setting it requires a reason
  (audited with operator + timestamp); clearing it (`null`) reverts instantly
  to `rule_transportation_amount` with no regenerate needed, since that
  field is always already there to revert to.
- **Bonus**: `WageEmployeeResult.bonus_amount` is its own dedicated
  per-employee-per-month field (never rolled over to the next month), with a
  required note whenever it's non-zero and its own operator/timestamp audit.
- **Departing-employee special period**: `calculation_period_start`/`_end`
  default to the full month, automatically capped at `leave_date` when it
  falls mid-month, or can be explicitly overridden by an admin — either way,
  both dates are validated to stay within the closing's own month. PATCHing
  either date, or clearing both, immediately reruns the closing calculation.
- PATCHing `bonus_amount` or `monthly_transportation_override` via the API
  recomputes `transportation_amount`/`estimated_total` immediately
  (`WageEmployeeResultViewSet.perform_update()`) — the displayed total is
  never stale until the next full `generate()`.
- Manual adjustments (`WageEmployeeResult.manual_addition`/`manual_deduction`,
  the v1-era fields) still require a non-empty `adjustment_reason` when used.
- Rounding: `Decimal.quantize(Decimal('1'), rounding=ROUND_HALF_UP)` — to the
  nearest yen, centrally configured (`round_yen()`, `YEN_ROUNDING_POINT`/
  `YEN_ROUNDING_MODE` in `wages/calculation.py`).
- If any confirmed attendance day has no matching `WageRule` in effect,
  `WageMonthlyClosing.confirm` is blocked and returns
  `{'code': 'missing-wage-rule', 'missing': [{employee, date}, ...]}` rather
  than silently generating a partial or zero result. `confirm` also refuses
  to proceed if results were never generated, or if `ActualWorkRecord`/
  `WageRule` data changed since the last `generate()`
  (`wages/services.py:check_calculation_freshness()`), checked both before
  and again inside the atomic lock to close the race between a confirming
  request and a concurrent record edit.
- The simplified daily-detail view exposes only date / actual-start /
  actual-end / actual-break-minutes / paid-minutes / base-amount
  (`WageDailyDetailSerializer` sources the actual-time fields through the
  linked `ActualWorkRecord` via a dotted `source=`, no duplicated columns).

**Every** wage result carries this disclaimer (`wages/calculation.py:DISCLAIMER`,
also rendered on-screen and on the printed payslip):

> 临时工／时薪员工工资计算资料，不包含所得税、住民税、社会保险、雇用保险等法定扣除，不属于最终工资申报结果。

**Monthly closing workflow**: `draft → generate (repeatable) → confirm
(freezes results, blocked if any day is missing a wage rule or results are
stale) → lock (admin-only, bumps `version`) → unlock (admin-only, requires a
`reason`, returns to `draft`)`. All status transitions are wrapped in
`transaction.atomic()` + `select_for_update()` to be race-safe.

### Employee-facing setup and API usage

The current UI does not expose “add wage rule”. `StaffMemberSerializer`
wraps the current effective historical `WageRule` as `wage_setting`
(`hourly_rate`, monthly `transportation_amount`, `effective_from`, `note`).
A later setting closes the preceding rule on the previous day; locked-month
rules are not overwritten. Monthly result edits use
`PATCH /api/wage-employee-results/{id}/` (not POST).

### Historical compatibility (v1 only)

`night_*`, `overtime_*`, `holiday_*`, `manual_addition`, and
`manual_deduction` columns remain solely so historical v1 locked results can
still be read. The current v2_simple UI and calculation path neither exposes
nor computes those premiums/adjustments.

## Promotions module (`promotions/`) — loyalty card + lottery

The customer-facing loyalty card from `打卡与抽奖实施方案.md`. **Phases 1,
2, 2.5 and 3 are built**: registration, per-visit check-in, staff
spend-confirmation, points earning (phase 1); weighted prize pool,
server-side lottery draw, next-visit vouchers, staff voucher redemption
(phase 2); spending points on a draw or a voucher, cumulative-points
milestones, points expiry (phase 2.5); IP rate limiting, a rule-based
risk-flag engine, per-account staff switches, an APPI retention cleanup,
and a monthly operational report (phase 3). New-device recovery is a
phone+PIN flow (see **Card identity & recovery**) — no SMS, no external
service.

### Three hard rules (do not weaken)

1. **The only trusted event is a signed-in staff member confirming a spend
   with the customer present.** The public guest API never accepts
   `amount_yen` / `table_number` / `consumed_at` / `points_granted` /
   `prize_id` or a direct balance write. Points are granted only by
   `promotions.services.verify_spend`, called from the authenticated
   staff endpoint. The **lottery draw is always server-side** —
   `services.draw_lottery` picks the prize with `secrets.SystemRandom`
   under a `select_for_update()` lock on the prize pool; the frontend only
   plays the reveal.
2. **All value is "next visit".** Nothing in this feature touches the
   current bill — no discount, no refund at the register. Lottery prizes,
   milestone rewards and points-redeemed vouchers are all `Voucher` rows
   redeemed by staff on a *later* visit.
3. **No phone verification.** `Customer.phone` is an unverified key, unique
   per Organization (`normalize_phone` folds surface variation to one
   local-format digit string). A fake or borrowed number is accepted by
   design.

### Model / scoping

- `Campaign` is branch-owned (org traced through `branch`, like
  `PurchaseRecord`), managed via `BranchScopedQuerysetMixin`. One `active`
  campaign per branch is the normal case.
- `Customer` is **Organization-scoped, not branch-scoped** — a card works at
  every branch in the chain. `CustomerViewSet` filters on
  `organization_id` directly.
- `PointsLedger` is the append-only points ledger (same rule as
  `inventory.StockTransaction`): every earn/spend/adjust is one immutable
  row, `Customer.points_balance` is their running sum, corrections are new
  offsetting rows. `verify_spend` / `adjust_points` / `void` all write the
  balance and the ledger row in one `transaction.atomic()` under a
  `select_for_update()` lock on the `Customer`.
- `SpendVerification` is append-only — the ViewSet routes no `PUT`/`PATCH`/
  `DELETE`; the only correction path is `POST
  /api/promotions/spend-verifications/{id}/void/` (admin only), which marks
  it voided and writes an offsetting ledger row.
- Points formula: `amount_yen // 1000 * campaign.points_per_1000yen` — the
  sub-¥1,000 remainder never earns.
- `CheckInRecord` has `UniqueConstraint(customer, campaign, local_date)`;
  `local_date` is the **business day** per `Campaign.business_day_cutover`
  (default 05:00 — a 02:00 sale counts as the previous day,
  `promotions.utils.business_local_date`). A second spend on the same
  business day still earns points, it just doesn't log a second check-in.
  `verify_spend` refuses a `consumed_at` in the future or more than 24h
  old; anything in between is filed against its own business day.

### Card identity & recovery

`Customer.card_token` (`secrets.token_urlsafe(16)`, unique, non-rotating)
is the card's **bearer credential** — the QR the counter scans, and what
the `pc_guest` cookie / `X-Guest-Token` header carry. It is only ever
returned to a caller that has already proved possession of it, or passed
the PIN check below. Phone numbers are not secret (`§14` — "a stranger who
knows your number can view, never take"), so:

| path | factor | grants |
| --- | --- | --- |
| `GET /guest/card/` | the token itself (cookie / header) | full card, echoes the token back |
| `POST /guest/login/` | phone + birthday `MM-DD` | **read-only** snapshot — never the token; birthday is a weak check, not a boundary |
| `POST /guest/recover/` | phone + 6-digit PIN | full card + re-issues the token (cookie) |
| in person | staff lookup by phone | `customers/lookup/` returns masked phone + balance, never the token |

The optional recovery **PIN** (`Customer.pin_hash`, Django password hash,
never plaintext) is set at registration or later via `POST /guest/set-pin/`
(needs the token — you can only PIN a card you hold). It is the only
self-service way back to a *spendable* card on a new device. Guards:
`normalize_pin` rejects a malformed or obvious PIN; `recover_card` is
per-phone rate-limited in the shared cache (5 wrong tries → 1h lock, 15/day
→ 24h lock) on top of the IP `GuestWriteThrottle`, and a lockout raises a
`RiskEvent`. There is **no self-service PIN reset** — a forgotten PIN goes
to staff in person (any reset keyed on phone+birthday would just re-open
the takeover hole). `PROMOTIONS_TRUSTED_PROXY_COUNT` (env, default 1) tells
`client_ip` how many proxies to trust in `X-Forwarded-For` so the throttle
key can't be spoofed.

### Lottery / vouchers / milestones (phase 2 / 2.5)

- `Prize` is the weighted pool (one row per tier). Probability =
  `weight / Σ(active weights)`, computed live; the drawn weight is
  snapshotted onto `LotteryDraw` so re-tuning never rewrites history.
  `reward_config` shape is validated per `reward_type`
  (`serializers.validate_reward_config`, 开发任务书 §4.8).
  `total_stock` caps lifetime wins, `daily_stock` caps per-branch-per-
  business-day (the ¥5,000 voucher is 1/day/branch). `reward_type ==
  points_refund` hands points back instead of a voucher ("谢谢参与");
  every other type issues a `Voucher`.
- `services.draw_lottery` is **idempotent on `request_id`** (unique
  column). It spends `campaign.points_per_draw` for `source='points'`, or
  one `Customer.draw_chances` for `source='direct'` (granted by the
  optional `direct_draw_threshold_yen` dual track at spend time).
- `Voucher` — `redemption_code` is an 8-char code from an unambiguous
  alphabet (no `0/O/1/I/L`). Staff redeem via
  `POST /api/promotions/vouchers/{verify,redeem}/`: the service checks
  Organization scope (a card works chain-wide), status, expiry, min-spend,
  and — for `requires_manual_approval` prizes (the ¥5,000 voucher) —
  refuses a `staff`-role account, requiring a `branch`/`admin` operator
  whose id is recorded as `approved_by`.
- `Milestone` + `MilestoneClaim`: `verify_spend` bumps
  `Customer.lifetime_points_earned` (monotonic — spending/expiry never
  lower it) and `services._apply_milestones` issues one voucher per newly
  crossed threshold, guarded by `UniqueConstraint(customer, milestone)`.
- `POST /api/guest/redeem/` `{type: draw|voucher, request_id}` and
  `POST /api/guest/draw/` `{request_id}` (spends a free draw chance).
- Points expiry: `python manage.py expire_promotions_points` (daily cron)
  zeroes the balance of any customer inactive for their campaign's
  `points_expire_months` (default 12) and logs an `expire` ledger row.
- Admin: `CRUD /api/promotions/{prizes,milestones}/?campaign=<id>`;
  `GET /api/promotions/campaigns/{id}/{draws,vouchers}/` (paginated).

### Anti-fraud & reports (phase 3)

- **Rate limiting** — `promotions/throttling.py` opts the public guest
  endpoints into IP-scoped DRF throttles (`GuestReadThrottle` 120/min,
  `GuestWriteThrottle` 20/min on register/login/redeem/draw), plus a
  per-account `StaffVerifyThrottle` (40/min) on spend-verification create.
  Counts live in the shared DB cache; no `DEFAULT_THROTTLE_CLASSES` is set,
  so nothing else in the project is throttled.
- **`RiskEvent`** — `promotions/risk.py` evaluates the §13 rules *after*
  `verify_spend` / `draw_lottery` / `register_customer` /
  `void_spend_verification` (each rule wrapped so a bug can never break a
  checkout). A flag is a signal, never a block — the hard rejections stay
  in the services. Rules: off-hours confirmation, staff rapid
  confirmations, amount == a voucher threshold, one customer across many
  branches, one IP registering many phones, rapid draws, concentrated
  high-value wins, spend voided after its value was already used.
  `dedupe_key` (unique) stops a re-evaluation piling up duplicates.
  `GET /api/promotions/risk-events/` (branch: own branch + branchless
  flags; admin: whole org), `POST {id}/review/` `{status, note}`.
- **`StaffPermission`** — per-account `can_verify_spend` /
  `can_redeem_voucher`. Absent row = both on (the phase-1 default). Checked
  in the staff endpoints; `GET/PATCH /api/promotions/staff-permissions/`
  (admin only) lists every staff account with its effective switches.
- **Retention** — `python manage.py purge_stale_promotion_customers`
  (`--dry-run`, `--months`) erases customers with no activity for
  `PROMOTIONS_CUSTOMER_RETENTION_MONTHS` (env, default 24), same
  de-identification as an explicit deletion request.
- **Report** — `GET /api/promotions/campaigns/{id}/report/?month=YYYY-MM`:
  spend / per-staff stats / points flow / draw & voucher shipment / risk
  counts for the month. Aggregation only, no `float`.

### Endpoints

| method | path | who | notes |
| --- | --- | --- | --- |
| POST | `/api/guest/register/` | public | `{store_token, phone, name?, birthday_md?, pin?, consent:true}` → `card_token` + `Set-Cookie: pc_guest`. `consent` must be `true`; `pin` (6 digits, optional) sets the recovery PIN. `store_token` is a `django.core.signing` token from `CampaignSerializer.store_token`. An already-registered phone returns `{existing:true}` (200, no token) |
| POST | `/api/guest/login/` | public | `{phone, birthday_md}` → **read-only** card snapshot. Never returns `card_token`. Birthday is a weak second factor, not a boundary |
| POST | `/api/guest/recover/` | public | `{phone, pin}` → full card + `Set-Cookie: pc_guest` (regain a spendable card on a new device). Per-phone rate limit; generic errors; lockout raises a `RiskEvent` |
| POST | `/api/guest/set-pin/` | public | guest cookie / `X-Guest-Token` required → `{pin}` sets/replaces the recovery PIN on the held card |
| GET | `/api/guest/card/` | public | guest cookie **or** `X-Guest-Token` header (cross-port dev) → balance / lifetime / stamps / draw chances / `has_pin` / recent ledger / active vouchers / milestone progress |
| POST | `/api/guest/redeem/` | public | `{type: draw\|voucher, request_id}` → spend points; returns the draw result or the issued voucher |
| POST | `/api/guest/draw/` | public | `{request_id}` → spend one free draw chance |
| POST | `/api/promotions/spend-verifications/` | staff/branch/admin | `{card_token\|phone, amount_yen, table_number?, consumed_at?}` → `verify_spend` |
| POST | `/api/promotions/vouchers/verify/` | staff/branch/admin | `{redemption_code\|card_token\|phone}` → voucher(s) + `redeemable`/`expired` flags |
| POST | `/api/promotions/vouchers/redeem/` | staff/branch/admin | `{redemption_code, spend_amount_yen?}` — `staff` refused for approval-required prizes |
| CRUD | `/api/promotions/{prizes,milestones}/` | branch (own) / admin | `?campaign=<id>` scoped |
| GET | `/api/promotions/spend-verifications/mine/` | staff/branch/admin | own confirmations since local midnight |
| GET | `/api/promotions/spend-verifications/` | branch/admin | paginated, filterable (`branch`, `campaign`, `status`, `date_from/to`) |
| POST | `/api/promotions/spend-verifications/{id}/void/` | admin | `{reason}` (required) — reverses points |
| POST | `/api/promotions/customers/lookup/` | staff/branch/admin | `{card_token\|phone}` → name + masked phone + balance (never the full number or token) |
| CRUD | `/api/promotions/campaigns/` | branch (own) / admin | `GET {id}/{checkins,verifications,draws,vouchers}/` (paginated) |
| GET | `/api/promotions/customers/` | branch/admin | `?search=` (name/phone), paginated; detail includes recent ledger |
| POST | `/api/promotions/customers/{id}/points-adjust/` | admin | `{delta:int, note:str}` (note required) |
| DELETE | `/api/promotions/customers/{id}/` | admin | APPI erasure — removes the `Customer`, detaches + de-identifies its check-ins/verifications/ledger (kept for branch stats + audit) |

All lists here use `promotions.views.PromotionsPagination` (50/page, up to
200) — a local override of the project-wide "no pagination" default,
because these tables grow far faster than the daily report. The public
guest endpoints opt into IP throttles (`promotions/throttling.py`,
`promo_guest_read` / `promo_guest_write`); `spend-verifications` `create`
adds a per-staff `promo_staff_verify` ceiling.

### Shared cache

`settings.CACHES` now defines a `DatabaseCache` on `promotions_cache_table`
(the default `LocMemCache` isn't shared across gunicorn workers, which
phase-3 rate limiting needs). The table is created by
`promotions/migrations/0002_create_cache_table.py` (`RunPython` →
`createcachetable`), so a plain `migrate` sets it up — no extra deploy
step. `GUEST_COOKIE_SECURE` (env, default `not DEBUG`) controls the
`Secure` flag on the `pc_guest` cookie.

### Demo seed (DEBUG only, idempotent)

```bash
python manage.py seed_promotions_demo   # active campaign + §6 prize pool + §5 milestones + a demo customer
```

Prints the store-QR token, the `/pc/register?t=…` URL, and the demo
customer's `card_token` for frontend integration. The seeded pool is the
`打卡与抽奖实施方案.md` §6 table (weights sum 500) and the campaign has the
dual-track (`direct_draw_threshold_yen = 3000`) enabled so a single seeded
spend produces a usable draw chance.

## Production configuration

Development defaults intentionally remain non-production. Deployment must
set `DEBUG=False`, a long random `SECRET_KEY`, correct `ALLOWED_HOSTS` and
`CORS_ALLOWED_ORIGINS`, and serve HTTPS. After the proxy/TLS path is verified,
set `SECURE_SSL_REDIRECT=True`, `SESSION_COOKIE_SECURE=True`,
`CSRF_COOKIE_SECURE=True`, and a reviewed `SECURE_HSTS_SECONDS` (plus include
subdomains/preload only when operationally safe). Do not enable HSTS merely to
silence local `check --deploy` warnings. `GUEST_COOKIE_SECURE` (promotions
guest card cookie) already defaults to `not DEBUG`, so production picks it up
without an explicit setting; set it only to override.

## Development seed and tenant provisioning

Development only (idempotent, never run by a migration):

```bash
python manage.py seed_schedule_wage_demo
```

This adds four named demo employees to 心斋桥, August 2026 shifts using all
four cell states, confirmed actual records (including 10:45 arrival and
22:30 departure examples), different rates/transport/bonuses, and wage
results. It creates no login account and changes none of the existing four
account passwords.

Provision a tenant atomically (never exposed through the business API):

```bash
python manage.py provision_organization \
  --code company-b --name-zh B用户店铺集团 --name-ja Bユーザー店舗グループ \
  --admin-account companyb-admin --admin-password 'replace-with-a-secret' \
  --branch-code first --branch-name-zh 第一店 --branch-name-ja 第一店
```

`Organization` uses the globally unique field `code` (not `slug`). The
admin username is globally unique and the password always goes through
Django `set_password`; any failure rolls back the whole transaction.

## Monthly business analysis (`dashboard/analysis.py`)

`GET /api/dashboard/monthly-analysis/?month=YYYY-MM&branch=<id>`

- Admin, no `branch` param → whole-chain aggregate + a branch-comparison
  chart. Admin + `branch` param → that branch only, no comparison chart.
- Branch role → **always** its own branch; a mismatched `branch` param is
  silently corrected, never rejected or honored (there is nothing to leak,
  so a 403 would be more confusing than useful here).
- `staff` role → 403 (blocked by `DenyStaffRole`, no opt-out).
- Revenue/customer figures are read **only** from the live `DailyReport`
  table, never from `DailyReportHistory` (which exists purely to power the
  "modified N times" edit-count signal, not as a data source).
- **"暂定经营差额" (tentative operating gap)** = revenue − purchasing −
  expenses − hourly/temporary wages. This figure, and any ratio derived from
  it, is deliberately **never** labeled 利润/毛利率/人工成本率 (profit /
  gross margin / labor cost ratio) anywhere in the API response or the UI —
  `dashboard/tests.py:MonthlyAnalysisTerminologyTests` asserts the forbidden
  terms never appear in the response body, including inside any clarifying
  parenthetical.
- January correctly resolves "previous month" to December of the prior year
  (`dashboard/analysis.py:previous_month()`).
- Division by zero (e.g. average-spend with 0 customers) returns an explicit
  `0`, never a 500 — verified by `MonthlyAnalysisEmptyDataTests`.
- All money values in the JSON response go through `Decimal(str(value))`
  server-side; `float` is never used for money.
- **Automated insights are deterministic, rule-based, and non-AI** — no LLM
  or external service is called. Each finding states its `rule`, `threshold`,
  and actual `value`. Wording is restricted to neutral phrases
  ("建议确认", "与通常数据差异较大" etc.) — words like 舞弊/经营异常 are
  never used. Current rules, both centrally configured as constants at the
  top of `dashboard/analysis.py`:
  - `insufficient_sample`: fewer than `MIN_SAMPLE_SIZE_FOR_TREND_ANALYSIS = 5`
    days with a report this month → "数据不足，暂不判断" instead of any trend claim.
  - `daily_deviation`: a single day's revenue diverging from the monthly
    average by ≥ `ANOMALY_DEVIATION_THRESHOLD_PCT = 40%`.
  - `heavy_edit`: a day edited ≥ `HISTORY_HEAVY_EDIT_THRESHOLD = 3` times
    (sourced from `DailyReportHistory` counts only, never used for revenue figures).

## Not yet done / known limitations

See `开发进度.md` at the repo root for the current, authoritative status,
including the full real-data-import history and remaining limitations list.
