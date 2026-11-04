/**
 * Time arithmetic for the schedule grid, kept apart from the view so it can
 * be tested on its own. Times are "HH:MM" strings, as the API returns them.
 *
 * The rules mirror the backend exactly, so the hours a manager sees while
 * drafting are the hours that will be paid:
 *   - an end that is not after the start runs into the next day
 *     (ShiftTemplate.crosses_midnight; the same rule Frappe HR's Shift Type
 *     uses);
 *   - paid minutes are the span minus the break, never negative
 *     (wages/calculation.py classify_minutes).
 */

export interface ShiftTimes {
  start: string
  end: string
  breakMinutes: number
  crossesMidnight: boolean
}

export function toMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(':')
  return Number(h) * 60 + Number(m)
}

export function endsNextDay(start: string, end: string): boolean {
  return toMinutes(end) <= toMinutes(start)
}

export function spanMinutes(start: string, end: string, crossesMidnight: boolean): number {
  return toMinutes(end) + (crossesMidnight ? 1440 : 0) - toMinutes(start)
}

export function paidMinutes(shift: ShiftTimes): number {
  return Math.max(0, spanMinutes(shift.start, shift.end, shift.crossesMidnight) - shift.breakMinutes)
}

/** null when the times are usable; otherwise the backend's own error code,
 * so the message shown is the one the server would have returned. */
export function shiftTimesError(shift: ShiftTimes): 'shift-invalid-time-range' | 'shift-break-exceeds-duration' | null {
  if (!shift.start || !shift.end || shift.start === shift.end) return 'shift-invalid-time-range'
  const span = spanMinutes(shift.start, shift.end, shift.crossesMidnight)
  if (span <= 0) return 'shift-invalid-time-range'
  if (shift.breakMinutes < 0 || shift.breakMinutes >= span) return 'shift-break-exceeds-duration'
  return null
}

/** "7.5h" — one decimal, trailing ".0" dropped. */
export function formatHours(minutes: number): string {
  return `${Number((minutes / 60).toFixed(1))}h`
}
