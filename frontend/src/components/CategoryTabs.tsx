/** CategoryTabs — Все · Кампус · ... */
import type { Category } from '../types'
import type { Lang } from '../i18n'
import { CATEGORY_LABELS, UI } from '../i18n'

interface Props {
  activeCategory: Category | 'all'
  onSelect: (c: Category | 'all') => void
  counts: Record<Category | 'all', number>
  lang: Lang
}

const TABS: (Category | 'all')[] = [
  'all',
  'campus',
  'dormitory',
  'classroom',
  'library',
  'lab',
  'sport',
  'student_life',
  'city'
]

export default function CategoryTabs({ activeCategory, onSelect, counts, lang }: Props) {
  const t = (k: string) => UI[k]?.[lang] ?? k

  return (
    <div className="flex overflow-x-auto hide-scrollbar border-b border-slate-200 mb-6 pb-px">
      <div className="flex gap-6 min-w-max px-2">
        {TABS.map(tab => {
          const isActive = activeCategory === tab
          const label = tab === 'all' ? t('allCategories') : (CATEGORY_LABELS[tab as Category]?.[lang] ?? tab)
          const count = counts[tab] || 0
          
          return (
            <button
              key={tab}
              onClick={() => onSelect(tab)}
              className={`pb-3 text-sm font-medium transition whitespace-nowrap relative
                ${isActive ? 'text-blue-600' : 'text-slate-500 hover:text-slate-800'}`}
            >
              {label} <span className="ml-1.5 text-xs text-slate-400 font-normal">{count}</span>
              {isActive && (
                <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-600 rounded-t-full" />
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
