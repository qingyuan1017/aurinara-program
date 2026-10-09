import { describe, expect, it } from 'vitest'

import { type RectInput, validateRect } from './acrf-panel'

/**
 * Unit tests for the pure rectangle-bounds validation helper (Task 15.2).
 *
 * `validateRect` gates aCRF annotation creation BEFORE any request is issued so
 * an out-of-range rectangle never reaches the backend, and it names the single
 * offending field for the UI (Requirement 17.3). The checks run in a stable
 * order — `page` first, then `x`/`y`/`width`/`height` within the inclusive
 * `0..1` range, then the `x + width <= 1` / `y + height <= 1` overflow guards —
 * so the first offending field is reported deterministically.
 */

/** A fully in-range rectangle used as the baseline for single-field mutations. */
const VALID: RectInput = { x: 0.1, y: 0.1, width: 0.2, height: 0.2, page: 1 }

describe('validateRect — accepts in-range rectangles', () => {
  it('returns null for a typical in-range rectangle', () => {
    expect(validateRect(VALID)).toBeNull()
  })

  it('accepts the inclusive boundary values (0 and 1)', () => {
    // Zero origin with full-page extent sits exactly on x+width == 1 and
    // y+height == 1, which the overflow guards permit (<= 1, not < 1).
    expect(validateRect({ x: 0, y: 0, width: 1, height: 1, page: 1 })).toBeNull()
  })

  it('accepts a zero-area rectangle at the origin', () => {
    expect(validateRect({ x: 0, y: 0, width: 0, height: 0, page: 1 })).toBeNull()
  })

  it('accepts a large page number', () => {
    expect(validateRect({ ...VALID, page: 9999 })).toBeNull()
  })
})

describe('validateRect — rejects each out-of-range unit field', () => {
  it.each<[keyof RectInput, number]>([
    ['x', -0.1],
    ['x', 1.1],
    ['y', -0.1],
    ['y', 1.1],
    ['width', -0.1],
    ['width', 1.1],
    ['height', -0.1],
    ['height', 1.1],
  ])('reports %s when %s is out of the 0..1 range (value %s)', (field, value) => {
    const result = validateRect({ ...VALID, [field]: value })
    expect(result).not.toBeNull()
    expect(result?.field).toBe(field)
    expect(result?.message).toBeTruthy()
  })

  it('reports the field when a unit value is not finite (NaN)', () => {
    const result = validateRect({ ...VALID, width: Number.NaN })
    expect(result?.field).toBe('width')
  })
})

describe('validateRect — rejects page < 1 and non-integer pages', () => {
  it('reports page for page below 1 (0)', () => {
    const result = validateRect({ ...VALID, page: 0 })
    expect(result?.field).toBe('page')
    expect(result?.message).toBeTruthy()
  })

  it('reports page for a negative page', () => {
    expect(validateRect({ ...VALID, page: -3 })?.field).toBe('page')
  })

  it('reports page for a non-integer page', () => {
    expect(validateRect({ ...VALID, page: 1.5 })?.field).toBe('page')
  })

  it('reports page before any unit-field check (page takes precedence)', () => {
    // page is validated first, so an also-invalid width is not reported.
    const result = validateRect({ ...VALID, page: 0, width: 5 })
    expect(result?.field).toBe('page')
  })
})

describe('validateRect — rejects page overflow (x + width > 1, y + height > 1)', () => {
  it('reports width when x + width exceeds 1', () => {
    // Requirement 17.3: horizontal overflow is attributed to width.
    const result = validateRect({ ...VALID, x: 0.6, width: 0.6 })
    expect(result?.field).toBe('width')
    expect(result?.message).toContain('x + width')
  })

  it('reports height when y + height exceeds 1', () => {
    // Requirement 17.3: vertical overflow is attributed to height.
    const result = validateRect({ ...VALID, y: 0.6, height: 0.6 })
    expect(result?.field).toBe('height')
    expect(result?.message).toContain('y + height')
  })

  it('reports width before height when both overflow (stable order)', () => {
    const result = validateRect({ x: 0.6, y: 0.6, width: 0.6, height: 0.6, page: 1 })
    expect(result?.field).toBe('width')
  })
})
