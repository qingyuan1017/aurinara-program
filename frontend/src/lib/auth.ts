// Minimal token storage for the externally issued JWT the backend expects as a
// bearer token. Release 1 relies on an external identity provider (Cognito in
// production, the dev JWT issuer locally), so the frontend only stores and
// attaches the token — it does not mint or verify it.

const TOKEN_KEY = 'aurinara.auth.token'

type Listener = (token: string | null) => void
const listeners = new Set<Listener>()

export function getAuthToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setAuthToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch (error) {
    // A sign-in is not complete unless the route guard can read the token back.
    // Surface storage failures to the login screen instead of reporting success
    // and immediately redirecting the user back to /login.
    throw new Error('The browser could not save the sign-in session.', {
      cause: error,
    })
  }
  listeners.forEach((listener) => listener(token))
}

export function clearAuthToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    // ignore
  }
  listeners.forEach((listener) => listener(null))
}

/**
 * Replace the token only if no newer authentication operation changed it.
 *
 * Cognito restoration and API requests are asynchronous. Their callbacks can
 * arrive after a new sign-in has stored a different token; those stale
 * callbacks must never overwrite or clear the newer session.
 */
export function replaceAuthTokenIfCurrent(
  expectedToken: string | null,
  replacementToken: string | null,
): boolean {
  if (getAuthToken() !== expectedToken) return false

  if (replacementToken === null) clearAuthToken()
  else setAuthToken(replacementToken)
  return true
}

export function isAuthenticated(): boolean {
  return getAuthToken() !== null
}

export function onAuthChange(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
