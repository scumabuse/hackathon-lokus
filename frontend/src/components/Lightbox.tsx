import { useEffect, useRef } from 'react'
import type { KeyboardEvent } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import type { Photo, ReasonCode } from '../types'
import {
  CATEGORY_LABELS,
  REASON_SENTENCES,
  VERIFICATION_LABELS,
  dateSentence,
  t,
  type Lang,
} from '../i18n'
import { formatConfidence, formatDistance } from '../lib/format'
import Icon from './Icon'

interface Props {
  photos: Photo[]
  index: number
  lang: Lang
  onClose: () => void
  onNavigate: (index: number) => void
}

const FOCUSABLE = 'a[href], button:not([disabled])'
const NEUTRAL: ReadonlySet<ReasonCode> = new Set<ReasonCode>([
  'vision_unavailable',
  'vision_timeout',
  'web_search_source',
  'commons_search_source',
  'category_heuristic',
  'cached_result',
])

/** Gallery viewer: dark frosted overlay, the picture centred with round prev/next controls
 *  (shared layout with its card), a white metadata panel on the right (below on phones).
 *  Escape closes, arrows move within the current tab, focus is trapped inside. */
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
      className="lightbox-bg fixed inset-0 z-50 overflow-y-auto outline-none text-paper"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: reduced ? 0 : 0.2 }}
    >
      <div className="min-h-full flex flex-col lg:flex-row lg:items-stretch">
        {/* picture */}
        <div className="relative flex-1 min-h-[52vh] lg:min-h-screen flex items-center justify-center p-4 pt-16 lg:p-10 lg:pr-6">
          <span className="absolute top-4 left-4 lg:top-6 lg:left-8 text-[13px] text-paper/70 num">
            {t(lang, 'lightbox_counter', { i: index + 1, n: photos.length })}
          </span>
          <button
            type="button"
            className="iconbtn iconbtn-dark absolute top-3 right-3 lg:top-5 lg:right-5"
            onClick={onClose}
            aria-label={t(lang, 'lightbox_close')}
          >
            <Icon name="close" size={18} />
          </button>
          <motion.img
            layoutId={`photo-${photo.id}`}
            src={photo.thumb_url}
            alt={title}
            className="block max-w-full max-h-[62vh] lg:max-h-[calc(100vh-80px)] w-auto h-auto object-contain rounded-md shadow-modal"
            transition={reduced ? { duration: 0 } : { type: 'spring', stiffness: 300, damping: 34 }}
          />
          <div className="absolute inset-x-3 lg:inset-x-5 top-1/2 -translate-y-1/2 flex justify-between pointer-events-none">
            <button
              type="button"
              className="iconbtn iconbtn-dark pointer-events-auto"
              disabled={index === 0}
              onClick={() => onNavigate(index - 1)}
              aria-label={t(lang, 'lightbox_prev')}
            >
              <Icon name="chevron-left" size={20} />
            </button>
            <button
              type="button"
              className="iconbtn iconbtn-dark pointer-events-auto"
              disabled={index >= photos.length - 1}
              onClick={() => onNavigate(index + 1)}
              aria-label={t(lang, 'lightbox_next')}
            >
              <Icon name="chevron-right" size={20} />
            </button>
          </div>
        </div>

        {/* metadata panel */}
        <aside className="lg:w-[400px] xl:w-[440px] flex-none p-4 lg:p-6 lg:pl-0">
          <div className="card rounded-xl text-ink p-5 md:p-6 lg:h-full flex flex-col text-[14px] leading-[1.5]">
            <div className="flex flex-wrap items-center gap-2">
              <span className="badge badge-soft">{categoryLabel}</span>
              <span className={`badge badge-${photo.verification}`}>
                {photo.verification === 'verified' ? (
                  <Icon name="check" size={12} strokeWidth={2.75} />
                ) : photo.verification === 'likely' ? (
                  <span className="w-[7px] h-[7px] rounded-full border-[1.5px] border-current" aria-hidden="true" />
                ) : (
                  <Icon name="minus" size={12} strokeWidth={2.5} />
                )}
                {VERIFICATION_LABELS[photo.verification][lang]}
              </span>
            </div>
            <h2 className="font-serif text-[24px] md:text-[26px] leading-[1.2] mt-4 m-0">{title}</h2>

            <dl className="infobox mt-5 m-0">
              <div className="row">
                <dt>{t(lang, 'lightbox_source')}</dt>
                <dd className="min-w-0">
                  <a
                    href={photo.source_page_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="link inline-flex items-center gap-1 max-w-full"
                  >
                    <span className="truncate">{photo.source_label}</span>
                    <Icon name="external" size={13} />
                  </a>
                </dd>
              </div>
              {rows.map(([label, value]) =>
                value ? (
                  <div key={label} className="row">
                    <dt>{label}</dt>
                    <dd className="min-w-0 break-words">{value}</dd>
                  </div>
                ) : null,
              )}
            </dl>

            <p className="eyebrow mt-6 mb-2">{t(lang, 'lightbox_reasons')}</p>
            <ul className="m-0 p-0 list-none grid gap-2 text-[13.5px]">
              {photo.reasons.map((code) => {
                const neutral = NEUTRAL.has(code)
                return (
                  <li key={code} className="flex items-start gap-2">
                    <span
                      className={`mt-[3px] flex-none inline-flex items-center justify-center w-4 h-4 rounded-full ${
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

            <div className="mt-auto pt-6 flex flex-wrap items-center gap-3">
              <a className="btn" href={photo.source_page_url} target="_blank" rel="noopener noreferrer">
                {t(lang, 'lightbox_open_source')}
                <Icon name="external" size={15} />
              </a>
              <a className="btn btn-secondary" href={photo.image_url} target="_blank" rel="noopener noreferrer">
                {t(lang, 'lightbox_open_original')}
              </a>
            </div>
          </div>
        </aside>
      </div>
    </motion.div>
  )
}
