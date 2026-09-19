import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { motion, useReducedMotion } from 'motion/react'
import type { Photo, ReasonCode } from '../types'
import { REASON_SENTENCES, VERIFICATION_LABELS, t, type Lang } from '../i18n'
import { formatConfidence } from '../lib/format'
import Icon from './Icon'

interface Props {
  id: string
  photo: Photo
  lang: Lang
  anchor: HTMLElement | null
  onClose: () => void
}

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
const WIDTH = 340
const MARGIN = 8

/** Reasons that lower or cap the label are listed with a dash instead of a check. */
const NEUTRAL: ReadonlySet<ReasonCode> = new Set<ReasonCode>([
  'vision_unavailable',
  'vision_timeout',
  'web_search_source',
  'commons_search_source',
  'category_heuristic',
  'cached_result',
])

/** The reasons card: verification pill, confidence bar and one line per reason. Rendered in a
 *  portal under the badge (cards use paint containment, which would clip it); Escape and an
 *  outside click close it; focus is trapped inside and returned to the badge by the caller. */
export default function ReasonsPopover({ id, photo, lang, anchor, onClose }: Props) {
  const reduced = useReducedMotion() ?? false
  const box = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null)

  useLayoutEffect(() => {
    const place = () => {
      if (!anchor) return
      const rect = anchor.getBoundingClientRect()
      const width = Math.min(WIDTH, window.innerWidth - 2 * MARGIN)
      const height = box.current?.offsetHeight ?? 260
      const left = Math.max(MARGIN, Math.min(rect.right - width, window.innerWidth - width - MARGIN))
      const below = rect.bottom + MARGIN
      const top = below + height > window.innerHeight - MARGIN && rect.top - MARGIN - height > MARGIN
        ? rect.top - MARGIN - height
        : below
      setPosition({ top, left })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [anchor])

  useEffect(() => {
    box.current?.focus()
    const onDocKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
    }
    const onDocDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (box.current && !box.current.contains(target) && !anchor?.contains(target)) onClose()
    }
    document.addEventListener('keydown', onDocKey, true)
    document.addEventListener('mousedown', onDocDown)
    return () => {
      document.removeEventListener('keydown', onDocKey, true)
      document.removeEventListener('mousedown', onDocDown)
    }
  }, [onClose, anchor])

  const trap = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Tab' || !box.current) return
    const items = Array.from(box.current.querySelectorAll<HTMLElement>(FOCUSABLE))
    if (items.length === 0) {
      e.preventDefault()
      return
    }
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && (document.activeElement === first || document.activeElement === box.current)) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  const label = VERIFICATION_LABELS[photo.verification][lang]
  const width = Math.min(WIDTH, window.innerWidth - 2 * MARGIN)
  const style = position ? { top: position.top, left: position.left, width } : { top: -9999, left: -9999, width }
  const percent = Math.round(Math.min(1, Math.max(0, photo.confidence)) * 100)

  return createPortal(
    <motion.div
      ref={box}
      id={id}
      role="dialog"
      aria-label={t(lang, 'popover_aria')}
      tabIndex={-1}
      onKeyDown={trap}
      initial={{ opacity: 0, y: -4, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: reduced ? 0 : 0.16, ease: [0.2, 0.8, 0.2, 1] }}
      style={style}
      className="fixed z-[60] card shadow-lift rounded-[12px] text-[13px] leading-[1.45] text-ink outline-none overflow-hidden"
    >
      <div className="px-4 pt-4 pb-3 border-b border-line">
        <div className="flex items-center justify-between gap-3">
          <span className={`badge badge-${photo.verification}`}>
            {photo.verification === 'verified' ? (
              <Icon name="check" size={12} strokeWidth={2.75} />
            ) : photo.verification === 'likely' ? (
              <span className="w-[7px] h-[7px] rounded-full border-[1.5px] border-current" aria-hidden="true" />
            ) : (
              <Icon name="minus" size={12} strokeWidth={2.5} />
            )}
            {label}
          </span>
          <span className="text-ink-3 num">
            {t(lang, 'lightbox_confidence')} {formatConfidence(photo.confidence, lang)}
          </span>
        </div>
        <div className="mt-3 h-[4px] rounded-full bg-paper-2 overflow-hidden" aria-hidden="true">
          <div
            className={`h-full rounded-full ${photo.verification === 'verified' ? 'bg-accent' : 'bg-ink-2'}`}
            style={{ width: `${percent}%` }}
          />
        </div>
      </div>
      <ul className="px-4 py-3 m-0 list-none grid gap-2">
        {photo.reasons.map((code) => {
          const neutral = NEUTRAL.has(code)
          return (
            <li key={code} className="flex items-start gap-2">
              <span
                className={`mt-[2px] flex-none inline-flex items-center justify-center w-4 h-4 rounded-full ${
                  neutral ? 'bg-paper-2 text-ink-3' : 'bg-accent-soft text-accent'
                }`}
                aria-hidden="true"
              >
                <Icon name={neutral ? 'minus' : 'check'} size={10} strokeWidth={3} />
              </span>
              <span className={neutral ? 'text-ink-2' : ''}>{REASON_SENTENCES[code][lang]}</span>
            </li>
          )
        })}
      </ul>
      <div className="px-4 pb-3">
        <button type="button" className="btn btn-secondary btn-sm w-full" onClick={onClose}>
          {t(lang, 'popover_close')}
        </button>
      </div>
    </motion.div>,
    document.body,
  )
}
