import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { Category } from '../types'
import { CATEGORY_LABELS, NAV_CATEGORIES, t, type Lang } from '../i18n'

export type NavKey = Category | 'all'

interface Props {
  active: NavKey
  counts: Record<string, number>
  onSelect: (key: NavKey) => void
  showUnverified: boolean
  hiddenCount: number
  onToggleUnverified: () => void
  lang: Lang
}

/** The sticky category bar: pill tabs with counters (the four case filters Общежития / Спорт /
 *  Лаборатории / Студенческая жизнь among them), arrow keys move the selection, and the
 *  «Показать непроверенные» switch sits at the row's end. Frosted background once stuck. */
export default function CategoryNav({
  active,
  counts,
  onSelect,
  showUnverified,
  hiddenCount,
  onToggleUnverified,
  lang,
}: Props) {
  const sentinel = useRef<HTMLDivElement>(null)
  const row = useRef<HTMLDivElement>(null)
  const [stuck, setStuck] = useState(false)

  useEffect(() => {
    const el = sentinel.current
    if (!el || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(([entry]) => setStuck(!entry.isIntersecting), {
      threshold: 0,
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const keys: NavKey[] = ['all', ...NAV_CATEGORIES]

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    const tabs = Array.from(row.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]') ?? [])
    const index = tabs.indexOf(document.activeElement as HTMLButtonElement)
    if (index === -1) return
    e.preventDefault()
    const next = tabs[(index + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length]
    next?.focus()
    const key = next?.dataset.key as NavKey | undefined
    if (key) onSelect(key)
  }

  return (
    <>
      <div ref={sentinel} aria-hidden="true" className="h-px" />
      <div className={`sticky-bar ${stuck ? 'is-stuck' : ''}`}>
        <div className="container-x">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2 md:py-3">
            <div
              ref={row}
              role="tablist"
              aria-label={t(lang, 'nav_aria')}
              onKeyDown={onKey}
              className="flex flex-wrap items-center gap-1 md:gap-1.5 -ml-2"
            >
              {keys.map((key) => {
                const label = key === 'all' ? t(lang, 'nav_all') : CATEGORY_LABELS[key][lang]
                const selected = key === active
                return (
                  <button
                    key={key}
                    type="button"
                    role="tab"
                    data-key={key}
                    aria-selected={selected}
                    tabIndex={selected ? 0 : -1}
                    onClick={() => onSelect(key)}
                    className="tab"
                  >
                    {label}
                    <span className="count">{counts[key] ?? 0}</span>
                  </button>
                )
              })}
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={showUnverified}
              className="switch ml-auto"
              onClick={onToggleUnverified}
            >
              <span className="track" aria-hidden="true" />
              {t(lang, showUnverified ? 'nav_hide_unverified' : 'nav_show_unverified', { n: hiddenCount })}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
