import { describe, expect, it } from 'vitest'

import {
  DEFAULT_PREVIEW_LIMIT,
  MAX_PREVIEW_LIMIT,
  MIN_PREVIEW_LIMIT,
  clampLimit,
  clampOffset,
} from './preview-panel'

/**
 * Unit tests for the preview clamping helpers (Task 7.3).
 *
 * These pure functions bound the preview window BEFORE a request is sent so the
 * client never asks for an out-of-range page (Requirements 5.2, 5.3). The same
 * 1-200 limit window is the shared semantics relied on by the SDTM derivation
 * preview (Requirement 13.2); no separate SDTM-side clamp helper exists, so
 * these helpers cover that requirement.
 */
describe('clampLimit', () => {
  it('clamps a value below the floor up to MIN_PREVIEW_LIMIT (0 -> 1)', () => {
    // Requirement 5.3: below 1 -> 1.
    expect(clampLimit(0)).toBe(MIN_PREVIEW_LIMIT)
    expect(clampLimit(0)).toBe(1)
  })

  it('passes the floor boundary through unchanged (1 -> 1)', () => {
    expect(clampLimit(1)).toBe(1)
  })

  it('passes the ceiling boundary through unchanged (200 -> 200)', () => {
    expect(clampLimit(200)).toBe(200)
  })

  it('clamps a value above the ceiling down to MAX_PREVIEW_LIMIT (201 -> 200)', () => {
    // Requirement 5.3: above 200 -> 200.
    expect(clampLimit(201)).toBe(MAX_PREVIEW_LIMIT)
    expect(clampLimit(201)).toBe(200)
  })

  it('falls back to the default for NaN/undefined inputs', () => {
    // Partial/invalid typing must not fire an out-of-range request; the default
    // page size is used instead.
    expect(clampLimit(Number.NaN)).toBe(DEFAULT_PREVIEW_LIMIT)
    expect(clampLimit(undefined)).toBe(DEFAULT_PREVIEW_LIMIT)
  })
})

describe('clampOffset', () => {
  it('clamps a negative value up to 0 (-1 -> 0)', () => {
    // Requirement 5.2: negative offset -> 0.
    expect(clampOffset(-1)).toBe(0)
  })

  it('passes a zero offset through unchanged (0 -> 0)', () => {
    expect(clampOffset(0)).toBe(0)
  })

  it('falls back to 0 for NaN/undefined inputs', () => {
    expect(clampOffset(Number.NaN)).toBe(0)
    expect(clampOffset(undefined)).toBe(0)
  })
})
