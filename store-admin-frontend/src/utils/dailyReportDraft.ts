import type { DailyReportFormData } from '@/components/DailyReportForm.vue'

/**
 * Offline fallback for the daily-report save button. When the network is
 * down at save time, the form data is kept here instead of being lost, and
 * synced back once connectivity returns. One entry per branch+date, so a
 * device that goes offline across several closing shifts doesn't lose any
 * of them — each is synced (or flagged as a conflict) independently.
 */

const STORAGE_PREFIX = 'sa_daily_report_draft:'

export interface DailyReportDraft {
  branchId: string
  date: string
  data: DailyReportFormData
  /** The report's server-side `updated_at` this draft was edited on top of
   * (null for a brand-new report) — compared against the server's current
   * value at sync time to detect someone else having saved in the meantime. */
  baseUpdatedAt: string | null
  savedLocallyAt: string
}

function key(branchId: string, date: string) {
  return `${STORAGE_PREFIX}${branchId}:${date}`
}

export function saveDraft(draft: DailyReportDraft) {
  try {
    localStorage.setItem(key(draft.branchId, draft.date), JSON.stringify(draft))
  } catch {
    // localStorage unavailable (private mode, quota) — nothing more we can
    // do locally; the caller already knows the network save itself failed.
  }
}

export function getDraft(branchId: string, date: string): DailyReportDraft | null {
  try {
    const raw = localStorage.getItem(key(branchId, date))
    return raw ? (JSON.parse(raw) as DailyReportDraft) : null
  } catch {
    return null
  }
}

export function clearDraft(branchId: string, date: string) {
  try {
    localStorage.removeItem(key(branchId, date))
  } catch {
    // ignore
  }
}

export function listDrafts(): DailyReportDraft[] {
  const drafts: DailyReportDraft[] = []
  try {
    for (let i = 0; i < localStorage.length; i += 1) {
      const k = localStorage.key(i)
      if (!k || !k.startsWith(STORAGE_PREFIX)) continue
      const raw = localStorage.getItem(k)
      if (!raw) continue
      try {
        drafts.push(JSON.parse(raw) as DailyReportDraft)
      } catch {
        // corrupt entry — skip it rather than block every other draft
      }
    }
  } catch {
    return []
  }
  return drafts
}

/** A plain `fetch()` failure (offline, DNS, timeout, CORS) throws before a
 * response is ever received — no HTTP status, so it never becomes an
 * ApiError. A real server-side error (validation, 500) always does. This
 * is the only reliable way to tell "we're offline" apart from "the server
 * rejected this", and only the former should fall back to a local draft. */
export function isNetworkFailure(error: unknown): boolean {
  return !(error && typeof error === 'object' && 'status' in error)
}
