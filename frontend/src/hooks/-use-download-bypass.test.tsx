// @vitest-environment jsdom
//
// Download-bypass test for the Specification export path — task 11.3 (Req 11.6,
// also Req 1.4). The Specification panel's export buttons go through
// `useDownload().downloadSpecificationExport`, which must hit the SAME axios
// instance the generated hooks use so it inherits the base URL and the bearer
// request interceptor, and must request a binary body (`responseType: 'blob'`).
//
// This drives the REAL `useDownload` hook over the REAL `AXIOS_INSTANCE` with a
// custom adapter installed, so the final request config observed by the
// transport is exactly what the browser would send: the configured base URL,
// the `Authorization: Bearer …` header added by the instance interceptor, and
// `responseType: 'blob'`.
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AxiosAdapter, InternalAxiosRequestConfig } from 'axios'

import { AXIOS_INSTANCE } from '@/api/axios-instance'
import { setAuthToken, clearAuthToken } from '@/lib/auth'
import { useDownload } from '@/hooks/use-download'

// Capture the fully-resolved request config the transport receives (after the
// base URL join and the bearer-token request interceptor run).
let captured: InternalAxiosRequestConfig | null = null
const originalAdapter = AXIOS_INSTANCE.defaults.adapter

const captureAdapter: AxiosAdapter = async (config) => {
  captured = config as InternalAxiosRequestConfig
  return {
    data: new Blob(['{}'], { type: 'application/json' }),
    status: 200,
    statusText: 'OK',
    headers: { 'content-type': 'application/json' },
    config,
  }
}

// jsdom lacks object-URL plumbing used by the save path; stub it out.
beforeEach(() => {
  captured = null
  AXIOS_INSTANCE.defaults.adapter = captureAdapter
  setAuthToken('test-bearer-token')
  if (!URL.createObjectURL) {
    URL.createObjectURL = vi.fn(() => 'blob:mock')
  } else {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock')
  }
  if (!URL.revokeObjectURL) {
    URL.revokeObjectURL = vi.fn()
  } else {
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  }
})

afterEach(() => {
  AXIOS_INSTANCE.defaults.adapter = originalAdapter
  clearAuthToken()
  vi.restoreAllMocks()
})

describe('useDownload specification export bypass (Req 11.6, 1.4)', () => {
  it('requests the export through AXIOS_INSTANCE with base URL + bearer + responseType blob', async () => {
    const { result } = renderHook(() => useDownload())

    await act(async () => {
      await result.current.downloadSpecificationExport('sdtm-1', 'xlsx')
    })

    expect(captured).not.toBeNull()
    const config = captured as InternalAxiosRequestConfig
    // Binary body: the typed JSON client cannot model it, so the bypass asks
    // axios for a blob.
    expect(config.responseType).toBe('blob')
    // Hits the Specification export endpoint with the exact format param.
    expect(config.url).toBe('/api/v1/sdtms/sdtm-1/specification/export')
    expect(config.params).toEqual({ format: 'xlsx' })
    // Inherits the instance base URL (empty by default so the /api/v1 prefix is
    // not doubled) rather than hand-rolling a different origin.
    expect(config.baseURL).toBe(AXIOS_INSTANCE.defaults.baseURL)
    // Inherits the bearer-token request interceptor applied to every call.
    expect(config.headers.Authorization).toBe('Bearer test-bearer-token')
  })

  it('requests format=json for the JSON export', async () => {
    const { result } = renderHook(() => useDownload())

    await act(async () => {
      await result.current.downloadSpecificationExport('sdtm-9', 'json')
    })

    const config = captured as InternalAxiosRequestConfig
    expect(config.responseType).toBe('blob')
    expect(config.url).toBe('/api/v1/sdtms/sdtm-9/specification/export')
    expect(config.params).toEqual({ format: 'json' })
  })
})
