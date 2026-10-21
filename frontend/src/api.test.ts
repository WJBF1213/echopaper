import { describe, expect, it, vi } from 'vitest'
import { ApiError, api } from './api'

function mockFetch(response: Partial<Response> & { json?: () => Promise<unknown>; text?: () => Promise<string> }) {
  const full = {
    ok: response.ok ?? true,
    status: response.status ?? 200,
    headers: new Headers(
      (response as { contentType?: string }).contentType
        ? { 'content-type': (response as { contentType?: string }).contentType as string }
        : { 'content-type': 'application/json' },
    ),
    json: response.json ?? (() => Promise.resolve({})),
    text: response.text ?? (() => Promise.resolve('')),
  }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(full))
  return full
}

describe('api client', () => {
  it('throws ApiError carrying the server detail', async () => {
    mockFetch({
      ok: false,
      status: 400,
      json: () => Promise.resolve({ detail: '材料不存在' }),
    })
    await expect(api.getMaterial('missing')).rejects.toMatchObject({
      name: 'ApiError',
      status: 400,
      detail: '材料不存在',
    })
  })

  it('wraps network failures in ApiError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    const err = await api.health().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(0)
    expect((err as ApiError).detail).toContain('无法连接后端服务')
  })

  it('posts graded answers to the set attempts endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ attempt_id: 'a1', ok: 1, total: 1, results: [] }),
    })
    vi.stubGlobal('fetch', fetchMock)
    await api.submitAttempt('s1', [{ blank_id: 'b1', text: 'hello' }], 30)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/sets/s1/attempts')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({
      answers: [{ blank_id: 'b1', text: 'hello' }],
      duration_s: 30,
    })
  })

  it('sends multipart form data for material creation', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ job_id: 'j1' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    await api.createMaterial({ name: 'T1', transcript: 'hello world', mode: 'llm', blankCount: 10 })
    const body = fetchMock.mock.calls[0][1].body as FormData
    expect(body.get('name')).toBe('T1')
    expect(body.get('transcript')).toBe('hello world')
    expect(body.get('blank_count')).toBe('10')
  })

  it('builds the range-capable audio URL', () => {
    expect(api.audioUrl('m1')).toBe('/api/materials/m1/audio')
  })
})
