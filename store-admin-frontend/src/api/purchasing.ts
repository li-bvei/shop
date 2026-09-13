import { http } from './http'

export type PriceDirection = 'up' | 'down' | 'same' | null

export interface PurchaseRecord {
  id: string
  date: string
  branchId: string
  supplierId: string
  itemName: string
  quantity: number
  unitPrice: number
  amount: number
  note: string
  priceDirection: PriceDirection
  priorMonthAvgUnitPrice: number | null
  priceDeltaAmount: number | null
  priceDeltaPercent: number | null
  // vs the immediately preceding purchase of the same item — see
  // purchasing.services.compute_prior_purchase_deltas on the backend for
  // why this is a separate comparison from the month-average one above.
  priorPurchaseUnitPrice: number | null
  priorPurchaseDirection: 'up' | 'down' | null
  priorPurchaseDeltaAmount: number | null
  priorPurchaseDeltaPercent: number | null
}

interface PurchaseDto {
  id: number
  date: string
  branch: string
  supplier: number
  item_name: string
  quantity: string | number
  unit_price: string | number
  amount: string | number
  note: string
  price_direction: PriceDirection
  prior_month_avg_unit_price: string | number | null
  price_delta_amount: string | number | null
  price_delta_percent: string | number | null
  prior_purchase_unit_price: string | number | null
  prior_purchase_direction: 'up' | 'down' | null
  prior_purchase_delta_amount: string | number | null
  prior_purchase_delta_percent: string | number | null
}

function fromDto(dto: PurchaseDto): PurchaseRecord {
  return {
    id: String(dto.id),
    date: dto.date,
    branchId: dto.branch,
    supplierId: String(dto.supplier),
    itemName: dto.item_name,
    quantity: Number(dto.quantity),
    unitPrice: Number(dto.unit_price),
    amount: Number(dto.amount),
    note: dto.note,
    priceDirection: dto.price_direction,
    priorMonthAvgUnitPrice: dto.prior_month_avg_unit_price !== null ? Number(dto.prior_month_avg_unit_price) : null,
    priceDeltaAmount: dto.price_delta_amount !== null ? Number(dto.price_delta_amount) : null,
    priceDeltaPercent: dto.price_delta_percent !== null ? Number(dto.price_delta_percent) : null,
    priorPurchaseUnitPrice: dto.prior_purchase_unit_price !== null ? Number(dto.prior_purchase_unit_price) : null,
    priorPurchaseDirection: dto.prior_purchase_direction,
    priorPurchaseDeltaAmount: dto.prior_purchase_delta_amount !== null ? Number(dto.prior_purchase_delta_amount) : null,
    priorPurchaseDeltaPercent: dto.prior_purchase_delta_percent !== null ? Number(dto.prior_purchase_delta_percent) : null,
  }
}

type PurchaseWrite = Omit<
  PurchaseRecord,
  'id' | 'amount' | 'priceDirection' | 'priorMonthAvgUnitPrice' | 'priceDeltaAmount' | 'priceDeltaPercent' |
  'priorPurchaseUnitPrice' | 'priorPurchaseDirection' | 'priorPurchaseDeltaAmount' | 'priorPurchaseDeltaPercent'
>

function toDto(payload: PurchaseWrite) {
  return {
    date: payload.date,
    // Branch-role accounts omit this — BranchScopedQuerysetMixin fills it
    // in server-side; admins must include it, same as before.
    ...(payload.branchId ? { branch: payload.branchId } : {}),
    supplier: Number(payload.supplierId),
    item_name: payload.itemName,
    quantity: payload.quantity,
    unit_price: payload.unitPrice,
    note: payload.note,
  }
}

export interface PurchaseListParams {
  branchId?: string
  supplierId?: string
  month?: string // 'YYYY-MM'
  dateFrom?: string
  dateTo?: string
  itemName?: string
  priceChange?: 'up' | 'down'
  ordering?: string // e.g. 'date', '-unit_price'
  page?: number
  pageSize?: number
}

export interface PurchaseListResult {
  count: number
  next: string | null
  previous: string | null
  results: PurchaseRecord[]
}

function buildListQuery(params: PurchaseListParams): string {
  const query = new URLSearchParams()
  if (params.branchId) query.set('branch', params.branchId)
  if (params.supplierId) query.set('supplier', params.supplierId)
  if (params.month) query.set('month', params.month)
  if (params.dateFrom) query.set('date_from', params.dateFrom)
  if (params.dateTo) query.set('date_to', params.dateTo)
  if (params.itemName) query.set('item_name', params.itemName)
  if (params.priceChange) query.set('price_change', params.priceChange)
  if (params.ordering) query.set('ordering', params.ordering)
  if (params.page) query.set('page', String(params.page))
  if (params.pageSize) query.set('page_size', String(params.pageSize))
  return query.toString()
}

export async function fetchPurchases(params: PurchaseListParams = {}): Promise<PurchaseListResult> {
  const dto = await http.get<{
    count: number
    next: string | null
    previous: string | null
    results: PurchaseDto[]
  }>(`/purchases/?${buildListQuery(params)}`)
  return { count: dto.count, next: dto.next, previous: dto.previous, results: dto.results.map(fromDto) }
}

/** Fetches every page for the given filters — only safe to use when the
 * filters already bound the result to a small set (e.g. a single month),
 * never for an unfiltered full-table fetch. */
export async function fetchAllPurchases(params: PurchaseListParams = {}): Promise<PurchaseRecord[]> {
  const all: PurchaseRecord[] = []
  let page = 1
  for (;;) {
    const result = await fetchPurchases({ ...params, page, pageSize: 200 })
    all.push(...result.results)
    if (!result.next) break
    page += 1
  }
  return all
}

/** Sum of `amount` over the given filters, computed DB-side — replaces
 * summing fetchAllPurchases() client-side, which meant paging through every
 * matching record (and recomputing its price comparison) on every filter
 * change just to add up a total. */
export async function fetchPurchaseMonthTotal(params: PurchaseListParams = {}): Promise<number> {
  const dto = await http.get<{ total: string | number }>(`/purchases/month_total/?${buildListQuery(params)}`)
  return Number(dto.total)
}

export interface BulkReplacePreviewRow {
  id: string
  date: string
  branchId: string
  supplierId: string
  supplierName: string
  itemName: string
  quantity: number
  unitPrice: number
}

export interface BulkReplacePreview {
  matchedCount: number
  preview: BulkReplacePreviewRow[]
}

interface BulkReplacePreviewRowDto {
  id: number
  date: string
  branch_id: string
  supplier_id: number
  supplier__name: string
  item_name: string
  quantity: string | number
  unit_price: string | number
}

function fromPreviewDto(row: BulkReplacePreviewRowDto): BulkReplacePreviewRow {
  return {
    id: String(row.id), date: row.date, branchId: row.branch_id, supplierId: String(row.supplier_id),
    supplierName: row.supplier__name, itemName: row.item_name,
    quantity: Number(row.quantity), unitPrice: Number(row.unit_price),
  }
}

/** Find-and-replace one specific wrong value (a date or a supplier) across
 * every record matching `filters` — the same query params the list view
 * accepts. Always call with confirm=false first to preview the match count
 * before actually writing anything. */
export async function bulkReplacePurchases(options: {
  field: 'date' | 'supplier'
  oldValue: string
  newValue: string
  confirm: boolean
  filters?: PurchaseListParams
}): Promise<BulkReplacePreview | { replacedCount: number }> {
  const query = buildListQuery(options.filters ?? {})
  const body = { field: options.field, old_value: options.oldValue, new_value: options.newValue, confirm: options.confirm }
  const result = await http.post<
    { matchedCount: number; preview: BulkReplacePreviewRowDto[] } | { replacedCount: number }
  >(`/purchases/bulk_replace/?${query}`, body)
  if ('preview' in result) {
    return { matchedCount: result.matchedCount, preview: result.preview.map(fromPreviewDto) }
  }
  return result
}

export async function createPurchase(
  payload: PurchaseWrite,
): Promise<PurchaseRecord> {
  const dto = await http.post<PurchaseDto>('/purchases/', toDto(payload))
  return fromDto(dto)
}

export async function updatePurchase(
  id: string,
  payload: PurchaseWrite,
): Promise<void> {
  await http.patch(`/purchases/${id}/`, toDto(payload))
}

export async function deletePurchase(id: string): Promise<void> {
  await http.delete(`/purchases/${id}/`)
}

export interface PurchaseItemSuggestion {
  itemName: string
  lastUnitPrice: number
  useCount: number
}

/**
 * Ranks item names this supplier has been paid for before by frequency +
 * recency, so the most relevant item (and its last price) surfaces first
 * while typing.
 */
export async function fetchPurchaseItemSuggestions(
  supplierId: string,
  keyword = '',
): Promise<PurchaseItemSuggestion[]> {
  const params = new URLSearchParams({ supplier: supplierId, q: keyword })
  return http.get<PurchaseItemSuggestion[]>(`/purchases/suggestions/?${params.toString()}`)
}

export interface PriceHistoryEntry {
  id: string
  date: string
  itemName: string
  quantity: number
  unitPrice: number
  amount: number
}

interface PriceHistoryDto {
  id: number
  date: string
  itemName: string
  quantity: string | number
  unitPrice: string | number
  amount: string | number
}

/** Chronological unit-price history for one (branch, supplier, item) —
 * newest first, capped at the last 100 records server-side. */
export async function fetchPriceHistory(
  branchId: string,
  supplierId: string,
  itemName: string,
): Promise<PriceHistoryEntry[]> {
  const params = new URLSearchParams({ branch: branchId, supplier: supplierId, item_name: itemName })
  const rows = await http.get<PriceHistoryDto[]>(`/purchases/price_history/?${params.toString()}`)
  return rows.map((r) => ({
    id: String(r.id),
    date: r.date,
    itemName: r.itemName,
    quantity: Number(r.quantity),
    unitPrice: Number(r.unitPrice),
    amount: Number(r.amount),
  }))
}

export interface SupplierPriceComparisonEntry {
  supplierId: string
  supplierName: string
  latestUnitPrice: number | null
  latestDate: string | null
  avgUnitPrice: number | null
  recordCount: number
}

interface SupplierPriceComparisonDto {
  supplierId: number
  supplierName: string
  latestUnitPrice: string | number | null
  latestDate: string | null
  avgUnitPrice: string | number | null
  recordCount: number
}

/** Same item across every supplier at one branch, cheapest first — the one
 * place this feature deliberately mixes suppliers, since the point is
 * letting the user compare and pick. */
export async function fetchSupplierPriceComparison(
  branchId: string,
  itemName: string,
): Promise<SupplierPriceComparisonEntry[]> {
  const params = new URLSearchParams({ branch: branchId, item_name: itemName })
  const rows = await http.get<SupplierPriceComparisonDto[]>(`/purchases/supplier_comparison/?${params.toString()}`)
  return rows.map((r) => ({
    supplierId: String(r.supplierId),
    supplierName: r.supplierName,
    latestUnitPrice: r.latestUnitPrice !== null ? Number(r.latestUnitPrice) : null,
    latestDate: r.latestDate,
    avgUnitPrice: r.avgUnitPrice !== null ? Number(r.avgUnitPrice) : null,
    recordCount: r.recordCount,
  }))
}
