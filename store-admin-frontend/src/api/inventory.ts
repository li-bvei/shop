import { http } from './http'

export type StockTransactionType = 'purchase_in' | 'sale_out' | 'adjustment_in' | 'adjustment_out'

export interface Stock {
  id: string
  branchId: string
  productId: string
  productName: string
  janCode: string
  category: string
  unit: string
  quantity: number
  lowStockThreshold: number | null
  isLowStock: boolean
  updatedAt: string
}

interface StockDto {
  id: number
  branch: string
  product: number
  product_name: string
  jan_code: string
  category: string
  unit: string
  quantity: string | number
  low_stock_threshold: string | number | null
  is_low_stock: boolean
  updated_at: string
}

function fromDto(dto: StockDto): Stock {
  return {
    id: String(dto.id),
    branchId: dto.branch,
    productId: String(dto.product),
    productName: dto.product_name,
    janCode: dto.jan_code,
    category: dto.category,
    unit: dto.unit,
    quantity: Number(dto.quantity),
    lowStockThreshold: dto.low_stock_threshold !== null ? Number(dto.low_stock_threshold) : null,
    isLowStock: dto.is_low_stock,
    updatedAt: dto.updated_at,
  }
}

export interface StockListParams {
  branchId?: string
  lowStockOnly?: boolean
}

export async function fetchStock(params: StockListParams = {}): Promise<Stock[]> {
  const query = new URLSearchParams()
  if (params.branchId) query.set('branch', params.branchId)
  if (params.lowStockOnly) query.set('low_stock', 'true')
  const rows = await http.get<StockDto[]>(`/stock/?${query.toString()}`)
  return rows.map(fromDto)
}

export interface StockAdjustPayload {
  branchId?: string
  productId: string
  transactionType: StockTransactionType
  quantity: number
  note?: string
}

export async function adjustStock(payload: StockAdjustPayload): Promise<Stock> {
  const dto = await http.post<StockDto>('/stock/adjust/', {
    ...(payload.branchId ? { branch: payload.branchId } : {}),
    product: Number(payload.productId),
    transaction_type: payload.transactionType,
    quantity: payload.quantity,
    note: payload.note ?? '',
  })
  return fromDto(dto)
}

export interface StockTransaction {
  id: string
  branchId: string
  productName: string
  transactionType: StockTransactionType
  quantity: number
  note: string
  operatorName: string
  createdAt: string
}

interface StockTransactionDto {
  id: number
  branch: string
  product_name: string
  transaction_type: StockTransactionType
  quantity: string | number
  note: string
  operator_name: string
  created_at: string
}

export async function fetchStockTransactions(branchId?: string): Promise<StockTransaction[]> {
  const query = branchId ? `?branch=${encodeURIComponent(branchId)}` : ''
  const rows = await http.get<StockTransactionDto[]>(`/stock-transactions/${query}`)
  return rows.map((dto) => ({
    id: String(dto.id),
    branchId: dto.branch,
    productName: dto.product_name,
    transactionType: dto.transaction_type,
    quantity: Number(dto.quantity),
    note: dto.note,
    operatorName: dto.operator_name,
    createdAt: dto.created_at,
  }))
}
