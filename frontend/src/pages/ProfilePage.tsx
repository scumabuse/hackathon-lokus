import { useEffect, useState, useMemo } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { openStream, getProfile, SSECallbacks } from '../api'
import type { Lang } from '../i18n'
import type { 
  UniversityHeader, 
  Description, 
  Photo, 
  Stats, 
  Warning, 
  Category 
} from '../types'

import ProgressBar from '../components/ProgressBar'
import ProfileHeader from '../components/ProfileHeader'
import DescriptionCard from '../components/DescriptionCard'
import WarningsBanner from '../components/WarningsBanner'
import StatsBar from '../components/StatsBar'
import CategoryTabs from '../components/CategoryTabs'
import FilterChips from '../components/FilterChips'
import PhotoGrid from '../components/PhotoGrid'
import MapCard from '../components/MapCard'
import EmptyState from '../components/EmptyState'
import ErrorState from '../components/ErrorState'
import { UI } from '../i18n'

export default function ProfilePage({ lang }: { lang: Lang }) {
  const { qid } = useParams<{ qid: string }>()
  const [searchParams] = useSearchParams()
  const refresh = searchParams.get('refresh') === '1'

  // State
  const [header, setHeader] = useState<UniversityHeader | null>(null)
  const [description, setDescription] = useState<Description | null>(null)
  const [photos, setPhotos] = useState<Photo[]>([])
  const [warnings, setWarnings] = useState<Warning[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [step, setStep] = useState(0)

  // Filters
  const [activeCategory, setActiveCategory] = useState<Category | 'all'>('all')
  const [showUnverified, setShowUnverified] = useState(false)

  useEffect(() => {
    if (!qid) return
    
    // Reset state on new qid/refresh
    setHeader(null)
    setDescription(null)
    setPhotos([])
    setWarnings([])
    setStats(null)
    setDone(false)
    setError(null)
    setStep(0)
    setActiveCategory('all')
    setShowUnverified(false)

    let es: EventSource | null = null
    
    const callbacks: SSECallbacks = {
      onHeader: (h) => { setHeader(h); setStep(1) },
      onDescription: (d) => { setDescription(d) },
      onPhotos: (_, newPhotos) => {
        setPhotos(prev => {
          const map = new Map(prev.map(p => [p.id, p]))
          newPhotos.forEach(p => map.set(p.id, p))
          return Array.from(map.values())
        })
        setStep(2)
      },
      onWarning: (w) => { setWarnings(prev => [...prev, w]) },
      onStats: (s) => { setStats(s); setStep(3) },
      onDone: (_total_ms, _cached) => {
        setDone(true)
        setStep(3)
        if (es) {
          es.close()
        }
      },
      onError: (_code, msg) => {
        setError(msg)
        setDone(true)
        if (es) {
          es.close()
        }
      }
    }

    try {
      es = openStream(qid, refresh, callbacks)
      
      es.onerror = async () => {
        // Only fallback if header hasn't arrived
        if (!header && es) {
          es.close()
          es = null
          try {
            const profile = await getProfile(qid, refresh)
            setHeader(profile.header)
            if (profile.description) setDescription(profile.description)
            setPhotos(profile.photos)
            setStats(profile.stats)
            setWarnings(profile.warnings)
            setStep(3)
            setDone(true)
          } catch (e: any) {
            setError(e.message || UI.networkError[lang])
            setDone(true)
          }
        }
      }
    } catch (e: any) {
      setError(e.message || String(e))
      setDone(true)
    }

    return () => {
      if (es) es.close()
    }
  }, [qid, refresh, lang])

  const shownPhotos = useMemo(() => {
    return photos.filter(p => {
      if (p.verification === 'unverified' && !showUnverified) return false
      if (activeCategory !== 'all' && p.category !== activeCategory) return false
      return true
    }).sort((a, b) => {
      // verified first, then confidence desc
      if (a.verification !== b.verification) {
        if (a.verification === 'verified') return -1
        if (b.verification === 'verified') return 1
        if (a.verification === 'likely') return -1
        if (b.verification === 'likely') return 1
      }
      return b.confidence - a.confidence
    })
  }, [photos, showUnverified, activeCategory])

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: 0 }
    photos.forEach(p => {
      if (p.verification === 'unverified' && !showUnverified) return
      c[p.category] = (c[p.category] || 0) + 1
      c.all++
    })
    return c
  }, [photos, showUnverified])

  const hiddenCount = photos.filter(p => p.verification === 'unverified').length

  if (error) {
    return <ErrorState error={error} lang={lang} onRetry={() => window.location.reload()} />
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Top Nav (simple) */}
      <nav className="bg-white border-b border-slate-200 px-4 py-3 sticky top-0 z-40 shadow-sm flex items-center justify-between">
         <a href="/" className="text-xl font-bold text-slate-900 tracking-tight">Visual Campus</a>
      </nav>

      <main className="max-w-6xl mx-auto px-4 py-8">
        <ProgressBar step={step} lang={lang} done={done} />

        {header && <ProfileHeader header={header} lang={lang} />}
        
        <div className="flex flex-col lg:flex-row gap-6 mt-6">
          {/* Main content */}
          <div className="flex-1 min-w-0">
            <WarningsBanner warnings={warnings} lang={lang} />
            {stats && done && <StatsBar stats={stats} lang={lang} />}

            {(photos.length > 0 || done) && (
              <>
                <FilterChips 
                  activeCategory={activeCategory} 
                  onSelectCategory={setActiveCategory}
                  showUnverified={showUnverified}
                  onToggleUnverified={() => setShowUnverified(s => !s)}
                  hiddenCount={hiddenCount}
                  lang={lang}
                />
                
                <CategoryTabs 
                  activeCategory={activeCategory} 
                  onSelect={setActiveCategory}
                  counts={counts as Record<Category | 'all', number>}
                  lang={lang}
                />

                {shownPhotos.length > 0 ? (
                  <PhotoGrid photos={shownPhotos} lang={lang} />
                ) : done ? (
                  <EmptyState lang={lang} />
                ) : (
                  <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                    {[1,2,3,4].map(i => (
                      <div key={i} className="aspect-video bg-slate-200 animate-pulse rounded-xl" />
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
          
          {/* Sidebar */}
          <div className="w-full lg:w-80 shrink-0">
             {description && <DescriptionCard description={description} lang={lang} />}
             {header?.coords && (
               <MapCard 
                 uniCoords={header.coords} 
                 city={header.city} 
                 distanceKm={header.distance_to_city_center_km} 
                 lang={lang} 
               />
             )}
          </div>
        </div>
      </main>
    </div>
  )
}
