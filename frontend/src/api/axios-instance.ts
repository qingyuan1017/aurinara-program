import Axios, {
  type AxiosError,
  type AxiosRequestConfig,
  type AxiosResponse,
} from 'axios'
import { getAuthToken, clearAuthToken } from '@/lib/auth'

// Base URL the app calls. In dev, Vite proxies "/api" to the backend, so the
// default relative prefix works everywhere.
const baseURL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

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

// Clear the token on 401 so the app can route back to sign-in.
AXIOS_INSTANCE.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
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
