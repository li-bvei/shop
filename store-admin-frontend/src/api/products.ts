import { http } from './http'

export type ProductStatus = 'active' | 'inactive'

export interface Product {
  id: string
  janCode: string
  name: string
  category: string
  unit: string
  sellingPrice: number
  costPrice: number | null
  lowStockThreshold: number | null
  status: ProductStatus
  note: string
}

interface ProductDto {
  id: number
  jan_code: string
  name: string
  category: string
  unit: string
  selling_price: string | number
  cost_price: string | number | null
  low_stock_threshold: string | number | null
  status: ProductStatus
  note: string
}

function fromDto(dto: ProductDto): Product {
  return {
    id: String(dto.id),
    janCode: dto.jan_code,
    name: dto.name,
    category: dto.category,
    unit: dto.unit,
    sellingPrice: Number(dto.selling_price),
    costPrice: dto.cost_price !== null ? Number(dto.cost_price) : null,
    lowStockThreshold: dto.low_stock_threshold !== null ? Number(dto.low_stock_threshold) : null,
    status: dto.status,
    note: dto.note,
  }
}

function toDto(payload: Omit<Product, 'id'>) {
  return {
    jan_code: payload.janCode,
    name: payload.name,
    category: payload.category,
    unit: payload.unit,
    selling_price: payload.sellingPrice,
    cost_price: payload.costPrice,
    low_stock_threshold: payload.lowStockThreshold,
    status: payload.status,
    note: payload.note,
  }
}

export async function fetchProducts(keyword = ''): Promise<Product[]> {
  const query = keyword ? `?search=${encodeURIComponent(keyword)}` : ''
  const rows = await http.get<ProductDto[]>(`/products/${query}`)
  return rows.map(fromDto)
}

export async function createProduct(payload: Omit<Product, 'id'>): Promise<Product> {
  const dto = await http.post<ProductDto>('/products/', toDto(payload))
  return fromDto(dto)
}

export async function updateProduct(id: string, payload: Omit<Product, 'id'>): Promise<void> {
  await http.patch(`/products/${id}/`, toDto(payload))
}

export async function deleteProduct(id: string): Promise<void> {
  await http.delete(`/products/${id}/`)
}

/** Barcode-scanner lookup — returns null (not a 404) on no match, since a
 * miss during scanning is a routine outcome, not an error. */
export async function lookupProductByJan(jan: string): Promise<Product | null> {
  const dto = await http.get<ProductDto | null>(`/products/lookup/?jan=${encodeURIComponent(jan)}`)
  return dto ? fromDto(dto) : null
}
