import { describe, expect, it } from 'vitest'
import { selectOidcBearerToken } from './oidc'

describe('OIDC bearer selection', () => {
  it('uses the ID token when the provider returns one', () => {
    expect(
      selectOidcBearerToken({ access_token: 'access', id_token: 'identity' }),
    ).toBe('identity')
  })

  it('supports providers whose API access token carries the audience', () => {
    expect(selectOidcBearerToken({ access_token: 'access' })).toBe('access')
  })
})
