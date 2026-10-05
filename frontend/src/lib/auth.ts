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
  } catch {
    // ignore storage failures (private mode, etc.)
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

export function isAuthenticated(): boolean {
  return getAuthToken() !== null
}

export function onAuthChange(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
