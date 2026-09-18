import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { AnimatePresence, LayoutGroup } from 'motion/react'
import { getProfile, openStream, type SSECallbacks } from '../api'
import type { Description, Photo, Stats, UniversityHeader, Warning } from '../types'
import { CATEGORY_LABELS, t, type Lang } from '../i18n'
import ProgressLine, { type ProfilePhase } from '../components/ProgressLine'
import Masthead from '../components/Masthead'
import StatusLine from '../components/StatusLine'
import Notices from '../components/Notices'
import Lead from '../components/Lead'
import StatsSentence from '../components/StatsSentence'
import CategoryNav, { type NavKey } from '../components/CategoryNav'
import PhotoGrid, { type Arrival } from '../components/PhotoGrid'
import Lightbox from '../components/Lightbox'
import MapSection from '../components/MapSection'
import ErrorState from '../components/ErrorState'

declare global {
  interface Window {
    __vcTimings?: Record<string, number>
  }
}

const VERIFICATION_ORDER: Record<string, number> = { verified: 0, likely: 1, unverified: 2 }

interface Props {
  lang: Lang
  onToggleLang: () => void
}

export default function ProfilePage({ lang, onToggleLang }: Props) {
  const { qid } = useParams<{ qid: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const refresh = searchParams.get('refresh') === '1'

  // --- data (the EventSource/state logic below is kept from the previous version)
  const [header, setHeader] = useState<UniversityHeader | null>(null)
  const [description, setDescription] = useState<Description | null>(null)
  const [photos, setPhotos] = useState<Photo[]>([])
  const [warnings, setWarnings] = useState<Warning[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [phase, setPhase] = useState<ProfilePhase>('connecting')
  const [error, setError] = useState<string | null>(null)
  const [totalMs, setTotalMs] = useState<number | null>(null)
  const [cachedAt, setCachedAt] = useState<string | null>(null)
  const [elapsedMs, setElapsedMs] = useState(0)
  const [run, setRun] = useState(0)
  const arrivals = useRef<Map<string, Arrival>>(new Map())
  const startedAt = useRef(0)

  // --- view state
  const [active, setActive] = useState<NavKey>('all')
  const [showUnverified, setShowUnverified] = useState(false)
  const [popoverId, setPopoverId] = useState<string | null>(null)
  const [lightbox, setLightbox] = useState<number | null>(null)
  const lightboxReturn = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!qid) return
    setHeader(null)
    setDescription(null)
    setPhotos([])
    setWarnings([])
    setStats(null)
    setPhase('connecting')
    setError(null)
    setTotalMs(null)
    setCachedAt(null)
    setElapsedMs(0)
    setActive('all')
    setShowUnverified(false)
    setPopoverId(null)
    setLightbox(null)
    arrivals.current = new Map()
    startedAt.current = performance.now()
    window.__vcTimings = {}
    const mark = (key: string) => {
      if (window.__vcTimings && !(key in window.__vcTimings)) {
        window.__vcTimings[key] = Math.round(performance.now() - startedAt.current)
      }
    }

    let es: EventSource | null = null
    let gotHeader = false

    const callbacks: SSECallbacks = {
      onHeader: (h) => {
        gotHeader = true
        mark('header')
        setHeader(h)
        setPhase((p) => (p === 'connecting' ? 'searching' : p))
      },
      onDescription: (d) => setDescription(d),
      onPhotos: (batch, newPhotos) => {
        mark('firstPhotos')
        const at = Date.now()
        newPhotos.forEach((p, index) => {
          if (!arrivals.current.has(p.id)) arrivals.current.set(p.id, { batch, index, at })
        })
        setPhotos((prev) => {
          const map = new Map(prev.map((p) => [p.id, p]))
          newPhotos.forEach((p) => map.set(p.id, p))
          return Array.from(map.values())
        })
        setPhase((p) => (p === 'done' || p === 'error' ? p : 'verifying'))
      },
      onWarning: (w) => setWarnings((prev) => [...prev, w]),
      onStats: (s) => {
        setStats(s)
        setPhase((p) => (p === 'done' || p === 'error' ? p : 'sorting'))
      },
      onDone: (total, cached) => {
        mark('done')
        setTotalMs(total)
        setPhase('done')
        if (cached) setCachedAt((prev) => prev ?? new Date().toISOString())
        es?.close()
      },
      onError: (_code, message) => {
        setError(message)
        setPhase('error')
        es?.close()
      },
    }

    try {
      es = openStream(qid, refresh, callbacks)
      es.onerror = async () => {
        // Only fall back to the blocking endpoint if the header never arrived (Section 13).
        if (gotHeader || !es) return
        es.close()
        es = null
        try {
          const profile = await getProfile(qid, refresh)
          mark('header')
          setHeader(profile.header)
          if (profile.description) setDescription(profile.description)
          const at = Date.now()
          profile.photos.forEach((p, index) => arrivals.current.set(p.id, { batch: 0, index, at }))
          setPhotos(profile.photos)
          setStats(profile.stats)
          setWarnings(profile.warnings)
          setTotalMs(profile.stats.total_ms)
          if (profile.header.cached && profile.header.cached_at) setCachedAt(profile.header.cached_at)
          mark('firstPhotos')
          mark('done')
          setPhase('done')
        } catch (e: unknown) {
          setError(e instanceof Error ? e.message : t(lang, 'error_network'))
          setPhase('error')
        }
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }

    return () => {
      es?.close()
    }
  }, [qid, refresh, run, lang])

  // live elapsed seconds while the stream is open
  useEffect(() => {
    if (phase === 'done' || phase === 'error') return
    const timer = setInterval(() => setElapsedMs(performance.now() - startedAt.current), 100)
    return () => clearInterval(timer)
  }, [phase])

  useEffect(() => {
    if (header?.cached && header.cached_at) setCachedAt(header.cached_at)
  }, [header])

  const hiddenCount = photos.filter((p) => p.verification === 'unverified').length

  const visibleByToggle = useMemo(
    () => photos.filter((p) => showUnverified || p.verification !== 'unverified'),
    [photos, showUnverified],
  )

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: visibleByToggle.length }
    for (const p of visibleByToggle) c[p.category] = (c[p.category] ?? 0) + 1
    return c
  }, [visibleByToggle])

  const visible = useMemo(
    () =>
      visibleByToggle
        .filter((p) => active === 'all' || p.category === active)
        .sort((a, b) => {
          const order = VERIFICATION_ORDER[a.verification] - VERIFICATION_ORDER[b.verification]
          return order !== 0 ? order : b.confidence - a.confidence
        }),
    [visibleByToggle, active],
  )

  const openLightbox = useCallback((index: number) => {
    lightboxReturn.current = document.activeElement as HTMLElement | null
    setPopoverId(null)
    setLightbox(index)
  }, [])

  const closeLightbox = useCallback(() => {
    setLightbox(null)
    lightboxReturn.current?.focus()
  }, [])

  const onRefresh = useCallback(() => {
    if (refresh) setRun((r) => r + 1)
    else navigate(`/u/${qid}?refresh=1`)
  }, [navigate, qid, refresh])

  const streaming = phase !== 'done' && phase !== 'error'
  const emptyLabel = active === 'all' ? null : CATEGORY_LABELS[active][lang]

  return (
    <LayoutGroup>
      <div className="min-h-screen bg-paper text-ink px-gutter">
        <ProgressLine phase={phase} lang={lang} />
        <Masthead header={header} lang={lang} onToggleLang={onToggleLang} onRefresh={onRefresh} />
        <hr className="border-0 border-t border-line" />

        {phase === 'error' && error ? (
          <ErrorState message={error} lang={lang} onRetry={() => setRun((r) => r + 1)} />
        ) : (
          <main>
            <StatusLine
              phase={phase}
              elapsedMs={elapsedMs}
              totalMs={totalMs}
              cachedAt={cachedAt}
              lang={lang}
            />
            <Notices warnings={warnings} lang={lang} />
            {description && <Lead description={description} lang={lang} />}
            {stats && <StatsSentence stats={stats} lang={lang} />}

            {(photos.length > 0 || streaming) && (
              <section className="mt-8">
                <CategoryNav
                  active={active}
                  counts={counts}
                  onSelect={(key) => {
                    setActive(key)
                    setPopoverId(null)
                  }}
                  showUnverified={showUnverified}
                  hiddenCount={hiddenCount}
                  onToggleUnverified={() => setShowUnverified((s) => !s)}
                  lang={lang}
                />
                {visible.length === 0 && !streaming ? (
                  <p className="mt-6 text-[15px] text-ink-2 max-w-[60ch]">
                    {emptyLabel ? t(lang, 'empty_category', { label: emptyLabel }) : t(lang, 'empty_all')}
                  </p>
                ) : (
                  <PhotoGrid
                    photos={visible}
                    arrivals={arrivals.current}
                    lang={lang}
                    streaming={streaming}
                    popoverId={popoverId}
                    onTogglePopover={setPopoverId}
                    onOpen={openLightbox}
                  />
                )}
              </section>
            )}

            {header?.coords && (
              <>
                <hr className="border-0 border-t border-line mt-10" />
                <MapSection
                  campus={header.coords}
                  city={header.city ?? null}
                  distanceKm={header.distance_to_city_center_km ?? null}
                  lang={lang}
                />
              </>
            )}
            <footer className="py-10" />
          </main>
        )}

        <AnimatePresence>
          {lightbox !== null && visible[lightbox] && (
            <Lightbox
              key="lightbox"
              photos={visible}
              index={lightbox}
              lang={lang}
              onClose={closeLightbox}
              onNavigate={setLightbox}
            />
          )}
        </AnimatePresence>
      </div>
    </LayoutGroup>
  )
}
