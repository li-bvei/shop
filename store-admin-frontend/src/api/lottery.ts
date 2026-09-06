import { http } from './http'

export interface DabingStore {
  id: string
  name: string
  sortOrder: number
  isActive: boolean
}

export interface DabingPerson {
  id: string
  name: string
  phone: string
  contact: string
  phoneLastFour: string
  birthday: string | null
  mobileModel: string
  note: string
  isActive: boolean
}

export interface DabingRecord {
  id: string
  storeId: string
  storeName: string
  personId: string
  personName: string
  drawDate: string
  drawTime: string
  phone: string
  contact: string
  phoneLastFour: string
  mobileModel: string
  birthday: string | null
  createdByName: string | null
  createdAt: string
}

export interface KyotoPerson {
  id: string
  name: string
  phone: string
  phoneLastFour: string
  note: string
  isActive: boolean
}

export interface KyotoDrawBatch {
  id: string
  drawStartDate: string
  drawEndDate: string
  publishDate: string
  label: string
  displayLabel: string
  isActive: boolean
}

export interface KyotoRecord {
  id: string
  batchId: string
  batchLabel: string
  drawStartDate: string
  drawEndDate: string
  publishDate: string
  personId: string
  personName: string
  phone: string
  phoneLastFour: string
  quantity: number | null
  createdByName: string | null
  createdAt: string
}

interface DabingStoreDto { id: number; name: string; sort_order: number; is_active: boolean }
interface DabingPersonDto { id: number; name: string; phone: string; contact: string; phone_last_four: string; birthday: string | null; mobile_model: string; note: string; is_active: boolean }
interface DabingRecordDto {
  id: number; store: number; store_name: string; person: number; person_name: string; draw_date: string; draw_time: string;
  phone: string; contact: string; phone_last_four: string; mobile_model: string; birthday: string | null; created_by_name: string | null; created_at: string
}
interface KyotoPersonDto { id: number; name: string; phone: string; phone_last_four: string; note: string; is_active: boolean }
interface KyotoBatchDto { id: number; draw_start_date: string; draw_end_date: string; publish_date: string; label: string; display_label: string; is_active: boolean }
interface KyotoRecordDto {
  id: number; batch: number; batch_label: string; draw_start_date: string; draw_end_date: string; publish_date: string;
  person: number; person_name: string; phone: string; phone_last_four: string; quantity: number | null; created_by_name: string | null; created_at: string
}

function fromDabingStore(dto: DabingStoreDto): DabingStore {
  return { id: String(dto.id), name: dto.name, sortOrder: dto.sort_order, isActive: dto.is_active }
}

function fromDabingPerson(dto: DabingPersonDto): DabingPerson {
  return { id: String(dto.id), name: dto.name, phone: dto.phone, contact: dto.contact, phoneLastFour: dto.phone_last_four, birthday: dto.birthday, mobileModel: dto.mobile_model, note: dto.note, isActive: dto.is_active }
}

function fromDabingRecord(dto: DabingRecordDto): DabingRecord {
  return { id: String(dto.id), storeId: String(dto.store), storeName: dto.store_name, personId: String(dto.person), personName: dto.person_name, drawDate: dto.draw_date, drawTime: dto.draw_time, phone: dto.phone, contact: dto.contact, phoneLastFour: dto.phone_last_four, mobileModel: dto.mobile_model, birthday: dto.birthday, createdByName: dto.created_by_name, createdAt: dto.created_at }
}

function fromKyotoPerson(dto: KyotoPersonDto): KyotoPerson {
  return { id: String(dto.id), name: dto.name, phone: dto.phone, phoneLastFour: dto.phone_last_four, note: dto.note, isActive: dto.is_active }
}

function fromKyotoBatch(dto: KyotoBatchDto): KyotoDrawBatch {
  return { id: String(dto.id), drawStartDate: dto.draw_start_date, drawEndDate: dto.draw_end_date, publishDate: dto.publish_date, label: dto.label, displayLabel: dto.display_label, isActive: dto.is_active }
}

function fromKyotoRecord(dto: KyotoRecordDto): KyotoRecord {
  return { id: String(dto.id), batchId: String(dto.batch), batchLabel: dto.batch_label, drawStartDate: dto.draw_start_date, drawEndDate: dto.draw_end_date, publishDate: dto.publish_date, personId: String(dto.person), personName: dto.person_name, phone: dto.phone, phoneLastFour: dto.phone_last_four, quantity: dto.quantity, createdByName: dto.created_by_name, createdAt: dto.created_at }
}

export async function fetchDabingStores(): Promise<DabingStore[]> {
  const rows = await http.get<DabingStoreDto[]>('/lottery/dabing-stores/?is_active=true')
  return rows.map(fromDabingStore)
}

export async function createDabingStore(payload: { name: string; sortOrder?: number }): Promise<DabingStore> {
  const dto = await http.post<DabingStoreDto>('/lottery/dabing-stores/', { name: payload.name, sort_order: payload.sortOrder ?? 0, is_active: true })
  return fromDabingStore(dto)
}

export async function fetchDabingPeople(search = ''): Promise<DabingPerson[]> {
  const query = new URLSearchParams({ is_active: 'true' })
  if (search) query.set('search', search)
  const rows = await http.get<DabingPersonDto[]>(`/lottery/dabing-people/?${query.toString()}`)
  return rows.map(fromDabingPerson)
}

export async function createDabingPerson(payload: Omit<DabingPerson, 'id' | 'phoneLastFour' | 'isActive'>): Promise<DabingPerson> {
  const dto = await http.post<DabingPersonDto>('/lottery/dabing-people/', { name: payload.name, phone: payload.phone, contact: payload.contact, birthday: payload.birthday, mobile_model: payload.mobileModel, note: payload.note, is_active: true })
  return fromDabingPerson(dto)
}

export async function fetchDabingRecords(
  filters: { date?: string; storeId?: string; dateFrom?: string; dateTo?: string; search?: string } = {},
): Promise<DabingRecord[]> {
  const query = new URLSearchParams()
  if (filters.date) query.set('draw_date', filters.date)
  if (filters.storeId) query.set('store', filters.storeId)
  if (filters.dateFrom) query.set('date_from', filters.dateFrom)
  if (filters.dateTo) query.set('date_to', filters.dateTo)
  if (filters.search) query.set('search', filters.search)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  const rows = await http.get<DabingRecordDto[]>(`/lottery/dabing-records/${suffix}`)
  return rows.map(fromDabingRecord)
}

export async function createDabingRecord(payload: { storeId: string; personId: string; drawDate: string; drawTime: string }): Promise<DabingRecord> {
  const dto = await http.post<DabingRecordDto>('/lottery/dabing-records/', { store: payload.storeId, person: payload.personId, draw_date: payload.drawDate, draw_time: payload.drawTime })
  return fromDabingRecord(dto)
}

export async function deleteDabingRecord(id: string): Promise<void> {
  await http.delete(`/lottery/dabing-records/${id}/`)
}

export async function fetchKyotoPeople(search = ''): Promise<KyotoPerson[]> {
  const query = new URLSearchParams({ is_active: 'true' })
  if (search) query.set('search', search)
  const rows = await http.get<KyotoPersonDto[]>(`/lottery/kyoto-people/?${query.toString()}`)
  return rows.map(fromKyotoPerson)
}

export async function createKyotoPerson(payload: { name: string; phone: string; note: string }): Promise<KyotoPerson> {
  const dto = await http.post<KyotoPersonDto>('/lottery/kyoto-people/', { name: payload.name, phone: payload.phone, note: payload.note, is_active: true })
  return fromKyotoPerson(dto)
}

export async function fetchKyotoBatches(): Promise<KyotoDrawBatch[]> {
  const rows = await http.get<KyotoBatchDto[]>('/lottery/kyoto-batches/?is_active=true')
  return rows.map(fromKyotoBatch)
}

export async function createKyotoBatch(payload: { drawStartDate: string; drawEndDate: string; publishDate: string; label: string }): Promise<KyotoDrawBatch> {
  const dto = await http.post<KyotoBatchDto>('/lottery/kyoto-batches/', { draw_start_date: payload.drawStartDate, draw_end_date: payload.drawEndDate, publish_date: payload.publishDate, label: payload.label, is_active: true })
  return fromKyotoBatch(dto)
}

export async function fetchKyotoRecords(
  filters: { batchId?: string; publishFrom?: string; publishTo?: string; search?: string } = {},
): Promise<KyotoRecord[]> {
  const query = new URLSearchParams()
  if (filters.batchId) query.set('batch', filters.batchId)
  if (filters.publishFrom) query.set('publish_from', filters.publishFrom)
  if (filters.publishTo) query.set('publish_to', filters.publishTo)
  if (filters.search) query.set('search', filters.search)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  const rows = await http.get<KyotoRecordDto[]>(`/lottery/kyoto-records/${suffix}`)
  return rows.map(fromKyotoRecord)
}

export async function createKyotoRecord(payload: { batchId: string; personId: string }): Promise<KyotoRecord> {
  const dto = await http.post<KyotoRecordDto>('/lottery/kyoto-records/', { batch: payload.batchId, person: payload.personId })
  return fromKyotoRecord(dto)
}

export async function deleteKyotoRecord(id: string): Promise<void> {
  await http.delete(`/lottery/kyoto-records/${id}/`)
}
