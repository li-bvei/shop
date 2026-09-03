import { http, ApiError } from './http'

export type AccountRole = 'admin' | 'branch' | 'staff'

export interface AccountRecord {
  id: number
  account: string
  displayName: string
  role: AccountRole
  branchId: string | null
  staffMemberId: string | null
}

export async function fetchAccounts(): Promise<AccountRecord[]> {
  return http.get<AccountRecord[]>('/users/')
}

export interface CreateAccountPayload {
  account: string
  password: string
  displayName: string
  role: AccountRole
  branchId: string | null
  /** Required (and the source of branchId, which the server derives and
   * ignores from the client) when role is 'staff'. */
  staffMemberId?: string | null
}

export async function createAccount(payload: CreateAccountPayload): Promise<AccountRecord> {
  try {
    return await http.post<AccountRecord>('/users/', payload)
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) {
      const msgs = err.messages()
      if (msgs.some((m) => m.includes('already has a login account'))) throw new Error('employee-already-has-account')
      throw new Error('account-exists')
    }
    throw err
  }
}

export async function updateAccount(
  id: number,
  patch: { displayName: string; branchId: string | null },
): Promise<void> {
  await http.patch(`/users/${id}/`, patch)
}

export async function deleteAccount(id: number): Promise<void> {
  try {
    await http.delete(`/users/${id}/`)
  } catch (err) {
    if (err instanceof ApiError) {
      const msgs = err.messages()
      if (msgs.some((m) => m.includes('currently logged in'))) throw new Error('cannot-delete-self')
      if (msgs.some((m) => m.includes('at least one admin'))) throw new Error('cannot-delete-last-admin')
    }
    throw err
  }
}

/** Admin-only: overwrite any account's password without knowing the old one. */
export async function adminResetPassword(id: number, newPassword: string): Promise<void> {
  await http.post(`/users/${id}/reset_password/`, { password: newPassword })
}

/** Self-service: the currently logged-in account changes its own password. */
export async function changeOwnPassword(oldPassword: string, newPassword: string): Promise<void> {
  try {
    await http.post('/auth/change-password/', { old_password: oldPassword, new_password: newPassword })
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) {
      const msgs = err.messages()
      if (msgs.some((m) => m.includes('invalid-old-password'))) throw new Error('invalid-old-password')
    }
    throw err
  }
}

export interface OrganizationInfo {
  code: string
  nameZh: string
  nameJa: string
  logoUrl: string
}

export async function fetchOrganization(): Promise<OrganizationInfo> {
  const d = await http.get<{ code: string; name_zh: string; name_ja: string; logo_url: string }>(
    '/organization/',
  )
  return { code: d.code, nameZh: d.name_zh, nameJa: d.name_ja, logoUrl: d.logo_url }
}

export async function updateOrganization(patch: {
  nameZh?: string
  nameJa?: string
  logoUrl?: string
}): Promise<OrganizationInfo> {
  const d = await http.patch<{ code: string; name_zh: string; name_ja: string; logo_url: string }>(
    '/organization/',
    {
      ...(patch.nameZh !== undefined ? { name_zh: patch.nameZh } : {}),
      ...(patch.nameJa !== undefined ? { name_ja: patch.nameJa } : {}),
      ...(patch.logoUrl !== undefined ? { logo_url: patch.logoUrl } : {}),
    },
  )
  return { code: d.code, nameZh: d.name_zh, nameJa: d.name_ja, logoUrl: d.logo_url }
}
