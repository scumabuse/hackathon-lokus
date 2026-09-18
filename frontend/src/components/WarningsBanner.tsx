/** WarningsBanner — list of warnings */
import type { Warning } from '../types'
import type { Lang } from '../i18n'
import { WARNING_LABELS } from '../i18n'

interface Props {
  warnings: Warning[]
  lang: Lang
}

export default function WarningsBanner({ warnings, lang }: Props) {
  if (warnings.length === 0) return null

  return (
    <div className="flex flex-col gap-2 mb-4">
      {warnings.map((w, i) => {
        const text = WARNING_LABELS[w.code]?.(w.detail)?.[lang] ?? w.code
        
        // Use different styling based on warning severity/type
        let bg = 'bg-amber-50'
        let border = 'border-amber-200'
        let textCol = 'text-amber-800'
        let icon = '⚠️'

        if (w.code === 'served_from_cache' || w.code === 'queued') {
          bg = 'bg-blue-50'
          border = 'border-blue-200'
          textCol = 'text-blue-800'
          icon = 'ℹ️'
        } else if (w.code === 'time_budget_exceeded') {
          bg = 'bg-orange-50'
          border = 'border-orange-200'
          textCol = 'text-orange-800'
          icon = '⏱️'
        } else if (w.code === 'low_data' || w.code === 'missing_category') {
           icon = '🔍'
        }

        return (
          <div key={`${w.code}-${i}`} className={`flex items-start gap-2 ${bg} border ${border} ${textCol} px-4 py-3 rounded-xl text-sm`}>
            <span>{icon}</span>
            <span>{text}</span>
          </div>
        )
      })}
    </div>
  )
}
