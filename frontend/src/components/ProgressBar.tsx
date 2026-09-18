/** ProgressBar — shows Поиск → Проверка → Категории → Профиль + elapsed seconds */
import { useEffect, useRef, useState } from 'react'
import type { Lang } from '../i18n'
import { UI } from '../i18n'

interface Props {
  step: number  // 0-3
  lang: Lang
  done: boolean
}

const STEPS = ['stepSearch', 'stepVerify', 'stepCategories', 'stepProfile'] as const

export default function ProgressBar({ step, lang, done }: Props) {
  const [elapsed, setElapsed] = useState(0)
  const startRef = useRef(Date.now())
  const t = (k: string) => UI[k]?.[lang] ?? k

  useEffect(() => {
    if (done) return
    const id = setInterval(() => setElapsed(Math.round((Date.now() - startRef.current) / 1000)), 1000)
    return () => clearInterval(id)
  }, [done])

  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-2">
        <div className="flex gap-1 text-sm">
          {STEPS.map((s, i) => (
            <span key={s} className={`flex items-center gap-1 ${i <= step ? 'text-blue-600 font-medium' : 'text-slate-400'}`}>
              {i > 0 && <span className="text-slate-300">→</span>}
              {t(s)}
            </span>
          ))}
        </div>
        <span className="text-sm text-slate-400">{elapsed}с</span>
      </div>
      <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 rounded-full transition-all duration-500"
          style={{ width: done ? '100%' : `${((step + 1) / 4) * 85 + (done ? 15 : 0)}%` }}
        />
      </div>
    </div>
  )
}
