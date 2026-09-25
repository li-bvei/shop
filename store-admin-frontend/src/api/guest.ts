// Public loyalty-card ("promo card") API. Deliberately NOT built on
// src/api/http.ts — that client is hard-wired to the JWT access token and
// its 401→refresh dance, none of which applies here. A guest is identified
// only by the pc_guest cookie (same-origin production) or, when the dev
// server and API are on different ports, the X-Guest-Token header holding
// the same card_token.

import { API_BASE, ApiError } from './http'

const GUEST_TOKEN_KEY = 'pc_guest_token'

export function getGuestToken(): string {
  try {
    return localStorage.getItem(GUEST_TOKEN_KEY) ?? ''
  } catch {
    return ''
  }
}

export function setGuestToken(token: string) {
  try {
    localStorage.setItem(GUEST_TOKEN_KEY, token)
  } catch {
    /* private mode / storage disabled — the cookie still carries it same-origin */
  }
}

export function clearGuestToken() {
  try {
    localStorage.removeItem(GUEST_TOKEN_KEY)
  } catch {
    /* ignore */
  }
}

async function guestRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getGuestToken()
  const headers: Record<string, string> = {
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers as Record<string, string>),
  }
  if (token) headers['X-Guest-Token'] = token

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    credentials: 'include', // send/receive the pc_guest cookie same-origin
  })

  if (!res.ok) {
    const body: unknown = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body)
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

// ---- types ----------------------------------------------------------------

export interface LedgerEntry {
  id: string
  delta: number
  reason: 'spend' | 'milestone' | 'draw' | 'voucher' | 'expire' | 'adjust'
  balanceAfter: number
  note: string
  createdAt: string
}

export interface CardCampaign {
  name?: string
  pointsPer1000yen?: number
  pointsPerDraw?: number
  pointsPerVoucher?: number
  voucherYenPerUnit?: number
  hasPrizes?: boolean
}

export interface GuestVoucher {
  redemptionCode: string
  label: string
  rewardType: string
  rewardTypeDisplay: string
  source: 'lottery' | 'milestone' | 'points_redeem'
  minSpendYen: number
  requiresManualApproval: boolean
  status: 'active' | 'redeemed' | 'expired' | 'void'
  issuedAt: string
  expiresAt: string
}

export interface MilestoneProgress {
  threshold: number
  label: string
  reached: boolean
  claimed: boolean
}

export interface GuestCard {
  cardToken: string
  name: string
  orgNameZh: string
  orgNameJa: string
  orgLogoUrl: string
  // The branch the customer registered at — the recognisable "which shop"
  // hook the chain name alone doesn't give them.
  branchNameZh: string
  branchNameJa: string
  pointsBalance: number
  lifetimePoints: number
  stampCount: number
  stampTarget: number | null
  drawChances: number
  hasPin: boolean
  campaign: CardCampaign
  ledger: LedgerEntry[]
  vouchers: GuestVoucher[]
  milestones: MilestoneProgress[]
  readonly?: boolean
}

interface LedgerDto {
  id: number
  delta: number
  reason: LedgerEntry['reason']
  balance_after: number
  note: string
  created_at: string
}

interface VoucherDto {
  redemption_code: string
  label: string
  reward_type: string
  reward_type_display: string
  source: GuestVoucher['source']
  min_spend_yen: number
  requires_manual_approval: boolean
  status: GuestVoucher['status']
  issued_at: string
  expires_at: string
}

interface MilestoneDto {
  threshold: number
  label: string
  reached: boolean
  claimed: boolean
}

interface CardDto {
  // Only returned by the token-authenticated card endpoint; the
  // phone+birthday read-only recovery deliberately omits it (see
  // promotions.views._card_payload).
  card_token?: string
  has_pin?: boolean
  name: string
  org_name_zh?: string
  org_name_ja?: string
  org_logo_url?: string
  branch_name_zh?: string
  branch_name_ja?: string
  points_balance: number
  lifetime_points: number
  stamp_count: number
  stamp_target: number | null
  draw_chances: number
  campaign: Record<string, number | string | boolean>
  ledger: LedgerDto[]
  vouchers: VoucherDto[]
  milestones: MilestoneDto[]
  readonly?: boolean
}

function fromVoucherDto(d: VoucherDto): GuestVoucher {
  return {
    redemptionCode: d.redemption_code,
    label: d.label,
    rewardType: d.reward_type,
    rewardTypeDisplay: d.reward_type_display,
    source: d.source,
    minSpendYen: d.min_spend_yen,
    requiresManualApproval: d.requires_manual_approval,
    status: d.status,
    issuedAt: d.issued_at,
    expiresAt: d.expires_at,
  }
}

function fromLedgerDto(dto: LedgerDto): LedgerEntry {
  return {
    id: String(dto.id),
    delta: dto.delta,
    reason: dto.reason,
    balanceAfter: dto.balance_after,
    note: dto.note,
    createdAt: dto.created_at,
  }
}

function fromCardDto(dto: CardDto): GuestCard {
  const c = dto.campaign || {}
  return {
    cardToken: dto.card_token ?? '',
    name: dto.name,
    orgNameZh: dto.org_name_zh ?? '',
    orgNameJa: dto.org_name_ja ?? '',
    orgLogoUrl: dto.org_logo_url ?? '',
    branchNameZh: dto.branch_name_zh ?? '',
    branchNameJa: dto.branch_name_ja ?? '',
    pointsBalance: dto.points_balance,
    lifetimePoints: dto.lifetime_points ?? 0,
    stampCount: dto.stamp_count,
    stampTarget: dto.stamp_target,
    drawChances: dto.draw_chances ?? 0,
    hasPin: dto.has_pin ?? false,
    campaign: {
      name: c.name as string | undefined,
      pointsPer1000yen: c.points_per_1000yen as number | undefined,
      pointsPerDraw: c.points_per_draw as number | undefined,
      pointsPerVoucher: c.points_per_voucher as number | undefined,
      voucherYenPerUnit: c.voucher_yen_per_unit as number | undefined,
      hasPrizes: Boolean(c.has_prizes),
    },
    ledger: (dto.ledger || []).map(fromLedgerDto),
    vouchers: (dto.vouchers || []).map(fromVoucherDto),
    milestones: (dto.milestones || []).map((m) => ({ ...m })),
    readonly: dto.readonly,
  }
}

export interface DrawResult {
  drawId: number
  status: 'won' | 'refund'
  /** The prize row the backend actually drew — the wheel lands on this id,
   * never on a name match. Null only if the prize was deleted afterwards. */
  prizeId: number | null
  prizeName: string
  rewardType: string
  pointsRefunded: number
  voucher: GuestVoucher | null
}

interface DrawResultDto {
  draw_id: number
  status: 'won' | 'refund'
  prize_id: number | null
  prize_name: string
  reward_type: string
  points_refunded: number
  voucher: VoucherDto | null
}

function fromDrawResultDto(d: DrawResultDto): DrawResult {
  return {
    drawId: d.draw_id,
    status: d.status,
    prizeId: d.prize_id ?? null,
    prizeName: d.prize_name,
    rewardType: d.reward_type,
    pointsRefunded: d.points_refunded,
    voucher: d.voucher ? fromVoucherDto(d.voucher) : null,
  }
}

export interface RedeemResult {
  pointsBalance: number
  drawChances?: number
  result?: DrawResult
  voucher?: GuestVoucher
}

/** Spend points: 'draw' runs a lottery draw, 'voucher' issues the fixed ¥N
 * voucher, 'option' buys a ポイント交換所 item (pass its id). */
export async function redeem(
  kind: 'draw' | 'voucher' | 'option',
  requestId: string,
  optionId?: number,
): Promise<RedeemResult> {
  const dto = await guestRequest<{
    points_balance: number
    result?: DrawResultDto
    voucher?: VoucherDto
  }>('/guest/redeem/', {
    method: 'POST',
    body: JSON.stringify({
      type: kind,
      request_id: requestId,
      ...(kind === 'option' ? { option_id: optionId } : {}),
    }),
  })
  return {
    pointsBalance: dto.points_balance,
    result: dto.result ? fromDrawResultDto(dto.result) : undefined,
    voucher: dto.voucher ? fromVoucherDto(dto.voucher) : undefined,
  }
}

export interface RedemptionItem {
  id: number
  name: string
  pointsCost: number
  rewardType: string
  soldOut: boolean
}

/** The campaign's ポイント交換所 — items bought outright with balance points. */
export async function fetchRedemptions(): Promise<RedemptionItem[]> {
  const d = await guestRequest<
    Array<{ id: number; name: string; points_cost: number; reward_type: string; sold_out: boolean }>
  >('/guest/redemptions/')
  return d.map((o) => ({
    id: o.id,
    name: o.name,
    pointsCost: o.points_cost,
    rewardType: o.reward_type,
    soldOut: o.sold_out,
  }))
}

/** Use one free draw chance (from the spend-threshold dual track). */
export async function useDrawChance(requestId: string): Promise<RedeemResult> {
  const dto = await guestRequest<{
    points_balance: number
    draw_chances: number
    result: DrawResultDto
  }>('/guest/draw/', {
    method: 'POST',
    body: JSON.stringify({ request_id: requestId }),
  })
  return {
    pointsBalance: dto.points_balance,
    drawChances: dto.draw_chances,
    result: fromDrawResultDto(dto.result),
  }
}

// ---- calls ---------------------------------------------------------------

export interface RegisterPayload {
  storeToken: string
  phone: string
  name?: string
  birthdayMd?: string
  pin?: string
  consent: boolean
}

export interface RegisterResult {
  cardToken: string
  name: string
  pointsBalance: number
  stampCount: number
}

/** Thrown when the phone already has a card — the backend won't hand back
 * an existing card's credential (see promotions.services.register_customer).
 * The caller should send the customer to the phone+birthday recovery. */
export class AlreadyRegisteredError extends Error {
  constructor() {
    super('already-registered')
    this.name = 'AlreadyRegisteredError'
  }
}

/** The chain's brand identity behind a printed store-QR token — used to
 * show the logo on the register page before the customer types anything. */
export interface StoreContext {
  orgNameZh: string
  orgNameJa: string
  orgLogoUrl: string
  branchNameZh: string
  branchNameJa: string
}

export async function fetchStoreContext(storeToken: string): Promise<StoreContext> {
  const d = await guestRequest<{
    org_name_zh?: string
    org_name_ja?: string
    org_logo_url?: string
    branch_name_zh?: string
    branch_name_ja?: string
  }>(`/guest/store-context/?t=${encodeURIComponent(storeToken)}`)
  return {
    orgNameZh: d.org_name_zh ?? '',
    orgNameJa: d.org_name_ja ?? '',
    orgLogoUrl: d.org_logo_url ?? '',
    branchNameZh: d.branch_name_zh ?? '',
    branchNameJa: d.branch_name_ja ?? '',
  }
}

export interface CheckinResult {
  alreadyCheckedIn: boolean
  stampCount: number
  rewardVoucher: GuestVoucher | null
  milestoneVouchers: GuestVoucher[]
}

/** The rotating proof (`w` window, `c` code) carried by a QR shown on the
 * in-store display — see public/checkin-display.html. Absent when the
 * customer scanned the plain printed QR. */
export interface LiveQrProof {
  w: string
  c: string
}

/** Self-service check-in: the customer scanned a store QR while already
 * holding a card. Pass `live` when the QR came from the in-store display —
 * a campaign with `checkin_requires_live_qr` rejects a check-in without it. */
export async function guestCheckin(
  storeToken: string,
  live?: LiveQrProof | null,
): Promise<CheckinResult> {
  const body: Record<string, string> = { store_token: storeToken }
  if (live?.w && live?.c) {
    body.w = live.w
    body.c = live.c
  }
  const d = await guestRequest<{
    already_checked_in: boolean
    stamp_count: number
    reward_voucher: VoucherDto | null
    milestone_vouchers: VoucherDto[]
  }>('/guest/checkin/', {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return {
    alreadyCheckedIn: d.already_checked_in,
    stampCount: d.stamp_count,
    rewardVoucher: d.reward_voucher ? fromVoucherDto(d.reward_voucher) : null,
    milestoneVouchers: (d.milestone_vouchers || []).map(fromVoucherDto),
  }
}

/** Pull the rotating proof out of a scanned URL or the current route query. */
export function liveQrProofFrom(source: URLSearchParams | Record<string, unknown>): LiveQrProof | null {
  const get = (k: string) =>
    source instanceof URLSearchParams ? source.get(k) : (source[k] as string | undefined)
  const w = get('w')
  const c = get('c')
  return w && c ? { w: String(w), c: String(c) } : null
}

export async function register(payload: RegisterPayload): Promise<RegisterResult> {
  const dto = await guestRequest<{
    existing?: boolean
    card_token?: string
    name?: string
    points_balance?: number
    stamp_count?: number
  }>('/guest/register/', {
    method: 'POST',
    body: JSON.stringify({
      store_token: payload.storeToken,
      phone: payload.phone,
      name: payload.name ?? '',
      birthday_md: payload.birthdayMd ?? '',
      pin: payload.pin ?? '',
      consent: payload.consent,
    }),
  })
  if (dto.existing || !dto.card_token) throw new AlreadyRegisteredError()
  setGuestToken(dto.card_token)
  return {
    cardToken: dto.card_token,
    name: dto.name ?? '',
    pointsBalance: dto.points_balance ?? 0,
    stampCount: dto.stamp_count ?? 0,
  }
}

/** One entry per chain when a phone holds a card at more than one — the
 * caller shows a merchant picker and re-requests with `org`. */
export interface RecoveryOption {
  org: string
  orgNameZh: string
  orgNameJa: string
  logoUrl: string
  branchNameZh: string
  branchNameJa: string
}

interface MultipleDto {
  multiple: true
  options: Array<{
    org: string
    org_name_zh: string
    org_name_ja: string
    logo_url: string
    branch_name_zh?: string
    branch_name_ja?: string
  }>
}

function toOptions(d: MultipleDto): RecoveryOption[] {
  return d.options.map((o) => ({
    org: o.org,
    orgNameZh: o.org_name_zh,
    orgNameJa: o.org_name_ja,
    logoUrl: o.logo_url,
    branchNameZh: o.branch_name_zh ?? '',
    branchNameJa: o.branch_name_ja ?? '',
  }))
}

export async function guestLogin(
  phone: string,
  birthdayMd: string,
  org?: string,
): Promise<{ card: GuestCard } | { options: RecoveryOption[] }> {
  const dto = await guestRequest<CardDto | MultipleDto>('/guest/login/', {
    method: 'POST',
    body: JSON.stringify({ phone, birthday_md: birthdayMd, ...(org ? { org } : {}) }),
  })
  if ('multiple' in dto) return { options: toOptions(dto) }
  return { card: fromCardDto(dto) }
}

/** Full-access recovery on a new device: phone + birthday + 6-digit PIN.
 * On success the card credential is re-issued (cookie + stored token).
 * Returns options instead when the triple matches more than one chain. */
export async function recoverCard(
  phone: string,
  birthdayMd: string,
  pin: string,
  org?: string,
): Promise<{ result: RegisterResult } | { options: RecoveryOption[] }> {
  const dto = await guestRequest<
    | { card_token: string; name?: string; points_balance?: number; stamp_count?: number }
    | MultipleDto
  >('/guest/recover/', {
    method: 'POST',
    body: JSON.stringify({ phone, birthday_md: birthdayMd, pin, ...(org ? { org } : {}) }),
  })
  if ('multiple' in dto) return { options: toOptions(dto) }
  setGuestToken(dto.card_token)
  return {
    result: {
      cardToken: dto.card_token,
      name: dto.name ?? '',
      pointsBalance: dto.points_balance ?? 0,
      stampCount: dto.stamp_count ?? 0,
    },
  }
}

/** Set / change the recovery PIN for the card the browser currently holds. */
export async function setPin(pin: string): Promise<void> {
  await guestRequest('/guest/set-pin/', {
    method: 'POST',
    body: JSON.stringify({ pin }),
  })
}

/** Self-serve redeem: the customer slides to confirm a low-value voucher
 * (drink / dessert / side dish) on their own phone with staff present. */
export async function selfServeRedeem(redemptionCode: string): Promise<void> {
  await guestRequest('/guest/voucher/redeem/', {
    method: 'POST',
    body: JSON.stringify({ redemption_code: redemptionCode }),
  })
}

export const SELF_SERVE_REWARD_TYPES = ['drink', 'dessert', 'side_dish']

export async function fetchCard(): Promise<GuestCard> {
  const dto = await guestRequest<CardDto>('/guest/card/')
  return fromCardDto(dto)
}

export interface CardPulse {
  pointsBalance: number
  lifetimePoints: number
  stampCount: number
  drawChances: number
  voucherCount: number
}

export interface WheelPrize {
  id: number
  name: string
  rewardType: string
  soldOut: boolean
}

/** The prize pool shown on the lottery wheel — names/types only, no odds. */
export async function fetchPrizes(): Promise<WheelPrize[]> {
  const d = await guestRequest<
    Array<{ id: number; name: string; reward_type: string; sold_out: boolean }>
  >('/guest/prizes/')
  return d.map((p) => ({
    id: p.id,
    name: p.name,
    rewardType: p.reward_type,
    soldOut: p.sold_out,
  }))
}

/** Cheap counters-only snapshot the open card page polls for live updates. */
export async function pulseCard(): Promise<CardPulse> {
  const d = await guestRequest<{
    points_balance: number
    lifetime_points: number
    stamp_count: number
    draw_chances: number
    voucher_count: number
  }>('/guest/card/pulse/')
  return {
    pointsBalance: d.points_balance,
    lifetimePoints: d.lifetime_points,
    stampCount: d.stamp_count,
    drawChances: d.draw_chances,
    voucherCount: d.voucher_count,
  }
}
