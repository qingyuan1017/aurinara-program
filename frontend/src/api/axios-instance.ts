import Axios, {
  type AxiosError,
  type AxiosRequestConfig,
  type AxiosResponse,
} from 'axios'
import { getAuthToken, clearAuthToken } from '@/lib/auth'

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

// Clear the stored token only when a request that ACTUALLY carried a bearer
// token is rejected with 401 — i.e. the token itself was refused (expired or
// invalid). A 401 on a request that had no Authorization header must not wipe
// the session (that would log the user out on an unauthenticated race), and a
// request error with no response (network/CORS) is left alone.
AXIOS_INSTANCE.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const hadBearer = Boolean(error.config?.headers?.Authorization)
    if (error.response?.status === 401 && hadBearer) {
      clearAuthToken()
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
