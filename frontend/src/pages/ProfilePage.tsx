import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { AnimatePresence, LayoutGroup } from 'motion/react'
import { getProfile, openStream, type SSECallbacks } from '../api'
import type { Description, Photo, Stats, UniversityHeader, Warning } from '../types'
import { CATEGORY_LABELS, t, type Lang } from '../i18n'
import { formatKm } from '../lib/format'
import ProgressLine, { type ProfilePhase } from '../components/ProgressLine'
import TopBar from '../components/TopBar'
import SiteFooter from '../components/SiteFooter'
import StatusLine from '../components/StatusLine'
import Notices from '../components/Notices'
import Lead from '../components/Lead'
import InfoBox from '../components/InfoBox'
import CoverPhoto, { pickCover } from '../components/CoverPhoto'
import StatsSentence from '../components/StatsSentence'
import CategoryNav, { type NavKey } from '../components/CategoryNav'
import PhotoGrid, { type Arrival } from '../components/PhotoGrid'
import EmptyState from '../components/EmptyState'
import Lightbox from '../components/Lightbox'
import MapSection from '../components/MapSection'
import ErrorState from '../components/ErrorState'
import Icon from '../components/Icon'

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

  const cover = useMemo(() => pickCover(visibleByToggle), [visibleByToggle])

  const openLightbox = useCallback((index: number) => {
    lightboxReturn.current = document.activeElement as HTMLElement | null
    setPopoverId(null)
    setLightbox(index)
  }, [])

  const openCover = useCallback(() => {
    if (!cover) return
    const index = visible.findIndex((p) => p.id === cover.id)
    if (index >= 0) {
      openLightbox(index)
    } else {
      window.open(cover.source_page_url, '_blank', 'noopener,noreferrer')
    }
  }, [cover, visible, openLightbox])

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
      <div className="min-h-screen bg-paper text-ink flex flex-col">
        <ProgressLine phase={phase} lang={lang} />
        <TopBar lang={lang} onToggleLang={onToggleLang} variant="profile" />

        {phase === 'error' && error ? (
          <main className="container-x flex-1">
            <ErrorState message={error} lang={lang} onRetry={() => setRun((r) => r + 1)} />
          </main>
        ) : (
          <main className="flex-1">
            {/* ---------------------------------------------------------------- hero */}
            <section className="container-x pt-6 md:pt-10">
              <div className="grid gap-8 lg:grid-cols-12 lg:gap-10 xl:gap-14 items-center">
                <div className="lg:col-span-7 min-w-0">
                  <StatusLine
                    phase={phase}
                    elapsedMs={elapsedMs}
                    totalMs={totalMs}
                    cachedAt={cachedAt}
                    lang={lang}
                    onRefresh={onRefresh}
                  />
                  {header ? (
                    <>
                      <h1 className="display text-[38px] sm:text-[52px] lg:text-[60px] xl:text-[72px] mt-6 m-0 break-words">
                        {header.name}
                      </h1>
                      {header.local_name && header.local_name !== header.name && (
                        <p className="font-serif italic text-[20px] md:text-[26px] leading-[1.25] text-ink-2 mt-3 m-0">
                          {header.local_name}
                        </p>
                      )}
                      <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-3 text-[15px]">
                        {header.city?.name && (
                          <span className="inline-flex items-center gap-1.5 text-ink-2">
                            <Icon name="pin" size={15} />
                            {[header.city.name, header.country].filter(Boolean).join(', ')}
                            {header.distance_to_city_center_km != null && (
                              <span className="text-ink-3">
                                {' · '}
                                {t(lang, 'masthead_distance', {
                                  km: formatKm(header.distance_to_city_center_km, lang),
                                })}
                              </span>
                            )}
                          </span>
                        )}
                      </div>
                      {(header.official_website || header.wikipedia_url) && (
                        <div className="mt-4 flex flex-wrap gap-2">
                          {header.official_website && (
                            <a
                              href={header.official_website}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="btn btn-secondary btn-sm"
                            >
                              <Icon name="globe" size={15} />
                              {t(lang, 'masthead_site')}
                              <Icon name="external" size={13} />
                            </a>
                          )}
                          {header.wikipedia_url && (
                            <a
                              href={header.wikipedia_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="btn btn-secondary btn-sm"
                            >
                              {t(lang, 'masthead_wikipedia')}
                              <Icon name="external" size={13} />
                            </a>
                          )}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="mt-6" aria-hidden="true">
                      <div className="skeleton h-[52px] md:h-[64px] w-4/5" />
                      <div className="skeleton h-[52px] md:h-[64px] w-3/5 mt-3" />
                      <div className="skeleton h-[22px] w-2/5 mt-6" />
                      <div className="skeleton h-[18px] w-1/3 mt-5" />
                    </div>
                  )}
                </div>
                <div className="lg:col-span-5">
                  <CoverPhoto
                    photo={cover}
                    streaming={streaming}
                    universityName={header?.name ?? ''}
                    lang={lang}
                    onOpen={openCover}
                  />
                </div>
              </div>
            </section>

            {/* ---------------------------------------------------------------- description + facts */}
            {header && (
              <section className="container-x mt-10 md:mt-14">
                {warnings.length > 0 && (
                  <div className="mb-8">
                    <Notices warnings={warnings} lang={lang} />
                  </div>
                )}
                <div className="grid gap-8 lg:grid-cols-12 lg:gap-10 xl:gap-14 items-start">
                  <div className="lg:col-span-7 min-w-0">
                    {description ? (
                      <Lead description={description} lang={lang} />
                    ) : streaming ? (
                      <div aria-hidden="true">
                        <div className="skeleton h-[20px] w-full" />
                        <div className="skeleton h-[20px] w-11/12 mt-3" />
                        <div className="skeleton h-[20px] w-4/5 mt-3" />
                        <div className="skeleton h-[20px] w-2/3 mt-3" />
                      </div>
                    ) : null}
                  </div>
                  <div className="lg:col-span-5">
                    <InfoBox
                      header={header}
                      stats={stats}
                      totalMs={totalMs}
                      cachedAt={cachedAt}
                      done={phase === 'done'}
                      lang={lang}
                    />
                  </div>
                </div>
              </section>
            )}

            {/* ---------------------------------------------------------------- pictures */}
            {(photos.length > 0 || streaming) && (
              <section className="mt-12 md:mt-16">
                <div className="container-x flex flex-wrap items-end justify-between gap-4 mb-2">
                  <div>
                    <p className="eyebrow m-0">{t(lang, 'grid_title')}</p>
                    {stats ? (
                      <StatsSentence stats={stats} lang={lang} />
                    ) : (
                      <h2 className="font-serif text-[26px] md:text-[32px] leading-[1.15] mt-2 m-0">
                        {t(lang, 'grid_title')}
                      </h2>
                    )}
                  </div>
                </div>
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
                <div className="container-x mt-6">
                  {visible.length === 0 && !streaming ? (
                    <EmptyState
                      lang={lang}
                      categoryLabel={emptyLabel}
                      hiddenCount={hiddenCount}
                      showUnverified={showUnverified}
                      onShowAll={() => setActive('all')}
                      onToggleUnverified={() => setShowUnverified(true)}
                    />
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
                </div>
              </section>
            )}

            {header?.coords && (
              <div className="container-x">
                <MapSection
                  campus={header.coords}
                  city={header.city ?? null}
                  distanceKm={header.distance_to_city_center_km ?? null}
                  lang={lang}
                />
              </div>
            )}
          </main>
        )}

        <SiteFooter lang={lang} onToggleLang={onToggleLang} />

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
