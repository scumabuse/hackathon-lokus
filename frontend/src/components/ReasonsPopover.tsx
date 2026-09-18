import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { motion, useReducedMotion } from 'motion/react'
import type { Photo } from '../types'
import { REASON_SENTENCES, VERIFICATION_LABELS, t, type Lang } from '../i18n'
import { formatConfidence } from '../lib/format'

interface Props {
  id: string
  photo: Photo
  lang: Lang
  anchor: HTMLElement | null
  onClose: () => void
}

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
const WIDTH = 320
const MARGIN = 8

/** White box, 1px rule border, ≤ 320 px (B5.9), rendered through a portal next to the mark
 *  (frames use paint containment, which would clip it). Escape/outside click close it; focus is
 *  trapped inside and returned to the mark by the caller. */
export default function ReasonsPopover({ id, photo, lang, anchor, onClose }: Props) {
  const reduced = useReducedMotion() ?? false
  const box = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null)

  useLayoutEffect(() => {
    const place = () => {
      if (!anchor) return
      const rect = anchor.getBoundingClientRect()
      const width = Math.min(WIDTH, window.innerWidth - 2 * MARGIN)
      const left = Math.max(MARGIN, Math.min(rect.left, window.innerWidth - width - MARGIN))
      setPosition({ top: rect.bottom + MARGIN, left })
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
  const title = t(lang, 'popover_title', {
    label,
    confidence: formatConfidence(photo.confidence, lang),
  })
  const style = position
    ? { top: position.top, left: position.left, width: Math.min(WIDTH, window.innerWidth - 2 * MARGIN) }
    : { top: -9999, left: -9999, width: WIDTH }

  return createPortal(
    <motion.div
      ref={box}
      id={id}
      role="dialog"
      aria-label={t(lang, 'popover_aria')}
      tabIndex={-1}
      onKeyDown={trap}
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: reduced ? 0 : 0.14 }}
      style={style}
      className="fixed z-[60] bg-paper border border-line text-[13px] leading-[1.45] text-ink outline-none"
    >
      <p className={`px-3 py-2 ${photo.verification === 'verified' ? 'bg-mark-soft' : ''}`}>
        {title}
      </p>
      <ul className="px-3 py-2 border-t border-line">
        {photo.reasons.map((code) => (
          <li key={code} className="py-[2px]">
            {REASON_SENTENCES[code][lang]}
          </li>
        ))}
      </ul>
      <p className="px-3 pb-2">
        <button type="button" className="textlink text-ink-2" onClick={onClose}>
          {t(lang, 'popover_close')}
        </button>
      </p>
    </motion.div>,
    document.body,
  )
}
