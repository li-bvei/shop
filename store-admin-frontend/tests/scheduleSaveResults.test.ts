import assert from 'node:assert/strict'
import test from 'node:test'

import { reconcileScheduleSave } from '../src/utils/scheduleSaveResults.ts'

const lunch = { start: '11:00', end: '15:30', breakMinutes: 0, crossesMidnight: false, templateId: '1' }
const custom = { start: '12:15', end: '16:45', breakMinutes: 15, crossesMidnight: false, templateId: null }
const late = { start: '22:00', end: '02:00', breakMinutes: 30, crossesMidnight: true, templateId: '2' }

test('partial save keeps failed and declined cells dirty without losing selections', () => {
  const result = reconcileScheduleSave({
    '1:2026-08-01': { shift: lunch, shiftId: null, dirty: true },
    '1:2026-08-02': { shift: custom, shiftId: null, dirty: true },
    '2:2026-08-01': { shift: late, shiftId: '9', dirty: true },
  }, [
    { key: '1:2026-08-01', ok: true, shiftId: '101' },
    { key: '1:2026-08-02', ok: false, reason: 'override declined' },
    { key: '2:2026-08-01', ok: false, reason: 'server validation' },
  ])

  assert.equal(result.succeeded, 1)
  assert.equal(result.failed.length, 2)
  assert.deepEqual(result.cells['1:2026-08-01'], { shift: lunch, shiftId: '101', dirty: false })
  assert.deepEqual(result.cells['1:2026-08-02'], { shift: custom, shiftId: null, dirty: true })
  assert.deepEqual(result.cells['2:2026-08-01'], { shift: late, shiftId: '9', dirty: true })
})

test('a cell cleared to a day off saves with no shift id', () => {
  const result = reconcileScheduleSave({
    '1:2026-08-03': { shift: null, shiftId: '55', dirty: true },
  }, [{ key: '1:2026-08-03', ok: true, shiftId: null }])
  assert.deepEqual(result.cells['1:2026-08-03'], { shift: null, shiftId: null, dirty: false })
})
