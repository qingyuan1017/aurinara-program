// @vitest-environment jsdom

import type { CognitoUser, CognitoUserSession } from 'amazon-cognito-identity-js'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getAuthToken, setAuthToken } from './auth'
import { getCognitoUserPool, restoreSession } from './cognito'

type SessionCallback = (
  error: Error | null,
  session: CognitoUserSession | null,
) => void

describe('Cognito session restoration', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('does not clear a newer login when an old restoration fails late', async () => {
    let completeRestore: SessionCallback | undefined
    const oldUser = {
      getSession: (callback: SessionCallback) => {
        completeRestore = callback
      },
      getUsername: () => 'old-user',
    } as unknown as CognitoUser
    vi.spyOn(getCognitoUserPool(), 'getCurrentUser').mockReturnValue(oldUser)
    setAuthToken('old-token')

    const restoration = restoreSession()
    setAuthToken('new-login-token')
    completeRestore?.(new Error('old session expired'), null)

    await expect(restoration).resolves.toBeNull()
    expect(getAuthToken()).toBe('new-login-token')
  })

  it('does not overwrite a newer login when an old restoration succeeds late', async () => {
    let completeRestore: SessionCallback | undefined
    const oldUser = {
      getSession: (callback: SessionCallback) => {
        completeRestore = callback
      },
      getUsername: () => 'old-user',
    } as unknown as CognitoUser
    const oldSession = {
      isValid: () => true,
      getIdToken: () => ({
        getJwtToken: () => 'refreshed-old-token',
        decodePayload: () => ({ sub: 'old-subject' }),
      }),
    } as unknown as CognitoUserSession
    vi.spyOn(getCognitoUserPool(), 'getCurrentUser').mockReturnValue(oldUser)
    setAuthToken('old-token')

    const restoration = restoreSession()
    setAuthToken('new-login-token')
    completeRestore?.(null, oldSession)

    await expect(restoration).resolves.toMatchObject({
      username: 'old-user',
      sub: 'old-subject',
    })
    expect(getAuthToken()).toBe('new-login-token')
  })
})
