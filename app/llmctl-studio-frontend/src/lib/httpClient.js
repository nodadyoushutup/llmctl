import { resolveApiUrl } from '../config/runtime'

export class HttpError extends Error {
  constructor(message, { status, body, url }) {
    super(message)
    this.name = 'HttpError'
    this.status = status
    this.body = body
    this.url = url
    this.isAuthError = status === 401 || status === 403
  }
}

async function parseResponseBody(response) {
  if (response.status === 204) {
    return null
  }
  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    return response.json()
  }
  const text = await response.text()
  return text || null
}

function toRequestBody(body, headers) {
  if (body == null) {
    return null
  }
  if (body instanceof FormData) {
    return body
  }
  headers.set('Content-Type', 'application/json')
  return JSON.stringify(body)
}

export async function requestJson(endpoint, options = {}) {
  const { method = 'GET', headers: inputHeaders = {}, body, signal } = options
  const headers = new Headers(inputHeaders)
  headers.set('Accept', 'application/json')
  const url = resolveApiUrl(endpoint)

  let response
  try {
    response = await fetch(url, {
      method,
      credentials: 'include',
      headers,
      body: toRequestBody(body, headers),
      signal,
    })
  } catch (error) {
    throw new HttpError(error instanceof Error ? error.message : 'Network request failed.', {
      status: 0,
      body: null,
      url,
    })
  }

  const payload = await parseResponseBody(response)
  if (!response.ok) {
    const message =
      (payload && typeof payload === 'object' && 'error' in payload && String(payload.error)) ||
      `Request failed with status ${response.status}`
    throw new HttpError(message, {
      status: response.status,
      body: payload,
      url,
    })
  }

  return payload
}
