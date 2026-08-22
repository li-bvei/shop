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
