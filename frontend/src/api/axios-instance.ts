import Axios, {
  type AxiosError,
  type AxiosRequestConfig,
  type AxiosResponse,
} from 'axios'
import { getAuthToken, replaceAuthTokenIfCurrent } from '@/lib/auth'

// Base URL for API requests. The Orval-generated client already includes the
// full path prefix ("/api/v1/...") in every request URL, so the base URL must
// be empty (or just the origin) to avoid doubling the prefix.
const baseURL = import.meta.env.VITE_API_BASE_URL ?? ''

export const AXIOS_INSTANCE = Axios.create({ baseURL })

// Attach the bearer token to every request when present.
AXIOS_INSTANCE.interceptors.request.use((config) => {
  const token = getAuthToken()
  if (token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Build a /login URL that preserves the current path as the `redirect` search
// param, so a server-rejected token sends the user back where they were after
// re-authenticating (login.tsx reads `redirect`). The already-on-login guard
// below prevents a redirect loop when the 401 came from the login screen.
function loginRedirectUrl(): string {
  const { pathname, search, hash } = window.location
  const next = `${pathname}${search}${hash}`
  return `/login?redirect=${encodeURIComponent(next)}`
}

// Clear the stored token and bounce to /login only when the token rejected by a
// 401 is still the current token. A response from an older request may arrive
// after Cognito has completed a newer sign-in; that stale response must not
// erase the new session. Requests without a bearer token and network/CORS
// failures are left alone. The redirect is skipped when already on /login.
AXIOS_INSTANCE.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const authorization =
      error.config?.headers?.get?.('Authorization') ??
      error.config?.headers?.Authorization
    const rejectedToken =
      typeof authorization === 'string' && authorization.startsWith('Bearer ')
        ? authorization.slice('Bearer '.length)
        : null
    if (
      error.response?.status === 401 &&
      rejectedToken &&
      replaceAuthTokenIfCurrent(rejectedToken, null)
    ) {
      if (
        typeof window !== 'undefined' &&
        window.location.pathname !== '/login'
      ) {
        window.location.assign(loginRedirectUrl())
      }
    }
    return Promise.reject(error)
  },
)

/**
 * The mutator Orval wires into every generated hook. Supports request
 * cancellation via the AbortController signal that TanStack Query provides.
 */
export const customInstance = <T>(
  config: AxiosRequestConfig,
  options?: AxiosRequestConfig,
): Promise<T> => {
  const controller = new AbortController()

  const promise = AXIOS_INSTANCE({
    ...config,
    ...options,
    signal: options?.signal ?? controller.signal,
  }).then((response: AxiosResponse<T>) => response.data)

  // Allow TanStack Query to cancel in-flight requests.
  // @ts-expect-error attach a cancel handle for the query cache.
  promise.cancel = () => {
    controller.abort()
  }

  return promise
}

export type ErrorType<Error> = AxiosError<Error>
export type BodyType<BodyData> = BodyData

export default customInstance
