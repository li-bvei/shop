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

export interface PlatformUser {
  id: number
  account: string
  displayName: string
  role: 'admin' | 'branch' | 'staff'
  branchId: string | null
  isActive: boolean
  isSuperuser: boolean
}

export async function fetchOrganizationUsers(orgId: number): Promise<PlatformUser[]> {
  return http.get<PlatformUser[]>(`/platform/organizations/${orgId}/users/`)
}

export async function setPlatformUserActive(userId: number, isActive: boolean): Promise<PlatformUser> {
  return http.post<PlatformUser>(`/platform/users/${userId}/set_active/`, { is_active: isActive })
}
