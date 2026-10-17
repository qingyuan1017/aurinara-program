import {
  UserManager,
  WebStorageStateStore,
  type User,
  type UserManagerSettings,
} from 'oidc-client-ts'
import { clearAuthToken, setAuthToken } from '@/lib/auth'
import type { AuthUser } from '@/lib/cognito'

interface TokenResponse {
  access_token: string
  id_token?: string
}

export function selectOidcBearerToken(tokens: TokenResponse): string {
  // Cognito ID tokens carry the SPA client's `aud` claim expected by the API.
  return tokens.id_token || tokens.access_token
}

export function getOidcConfig() {
  return {
    authority: import.meta.env.VITE_OIDC_AUTHORITY?.trim(),
    clientId: import.meta.env.VITE_OIDC_CLIENT_ID?.trim(),
    redirectUri: import.meta.env.VITE_OIDC_REDIRECT_URI?.trim(),
    logoutUri: import.meta.env.VITE_OIDC_LOGOUT_URI?.trim(),
    endSessionEndpoint: import.meta.env.VITE_OIDC_END_SESSION_ENDPOINT?.trim(),
    scopes: import.meta.env.VITE_OIDC_SCOPES?.trim() || 'openid profile email',
  }
}

export function isOidcConfigured(): boolean {
  const config = getOidcConfig()
  return Boolean(
    config.authority &&
      config.clientId &&
      config.redirectUri &&
      config.logoutUri &&
      config.endSessionEndpoint,
  )
}

let manager: UserManager | undefined

function getManager(): UserManager {
  if (manager) return manager
  const config = getOidcConfig()
  if (
    !config.authority ||
    !config.clientId ||
    !config.redirectUri ||
    !config.logoutUri ||
    !config.endSessionEndpoint
  ) {
    throw new Error('OIDC login is not configured')
  }
  const settings: UserManagerSettings = {
    authority: config.authority,
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    post_logout_redirect_uri: config.logoutUri,
    response_type: 'code',
    scope: config.scopes,
    automaticSilentRenew: true,
    monitorSession: false,
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
  }
  manager = new UserManager(settings)
  manager.events.addUserLoaded(storeBearerToken)
  manager.events.addUserUnloaded(clearAuthToken)
  manager.events.addAccessTokenExpired(clearAuthToken)
  return manager
}

function storeBearerToken(user: User): void {
  setAuthToken(selectOidcBearerToken(user))
}

function toAuthUser(user: User): AuthUser {
  return {
    username:
      typeof user.profile.preferred_username === 'string'
        ? user.profile.preferred_username
        : user.profile.sub,
    email: typeof user.profile.email === 'string' ? user.profile.email : undefined,
    sub: user.profile.sub,
  }
}

export async function beginOidcLogin(returnTo = '/'): Promise<void> {
  await getManager().signinRedirect({
    state: { returnTo: returnTo.startsWith('/') ? returnTo : '/' },
  })
}

export async function completeOidcLogin(_search: string): Promise<string> {
  const user = await getManager().signinRedirectCallback()
  storeBearerToken(user)
  const state = user.state as { returnTo?: unknown } | undefined
  return typeof state?.returnTo === 'string' && state.returnTo.startsWith('/')
    ? state.returnTo
    : '/'
}

export async function restoreOidcSession(): Promise<AuthUser | null> {
  if (!isOidcConfigured()) return null
  const user = await getManager().getUser()
  if (!user || user.expired) {
    clearAuthToken()
    return null
  }
  storeBearerToken(user)
  return toAuthUser(user)
}

export async function clearOidcSession(): Promise<void> {
  clearAuthToken()
  const oidc = getManager()
  const user = await oidc.getUser()
  await oidc.removeUser()
  const config = getOidcConfig()
  if (user && config.endSessionEndpoint && config.clientId && config.logoutUri) {
    const query = new URLSearchParams({
      client_id: config.clientId,
      logout_uri: config.logoutUri,
    })
    window.location.assign(`${config.endSessionEndpoint}?${query}`)
  }
}
