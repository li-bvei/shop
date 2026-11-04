import assert from 'node:assert/strict'
import test from 'node:test'

import { endsNextDay, formatHours, paidMinutes, shiftTimesError } from '../src/utils/shiftTime.ts'

test('an end not after the start runs into the next day', () => {
  assert.equal(endsNextDay('22:00', '02:00'), true)
  assert.equal(endsNextDay('09:00', '09:00'), true)
  assert.equal(endsNextDay('11:00', '15:30'), false)
})

test('paid minutes are the span minus the break, as wages count them', () => {
  assert.equal(paidMinutes({ start: '11:00', end: '22:00', breakMinutes: 90, crossesMidnight: false }), 570)
  assert.equal(paidMinutes({ start: '22:00', end: '02:00', breakMinutes: 30, crossesMidnight: true }), 210)
  assert.equal(paidMinutes({ start: '10:00', end: '10:30', breakMinutes: 60, crossesMidnight: false }), 0)
})

test('invalid times report the backend error code', () => {
  assert.equal(shiftTimesError({ start: '10:00', end: '10:00', breakMinutes: 0, crossesMidnight: true }), 'shift-invalid-time-range')
  assert.equal(shiftTimesError({ start: '17:00', end: '09:00', breakMinutes: 0, crossesMidnight: false }), 'shift-invalid-time-range')
  assert.equal(shiftTimesError({ start: '10:00', end: '12:00', breakMinutes: 120, crossesMidnight: false }), 'shift-break-exceeds-duration')
  assert.equal(shiftTimesError({ start: '22:00', end: '02:00', breakMinutes: 30, crossesMidnight: true }), null)
})

test('hours are shown with one decimal', () => {
  assert.equal(formatHours(570), '9.5h')
  assert.equal(formatHours(480), '8h')
  assert.equal(formatHours(0), '0h')
})
