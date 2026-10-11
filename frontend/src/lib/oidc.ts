import { clearAuthToken, getAuthToken, setAuthToken } from '@/lib/auth'
import type { AuthUser } from '@/lib/cognito'

const STATE_KEY = 'aurinara.oidc.state'
const VERIFIER_KEY = 'aurinara.oidc.verifier'
const RETURN_TO_KEY = 'aurinara.oidc.return_to'
const PROVIDER_KEY = 'aurinara.auth.provider'

interface TokenResponse {
  access_token: string
  id_token?: string
  token_type?: string
  expires_in?: number
}

export function selectOidcBearerToken(tokens: TokenResponse): string {
  // Cognito access tokens identify the public client with `client_id`, while
  // its ID tokens carry the API verifier's expected `aud` claim.
  return tokens.id_token || tokens.access_token
}

export function getOidcConfig() {
  return {
    authorizeUrl: import.meta.env.VITE_OIDC_AUTHORIZE_URL?.trim(),
    tokenUrl: import.meta.env.VITE_OIDC_TOKEN_URL?.trim(),
    clientId: import.meta.env.VITE_OIDC_CLIENT_ID?.trim(),
    redirectUri: import.meta.env.VITE_OIDC_REDIRECT_URI?.trim(),
    scopes: import.meta.env.VITE_OIDC_SCOPES?.trim() || 'openid profile email',
  }
}

export function isOidcConfigured(): boolean {
  const config = getOidcConfig()
  return Boolean(
    config.authorizeUrl && config.tokenUrl && config.clientId && config.redirectUri,
  )
}

function base64Url(bytes: Uint8Array): string {
  let binary = ''
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte)
  })
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function randomUrlSafe(length = 48): string {
  const bytes = new Uint8Array(length)
  crypto.getRandomValues(bytes)
  return base64Url(bytes)
}

async function challenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  return base64Url(new Uint8Array(digest))
}

export async function beginOidcLogin(returnTo = '/'): Promise<void> {
  const config = getOidcConfig()
  if (!config.authorizeUrl || !config.clientId || !config.redirectUri) {
    throw new Error('OIDC login is not configured')
  }
  const state = randomUrlSafe(32)
  const verifier = randomUrlSafe()
  sessionStorage.setItem(STATE_KEY, state)
  sessionStorage.setItem(VERIFIER_KEY, verifier)
  sessionStorage.setItem(RETURN_TO_KEY, returnTo.startsWith('/') ? returnTo : '/')
  const params = new URLSearchParams({
    response_type: 'code',
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    scope: config.scopes,
    state,
    code_challenge: await challenge(verifier),
    code_challenge_method: 'S256',
  })
  window.location.assign(`${config.authorizeUrl}?${params.toString()}`)
}

export async function completeOidcLogin(search: string): Promise<string> {
  const params = new URLSearchParams(search)
  if (params.get('error')) {
    throw new Error('The identity provider did not complete sign-in')
  }
  const code = params.get('code')
  const state = params.get('state')
  const expectedState = sessionStorage.getItem(STATE_KEY)
  const verifier = sessionStorage.getItem(VERIFIER_KEY)
  const returnTo = sessionStorage.getItem(RETURN_TO_KEY) || '/'
  sessionStorage.removeItem(STATE_KEY)
  sessionStorage.removeItem(VERIFIER_KEY)
  sessionStorage.removeItem(RETURN_TO_KEY)
  if (!code || !state || state !== expectedState || !verifier) {
    throw new Error('The OIDC callback state is invalid')
  }
  const config = getOidcConfig()
  if (!config.tokenUrl || !config.clientId || !config.redirectUri) {
    throw new Error('OIDC token exchange is not configured')
  }
  const response = await fetch(config.tokenUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: config.clientId,
      redirect_uri: config.redirectUri,
      code,
      code_verifier: verifier,
    }),
  })
  if (!response.ok) throw new Error('OIDC token exchange failed')
  const tokens = (await response.json()) as TokenResponse
  if (!tokens.access_token) throw new Error('OIDC response did not include an access token')
  setAuthToken(selectOidcBearerToken(tokens))
  localStorage.setItem(PROVIDER_KEY, 'oidc')
  return returnTo
}

function decodePayload(token: string): Record<string, unknown> | null {
  try {
    const encoded = token.split('.')[1]
    if (!encoded) return null
    const normalized = encoded.replace(/-/g, '+').replace(/_/g, '/')
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=')
    return JSON.parse(atob(padded)) as Record<string, unknown>
  } catch {
    return null
  }
}

export function restoreOidcSession(): AuthUser | null {
  if (localStorage.getItem(PROVIDER_KEY) !== 'oidc') return null
  const token = getAuthToken()
  const claims = token ? decodePayload(token) : null
  const expiresAt = typeof claims?.exp === 'number' ? claims.exp * 1000 : 0
  if (!claims || expiresAt <= Date.now() || typeof claims.sub !== 'string') {
    clearOidcSession()
    return null
  }
  return {
    username:
      typeof claims.preferred_username === 'string'
        ? claims.preferred_username
        : claims.sub,
    email: typeof claims.email === 'string' ? claims.email : undefined,
    sub: claims.sub,
  }
}

export function clearOidcSession(): void {
  localStorage.removeItem(PROVIDER_KEY)
  clearAuthToken()
}
