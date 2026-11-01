import type { Branch } from '@/api/masterData'

const JST_TIME_ZONE = 'Asia/Tokyo'

/** Current date in Asia/Tokyo as YYYY-MM-DD — every business day in this
 * app is a Japan business day, regardless of the browser's own timezone.
 * 'sv-SE' is a locale-formatting trick: Swedish renders dates as
 * YYYY-MM-DD, which is otherwise awkward to get out of Intl directly. */
export function todayJst(): string {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: JST_TIME_ZONE }).format(new Date())
}

/** Current year-month in Asia/Tokyo as YYYY-MM. */
export function currentMonthJst(): string {
  return todayJst().slice(0, 7)
}

export function formatCurrency(value: number): string {
  return `¥${value.toLocaleString('ja-JP')}`
}

/** Like formatCurrency but always shows the sign (±¥0 for zero) — for
 * differences, where "+" vs "-" is the information. */
export function formatSignedCurrency(value: number): string {
  if (value === 0) return '±¥0'
  return `${value > 0 ? '+' : '-'}${formatCurrency(Math.abs(value))}`
}

export function formatNumber(value: number): string {
  return value.toLocaleString('ja-JP')
}

/** Branch names are entered directly in both locales (no i18n key indirection),
 * so admin-added branches display correctly without touching the locale files. */
export function branchDisplayName(branch: Branch | undefined, locale: string, fallback = ''): string {
  if (!branch) return fallback
  return locale === 'ja' ? branch.nameJa : branch.nameZh
}

/** 'YYYY-MM-DD' -> '2026年9月18日' — no leading zeros on month/day, matching
 * the existing 'year年Number(month)月' pattern already used for supplier PDF
 * headers (SuppliersView.vue's monthTitle), extended to the day. Used for
 * PDF download filenames, which use a distinct kanji-date naming convention
 * from the existing dash-separated Excel/print filenames. */
export function formatDateKanji(dateStr: string): string {
  const [year, month, day] = dateStr.split('-')
  return `${year}年${Number(month)}月${Number(day)}日`
}

/** 'YYYY-MM' -> '2026年9月'. */
export function formatMonthKanji(monthStr: string): string {
  const [year, month] = monthStr.split('-')
  return `${year}年${Number(month)}月`
}

// ---------------------------------------------------------------------------
// Accounting presentation of amounts — the single source of truth shared by
// every generated report surface (PDF documents, printed documents and Excel
// workbooks) for the daily, monthly and yearly reports.
//
// Why this is deliberately *not* the same function as formatCurrency above:
// formatCurrency is the on-screen style (`¥-1,234` for a negative), and
// formatSignedCurrency is for difference fields where the sign itself is the
// information (`±¥0`, `+¥500`). A finished report document instead follows
// the accounting convention the printed/exported reports are read as:
// thousands separators, amounts right-aligned in their column, negatives in
// parentheses rather than with a leading minus (a minus sign is easy to miss
// or to lose to a bad scan/fax, brackets are not), and one fixed rule each
// for zero and for "no value at all".
//
// The two cases that are constantly conflated are kept distinct:
//   • a real zero       -> `¥0`  (the day was reported and the amount was 0)
//   • no value at all   -> `—`   (no report exists for that day)
// so a reader can never mistake a missing day for a zero-revenue day.
//
// None of these functions ever round, clamp or otherwise alter the number
// they are handed — they are presentation only. Business arithmetic stays on
// the raw values (and, for Excel, the raw value is what lands in the cell;
// only its *display* is an accounting format, so the cell is still summable).
// ---------------------------------------------------------------------------

/** What every report shows in place of an amount that does not exist, as
 * distinct from an amount that exists and is zero. */
export const MISSING_AMOUNT_TEXT = '—'

function isMissing(value: number | null | undefined): value is null | undefined {
  return value === null || value === undefined || Number.isNaN(value)
}

/** Accounting form of a yen amount for a report document: `¥1,234`,
 * `(¥1,234)` for a negative, `¥0` for zero, `—` for a missing value. */
export function formatAccountingCurrency(value: number | null | undefined): string {
  if (isMissing(value)) return MISSING_AMOUNT_TEXT
  if (value < 0) return `(${formatCurrency(Math.abs(value))})`
  return formatCurrency(value)
}

/** Accounting form of a plain count (customers, days, quantities) — same
 * negative/zero/missing rules as formatAccountingCurrency, without the yen
 * symbol, so a count column lines up with the amount columns beside it. */
export function formatAccountingNumber(value: number | null | undefined): string {
  if (isMissing(value)) return MISSING_AMOUNT_TEXT
  if (value < 0) return `(${formatNumber(Math.abs(value))})`
  return formatNumber(value)
}

// Excel number formats matching the two functions above, so an amount reads
// the same in the workbook as it does in the PDF while staying a real
// number in the cell (never a pre-formatted string, which Excel cannot sum).
//
// Format sections are `positive;negative;zero`. The trailing `_)` on the
// positive and zero sections reserves the width of a `)` so digits in those
// rows align with the bracketed negatives directly above/below them, which
// is the whole point of the convention. `¥` is quoted so Excel treats it as
// a literal and does not re-interpret it under a non-Japanese locale's own
// currency symbol.
/** Excel display format for a yen amount cell. */
export const EXCEL_CURRENCY_FORMAT = '"¥"#,##0_);("¥"#,##0);"¥"0_)'
/** Excel display format for a plain count cell. */
export const EXCEL_COUNT_FORMAT = '#,##0_);(#,##0);0_)'

/** What goes into an Excel *amount* cell: the raw number so the cell stays
 * summable, or null for a missing value — never the '—' placeholder string,
 * which would silently turn a numeric column into a text column. */
export function excelAmount(value: number | null | undefined): number | null {
  return isMissing(value) ? null : value
}
