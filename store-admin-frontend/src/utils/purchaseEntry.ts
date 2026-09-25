/** Rules for one purchase-entry row, shared by the desktop single-row entry
 * and the phone entry form so both accept and reject exactly the same input
 * (and produce the same payload). Returns the i18n key of the first problem,
 * in the same order the desktop row always checked them. */
export interface PurchaseEntryRow {
  date: string
  branchId: string
  supplierId: string
  itemName: string
  quantity: number
  unitPrice: number
  note: string
}

export type PurchaseEntryProblem = { key: string; field?: 'itemName' }

export function validatePurchaseRow(row: PurchaseEntryRow): PurchaseEntryProblem | null {
  if (!row.branchId) return { key: 'purchasing.validateBranch' }
  if (!row.supplierId) return { key: 'purchasing.validateSupplier' }
  if (!row.itemName.trim()) return { key: 'purchasing.validateItemName', field: 'itemName' }
  if (!row.quantity || row.quantity <= 0) return { key: 'purchasing.validateQuantity' }
  if (!row.unitPrice || row.unitPrice <= 0) return { key: 'purchasing.validateUnitPrice' }
  return null
}

export function buildPurchasePayload(row: PurchaseEntryRow) {
  return {
    date: row.date,
    branchId: row.branchId,
    supplierId: row.supplierId,
    itemName: row.itemName.trim(),
    quantity: row.quantity,
    unitPrice: row.unitPrice,
    note: row.note,
  }
}

/** The on-screen 金額 preview; the server computes the stored amount itself. */
export function purchaseAmountPreview(row: Pick<PurchaseEntryRow, 'quantity' | 'unitPrice'>) {
  return row.quantity * row.unitPrice
}
