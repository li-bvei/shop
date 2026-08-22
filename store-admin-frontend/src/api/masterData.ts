import { http, ApiError } from './http'

export interface Branch {
  id: string
  nameZh: string
  nameJa: string
}

interface BranchDto {
  id: string
  name_zh: string
  name_ja: string
}

function fromBranchDto(dto: BranchDto): Branch {
  return { id: dto.id, nameZh: dto.name_zh, nameJa: dto.name_ja }
}

export async function fetchBranches(): Promise<Branch[]> {
  const rows = await http.get<BranchDto[]>('/branches/')
  return rows.map(fromBranchDto)
}

export async function addBranch(nameZh: string, nameJa: string): Promise<Branch> {
  // id is a slug the backend derives; the API only needs the two names.
  const dto = await http.post<BranchDto>('/branches/', { id: slugify(nameZh), name_zh: nameZh, name_ja: nameJa })
  return fromBranchDto(dto)
}

function slugify(nameZh: string): string {
  return `branch-${Date.now()}-${nameZh.slice(0, 1)}`
}

export async function updateBranch(id: string, nameZh: string, nameJa: string): Promise<void> {
  await http.patch(`/branches/${id}/`, { name_zh: nameZh, name_ja: nameJa })
}

export async function deleteBranch(id: string): Promise<void> {
  try {
    await http.delete(`/branches/${id}/`)
  } catch (err) {
    if (err instanceof ApiError && err.messages().some((m) => m.includes('branch-has-accounts'))) {
      throw new Error('branch-has-accounts')
    }
    throw err
  }
}

export interface PaymentMethodDef {
  id: number
  code: string
  branchId: string
  i18nKey: string
  customName?: string
  sortOrder: number
  protected: boolean
}

interface PaymentMethodDto {
  id: number
  code: string
  branch: string
  i18n_key: string
  custom_name: string
  sort_order: number
  protected: boolean
}

function fromPaymentMethodDto(dto: PaymentMethodDto): PaymentMethodDef {
  return {
    id: dto.id,
    code: dto.code,
    branchId: dto.branch,
    i18nKey: dto.i18n_key,
    customName: dto.custom_name,
    sortOrder: dto.sort_order,
    protected: dto.protected,
  }
}

export async function fetchPaymentMethods(branchId: string): Promise<PaymentMethodDef[]> {
  const rows = await http.get<PaymentMethodDto[]>(`/payment-methods/?branch=${encodeURIComponent(branchId)}`)
  return rows.map(fromPaymentMethodDto).sort((a, b) => a.sortOrder - b.sortOrder)
}

export async function renamePaymentMethod(id: number, name: string): Promise<void> {
  await http.patch(`/payment-methods/${id}/`, { custom_name: name })
}

export async function deletePaymentMethod(id: number): Promise<void> {
  await http.delete(`/payment-methods/${id}/`)
}

export async function addPaymentMethod(branchId: string, name: string): Promise<PaymentMethodDef> {
  const existing = await fetchPaymentMethods(branchId)
  const maxSort = existing.reduce((max, m) => Math.max(max, m.sortOrder), 0)
  const dto = await http.post<PaymentMethodDto>('/payment-methods/', {
    branch: branchId,
    code: `custom-${Date.now()}`,
    custom_name: name,
    i18n_key: '',
    sort_order: maxSort + 1,
  })
  return fromPaymentMethodDto(dto)
}

/** Atomically rewrites the branch's full sort order from a dragged id list
 * — `orderedIds` must be exactly the branch's existing method ids, each
 * once (including the cash row, which is reorderable even though it can't
 * be renamed or deleted). */
export async function reorderPaymentMethods(branchId: string, orderedIds: number[]): Promise<PaymentMethodDef[]> {
  const rows = await http.post<PaymentMethodDto[]>('/payment-methods/reorder/', {
    branch: branchId, order: orderedIds,
  })
  return rows.map(fromPaymentMethodDto)
}

export interface ExpenseSuggestion {
  itemName: string
  lastAmount: number
  lastPurpose: string
  useCount: number
}

/**
 * Ranks item names this branch has used before by frequency + recency,
 * so the most relevant suggestion surfaces first while typing.
 */
export async function fetchExpenseSuggestions(branchId: string, keyword = ''): Promise<ExpenseSuggestion[]> {
  const params = new URLSearchParams({ branch: branchId, q: keyword })
  return http.get<ExpenseSuggestion[]>(`/daily-reports/expense_suggestions/?${params.toString()}`)
}
