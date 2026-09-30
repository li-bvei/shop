import assert from 'node:assert/strict'
import test from 'node:test'

import { calculatePrintScale } from '../src/composables/usePrintFit.ts'

const A4_AVAILABLE_WIDTH_PX = (210 - 20) * (96 / 25.4)
const A4_AVAILABLE_HEIGHT_PX = (297 - 20) * (96 / 25.4)

test('content that already fits one page prints at natural size (scale 1)', () => {
  const scale = calculatePrintScale(500, 800, A4_AVAILABLE_WIDTH_PX, A4_AVAILABLE_HEIGHT_PX, 0)
  assert.equal(scale, 1)
})

test('content taller than one page shrinks (scale < 1) when minScale allows it', () => {
  const scale = calculatePrintScale(500, A4_AVAILABLE_HEIGHT_PX * 2, A4_AVAILABLE_WIDTH_PX, A4_AVAILABLE_HEIGHT_PX, 0)
  assert.ok(scale < 1, `expected scale < 1, got ${scale}`)
  assert.ok(scale > 0, `expected scale > 0, got ${scale}`)
})

test('content wider than the page shrinks (scale < 1) when minScale allows it', () => {
  const scale = calculatePrintScale(A4_AVAILABLE_WIDTH_PX * 3, 500, A4_AVAILABLE_WIDTH_PX, A4_AVAILABLE_HEIGHT_PX, 0)
  assert.ok(scale < 1, `expected scale < 1, got ${scale}`)
})

test('minScale=0.6 (the schedule grid) never shrinks below 0.6 no matter how long the content is', () => {
  const scale = calculatePrintScale(500, A4_AVAILABLE_HEIGHT_PX * 50, A4_AVAILABLE_WIDTH_PX, A4_AVAILABLE_HEIGHT_PX, 0.6)
  assert.equal(scale, 0.6)
})

test('minScale=1 never shrinks at all, even when content is far taller than one page', () => {
  const scale = calculatePrintScale(500, A4_AVAILABLE_HEIGHT_PX * 5, A4_AVAILABLE_WIDTH_PX, A4_AVAILABLE_HEIGHT_PX, 1)
  assert.equal(scale, 1)
})

test('the daily report\'s call (minScale=0) is allowed to shrink to fit a tall page', () => {
  // Regression test for the bug this whole file exists to catch: minScale
  // defaulting to 1 made `Math.max(minScale, ...)` always resolve to 1,
  // silently disabling shrinking for every call site that didn't pass its
  // own minScale — which the daily report never did.
  const naturalHeight = A4_AVAILABLE_HEIGHT_PX * 1.3
  const scale = calculatePrintScale(700, naturalHeight, A4_AVAILABLE_WIDTH_PX, A4_AVAILABLE_HEIGHT_PX, 0)
  assert.ok(scale < 1, `expected scale < 1, got ${scale}`)
  // And the scaled-down height must actually fit within the available page.
  assert.ok(naturalHeight * scale <= A4_AVAILABLE_HEIGHT_PX + 0.001)
})

test('never enlarges content that is smaller than the page', () => {
  const scale = calculatePrintScale(100, 100, A4_AVAILABLE_WIDTH_PX, A4_AVAILABLE_HEIGHT_PX, 0)
  assert.equal(scale, 1)
})

test('minScale outside [0, 1] is clamped instead of trusted verbatim', () => {
  const tooHigh = calculatePrintScale(500, A4_AVAILABLE_HEIGHT_PX * 5, A4_AVAILABLE_WIDTH_PX, A4_AVAILABLE_HEIGHT_PX, 2)
  assert.equal(tooHigh, 1)
  const tooLow = calculatePrintScale(500, A4_AVAILABLE_HEIGHT_PX * 5, A4_AVAILABLE_WIDTH_PX, A4_AVAILABLE_HEIGHT_PX, -1)
  assert.ok(tooLow > 0 && tooLow < 1, `expected a real shrink-to-fit scale, got ${tooLow}`)
})
