import { useCallback, useRef } from 'react'
import type { AxiosRequestConfig } from 'axios'

/**
 * Header helpers — the ONLY place header strings for mutations are built.
 *
 * The mutator (`src/api/axios-instance.ts`) shallow-spreads `{ ...config,
 * ...options }`, so an injected `headers` object REPLACES the generated
 * `{ 'Content-Type': 'application/json' }`. Every helper therefore re-emits
 * `Content-Type: application/json` so JSON bodies keep their content type.
 */

const JSON_CT = { 'Content-Type': 'application/json' } as const

/**
 * If-Match for a conditional write, derived from the entity revision. The
 * backend ETag is deterministically the string `"revision-{N}"` (embedded
 * double-quotes included) and is compared with `hmac.compare_digest`.
 *
 * Retains `Content-Type` (Requirement 21.1).
 */
export function ifMatchRequest(revision: number): AxiosRequestConfig {
  return { headers: { ...JSON_CT, 'If-Match': `"revision-${revision}"` } }
}

/**
 * Idempotency-Key for an operation-creating POST (bulk import, build, compile,
 * execution, reconciliation).
 *
 * The key MUST be identical across the automatic retries of a single operation
 * attempt (Requirement 21.2). Because this function returns a NEW config each
 * call, callers that live inside a React render MUST NOT call it inline per
 * render (that would mint a fresh UUID every render/retry). Instead:
 *
 * - In a component/hook, use {@link useIdempotencyKey}, which holds the key in
 *   a ref so it is generated once per attempt and stays stable across retries.
 * - When you already hold a stable key (e.g. from that ref), pass it in so the
 *   emitted header is deterministic for the attempt.
 *
 * Retains `Content-Type`.
 *
 * @param key - A stable idempotency key for the current operation attempt. When
 *   omitted a fresh UUID is generated (suitable only for a one-shot call that is
 *   not re-invoked across retries).
 */
export function idempotentRequest(key: string = crypto.randomUUID()): AxiosRequestConfig {
  return { headers: { ...JSON_CT, 'Idempotency-Key': key } }
}

/** Plain JSON create: no conditional/idempotency header, but keep Content-Type. */
export function jsonRequest(): AxiosRequestConfig {
  return { headers: { ...JSON_CT } }
}

/**
 * Holds a single `Idempotency-Key` stable across the automatic retries of one
 * operation attempt (Requirement 21.2).
 *
 * The key is generated once per attempt (lazily on first access, or explicitly
 * via {@link IdempotencyKeyHandle.begin}) and stored in a ref, so repeated
 * renders and automatic retries of the same attempt reuse the identical value.
 * Start a NEW attempt by calling `begin()` (or `reset()` then reading the
 * config again), which mints a fresh UUID for the next operation.
 */
export interface IdempotencyKeyHandle {
  /** The stable key for the current attempt. */
  key: string
  /**
   * Per-call axios config carrying the stable `Idempotency-Key` (and
   * `Content-Type`) for the current attempt. Stable identity across renders
   * is NOT guaranteed; the header VALUE is stable within an attempt.
   */
  requestConfig: AxiosRequestConfig
  /**
   * Mint a fresh key for a new operation attempt and return it. Call this when
   * the user initiates the operation so retries of that attempt reuse the key.
   */
  begin: () => string
  /** Drop the current key so the next access/`begin()` mints a fresh one. */
  reset: () => void
}

export function useIdempotencyKey(): IdempotencyKeyHandle {
  const keyRef = useRef<string | null>(null)

  if (keyRef.current === null) {
    keyRef.current = crypto.randomUUID()
  }

  const begin = useCallback(() => {
    const next = crypto.randomUUID()
    keyRef.current = next
    return next
  }, [])

  const reset = useCallback(() => {
    keyRef.current = null
  }, [])

  const key = keyRef.current
  return {
    key,
    requestConfig: idempotentRequest(key),
    begin,
    reset,
  }
}
