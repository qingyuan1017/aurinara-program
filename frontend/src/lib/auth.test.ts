// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  clearAuthToken,
  getAuthToken,
  replaceAuthTokenIfCurrent,
  setAuthToken,
} from './auth'

describe('auth token storage', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('does not let a stale operation clear a newer session', () => {
    setAuthToken('new-token')

    expect(replaceAuthTokenIfCurrent('old-token', null)).toBe(false)
    expect(getAuthToken()).toBe('new-token')
  })

  it('clears the session when the rejected token is still current', () => {
    setAuthToken('rejected-token')

    expect(replaceAuthTokenIfCurrent('rejected-token', null)).toBe(true)
    expect(getAuthToken()).toBeNull()
  })

  it('does not let stale restoration overwrite a newer session', () => {
    clearAuthToken()
    const tokenAtRestoreStart = getAuthToken()
    setAuthToken('interactive-login-token')

    expect(
      replaceAuthTokenIfCurrent(tokenAtRestoreStart, 'restored-old-token'),
    ).toBe(false)
    expect(getAuthToken()).toBe('interactive-login-token')
  })

  it('surfaces storage failures instead of reporting a successful login', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Storage disabled', 'SecurityError')
    })

    expect(() => setAuthToken('token')).toThrow(
      'The browser could not save the sign-in session.',
    )
  })
})
