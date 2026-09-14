import { http } from './http'

export interface ReportUnlock {
  token: string
  expiresInSeconds: number
}

/** Verifies the org's shared report-unlock password and, on success,
 * returns a short-lived token to pass as the X-Report-Unlock-Token header
 * on the daily-report save that follows (see api/dailyReport.ts). Kept out
 * of the current-user-password / account APIs — this is a shared
 * operational secret, not an individual credential. */
export async function verifyReportUnlockPassword(password: string): Promise<ReportUnlock> {
  const d = await http.post<{ token: string; expires_in_seconds: number }>('/daily-reports-unlock/', { password })
  return { token: d.token, expiresInSeconds: d.expires_in_seconds }
}
