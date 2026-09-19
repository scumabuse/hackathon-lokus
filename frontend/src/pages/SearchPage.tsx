import { useCallback, useMemo, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useReducedMotion } from 'motion/react'
import { searchUniversities } from '../api'
import type { Candidate, SearchResponse } from '../types'
import { t, type Lang } from '../i18n'
import { useTypingPlaceholder } from '../hooks/useTypingPlaceholder'
import { CHIP_QIDS, EXAMPLES, exampleByQid } from '../data/examples'
import TopBar from '../components/TopBar'
import SiteFooter from '../components/SiteFooter'
import PreviewMosaic from '../components/PreviewMosaic'
import HowItWorks from '../components/HowItWorks'
import UniversityCards from '../components/UniversityCards'
import Icon from '../components/Icon'

interface Props {
  lang: Lang
  onToggleLang: () => void
}

const SOURCE_KEYS = ['sources_wikidata', 'sources_commons', 'sources_wikipedia', 'sources_official']

/** The landing page: hero with the search box and a mosaic of real cards, «Как это работает»,
 *  example universities, the sources band and the footer. */
export default function SearchPage({ lang, onToggleLang }: Props) {
  const [q, setQ] = useState('')
  const [focused, setFocused] = useState(false)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const reducedMotion = useReducedMotion() ?? false
  const listRef = useRef<HTMLUListElement>(null)

  const names = useMemo(() => EXAMPLES.map((e) => e.name), [])
  const placeholder = useTypingPlaceholder(names, !focused && q.length === 0, reducedMotion)
  const chips = useMemo(() => CHIP_QIDS.map(exampleByQid).filter((e): e is NonNullable<typeof e> => !!e), [])

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

  // Arrow keys move through the candidate rows.
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
    <div className="min-h-screen bg-paper text-ink flex flex-col">
      <TopBar lang={lang} onToggleLang={onToggleLang} variant="home" />

      <main className="flex-1">
        {/* ---------------------------------------------------------------- hero */}
        <section className="container-x pt-8 md:pt-14 lg:pt-20">
          <div className="grid gap-12 lg:grid-cols-12 lg:gap-10 xl:gap-16 items-center">
            <div className="lg:col-span-6">
              <p className="eyebrow m-0 flex items-center gap-2">
                <span className="w-[6px] h-[6px] rounded-full bg-accent" aria-hidden="true" />
                {t(lang, 'home_eyebrow')}
              </p>
              <h1 className="display text-[40px] sm:text-[52px] lg:text-[60px] xl:text-[68px] mt-5 m-0 max-w-[16ch]">
                {t(lang, 'home_headline')}
              </h1>
              <p className="mt-6 text-[16px] md:text-[17px] leading-[1.6] text-ink-2 max-w-[54ch] m-0">
                {t(lang, 'home_lead')}
              </p>

              <form onSubmit={handleSubmit} className="mt-8" role="search">
                <label htmlFor="search-input" className="sr-only">
                  {t(lang, 'home_input_label')}
                </label>
                <div className="searchbox">
                  <span className="text-ink-3 flex-none" aria-hidden="true">
                    <Icon name="search" size={20} />
                  </span>
                  <input
                    id="search-input"
                    name="q"
                    type="text"
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    onFocus={() => setFocused(true)}
                    onBlur={() => setFocused(false)}
                    placeholder={placeholder}
                    autoComplete="off"
                    spellCheck={false}
                    aria-describedby="search-hint"
                  />
                  <button id="search-button" type="submit" className="btn hidden sm:inline-flex" aria-busy={loading}>
                    {loading ? t(lang, 'home_searching') : t(lang, 'home_button')}
                    <Icon name="arrow-right" size={16} />
                  </button>
                </div>
                <button type="submit" className="btn w-full mt-3 sm:hidden" aria-busy={loading}>
                  {loading ? t(lang, 'home_searching') : t(lang, 'home_button')}
                  <Icon name="arrow-right" size={16} />
                </button>
                <p id="search-hint" className="sr-only">
                  {t(lang, 'home_promise')}
                </p>
              </form>

              <div className="mt-5 flex flex-wrap items-center gap-2">
                <span className="text-[13px] text-ink-3 mr-1">{t(lang, 'home_examples')}</span>
                {chips.map((u) => (
                  <button
                    key={u.qid}
                    type="button"
                    className="chip"
                    onClick={() => navigate(`/u/${u.qid}`)}
                  >
                    {u.qid === 'Q49108' ? 'MIT' : u.qid === 'Q13164' && lang === 'ru' ? 'МГУ' : u.name}
                  </button>
                ))}
              </div>

              <div aria-live="polite" className="mt-6">
                {error && (
                  <div className="notice">
                    <span className="text-accent mt-[3px]">
                      <Icon name="info" size={16} />
                    </span>
                    <p className="text-[14px] m-0">{t(lang, 'home_error', { message: error })}</p>
                  </div>
                )}
                {result?.corrected_query && (
                  <p className="text-[14px] text-ink-2 m-0 mb-3">
                    {t(lang, 'home_corrected', { name: result.corrected_query })}
                  </p>
                )}
                {result && result.candidates.length === 0 && (
                  <div className="notice">
                    <span className="text-ink-3 mt-[3px]">
                      <Icon name="info" size={16} />
                    </span>
                    <p className="text-[14px] m-0">{t(lang, 'home_not_found')}</p>
                  </div>
                )}
                {result && result.candidates.length > 1 && (
                  <div className="card rounded-xl overflow-hidden">
                    <p className="px-4 pt-4 pb-2 text-[13px] text-ink-3 m-0">{t(lang, 'home_several')}</p>
                    <ul ref={listRef} onKeyDown={onListKey} className="m-0 p-0 list-none">
                      {result.candidates.map((c: Candidate) => (
                        <li key={c.qid} className="border-t border-line">
                          <button
                            type="button"
                            onClick={() => navigate(`/u/${c.qid}`)}
                            className="w-full text-left px-4 py-3 flex items-center justify-between gap-4 hover:bg-paper-2 focus-visible:bg-paper-2 transition-colors"
                          >
                            <span className="min-w-0">
                              <span className="block text-[15px] font-medium">{c.label}</span>
                              {(c.description || c.city || c.country) && (
                                <span className="block text-[13px] text-ink-3 truncate">
                                  {[c.description, [c.city, c.country].filter(Boolean).join(', ')]
                                    .filter(Boolean)
                                    .join(' · ')}
                                </span>
                              )}
                            </span>
                            <span className="text-ink-3 flex-none" aria-hidden="true">
                              <Icon name="arrow-right" size={16} />
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>

            <div className="lg:col-span-6">
              <PreviewMosaic lang={lang} />
            </div>
          </div>
        </section>

        <div className="container-x">
          <HowItWorks lang={lang} />
          <UniversityCards lang={lang} />

          {/* ---------------------------------------------------------------- sources */}
          <section id="sources" className="scroll-mt-20 mt-20 md:mt-28">
            <div className="card rounded-2xl p-6 md:p-10 lg:p-12 grid gap-8 lg:grid-cols-12 lg:items-center">
              <div className="lg:col-span-7">
                <p className="eyebrow m-0">{t(lang, 'topbar_sources')}</p>
                <h2 className="display text-[30px] md:text-[40px] mt-3 m-0">{t(lang, 'sources_title')}</h2>
                <p className="mt-4 text-[16px] leading-[1.6] text-ink-2 max-w-[58ch] m-0">{t(lang, 'sources_text')}</p>
              </div>
              <ul className="lg:col-span-5 m-0 p-0 list-none grid grid-cols-2 gap-3">
                {SOURCE_KEYS.map((key) => (
                  <li
                    key={key}
                    className="rounded-lg border border-line bg-paper-2/70 px-4 py-4 text-[14px] font-medium flex items-center gap-2"
                  >
                    <span className="vdot vdot-verified w-5 h-5 flex-none" aria-hidden="true">
                      <Icon name="check" size={10} strokeWidth={3} />
                    </span>
                    {t(lang, key)}
                  </li>
                ))}
              </ul>
            </div>
          </section>
        </div>
      </main>

      <SiteFooter lang={lang} onToggleLang={onToggleLang} />
    </div>
  )
}
