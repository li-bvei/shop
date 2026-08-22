export interface ScheduleSaveOutcome {
  key: string
  ok: boolean
  shiftId?: string | null
  reason?: string
}

export interface ScheduleSaveCellState {
  state: string
  shiftId: string | null
  dirty: boolean
}

/** Pure reconciliation used after a partial batch save. Successful cells
 * become clean and receive their persisted id; failed/declined cells retain
 * the exact local selection and remain dirty. */
export function reconcileScheduleSave<T extends ScheduleSaveCellState>(
  cells: Record<string, T>,
  outcomes: ScheduleSaveOutcome[],
): { cells: Record<string, T>; succeeded: number; failed: ScheduleSaveOutcome[] } {
  const next = Object.fromEntries(Object.entries(cells).map(([key, cell]) => [key, { ...cell } as T]))
  const failed: ScheduleSaveOutcome[] = []
  let succeeded = 0
  for (const outcome of outcomes) {
    const cell = next[outcome.key]
    if (!cell) continue
    if (outcome.ok) {
      cell.dirty = false
      if ('shiftId' in outcome) cell.shiftId = outcome.shiftId ?? null
      succeeded += 1
    } else {
      cell.dirty = true
      failed.push(outcome)
    }
  }
  return { cells: next, succeeded, failed }
}
