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

  it('sends multipart form data for material creation (transcription only)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ job_id: 'j1' }),
    })
    vi.stubGlobal('fetch', fetchMock)
    await api.createMaterial({ name: 'T1', transcript: 'hello world' })
    const body = fetchMock.mock.calls[0][1].body as FormData
    expect(body.get('name')).toBe('T1')
    expect(body.get('transcript')).toBe('hello world')
    // Import is transcription-only: no question-mode or blank-count fields.
    expect(body.get('mode')).toBeNull()
    expect(body.get('blank_count')).toBeNull()
  })

  it('sends batch imports without generation options', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ batch_id: 'b1', jobs: [] }),
    })
    vi.stubGlobal('fetch', fetchMock)
    await api.createMaterialsBatch({
      files: [new File(['a'], 'one.mp3', { type: 'audio/mpeg' })],
    })
    const body = fetchMock.mock.calls[0][1].body as FormData
    expect(body.getAll('audios')).toHaveLength(1)
    expect(body.get('mode')).toBeNull()
    expect(body.get('blank_count')).toBeNull()
    expect(body.get('generate_sets')).toBeNull()
  })

  it('builds the range-capable audio URL', () => {
    expect(api.audioUrl('m1')).toBe('/api/materials/m1/audio')
  })

  it('posts the blocks contract to the exam endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ paper: { groups: [] }, skipped: [] }),
    })
    vi.stubGlobal('fetch', fetchMock)
    await api.generateExam(
      'm1',
      [
        { type: 'completion', count: 10 },
        { type: 'mcq_single', count: 5 },
      ],
      { layoutHint: 'table', regenerate: true },
    )
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/materials/m1/exam')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({
      blocks: [
        { type: 'completion', count: 10 },
        { type: 'mcq_single', count: 5 },
      ],
      layout_hint: 'table',
      regenerate: true,
    })
  })

  it('omits layout_hint when no hint is given', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ paper: { groups: [] }, skipped: [] }),
    })
    vi.stubGlobal('fetch', fetchMock)
    await api.generateExam('m1', [{ type: 'matching', count: 5 }])
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      blocks: [{ type: 'matching', count: 5 }],
      layout_hint: null,
      regenerate: false,
    })
  })

  it('carries the structured skipped body of an all-refused 400', async () => {
    const skipped = [{ type: 'map_labelling', reason: '转写无空间方位描述' }]
    mockFetch({
      ok: false,
      status: 400,
      json: () => Promise.resolve({ detail: { skipped } }),
    })
    const err = await api
      .generateExam('m1', [{ type: 'map_labelling', count: 5 }])
      .catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    const apiErr = err as ApiError
    expect(apiErr.status).toBe(400)
    expect(apiErr.data).toEqual({ skipped })
  })
})
