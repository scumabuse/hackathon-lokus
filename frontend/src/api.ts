/** Typed wrappers for fetch and EventSource (SPEC Section 13). */

import type { Profile, SearchResponse, UniversityHeader, Description, Photo, Stats, Warning } from './types'

const BASE = ''

export async function searchUniversities(q: string): Promise<SearchResponse> {
  const r = await fetch(`${BASE}/api/search?q=${encodeURIComponent(q)}`)
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err?.error?.message ?? `HTTP ${r.status}`)
  }
  return r.json()
}

export async function getProfile(qid: string, refresh = false): Promise<Profile> {
  const url = `${BASE}/api/profile/${qid}${refresh ? '?refresh=1' : ''}`
  const r = await fetch(url)
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err?.error?.message ?? `HTTP ${r.status}`)
  }
  return r.json()
}

export type SSECallbacks = {
  onHeader?: (h: UniversityHeader) => void
  onDescription?: (d: Description) => void
  onPhotos?: (batch: number, photos: Photo[]) => void
  onWarning?: (w: Warning) => void
  onStats?: (s: Stats) => void
  onDone?: (total_ms: number, cached: boolean) => void
  onError?: (code: string, message: string) => void
}

export function openStream(qid: string, refresh: boolean, callbacks: SSECallbacks): EventSource {
  const url = `${BASE}/api/profile/${qid}/stream${refresh ? '?refresh=1' : ''}`
  const es = new EventSource(url)

  const handle = (event: MessageEvent, name: string) => {
    try {
      const data = JSON.parse(event.data)
      if (name === 'header') callbacks.onHeader?.(data)
      else if (name === 'description') callbacks.onDescription?.(data)
      else if (name === 'photos') callbacks.onPhotos?.(data.batch, data.photos)
      else if (name === 'warning') callbacks.onWarning?.(data)
      else if (name === 'stats') callbacks.onStats?.(data)
      else if (name === 'done') callbacks.onDone?.(data.total_ms, data.cached)
      else if (name === 'error') callbacks.onError?.(data.code, data.message)
    } catch {
      // malformed JSON — ignore
    }
  }

  for (const evt of ['header', 'description', 'photos', 'warning', 'stats', 'done', 'error']) {
    es.addEventListener(evt, (e) => handle(e as MessageEvent, evt))
  }

  return es
}
