import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { motion } from 'motion/react'
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

/** ONE sticky row (B5.7): Все N · Кампус N · … · Город N, counts in ink-2, a 2 px black
 *  underline that slides, and the unverified toggle at the row's end. The four items
 *  Общежития / Спорт / Лаборатории / Студенческая жизнь are the case's required filters. */
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
      <div
        className={`sticky top-0 z-40 bg-paper ${stuck ? 'border-b border-line' : ''}`}
      >
        <div
          ref={row}
          role="tablist"
          aria-label={t(lang, 'nav_aria')}
          onKeyDown={onKey}
          className="flex items-center gap-6 overflow-x-auto no-scrollbar text-[15px] font-medium whitespace-nowrap"
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
                className="relative py-3 flex-none"
              >
                {label} <span className="text-ink-2 font-normal">{counts[key] ?? 0}</span>
                {selected && (
                  <motion.span
                    layoutId="nav-underline"
                    className="absolute left-0 right-0 bottom-0 h-[2px] bg-ink"
                    transition={{ type: 'spring', stiffness: 420, damping: 40 }}
                  />
                )}
              </button>
            )
          })}
          <span className="flex-1" aria-hidden="true" />
          <button
            type="button"
            className="textlink py-3 flex-none font-normal text-[15px]"
            aria-pressed={showUnverified}
            onClick={onToggleUnverified}
          >
            {t(lang, showUnverified ? 'nav_hide_unverified' : 'nav_show_unverified', {
              n: hiddenCount,
            })}
          </button>
        </div>
      </div>
    </>
  )
}
