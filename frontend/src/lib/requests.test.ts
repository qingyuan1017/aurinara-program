// @vitest-environment jsdom
//
// `useIdempotencyKey` renders a React hook, so this file runs under jsdom. The
// pure header helpers below work in any environment; keeping them here matches
// the task's single "request header helpers" suite.
import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { idempotentRequest, ifMatchRequest, useIdempotencyKey } from './requests'

/**
 * A syntactically valid RFC 4122 UUID (any version). `crypto.randomUUID()`
 * emits a v4 UUID, but the assertion only cares that the key is a well-formed
 * UUID string, not that a specific version nibble is present.
 */
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

describe('ifMatchRequest', () => {
  it('emits the exact If-Match header for the given revision', () => {
    // The backend ETag is deterministically `"revision-{N}"` (embedded quotes
    // included), so the emitted header must match byte-for-byte.
    expect(ifMatchRequest(0).headers).toMatchObject({
      'If-Match': '"revision-0"',
    })
    expect(ifMatchRequest(7).headers).toMatchObject({
      'If-Match': '"revision-7"',
    })
    expect(ifMatchRequest(42).headers?.['If-Match']).toBe('"revision-42"')
  })

  it('retains Content-Type: application/json (Requirement 21.1)', () => {
    // The mutator REPLACES the generated headers with the injected object, so a
    // helper that forgot Content-Type would silently drop the JSON body type.
    expect(ifMatchRequest(1).headers).toMatchObject({
      'Content-Type': 'application/json',
      'If-Match': '"revision-1"',
    })
  })
})

describe('idempotentRequest', () => {
  it('emits a syntactically valid UUID Idempotency-Key', () => {
    const key = idempotentRequest().headers?.['Idempotency-Key']
    expect(typeof key).toBe('string')
    expect(key).toMatch(UUID_RE)
  })

  it('uses a supplied stable key verbatim', () => {
    const stable = '11111111-2222-4333-8444-555555555555'
    expect(idempotentRequest(stable).headers?.['Idempotency-Key']).toBe(stable)
  })

  it('retains Content-Type: application/json', () => {
    expect(idempotentRequest().headers).toMatchObject({
      'Content-Type': 'application/json',
    })
  })

  it('mints a fresh UUID on each no-argument call', () => {
    // Documents why callers inside a render must NOT call this inline per
    // render: a bare call is a one-shot and would differ across retries.
    const first = idempotentRequest().headers?.['Idempotency-Key']
    const second = idempotentRequest().headers?.['Idempotency-Key']
    expect(first).not.toBe(second)
  })
})

describe('useIdempotencyKey', () => {
  it('emits a syntactically valid UUID key and config', () => {
    const { result } = renderHook(() => useIdempotencyKey())
    expect(result.current.key).toMatch(UUID_RE)
    expect(result.current.requestConfig.headers).toMatchObject({
      'Content-Type': 'application/json',
      'Idempotency-Key': result.current.key,
    })
  })

  it('keeps the key identical across simulated retries of one attempt', () => {
    // Re-rendering stands in for the automatic retries of a single operation
    // attempt: the ref-held key must survive every render unchanged.
    const { result, rerender } = renderHook(() => useIdempotencyKey())
    const attemptKey = result.current.key

    rerender()
    rerender()
    rerender()

    expect(result.current.key).toBe(attemptKey)
    // The emitted header value is likewise stable across the attempt's retries.
    expect(result.current.requestConfig.headers?.['Idempotency-Key']).toBe(
      attemptKey,
    )
  })

  it('mints a distinct key for a new attempt started with begin()', () => {
    const { result, rerender } = renderHook(() => useIdempotencyKey())
    const firstAttempt = result.current.key

    // `begin()` returns the fresh key directly for the imperative caller; a
    // component then observes it via the hook's next render (modelled here by
    // the explicit rerender).
    let secondAttempt = ''
    act(() => {
      secondAttempt = result.current.begin()
    })
    rerender()

    expect(secondAttempt).toMatch(UUID_RE)
    expect(secondAttempt).not.toBe(firstAttempt)
    expect(result.current.key).toBe(secondAttempt)
    expect(result.current.requestConfig.headers?.['Idempotency-Key']).toBe(
      secondAttempt,
    )
  })

  it('mints a distinct key after reset() for the next attempt', () => {
    const { result, rerender } = renderHook(() => useIdempotencyKey())
    const firstAttempt = result.current.key

    act(() => {
      result.current.reset()
    })
    // After reset the next render lazily mints a fresh key for a new attempt.
    rerender()

    expect(result.current.key).toMatch(UUID_RE)
    expect(result.current.key).not.toBe(firstAttempt)
  })
})
