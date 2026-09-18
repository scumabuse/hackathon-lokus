import { useEffect, useRef } from 'react'
import type { KeyboardEvent } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import type { Photo } from '../types'
import {
  CATEGORY_LABELS,
  REASON_SENTENCES,
  VERIFICATION_LABELS,
  dateSentence,
  t,
  type Lang,
} from '../i18n'
import { formatConfidence, formatDistance } from '../lib/format'

interface Props {
  photos: Photo[]
  index: number
  lang: Lang
  onClose: () => void
  onNavigate: (index: number) => void
}

const FOCUSABLE = 'a[href], button:not([disabled])'

/** Opaque paper overlay (B5.10): image left ≤ 68 % (shared layout with the frame), metadata
 *  right; Escape closes, arrows move within the current tab; stacks below 1024 px. */
export default function Lightbox({ photos, index, lang, onClose, onNavigate }: Props) {
  const reduced = useReducedMotion() ?? false
  const box = useRef<HTMLDivElement>(null)
  const photo = photos[index]

  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    box.current?.focus()
    return () => {
      document.body.style.overflow = previous
    }
  }, [])

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowRight' && index < photos.length - 1) onNavigate(index + 1)
      else if (e.key === 'ArrowLeft' && index > 0) onNavigate(index - 1)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [index, photos.length, onClose, onNavigate])

  const trap = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Tab' || !box.current) return
    const items = Array.from(box.current.querySelectorAll<HTMLElement>(FOCUSABLE))
    if (items.length === 0) return
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

  if (!photo) return null
  const categoryLabel = CATEGORY_LABELS[photo.category][lang]
  const title = photo.title?.trim() || categoryLabel
  const rows: Array<[string, string | null]> = [
    [t(lang, 'lightbox_category'), categoryLabel],
    [t(lang, 'lightbox_date'), dateSentence(photo, lang)],
    [t(lang, 'lightbox_author'), photo.author ?? null],
    [t(lang, 'lightbox_license'), photo.license ?? null],
    [
      t(lang, 'lightbox_distance'),
      photo.distance_m != null ? formatDistance(photo.distance_m, lang) : null,
    ],
    [t(lang, 'lightbox_confidence'), formatConfidence(photo.confidence, lang)],
    [t(lang, 'lightbox_visible_text'), photo.visible_text ?? null],
  ]

  return (
    <motion.div
      ref={box}
      role="dialog"
      aria-modal="true"
      aria-label={t(lang, 'lightbox_aria')}
      tabIndex={-1}
      onKeyDown={trap}
      className="fixed inset-0 z-50 bg-paper overflow-y-auto outline-none"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: reduced ? 0 : 0.18 }}
    >
      <div className="min-h-full flex flex-col lg:flex-row">
        <div className="lg:w-[68%] p-gutter flex items-start justify-center lg:items-center">
          <motion.img
            layoutId={`photo-${photo.id}`}
            src={photo.thumb_url}
            alt={title}
            className="block w-full h-auto max-h-[70vh] lg:max-h-[calc(100vh-96px)] object-contain"
            transition={reduced ? { duration: 0 } : { type: 'spring', stiffness: 300, damping: 34 }}
          />
        </div>
        <div className="lg:w-[32%] p-gutter lg:pl-0 flex flex-col text-[15px] leading-[1.5]">
          <div className="flex items-center justify-between gap-4 min-h-[44px]">
            <span className="text-ink-2 text-[13px]">
              {t(lang, 'lightbox_counter', { i: index + 1, n: photos.length })}
            </span>
            <button type="button" className="textlink min-h-[44px]" onClick={onClose}>
              {t(lang, 'lightbox_close')}
            </button>
          </div>
          <h2 className="font-serif text-[26px] leading-[1.2] mt-4">{title}</h2>
          <p className="mt-3 flex items-center gap-2">
            <span className={`mark mark-${photo.verification}`} aria-hidden="true" />
            {VERIFICATION_LABELS[photo.verification][lang]}
          </p>
          <dl className="mt-4 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-[13px]">
            <dt className="text-ink-2">{t(lang, 'lightbox_source')}</dt>
            <dd className="m-0 break-all">
              <a href={photo.source_page_url} target="_blank" rel="noopener noreferrer">
                {photo.source_label}
              </a>
            </dd>
            {rows.map(([label, value]) =>
              value ? (
                <div key={label} className="contents">
                  <dt className="text-ink-2">{label}</dt>
                  <dd className="m-0">{value}</dd>
                </div>
              ) : null,
            )}
          </dl>
          <p className="mt-4 text-[13px] text-ink-2">{t(lang, 'lightbox_reasons')}</p>
          <ul className="text-[13px] leading-[1.45]">
            {photo.reasons.map((code) => (
              <li key={code}>{REASON_SENTENCES[code][lang]}</li>
            ))}
          </ul>
          <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-3">
            <a className="btn" href={photo.source_page_url} target="_blank" rel="noopener noreferrer">
              {t(lang, 'lightbox_open_source')}
            </a>
            <a href={photo.image_url} target="_blank" rel="noopener noreferrer">
              {t(lang, 'lightbox_open_original')}
            </a>
          </div>
          <div className="mt-auto pt-8 flex gap-6 text-[13px]">
            <button
              type="button"
              className="textlink disabled:no-underline disabled:text-ink-2"
              disabled={index === 0}
              onClick={() => onNavigate(index - 1)}
            >
              {t(lang, 'lightbox_prev')}
            </button>
            <button
              type="button"
              className="textlink disabled:no-underline disabled:text-ink-2"
              disabled={index >= photos.length - 1}
              onClick={() => onNavigate(index + 1)}
            >
              {t(lang, 'lightbox_next')}
            </button>
          </div>
        </div>
      </div>
    </motion.div>
  )
}
