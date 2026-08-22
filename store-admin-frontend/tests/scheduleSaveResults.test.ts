import assert from 'node:assert/strict'
import test from 'node:test'

import { reconcileScheduleSave } from '../src/utils/scheduleSaveResults.ts'

test('partial save keeps failed and declined cells dirty without losing selections', () => {
  const result = reconcileScheduleSave({
    '1:2026-08-01': { state: 'morning', shiftId: null, dirty: true },
    '1:2026-08-02': { state: 'full_day', shiftId: null, dirty: true },
    '2:2026-08-01': { state: 'afternoon', shiftId: '9', dirty: true },
  }, [
    { key: '1:2026-08-01', ok: true, shiftId: '101' },
    { key: '1:2026-08-02', ok: false, reason: 'override declined' },
    { key: '2:2026-08-01', ok: false, reason: 'server validation' },
  ])

  assert.equal(result.succeeded, 1)
  assert.equal(result.failed.length, 2)
  assert.deepEqual(result.cells['1:2026-08-01'], { state: 'morning', shiftId: '101', dirty: false })
  assert.deepEqual(result.cells['1:2026-08-02'], { state: 'full_day', shiftId: null, dirty: true })
  assert.deepEqual(result.cells['2:2026-08-01'], { state: 'afternoon', shiftId: '9', dirty: true })
})
