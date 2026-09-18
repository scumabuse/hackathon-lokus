/** ConfidenceBadge — verified, likely, unverified with popover */
import { useState, useRef, useEffect } from 'react'
import type { Verification, ReasonCode } from '../types'
import type { Lang } from '../i18n'
import { VERIFICATION_LABELS, REASON_LABELS } from '../i18n'

interface Props {
  verification: Verification
  reasons: ReasonCode[]
  lang: Lang
}

export default function ConfidenceBadge({ verification, reasons, lang }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const label = VERIFICATION_LABELS[verification]?.[lang] ?? verification
  
  let bg = 'bg-slate-100'
  let text = 'text-slate-600'
  let border = 'border-slate-200'
  let icon = '❓'

  if (verification === 'verified') {
    bg = 'bg-emerald-50'
    text = 'text-emerald-700'
    border = 'border-emerald-200'
    icon = '✅'
  } else if (verification === 'likely') {
    bg = 'bg-amber-50'
    text = 'text-amber-700'
    border = 'border-amber-200'
    icon = '⚠️'
  }

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={(e) => {
          e.preventDefault()
          setOpen(!open)
        }}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        className={`flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium border ${bg} ${text} ${border} hover:opacity-80 transition`}
      >
        <span>{icon}</span>
        <span>{label}</span>
      </button>

      {open && reasons.length > 0 && (
        <div className="absolute z-10 bottom-full left-0 mb-1 w-64 bg-slate-800 text-white text-xs rounded-lg shadow-xl p-3">
          <ul className="space-y-1.5 list-disc pl-4">
            {reasons.map((r) => (
              <li key={r}>{REASON_LABELS[r]?.[lang] ?? r}</li>
            ))}
          </ul>
          {/* Arrow */}
          <div className="absolute top-full left-4 -mt-px border-4 border-transparent border-t-slate-800" />
        </div>
      )}
    </div>
  )
}
