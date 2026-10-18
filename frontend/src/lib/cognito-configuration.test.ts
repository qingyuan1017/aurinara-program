// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'

describe('Cognito fallback configuration', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it('does not crash module initialization when production uses managed OIDC', async () => {
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', '')
    vi.stubEnv('VITE_COGNITO_CLIENT_ID', '')
    vi.resetModules()

    const cognito = await import('./cognito')

    expect(cognito.getCognitoUserPool).toThrowError(
      /Direct Cognito login is not configured/,
    )
  })
})
