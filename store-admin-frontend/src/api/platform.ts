import { http } from './http'

// Platform (super-admin) API — cross-tenant oversight, entitlements, accounts.

export interface PlatformOverviewOrg {
  id: number
  code: string
  name_zh: string
  name_ja: string
  active: boolean
  branch_count: number
  accounts: { total: number; active: number; inactive: number }
  features_enabled: number
  features_total: number
  disabled_features: string[]
  month_revenue: string
  month_revenue_delta_pct: number | null
  month_customers: number
  month_purchasing: string
  loyalty_customers: number
  active_campaigns: number
}

export interface PlatformOverview {
  month: string
  totals: {
    organizations: number
    branches: number
    accounts: number
    active_accounts: number
    month_revenue: string
    month_revenue_delta_pct: number | null
    month_customers: number
    month_purchasing: string
    loyalty_customers: number
  }
  organizations: PlatformOverviewOrg[]
}

export async function fetchPlatformOverview(): Promise<PlatformOverview> {
  return http.get<PlatformOverview>('/platform/overview/')
}

export interface OrgFeatureState {
  feature: string
  enabled: boolean
  name_zh: string
  name_ja: string
}

export interface PlatformOrg {
  id: number
  code: string
  nameZh: string
  nameJa: string
  active: boolean
  branchCount: number
  features: OrgFeatureState[]
}

interface PlatformOrgDto {
  id: number
  code: string
  name_zh: string
  name_ja: string
  active: boolean
  branch_count: number
  features: OrgFeatureState[]
}

function fromDto(d: PlatformOrgDto): PlatformOrg {
  return {
    id: d.id,
    code: d.code,
    nameZh: d.name_zh,
    nameJa: d.name_ja,
    active: d.active,
    branchCount: d.branch_count,
    features: d.features,
  }
}

export async function fetchPlatformOrganizations(): Promise<PlatformOrg[]> {
  const rows = await http.get<PlatformOrgDto[]>('/platform/organizations/')
  return rows.map(fromDto)
}

export async function setOrganizationFeature(
  orgId: number,
  feature: string,
  enabled: boolean,
): Promise<PlatformOrg> {
  return fromDto(
    await http.patch<PlatformOrgDto>(`/platform/organizations/${orgId}/features/`, { [feature]: enabled }),
  )
}

/** Onboards a brand-new tenant — organization, and optionally its first
 * branch and first admin account, all in one call (the UI form for what
 * `manage.py provision_organization` has always done from the shell). The
 * organization and branch codes are generated server-side. */
export async function createPlatformOrganization(payload: {
  nameZh: string
  nameJa: string
  branchNameZh?: string
  branchNameJa?: string
  adminAccount?: string
  adminPassword?: string
}): Promise<PlatformOrg> {
  return fromDto(await http.post<PlatformOrgDto>('/platform/organizations/', {
    name_zh: payload.nameZh, name_ja: payload.nameJa,
    branch_name_zh: payload.branchNameZh, branch_name_ja: payload.branchNameJa,
    admin_account: payload.adminAccount, admin_password: payload.adminPassword,
  }))
}

/** Rename a tenant, or suspend/reactivate it (`active`) — a suspended
 * tenant's accounts are rejected at login and on every request after. */
export async function updatePlatformOrganization(
  orgId: number,
  payload: { nameZh?: string; nameJa?: string; active?: boolean },
): Promise<PlatformOrg> {
  return fromDto(await http.patch<PlatformOrgDto>(`/platform/organizations/${orgId}/`, {
    ...(payload.nameZh !== undefined ? { name_zh: payload.nameZh } : {}),
    ...(payload.nameJa !== undefined ? { name_ja: payload.nameJa } : {}),
    ...(payload.active !== undefined ? { active: payload.active } : {}),
  }))
}

export interface PlatformBranch {
  id: string
  code: string
  nameZh: string
  nameJa: string
  accountCount: number
}

interface PlatformBranchDto {
  id: string
  code: string
  name_zh: string
  name_ja: string
  account_count: number
}

function fromBranchDto(d: PlatformBranchDto): PlatformBranch {
  return { id: d.id, code: d.code, nameZh: d.name_zh, nameJa: d.name_ja, accountCount: d.account_count }
}

export async function fetchPlatformBranches(orgId: number): Promise<PlatformBranch[]> {
  const rows = await http.get<PlatformBranchDto[]>(`/platform/organizations/${orgId}/branches/`)
  return rows.map(fromBranchDto)
}

/** The branch code is generated server-side. */
export async function createPlatformBranch(
  orgId: number,
  payload: { nameZh: string; nameJa: string },
): Promise<PlatformBranch> {
  return fromBranchDto(await http.post<PlatformBranchDto>(`/platform/organizations/${orgId}/branches/`, {
    name_zh: payload.nameZh, name_ja: payload.nameJa,
  }))
}

export async function updatePlatformBranch(
  branchId: string,
  payload: { nameZh?: string; nameJa?: string },
): Promise<PlatformBranch> {
  return fromBranchDto(await http.patch<PlatformBranchDto>(`/platform/branches/${branchId}/`, {
    ...(payload.nameZh !== undefined ? { name_zh: payload.nameZh } : {}),
    ...(payload.nameJa !== undefined ? { name_ja: payload.nameJa } : {}),
  }))
}

/** Rejects with an Error whose message is 'branch-has-accounts' if the
 * branch still has login accounts on it — same guard as a tenant's own
 * Settings screen. */
export async function deletePlatformBranch(branchId: string): Promise<void> {
  await http.delete(`/platform/branches/${branchId}/`)
}

export interface PlatformUser {
  id: number
  account: string
  displayName: string
  role: 'admin' | 'branch' | 'staff'
  branchId: string | null
  staffMemberId: string | null
  isActive: boolean
  isSuperuser: boolean
}

export async function fetchOrganizationUsers(orgId: number): Promise<PlatformUser[]> {
  return http.get<PlatformUser[]>(`/platform/organizations/${orgId}/users/`)
}

export async function createPlatformUser(orgId: number, payload: {
  account: string
  password: string
  displayName: string
  role: 'admin' | 'branch' | 'staff'
  branchId?: string | null
  staffMemberId?: string | null
}): Promise<PlatformUser> {
  return http.post<PlatformUser>(`/platform/organizations/${orgId}/users/`, {
    account: payload.account, password: payload.password, display_name: payload.displayName,
    role: payload.role, branch_id: payload.branchId, staff_member_id: payload.staffMemberId,
  })
}

export async function updatePlatformUser(
  userId: number,
  payload: { displayName?: string; branchId?: string | null },
): Promise<PlatformUser> {
  return http.patch<PlatformUser>(`/platform/users/${userId}/`, {
    ...(payload.displayName !== undefined ? { display_name: payload.displayName } : {}),
    ...(payload.branchId !== undefined ? { branch_id: payload.branchId } : {}),
  })
}

export async function deletePlatformUser(userId: number): Promise<void> {
  await http.delete(`/platform/users/${userId}/`)
}

export async function resetPlatformUserPassword(userId: number, password: string): Promise<void> {
  await http.post(`/platform/users/${userId}/reset_password/`, { password })
}

export async function setPlatformUserActive(userId: number, isActive: boolean): Promise<PlatformUser> {
  return http.post<PlatformUser>(`/platform/users/${userId}/set_active/`, { is_active: isActive })
}
