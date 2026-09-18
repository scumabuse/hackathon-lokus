/** FilterChips — Общежитие · Спорт · Лаборатории · Студенческая жизнь + Show Unverified */
import type { Category } from '../types'
import type { Lang } from '../i18n'
import { CATEGORY_LABELS, UI } from '../i18n'

interface Props {
  activeCategory: Category | 'all'
  onSelectCategory: (c: Category | 'all') => void
  showUnverified: boolean
  onToggleUnverified: () => void
  hiddenCount: number
  lang: Lang
}

const REQUIRED_CHIPS: Category[] = ['dormitory', 'sport', 'lab', 'student_life']

export default function FilterChips({ 
  activeCategory, 
  onSelectCategory, 
  showUnverified, 
  onToggleUnverified,
  hiddenCount,
  lang
}: Props) {
  const t = (k: string) => UI[k]?.[lang] ?? k

  return (
    <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
      <div className="flex flex-wrap gap-2">
        {REQUIRED_CHIPS.map(cat => {
          const isActive = activeCategory === cat
          const label = CATEGORY_LABELS[cat]?.[lang] ?? cat
          return (
            <button
              key={cat}
              onClick={() => onSelectCategory(isActive ? 'all' : cat)}
              className={`px-4 py-1.5 rounded-full text-sm font-medium transition border
                ${isActive 
                  ? 'bg-blue-50 border-blue-200 text-blue-700' 
                  : 'bg-white border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50'}`}
            >
              {label}
            </button>
          )
        })}
      </div>
      
      {hiddenCount > 0 && (
        <label className="flex items-center gap-2 cursor-pointer text-sm text-slate-600 font-medium select-none bg-white border border-slate-200 px-3 py-1.5 rounded-full hover:bg-slate-50 transition">
          <input 
            type="checkbox"
            checked={showUnverified}
            onChange={onToggleUnverified}
            className="w-4 h-4 text-blue-600 rounded border-slate-300 focus:ring-blue-500"
          />
          {t('showUnverified')} <span className="text-slate-400">({hiddenCount})</span>
        </label>
      )}
    </div>
  )
}
