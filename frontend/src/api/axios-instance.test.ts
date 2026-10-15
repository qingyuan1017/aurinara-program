// @vitest-environment jsdom

import {
  AxiosError,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'
import { beforeEach, describe, expect, it } from 'vitest'

import { AXIOS_INSTANCE } from './axios-instance'
import { getAuthToken, setAuthToken } from '@/lib/auth'

describe('authenticated response handling', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('ignores a late 401 sent with a superseded token', async () => {
    let rejectRequest:
      | ((reason: AxiosError) => void)
      | undefined
    let sentConfig: InternalAxiosRequestConfig | undefined
    setAuthToken('old-token')

    const request = AXIOS_INSTANCE.get('/auth-race-test', {
      adapter: (config) =>
        new Promise<AxiosResponse>((_resolve, reject) => {
          sentConfig = config
          rejectRequest = reject
        }),
    })

    await expect.poll(() => sentConfig?.headers.get('Authorization')).toBe(
      'Bearer old-token',
    )
    setAuthToken('new-token')

    const response: AxiosResponse = {
      data: {},
      status: 401,
      statusText: 'Unauthorized',
      headers: {},
      config: sentConfig!,
    }
    rejectRequest?.(
      new AxiosError(
        'Unauthorized',
        AxiosError.ERR_BAD_REQUEST,
        sentConfig,
        undefined,
        response,
      ),
    )

    await expect(request).rejects.toMatchObject({ response: { status: 401 } })
    expect(getAuthToken()).toBe('new-token')
  })
})
