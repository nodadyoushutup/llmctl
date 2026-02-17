import { beforeEach, describe, expect, test, vi } from 'vitest'
import { HttpError, requestJson } from './httpClient'

describe('requestJson', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  test('sends credentials and accept header for api requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const payload = await requestJson('/health')

    expect(payload).toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/health')
    expect(options.credentials).toBe('include')
    expect(options.method).toBe('GET')
    expect(options.headers.get('Accept')).toBe('application/json')
  })

  test('serializes json body and sets content type on write requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await requestJson('/chat/threads/1/config', {
      method: 'POST',
      body: { model_id: 3 },
    })

    const [, options] = fetchMock.mock.calls[0]
    expect(options.headers.get('Content-Type')).toBe('application/json')
    expect(options.body).toBe(JSON.stringify({ model_id: 3 }))
  })

  test('raises auth-aware HttpError on 401 responses', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: 'Unauthorized' }), {
        status: 401,
        headers: { 'content-type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(requestJson('/chat/activity')).rejects.toMatchObject({
      name: 'HttpError',
      status: 401,
      isAuthError: true,
      message: 'Unauthorized',
    })
  })

  test('wraps network failures in HttpError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))

    let error
    try {
      await requestJson('/health')
    } catch (caught) {
      error = caught
    }

    expect(error).toBeInstanceOf(HttpError)
    expect(error.status).toBe(0)
    expect(error.message).toBe('offline')
    expect(error.url).toBe('/api/health')
  })
})
