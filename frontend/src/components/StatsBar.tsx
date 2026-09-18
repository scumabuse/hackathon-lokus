/** StatsBar — shows counts and time */
import type { Stats } from '../types'
import type { Lang } from '../i18n'
import { UI } from '../i18n'

interface Props {
  stats: Stats
  lang: Lang
}

export default function StatsBar({ stats, lang }: Props) {
  const template = UI.statsBar?.[lang] ?? UI.statsBar.ru
  
  const text = template
    .replace('{found}', String(stats.found))
    .replace('{dupes}', String(stats.duplicates_removed))
    .replace('{irrel}', String(stats.irrelevant_removed))
    .replace('{shown}', String(stats.shown))

  const seconds = (stats.total_ms / 1000).toFixed(1)

  return (
    <div className="bg-slate-50 border border-slate-100 rounded-xl px-4 py-3 mb-6 flex justify-between items-center text-sm text-slate-500">
      <span>{text}</span>
      <span className="font-medium">{seconds} с</span>
    </div>
  )
}
