import { useCallback, useMemo, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useReducedMotion } from 'motion/react'
import { searchUniversities } from '../api'
import type { Candidate, SearchResponse } from '../types'
import { t, type Lang } from '../i18n'
import { useTypingPlaceholder } from '../hooks/useTypingPlaceholder'
import LangSwitch from '../components/LangSwitch'

const EXAMPLES = [
  'Nazarbayev University',
  'ETH Zurich',
  'University of Tokyo',
  'Kostanay Regional University',
]

interface Props {
  lang: Lang
  onToggleLang: () => void
}

export default function SearchPage({ lang, onToggleLang }: Props) {
  const [q, setQ] = useState('')
  const [focused, setFocused] = useState(false)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const reducedMotion = useReducedMotion() ?? false
  const listRef = useRef<HTMLUListElement>(null)

  const names = useMemo(() => EXAMPLES, [])
  const placeholder = useTypingPlaceholder(names, !focused && q.length === 0, reducedMotion)

  const doSearch = useCallback(
    async (query: string) => {
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
    },
    [navigate],
  )

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    void doSearch(q)
  }

  // Arrow keys move through the candidate rows (B5).
  const onListKey = (e: KeyboardEvent<HTMLUListElement>) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
    const buttons = Array.from(listRef.current?.querySelectorAll('button') ?? [])
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
    if (index === -1) return
    e.preventDefault()
    const next = e.key === 'ArrowDown' ? index + 1 : index - 1
    buttons[(next + buttons.length) % buttons.length]?.focus()
  }

  return (
    <div className="min-h-screen bg-paper text-ink px-gutter flex flex-col">
      <main className="flex-1 max-w-[1100px] w-full">
        <h1 className="font-serif text-[clamp(32px,5vw,64px)] leading-[1.05] max-w-[22ch] mt-[18vh]">
          {t(lang, 'home_headline')}
        </h1>

        <form onSubmit={handleSubmit} className="mt-10" role="search">
          <label htmlFor="search-input" className="sr-only">
            {t(lang, 'home_input_label')}
          </label>
          <div className="relative">
            <input
              id="search-input"
              name="q"
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              className="field"
              autoComplete="off"
              spellCheck={false}
              aria-describedby="search-hint"
            />
            {q.length === 0 && !focused && (
              <span
                aria-hidden="true"
                className="pointer-events-none absolute left-0 top-0 h-full flex items-center font-serif text-ink-2 text-[clamp(36px,6vw,80px)] leading-[1.1]"
              >
                {placeholder}
                <span className="caret" aria-hidden="true" />
              </span>
            )}
          </div>
          <div className="mt-6 flex flex-wrap items-center gap-x-8 gap-y-3">
            <button id="search-button" type="submit" className="btn" aria-busy={loading}>
              {loading ? t(lang, 'home_searching') : t(lang, 'home_button')}
            </button>
          </div>
        </form>

        <p id="search-hint" className="mt-8 max-w-[60ch] text-[15px] leading-[1.5]">
          {t(lang, 'home_promise')}
        </p>

        <p className="mt-6 text-[15px]">
          <span className="text-ink-2">{t(lang, 'home_examples')} </span>
          {EXAMPLES.map((name, i) => (
            <span key={name}>
              <button
                type="button"
                className="textlink"
                onClick={() => {
                  setQ(name)
                  void doSearch(name)
                }}
              >
                {name}
              </button>
              {i < EXAMPLES.length - 1 ? ', ' : '.'}
            </span>
          ))}
        </p>

        <div aria-live="polite" className="mt-10">
          {error && <p className="max-w-[60ch]">{t(lang, 'home_error', { message: error })}</p>}

          {result?.corrected_query && (
            <p className="max-w-[60ch] text-ink-2">
              {t(lang, 'home_corrected', { name: result.corrected_query })}
            </p>
          )}

          {result && result.candidates.length === 0 && (
            <p className="max-w-[60ch]">{t(lang, 'home_not_found')}</p>
          )}

          {result && result.candidates.length > 1 && (
            <>
              <p className="text-ink-2 mb-2">{t(lang, 'home_several')}</p>
              <ul ref={listRef} onKeyDown={onListKey} className="border-t border-line max-w-[60ch]">
                {result.candidates.map((c: Candidate) => (
                  <li key={c.qid} className="border-b border-line">
                    <button
                      type="button"
                      onClick={() => navigate(`/u/${c.qid}`)}
                      className="w-full text-left py-3 hover:bg-surface focus-visible:bg-surface"
                    >
                      <span className="block">{c.label}</span>
                      {(c.description || c.city || c.country) && (
                        <span className="block text-[13px] text-ink-2">
                          {[c.description, [c.city, c.country].filter(Boolean).join(', ')]
                            .filter(Boolean)
                            .join('. ')}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </main>

      <footer className="py-8 flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px] text-ink-2 max-w-[1100px]">
        <span className="max-w-[70ch]">{t(lang, 'home_footer')}</span>
        <LangSwitch lang={lang} onToggle={onToggleLang} />
      </footer>
    </div>
  )
}
