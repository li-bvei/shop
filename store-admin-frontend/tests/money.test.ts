import assert from 'node:assert/strict'
import test from 'node:test'

import {
  EXCEL_COUNT_FORMAT,
  EXCEL_CURRENCY_FORMAT,
  MISSING_AMOUNT_TEXT,
  excelAmount,
  formatAccountingCurrency,
  formatAccountingNumber,
} from '../src/utils/format.ts'

test('a positive amount gets a yen symbol and thousands separators', () => {
  assert.equal(formatAccountingCurrency(1234567), '¥1,234,567')
})

test('a negative amount is bracketed, never signed with a minus', () => {
  assert.equal(formatAccountingCurrency(-1234), '(¥1,234)')
  assert.ok(!formatAccountingCurrency(-1234).includes('-'))
})

test('zero is a real amount (¥0), distinct from a missing one', () => {
  assert.equal(formatAccountingCurrency(0), '¥0')
  assert.notEqual(formatAccountingCurrency(0), MISSING_AMOUNT_TEXT)
})

test('null/undefined/NaN all render as the one missing-value placeholder', () => {
  assert.equal(formatAccountingCurrency(null), MISSING_AMOUNT_TEXT)
  assert.equal(formatAccountingCurrency(undefined), MISSING_AMOUNT_TEXT)
  assert.equal(formatAccountingCurrency(Number.NaN), MISSING_AMOUNT_TEXT)
})

test('counts follow the same negative/zero/missing rules without a yen symbol', () => {
  assert.equal(formatAccountingNumber(1234), '1,234')
  assert.equal(formatAccountingNumber(-7), '(7)')
  assert.equal(formatAccountingNumber(0), '0')
  assert.equal(formatAccountingNumber(null), MISSING_AMOUNT_TEXT)
  assert.ok(!formatAccountingNumber(1234).includes('¥'))
})

test('formatting never alters the magnitude it was handed', () => {
  for (const value of [0, 1, -1, 999, -999, 1000, -1000, 123456789, -123456789]) {
    const digits = formatAccountingCurrency(value).replace(/[^0-9]/g, '')
    assert.equal(digits, String(Math.abs(value)), `lost precision formatting ${value}`)
  }
})

test('an Excel amount cell carries the raw number, not a formatted string', () => {
  assert.equal(excelAmount(-1234), -1234)
  assert.equal(excelAmount(0), 0)
  assert.equal(typeof excelAmount(5), 'number')
})

test('a missing Excel amount is null, never the display placeholder', () => {
  assert.equal(excelAmount(null), null)
  assert.equal(excelAmount(undefined), null)
  assert.equal(excelAmount(Number.NaN), null)
})

test('the Excel formats carry all three sections (positive;negative;zero)', () => {
  for (const format of [EXCEL_CURRENCY_FORMAT, EXCEL_COUNT_FORMAT]) {
    assert.equal(format.split(';').length, 3, `${format} is missing a section`)
  }
  // The negative section must bracket, matching formatAccountingCurrency.
  const negativeSection = EXCEL_CURRENCY_FORMAT.split(';')[1] ?? ''
  assert.ok(negativeSection.startsWith('(') && negativeSection.endsWith(')'), negativeSection)
})

test('the screen and Excel renderings of the same amount agree on sign handling', () => {
  // Both bracket negatives; this is the "no unreasonable difference between
  // screen, PDF and Excel" invariant the formats exist to hold.
  assert.ok(formatAccountingCurrency(-50).startsWith('('))
  assert.ok((EXCEL_CURRENCY_FORMAT.split(';')[1] ?? '').startsWith('('))
})
