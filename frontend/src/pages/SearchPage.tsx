import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { searchUniversities } from '../api'
import type { Candidate, SearchResponse } from '../types'
import { UI, CATEGORY_LABELS } from '../i18n'
import type { Lang } from '../i18n'

const EXAMPLE_CHIPS = [
  'Nazarbayev University',
  'Al-Farabi Kazakh National University',
  'Massachusetts Institute of Technology',
  'ETH Zurich',
  'University of Tokyo',
  'Kostanay Regional University',
]

interface Props { lang: Lang }

export default function SearchPage({ lang }: Props) {
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()

  const t = (key: string) => UI[key]?.[lang] ?? key

  const doSearch = useCallback(async (query: string) => {
    const trimmed = query.trim()
    if (trimmed.length < 2) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await searchUniversities(trimmed)
      if (res.candidates.length === 1) {
        navigate(`/u/${res.candidates[0].qid}`)
        return
      }
      setResult(res)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [navigate])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    doSearch(q)
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex flex-col">
      {/* Header */}
      <header className="py-16 px-4 text-center">
        <h1 className="text-5xl font-bold text-slate-900 tracking-tight mb-3">
          Visual Campus
        </h1>
        <p className="text-xl text-slate-500 max-w-xl mx-auto">
          {t('appTagline')}
        </p>
      </header>

      {/* Search */}
      <main className="flex-1 px-4 max-w-2xl mx-auto w-full">
        <form onSubmit={handleSubmit} className="flex gap-3 mb-6">
          <input
            id="search-input"
            type="text"
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder={t('searchPlaceholder')}
            className="flex-1 px-5 py-3 rounded-xl border border-slate-200 bg-white shadow-sm text-lg focus:outline-none focus:ring-2 focus:ring-blue-400 transition"
            autoFocus
          />
          <button
            id="search-button"
            type="submit"
            disabled={loading || q.trim().length < 2}
            className="px-6 py-3 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-semibold rounded-xl shadow-sm transition"
          >
            {loading ? '…' : t('searchButton')}
          </button>
        </form>

        {/* Example chips */}
        <div className="flex flex-wrap gap-2 mb-8">
          <span className="text-sm text-slate-400 self-center">{t('exampleChips')}</span>
          {EXAMPLE_CHIPS.map(chip => (
            <button
              key={chip}
              onClick={() => { setQ(chip); doSearch(chip) }}
              className="text-sm px-3 py-1.5 bg-white border border-slate-200 rounded-full text-slate-600 hover:bg-blue-50 hover:border-blue-300 transition"
            >
              {chip}
            </button>
          ))}
        </div>

        {/* Corrected query notice */}
        {result?.corrected_query && (
          <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-4 py-2 mb-4">
            {t('correctedQuery')} <strong>{result.corrected_query}</strong>
          </p>
        )}

        {/* Error */}
        {error && (
          <p className="text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3 mb-4">
            {error}
          </p>
        )}

        {/* Results */}
        {result && result.candidates.length === 0 && (
          <div className="text-center py-12 text-slate-500">
            <div className="text-5xl mb-4">🔍</div>
            <p>{t('notFound')}</p>
          </div>
        )}

        {result && result.candidates.length > 1 && (
          <ul className="space-y-3">
            {result.candidates.map((c: Candidate) => (
              <li key={c.qid}>
                <button
                  onClick={() => navigate(`/u/${c.qid}`)}
                  className="w-full text-left px-5 py-4 bg-white border border-slate-200 rounded-xl shadow-sm hover:shadow-md hover:border-blue-300 transition group"
                >
                  <div className="font-semibold text-slate-900 group-hover:text-blue-700 transition">
                    {c.label}
                  </div>
                  {c.description && (
                    <div className="text-sm text-slate-500 mt-0.5">{c.description}</div>
                  )}
                  {(c.city || c.country) && (
                    <div className="text-xs text-slate-400 mt-1">
                      {[c.city, c.country].filter(Boolean).join(', ')}
                    </div>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </main>

      {/* Footer */}
      <footer className="py-8 px-4 text-center text-xs text-slate-400 max-w-2xl mx-auto">
        {t('footer')}
      </footer>
    </div>
  )
}
