import { http } from './http'

// ===========================================================================
// Shared
// ===========================================================================

export interface Paginated<T> {
  count: number
  results: T[]
}

interface PaginatedDto<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export type CampaignStatus = 'draft' | 'active' | 'paused' | 'ended'

// ===========================================================================
// Campaign
// ===========================================================================

export interface Campaign {
  id: string
  branchId: string
  branchNameZh: string
  branchNameJa: string
  name: string
  description: string
  status: CampaignStatus
  startsAt: string | null
  endsAt: string | null
  activeWeekdays: string
  activeDateFrom: string | null
  activeDateTo: string | null
  priority: number
  pointsPer1000yen: number
  pointsPerDraw: number
  pointsPerVoucher: number
  voucherYenPerUnit: number
  pointsExpireMonths: number
  directDrawThresholdYen: number | null
  maxDrawsPerVerification: number
  maxDrawsPerCustomerPerDay: number
  stampTarget: number | null
  businessDayCutover: string
  checkinRewardEnabled: boolean
  checkinRewardType: string
  checkinRewardConfig: Record<string, unknown>
  checkinRewardExpiresAfterDays: number
  createdByName: string
  updatedByName: string
  createdAt: string
  updatedAt: string
  storeToken: string
}

interface CampaignDto {
  id: number
  branch: string
  branch_name_zh: string
  branch_name_ja: string
  name: string
  description: string
  status: CampaignStatus
  starts_at: string | null
  ends_at: string | null
  active_weekdays: string
  active_date_from: string | null
  active_date_to: string | null
  priority: number
  points_per_1000yen: number
  points_per_draw: number
  points_per_voucher: number
  voucher_yen_per_unit: number
  points_expire_months: number
  direct_draw_threshold_yen: number | null
  max_draws_per_verification: number
  max_draws_per_customer_per_day: number
  stamp_target: number | null
  business_day_cutover: string
  checkin_reward_enabled: boolean
  checkin_reward_type: string
  checkin_reward_config: Record<string, unknown>
  checkin_reward_expires_after_days: number
  created_by_name: string
  updated_by_name: string
  created_at: string
  updated_at: string
  store_token: string
}

function fromCampaignDto(d: CampaignDto): Campaign {
  return {
    id: String(d.id),
    branchId: d.branch,
    branchNameZh: d.branch_name_zh,
    branchNameJa: d.branch_name_ja,
    name: d.name,
    description: d.description,
    status: d.status,
    startsAt: d.starts_at,
    endsAt: d.ends_at,
    activeWeekdays: d.active_weekdays,
    activeDateFrom: d.active_date_from,
    activeDateTo: d.active_date_to,
    priority: d.priority,
    pointsPer1000yen: d.points_per_1000yen,
    pointsPerDraw: d.points_per_draw,
    pointsPerVoucher: d.points_per_voucher,
    voucherYenPerUnit: d.voucher_yen_per_unit,
    pointsExpireMonths: d.points_expire_months,
    directDrawThresholdYen: d.direct_draw_threshold_yen,
    maxDrawsPerVerification: d.max_draws_per_verification,
    maxDrawsPerCustomerPerDay: d.max_draws_per_customer_per_day,
    stampTarget: d.stamp_target,
    businessDayCutover: d.business_day_cutover,
    checkinRewardEnabled: d.checkin_reward_enabled,
    checkinRewardType: d.checkin_reward_type,
    checkinRewardConfig: d.checkin_reward_config ?? {},
    checkinRewardExpiresAfterDays: d.checkin_reward_expires_after_days,
    createdByName: d.created_by_name,
    updatedByName: d.updated_by_name,
    createdAt: d.created_at,
    updatedAt: d.updated_at,
    storeToken: d.store_token,
  }
}

export interface CampaignPayload {
  branchId?: string
  name: string
  description?: string
  status: CampaignStatus
  startsAt: string | null
  endsAt: string | null
  activeWeekdays: string
  activeDateFrom: string | null
  activeDateTo: string | null
  priority: number
  pointsPer1000yen: number
  pointsPerDraw: number
  pointsPerVoucher: number
  voucherYenPerUnit: number
  pointsExpireMonths: number
  directDrawThresholdYen: number | null
  maxDrawsPerVerification: number
  maxDrawsPerCustomerPerDay: number
  stampTarget: number | null
  businessDayCutover: string
  checkinRewardEnabled: boolean
  checkinRewardType: string
  checkinRewardConfig: Record<string, unknown>
  checkinRewardExpiresAfterDays: number
}

function toCampaignDto(p: CampaignPayload): Record<string, unknown> {
  return {
    ...(p.branchId ? { branch: p.branchId } : {}),
    name: p.name,
    description: p.description ?? '',
    status: p.status,
    starts_at: p.startsAt,
    ends_at: p.endsAt,
    active_weekdays: p.activeWeekdays,
    active_date_from: p.activeDateFrom,
    active_date_to: p.activeDateTo,
    priority: p.priority,
    points_per_1000yen: p.pointsPer1000yen,
    points_per_draw: p.pointsPerDraw,
    points_per_voucher: p.pointsPerVoucher,
    voucher_yen_per_unit: p.voucherYenPerUnit,
    points_expire_months: p.pointsExpireMonths,
    direct_draw_threshold_yen: p.directDrawThresholdYen,
    max_draws_per_verification: p.maxDrawsPerVerification,
    max_draws_per_customer_per_day: p.maxDrawsPerCustomerPerDay,
    stamp_target: p.stampTarget,
    business_day_cutover: p.businessDayCutover,
    checkin_reward_enabled: p.checkinRewardEnabled,
    checkin_reward_type: p.checkinRewardType,
    checkin_reward_config: p.checkinRewardConfig,
    checkin_reward_expires_after_days: p.checkinRewardExpiresAfterDays,
  }
}

export async function fetchCampaigns(branchId?: string): Promise<Campaign[]> {
  const q = branchId ? `?branch=${encodeURIComponent(branchId)}` : ''
  const rows = await http.get<CampaignDto[]>(`/promotions/campaigns/${q}`)
  return rows.map(fromCampaignDto)
}

export async function createCampaign(payload: CampaignPayload): Promise<Campaign> {
  return fromCampaignDto(await http.post<CampaignDto>('/promotions/campaigns/', toCampaignDto(payload)))
}

export async function updateCampaign(id: string, payload: CampaignPayload): Promise<Campaign> {
  return fromCampaignDto(await http.patch<CampaignDto>(`/promotions/campaigns/${id}/`, toCampaignDto(payload)))
}

export async function deleteCampaign(id: string): Promise<void> {
  await http.delete(`/promotions/campaigns/${id}/`)
}

// ===========================================================================
// Customer
// ===========================================================================

export interface Customer {
  id: string
  phone: string
  name: string
  birthdayMd: string
  pointsBalance: number
  stampCount: number
  status: 'active' | 'blocked'
  riskLevel: string
  firstSeenAt: string
  lastSeenAt: string | null
  lastActivityAt: string | null
  privacyConsentedAt: string | null
}

export interface LedgerRow {
  id: string
  delta: number
  reason: string
  sourceRef: string
  balanceAfter: number
  note: string
  operatorName: string
  createdAt: string
}

export interface CustomerDetail extends Customer {
  recentLedger: LedgerRow[]
}

interface CustomerDto {
  id: number
  phone: string
  name: string
  birthday_md: string
  points_balance: number
  stamp_count: number
  status: 'active' | 'blocked'
  risk_level: string
  first_seen_at: string
  last_seen_at: string | null
  last_activity_at: string | null
  privacy_consented_at: string | null
  recent_ledger?: LedgerRowDto[]
}

interface LedgerRowDto {
  id: number
  delta: number
  reason: string
  source_ref: string
  balance_after: number
  note: string
  operator_name: string
  created_at: string
}

function fromLedgerRowDto(d: LedgerRowDto): LedgerRow {
  return {
    id: String(d.id),
    delta: d.delta,
    reason: d.reason,
    sourceRef: d.source_ref,
    balanceAfter: d.balance_after,
    note: d.note,
    operatorName: d.operator_name,
    createdAt: d.created_at,
  }
}

function fromCustomerDto(d: CustomerDto): Customer {
  return {
    id: String(d.id),
    phone: d.phone,
    name: d.name,
    birthdayMd: d.birthday_md,
    pointsBalance: d.points_balance,
    stampCount: d.stamp_count,
    status: d.status,
    riskLevel: d.risk_level,
    firstSeenAt: d.first_seen_at,
    lastSeenAt: d.last_seen_at,
    lastActivityAt: d.last_activity_at,
    privacyConsentedAt: d.privacy_consented_at,
  }
}

export interface CustomerListParams {
  search?: string
  status?: string
  page?: number
  pageSize?: number
}

export async function fetchCustomers(params: CustomerListParams = {}): Promise<Paginated<Customer>> {
  const q = new URLSearchParams()
  if (params.search) q.set('search', params.search)
  if (params.status) q.set('status', params.status)
  q.set('page', String(params.page ?? 1))
  q.set('page_size', String(params.pageSize ?? 50))
  const page = await http.get<PaginatedDto<CustomerDto>>(`/promotions/customers/?${q.toString()}`)
  return { count: page.count, results: page.results.map(fromCustomerDto) }
}

export async function fetchCustomer(id: string): Promise<CustomerDetail> {
  const d = await http.get<CustomerDto>(`/promotions/customers/${id}/`)
  return { ...fromCustomerDto(d), recentLedger: (d.recent_ledger ?? []).map(fromLedgerRowDto) }
}

export async function adjustCustomerPoints(
  id: string,
  delta: number,
  note: string,
): Promise<{ pointsBalance: number }> {
  const res = await http.post<{ points_balance: number }>(
    `/promotions/customers/${id}/points-adjust/`,
    { delta, note },
  )
  return { pointsBalance: res.points_balance }
}

export async function deleteCustomer(id: string): Promise<void> {
  await http.delete(`/promotions/customers/${id}/`)
}

// ===========================================================================
// Spend verification (staff + records)
// ===========================================================================

export interface CustomerLookup {
  id: string
  name: string
  phoneMasked: string
  pointsBalance: number
  stampCount: number
  stampTarget: number | null
  vouchers: unknown[]
}

export async function lookupCustomer(query: { cardToken?: string; phone?: string }): Promise<CustomerLookup> {
  const res = await http.post<{
    id: number
    name: string
    phone_masked: string
    points_balance: number
    stamp_count: number
    stamp_target: number | null
    vouchers: unknown[]
  }>('/promotions/customers/lookup/', {
    ...(query.cardToken ? { card_token: query.cardToken } : {}),
    ...(query.phone ? { phone: query.phone } : {}),
  })
  return {
    id: String(res.id),
    name: res.name,
    phoneMasked: res.phone_masked,
    pointsBalance: res.points_balance,
    stampCount: res.stamp_count,
    stampTarget: res.stamp_target,
    vouchers: res.vouchers,
  }
}

export interface SpendResult {
  id: string
  checkInId: string | null
  pointsGranted: number
  pointsBalance: number
  stampCount: number
  riskLevel: string
}

export async function confirmSpend(payload: {
  cardToken?: string
  phone?: string
  amountYen: number
  tableNumber?: string
  branchId?: string
  campaignId?: string
  requestId?: string
}): Promise<SpendResult> {
  const res = await http.post<{
    id: number
    check_in_id: number | null
    points_granted: number
    points_balance: number
    stamp_count: number
    risk_level: string
  }>('/promotions/spend-verifications/', {
    ...(payload.cardToken ? { card_token: payload.cardToken } : {}),
    ...(payload.phone ? { phone: payload.phone } : {}),
    ...(payload.branchId ? { branch: payload.branchId } : {}),
    ...(payload.campaignId ? { campaign: payload.campaignId } : {}),
    ...(payload.requestId ? { request_id: payload.requestId } : {}),
    amount_yen: payload.amountYen,
    table_number: payload.tableNumber ?? '',
  })
  return {
    id: String(res.id),
    checkInId: res.check_in_id !== null ? String(res.check_in_id) : null,
    pointsGranted: res.points_granted,
    pointsBalance: res.points_balance,
    stampCount: res.stamp_count,
    riskLevel: res.risk_level,
  }
}

export interface CheckinResult {
  alreadyCheckedIn: boolean
  rewardVoucher: { label: string; rewardType: string; redemptionCode: string } | null
}

/** Record a "customer showed their QR" visit with no purchase, and issue
 * the daily check-in reward voucher if the campaign has one. */
export async function recordCheckin(payload: {
  cardToken?: string
  phone?: string
  branchId?: string
  campaignId?: string
}): Promise<CheckinResult> {
  const res = await http.post<{
    already_checked_in: boolean
    reward_voucher: { label: string; reward_type: string; redemption_code: string } | null
  }>('/promotions/spend-verifications/checkin/', {
    ...(payload.cardToken ? { card_token: payload.cardToken } : {}),
    ...(payload.phone ? { phone: payload.phone } : {}),
    ...(payload.branchId ? { branch: payload.branchId } : {}),
    ...(payload.campaignId ? { campaign: payload.campaignId } : {}),
  })
  return {
    alreadyCheckedIn: res.already_checked_in,
    rewardVoucher: res.reward_voucher
      ? {
          label: res.reward_voucher.label,
          rewardType: res.reward_voucher.reward_type,
          redemptionCode: res.reward_voucher.redemption_code,
        }
      : null,
  }
}

export interface SpendVerification {
  id: string
  customerName: string
  customerPhone: string
  customerDeleted: boolean
  amountYen: number
  pointsGranted: number
  consumedAt: string
  verifiedByName: string
  status: 'accepted' | 'voided'
  voidReason: string
  createdAt: string
}

interface SpendVerificationDto {
  id: number
  customer_name: string
  customer_phone: string
  customer_deleted: boolean
  amount_yen: number
  points_granted: number
  consumed_at: string
  verified_by_name: string
  status: 'accepted' | 'voided'
  void_reason: string
  created_at: string
}

function fromSpendVerificationDto(d: SpendVerificationDto): SpendVerification {
  return {
    id: String(d.id),
    customerName: d.customer_name,
    customerPhone: d.customer_phone,
    customerDeleted: d.customer_deleted,
    amountYen: d.amount_yen,
    pointsGranted: d.points_granted,
    consumedAt: d.consumed_at,
    verifiedByName: d.verified_by_name,
    status: d.status,
    voidReason: d.void_reason,
    createdAt: d.created_at,
  }
}

export async function fetchMyVerifications(): Promise<SpendVerification[]> {
  const rows = await http.get<SpendVerificationDto[]>('/promotions/spend-verifications/mine/')
  return rows.map(fromSpendVerificationDto)
}

export interface VerificationListParams {
  campaignId: string
  status?: string
  page?: number
  pageSize?: number
}

export async function fetchCampaignVerifications(
  params: VerificationListParams,
): Promise<Paginated<SpendVerification>> {
  const q = new URLSearchParams()
  if (params.status) q.set('status', params.status)
  q.set('page', String(params.page ?? 1))
  q.set('page_size', String(params.pageSize ?? 50))
  const page = await http.get<PaginatedDto<SpendVerificationDto>>(
    `/promotions/campaigns/${params.campaignId}/verifications/?${q.toString()}`,
  )
  return { count: page.count, results: page.results.map(fromSpendVerificationDto) }
}

export async function voidVerification(id: string, reason: string): Promise<void> {
  await http.post(`/promotions/spend-verifications/${id}/void/`, { reason })
}

export interface CheckInRow {
  id: string
  customerName: string
  customerPhone: string
  localDate: string
  checkedInAt: string
  result: string
}

interface CheckInRowDto {
  id: number
  customer_name: string
  customer_phone: string
  local_date: string
  checked_in_at: string
  result: string
}

export async function fetchCampaignCheckins(
  campaignId: string,
  params: { localDate?: string; page?: number; pageSize?: number } = {},
): Promise<Paginated<CheckInRow>> {
  const q = new URLSearchParams()
  if (params.localDate) q.set('local_date', params.localDate)
  q.set('page', String(params.page ?? 1))
  q.set('page_size', String(params.pageSize ?? 50))
  const page = await http.get<PaginatedDto<CheckInRowDto>>(
    `/promotions/campaigns/${campaignId}/checkins/?${q.toString()}`,
  )
  return {
    count: page.count,
    results: page.results.map((d) => ({
      id: String(d.id),
      customerName: d.customer_name,
      customerPhone: d.customer_phone,
      localDate: d.local_date,
      checkedInAt: d.checked_in_at,
      result: d.result,
    })),
  }
}

// ===========================================================================
// Prize pool (phase 2)
// ===========================================================================

export type RewardType =
  | 'cash_voucher'
  | 'drink'
  | 'dessert'
  | 'side_dish'
  | 'chef_special'
  | 'points_refund'

export interface Prize {
  id: string
  campaignId: string
  name: string
  description: string
  displayOrder: number
  weight: number
  probability: number
  rewardType: RewardType
  rewardConfig: Record<string, unknown>
  totalStock: number | null
  remainingStock: number | null
  dailyStock: number | null
  voucherExpiresAfterDays: number
  voucherMinSpendYen: number
  requiresManualApproval: boolean
  active: boolean
}

interface PrizeDto {
  id: number
  campaign: number
  name: string
  description: string
  display_order: number
  weight: number
  probability: number
  reward_type: RewardType
  reward_config: Record<string, unknown>
  total_stock: number | null
  remaining_stock: number | null
  daily_stock: number | null
  voucher_expires_after_days: number
  voucher_min_spend_yen: number
  requires_manual_approval: boolean
  active: boolean
}

function fromPrizeDto(d: PrizeDto): Prize {
  return {
    id: String(d.id),
    campaignId: String(d.campaign),
    name: d.name,
    description: d.description,
    displayOrder: d.display_order,
    weight: d.weight,
    probability: d.probability,
    rewardType: d.reward_type,
    rewardConfig: d.reward_config ?? {},
    totalStock: d.total_stock,
    remainingStock: d.remaining_stock,
    dailyStock: d.daily_stock,
    voucherExpiresAfterDays: d.voucher_expires_after_days,
    voucherMinSpendYen: d.voucher_min_spend_yen,
    requiresManualApproval: d.requires_manual_approval,
    active: d.active,
  }
}

export interface PrizePayload {
  campaignId: string
  name: string
  description?: string
  displayOrder?: number
  weight: number
  rewardType: RewardType
  rewardConfig: Record<string, unknown>
  totalStock: number | null
  dailyStock: number | null
  voucherExpiresAfterDays: number
  voucherMinSpendYen: number
  requiresManualApproval: boolean
  active: boolean
}

function toPrizeDto(p: PrizePayload): Record<string, unknown> {
  return {
    campaign: Number(p.campaignId),
    name: p.name,
    description: p.description ?? '',
    display_order: p.displayOrder ?? 0,
    weight: p.weight,
    reward_type: p.rewardType,
    reward_config: p.rewardConfig,
    total_stock: p.totalStock,
    daily_stock: p.dailyStock,
    voucher_expires_after_days: p.voucherExpiresAfterDays,
    voucher_min_spend_yen: p.voucherMinSpendYen,
    requires_manual_approval: p.requiresManualApproval,
    active: p.active,
  }
}

export async function fetchPrizes(campaignId: string): Promise<Prize[]> {
  const rows = await http.get<PrizeDto[]>(`/promotions/prizes/?campaign=${encodeURIComponent(campaignId)}`)
  return rows.map(fromPrizeDto)
}

export async function createPrize(payload: PrizePayload): Promise<Prize> {
  return fromPrizeDto(await http.post<PrizeDto>('/promotions/prizes/', toPrizeDto(payload)))
}

export async function updatePrize(id: string, payload: PrizePayload): Promise<Prize> {
  return fromPrizeDto(await http.patch<PrizeDto>(`/promotions/prizes/${id}/`, toPrizeDto(payload)))
}

export async function deletePrize(id: string): Promise<void> {
  await http.delete(`/promotions/prizes/${id}/`)
}

// ===========================================================================
// Milestones (phase 2.5)
// ===========================================================================

export interface Milestone {
  id: string
  campaignId: string
  pointsThreshold: number
  rewardType: RewardType
  rewardConfig: Record<string, unknown>
  voucherExpiresAfterDays: number
  displayLabel: string
  active: boolean
}

interface MilestoneDto {
  id: number
  campaign: number
  points_threshold: number
  reward_type: RewardType
  reward_config: Record<string, unknown>
  voucher_expires_after_days: number
  display_label: string
  active: boolean
}

function fromMilestoneDto(d: MilestoneDto): Milestone {
  return {
    id: String(d.id),
    campaignId: String(d.campaign),
    pointsThreshold: d.points_threshold,
    rewardType: d.reward_type,
    rewardConfig: d.reward_config ?? {},
    voucherExpiresAfterDays: d.voucher_expires_after_days,
    displayLabel: d.display_label,
    active: d.active,
  }
}

export interface MilestonePayload {
  campaignId: string
  pointsThreshold: number
  rewardType: RewardType
  rewardConfig: Record<string, unknown>
  voucherExpiresAfterDays: number
  displayLabel: string
  active: boolean
}

export async function fetchMilestones(campaignId: string): Promise<Milestone[]> {
  const rows = await http.get<MilestoneDto[]>(
    `/promotions/milestones/?campaign=${encodeURIComponent(campaignId)}`,
  )
  return rows.map(fromMilestoneDto)
}

export async function createMilestone(p: MilestonePayload): Promise<Milestone> {
  return fromMilestoneDto(
    await http.post<MilestoneDto>('/promotions/milestones/', {
      campaign: Number(p.campaignId),
      points_threshold: p.pointsThreshold,
      reward_type: p.rewardType,
      reward_config: p.rewardConfig,
      voucher_expires_after_days: p.voucherExpiresAfterDays,
      display_label: p.displayLabel,
      active: p.active,
    }),
  )
}

export async function updateMilestone(id: string, p: MilestonePayload): Promise<Milestone> {
  return fromMilestoneDto(
    await http.patch<MilestoneDto>(`/promotions/milestones/${id}/`, {
      points_threshold: p.pointsThreshold,
      reward_type: p.rewardType,
      reward_config: p.rewardConfig,
      voucher_expires_after_days: p.voucherExpiresAfterDays,
      display_label: p.displayLabel,
      active: p.active,
    }),
  )
}

export async function deleteMilestone(id: string): Promise<void> {
  await http.delete(`/promotions/milestones/${id}/`)
}

// ===========================================================================
// Lottery draw & voucher records + staff redemption
// ===========================================================================

export interface LotteryDrawRow {
  id: string
  customerName: string
  customerPhone: string
  customerDeleted: boolean
  source: 'points' | 'direct'
  pointsSpent: number
  prizeName: string
  rewardType: string
  status: 'won' | 'refund'
  pointsRefunded: number
  drawnAt: string
}

interface LotteryDrawDto {
  id: number
  customer_name: string
  customer_phone: string
  customer_deleted: boolean
  source: 'points' | 'direct'
  points_spent: number
  prize_name_snapshot: string
  reward_type_snapshot: string
  status: 'won' | 'refund'
  points_refunded: number
  drawn_at: string
}

function fromDrawDto(d: LotteryDrawDto): LotteryDrawRow {
  return {
    id: String(d.id),
    customerName: d.customer_name,
    customerPhone: d.customer_phone,
    customerDeleted: d.customer_deleted,
    source: d.source,
    pointsSpent: d.points_spent,
    prizeName: d.prize_name_snapshot,
    rewardType: d.reward_type_snapshot,
    status: d.status,
    pointsRefunded: d.points_refunded,
    drawnAt: d.drawn_at,
  }
}

export interface VoucherRow {
  id: string
  redemptionCode: string
  label: string
  customerName: string
  customerPhone: string
  customerDeleted: boolean
  source: 'lottery' | 'milestone' | 'points_redeem'
  rewardType: string
  minSpendYen: number
  requiresManualApproval: boolean
  status: 'active' | 'redeemed' | 'expired' | 'void'
  issuedAt: string
  expiresAt: string
  redeemedAt: string | null
  redeemedSpendYen: number | null
  redeemable?: boolean
  expired?: boolean
}

interface VoucherRowDto {
  id: number
  redemption_code: string
  label: string
  customer_name: string
  customer_phone: string
  customer_deleted: boolean
  source: VoucherRow['source']
  reward_type: string
  min_spend_yen: number
  requires_manual_approval: boolean
  status: VoucherRow['status']
  issued_at: string
  expires_at: string
  redeemed_at: string | null
  redeemed_spend_yen: number | null
  redeemable?: boolean
  expired?: boolean
}

function fromVoucherRowDto(d: VoucherRowDto): VoucherRow {
  return {
    id: String(d.id),
    redemptionCode: d.redemption_code,
    label: d.label,
    customerName: d.customer_name,
    customerPhone: d.customer_phone,
    customerDeleted: d.customer_deleted,
    source: d.source,
    rewardType: d.reward_type,
    minSpendYen: d.min_spend_yen,
    requiresManualApproval: d.requires_manual_approval,
    status: d.status,
    issuedAt: d.issued_at,
    expiresAt: d.expires_at,
    redeemedAt: d.redeemed_at,
    redeemedSpendYen: d.redeemed_spend_yen,
    redeemable: d.redeemable,
    expired: d.expired,
  }
}

export async function fetchCampaignDraws(
  campaignId: string,
  params: { status?: string; page?: number; pageSize?: number } = {},
): Promise<Paginated<LotteryDrawRow>> {
  const q = new URLSearchParams()
  if (params.status) q.set('status', params.status)
  q.set('page', String(params.page ?? 1))
  q.set('page_size', String(params.pageSize ?? 50))
  const page = await http.get<PaginatedDto<LotteryDrawDto>>(
    `/promotions/campaigns/${campaignId}/draws/?${q.toString()}`,
  )
  return { count: page.count, results: page.results.map(fromDrawDto) }
}

export async function fetchCampaignVouchers(
  campaignId: string,
  params: { status?: string; page?: number; pageSize?: number } = {},
): Promise<Paginated<VoucherRow>> {
  const q = new URLSearchParams()
  if (params.status) q.set('status', params.status)
  q.set('page', String(params.page ?? 1))
  q.set('page_size', String(params.pageSize ?? 50))
  const page = await http.get<PaginatedDto<VoucherRowDto>>(
    `/promotions/campaigns/${campaignId}/vouchers/?${q.toString()}`,
  )
  return { count: page.count, results: page.results.map(fromVoucherRowDto) }
}

export async function verifyVouchers(query: {
  redemptionCode?: string
  cardToken?: string
  phone?: string
  name?: string
  phoneTail?: string
}): Promise<VoucherRow[]> {
  const rows = await http.post<VoucherRowDto[]>('/promotions/vouchers/verify/', {
    ...(query.redemptionCode ? { redemption_code: query.redemptionCode } : {}),
    ...(query.cardToken ? { card_token: query.cardToken } : {}),
    ...(query.phone ? { phone: query.phone } : {}),
    ...(query.name ? { name: query.name } : {}),
    ...(query.phoneTail ? { phone_tail: query.phoneTail } : {}),
  })
  return rows.map(fromVoucherRowDto)
}

export async function redeemVoucher(payload: {
  redemptionCode: string
  spendAmountYen?: number
}): Promise<VoucherRow> {
  return fromVoucherRowDto(
    await http.post<VoucherRowDto>('/promotions/vouchers/redeem/', {
      redemption_code: payload.redemptionCode,
      ...(payload.spendAmountYen != null ? { spend_amount_yen: payload.spendAmountYen } : {}),
    }),
  )
}

// ===========================================================================
// Phase 3 — risk events, staff permissions, reports
// ===========================================================================

export type RiskStatus = 'open' | 'reviewed' | 'confirmed' | 'dismissed'

export interface RiskEvent {
  id: string
  eventType: string
  eventTypeDisplay: string
  severity: 'low' | 'medium' | 'high'
  status: RiskStatus
  evidence: Record<string, unknown>
  sourceRef: string
  branchId: string | null
  branchNameZh: string
  customerName: string
  customerPhone: string
  staffName: string
  reviewedByName: string
  reviewedAt: string | null
  reviewNote: string
  createdAt: string
}

interface RiskEventDto {
  id: number
  event_type: string
  event_type_display: string
  severity: RiskEvent['severity']
  status: RiskStatus
  evidence: Record<string, unknown>
  source_ref: string
  branch: string | null
  branch_name_zh: string
  customer_name: string
  customer_phone: string
  staff_name: string
  reviewed_by_name: string
  reviewed_at: string | null
  review_note: string
  created_at: string
}

function fromRiskEventDto(d: RiskEventDto): RiskEvent {
  return {
    id: String(d.id),
    eventType: d.event_type,
    eventTypeDisplay: d.event_type_display,
    severity: d.severity,
    status: d.status,
    evidence: d.evidence ?? {},
    sourceRef: d.source_ref,
    branchId: d.branch,
    branchNameZh: d.branch_name_zh,
    customerName: d.customer_name,
    customerPhone: d.customer_phone,
    staffName: d.staff_name,
    reviewedByName: d.reviewed_by_name,
    reviewedAt: d.reviewed_at,
    reviewNote: d.review_note,
    createdAt: d.created_at,
  }
}

export async function fetchRiskEvents(
  params: { status?: string; eventType?: string; severity?: string; page?: number; pageSize?: number } = {},
): Promise<Paginated<RiskEvent>> {
  const q = new URLSearchParams()
  if (params.status) q.set('status', params.status)
  if (params.eventType) q.set('event_type', params.eventType)
  if (params.severity) q.set('severity', params.severity)
  q.set('page', String(params.page ?? 1))
  q.set('page_size', String(params.pageSize ?? 50))
  const page = await http.get<PaginatedDto<RiskEventDto>>(`/promotions/risk-events/?${q.toString()}`)
  return { count: page.count, results: page.results.map(fromRiskEventDto) }
}

export async function reviewRiskEvent(
  id: string,
  status: 'reviewed' | 'confirmed' | 'dismissed',
  note?: string,
): Promise<RiskEvent> {
  return fromRiskEventDto(
    await http.post<RiskEventDto>(`/promotions/risk-events/${id}/review/`, { status, note: note ?? '' }),
  )
}

export interface StaffPermission {
  id: string | null
  userId: string
  account: string
  displayName: string
  branchId: string | null
  canVerifySpend: boolean
  canRedeemVoucher: boolean
  note: string
}

interface StaffPermissionDto {
  id: number | null
  user: number
  account: string
  display_name: string
  branch_id: string | null
  can_verify_spend: boolean
  can_redeem_voucher: boolean
  note: string
}

function fromStaffPermissionDto(d: StaffPermissionDto): StaffPermission {
  return {
    id: d.id != null ? String(d.id) : null,
    userId: String(d.user),
    account: d.account,
    displayName: d.display_name,
    branchId: d.branch_id,
    canVerifySpend: d.can_verify_spend,
    canRedeemVoucher: d.can_redeem_voucher,
    note: d.note,
  }
}

export async function fetchStaffPermissions(): Promise<StaffPermission[]> {
  const rows = await http.get<StaffPermissionDto[]>('/promotions/staff-permissions/')
  return rows.map(fromStaffPermissionDto)
}

export async function updateStaffPermission(
  userId: string,
  patch: { canVerifySpend?: boolean; canRedeemVoucher?: boolean; note?: string },
): Promise<StaffPermission> {
  const body: Record<string, unknown> = {}
  if (patch.canVerifySpend !== undefined) body.can_verify_spend = patch.canVerifySpend
  if (patch.canRedeemVoucher !== undefined) body.can_redeem_voucher = patch.canRedeemVoucher
  if (patch.note !== undefined) body.note = patch.note
  return fromStaffPermissionDto(await http.patch<StaffPermissionDto>(`/promotions/staff-permissions/${userId}/`, body))
}

export interface CampaignReport {
  month: string
  spend: { verifications: number; totalAmount: number; voided: number }
  staffStats: { staff: string; count: number; totalAmount: number; avgAmount: number; voids: number }[]
  points: {
    earned: number
    spentOnDraws: number
    spentOnVouchers: number
    refunded: number
    expired: number
    adjusted: number
  }
  draws: { total: number; won: number; refund: number; byPrize: { prize: string; count: number }[] }
  vouchers: {
    issued: number
    issuedBySource: { source: string; count: number }[]
    redeemed: number
    cashFaceRedeemedYen: number
  }
  risk: { total: number; open: number; byType: { eventType: string; count: number }[] }
}

export async function fetchCampaignReport(campaignId: string, month: string): Promise<CampaignReport> {
  const d = await http.get<{
    month: string
    spend: { verifications: number; total_amount: number; voided: number }
    staff_stats: { staff: string; count: number; total_amount: number; avg_amount: number; voids: number }[]
    points: {
      earned: number
      spent_on_draws: number
      spent_on_vouchers: number
      refunded: number
      expired: number
      adjusted: number
    }
    draws: { total: number; won: number; refund: number; by_prize: { prize: string; count: number }[] }
    vouchers: {
      issued: number
      issued_by_source: { source: string; count: number }[]
      redeemed: number
      cash_face_redeemed_yen: number
    }
    risk: { total: number; open: number; by_type: { event_type: string; count: number }[] }
  }>(`/promotions/campaigns/${campaignId}/report/?month=${encodeURIComponent(month)}`)
  return {
    month: d.month,
    spend: { verifications: d.spend.verifications, totalAmount: d.spend.total_amount, voided: d.spend.voided },
    staffStats: d.staff_stats.map((s) => ({
      staff: s.staff, count: s.count, totalAmount: s.total_amount, avgAmount: s.avg_amount, voids: s.voids,
    })),
    points: {
      earned: d.points.earned,
      spentOnDraws: d.points.spent_on_draws,
      spentOnVouchers: d.points.spent_on_vouchers,
      refunded: d.points.refunded,
      expired: d.points.expired,
      adjusted: d.points.adjusted,
    },
    draws: {
      total: d.draws.total, won: d.draws.won, refund: d.draws.refund,
      byPrize: d.draws.by_prize.map((p) => ({ prize: p.prize, count: p.count })),
    },
    vouchers: {
      issued: d.vouchers.issued,
      issuedBySource: d.vouchers.issued_by_source.map((s) => ({ source: s.source, count: s.count })),
      redeemed: d.vouchers.redeemed,
      cashFaceRedeemedYen: d.vouchers.cash_face_redeemed_yen,
    },
    risk: {
      total: d.risk.total, open: d.risk.open,
      byType: d.risk.by_type.map((r) => ({ eventType: r.event_type, count: r.count })),
    },
  }
}
