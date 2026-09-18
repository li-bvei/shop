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
