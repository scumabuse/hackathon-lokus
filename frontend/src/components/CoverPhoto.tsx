import { motion, useReducedMotion } from 'motion/react'
import type { Photo } from '../types'
import { CATEGORY_LABELS, VERIFICATION_LABELS, dateSentence, t, type Lang } from '../i18n'
import Icon from './Icon'

interface Props {
  photo: Photo | null
  streaming: boolean
  universityName: string
  lang: Lang
  onOpen?: () => void
}

const ORDER: Record<Photo['verification'], number> = { verified: 0, likely: 1, unverified: 2 }

/** The best cover: verified campus pictures first, landscape preferred, highest confidence. */
export function pickCover(photos: Photo[]): Photo | null {
  if (photos.length === 0) return null
  const scored = photos.map((p) => {
    const landscape = p.width && p.height ? (p.width >= p.height ? 0 : 1) : 0
    return { p, key: [ORDER[p.verification], p.category === 'campus' ? 0 : 1, landscape, -p.confidence] }
  })
  scored.sort((a, b) => {
    for (let i = 0; i < a.key.length; i++) {
      if (a.key[i] !== b.key[i]) return a.key[i] - b.key[i]
    }
    return 0
  })
  return scored[0].p
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter((w) => w.length > 2)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')
}

/** The hero's right column: a large cover picture with its badges and a caption, a shimmering
 *  placeholder while the stream is open, a typographic tile when nothing was found. */
export default function CoverPhoto({ photo, streaming, universityName, lang, onOpen }: Props) {
  const reduced = useReducedMotion() ?? false
  const title = photo ? photo.title?.trim() || CATEGORY_LABELS[photo.category][lang] : ''
  return (
    <figure className="card overflow-hidden m-0 rounded-xl shadow-lift">
      <div className="relative aspect-[4/3] lg:aspect-[5/4] bg-paper-2 overflow-hidden">
        {photo ? (
          <button
            type="button"
            onClick={onOpen}
            className="block w-full h-full cursor-zoom-in group"
            aria-label={`${t(lang, 'frame_open')}: ${title}`}
          >
            <motion.img
              key={photo.id}
              src={photo.thumb_url}
              alt={title}
              initial={{ opacity: 0, scale: 1.03 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: reduced ? 0 : 0.7, ease: [0.16, 1, 0.3, 1] }}
              className="block w-full h-full object-cover transition-transform duration-700 group-hover:scale-[1.03]"
            />
          </button>
        ) : streaming ? (
          <div className="absolute inset-0">
            <div className="skeleton absolute inset-0 rounded-none" />
            <span className="absolute bottom-4 left-4 badge badge-frost">
              <span className="live-dot" aria-hidden="true" />
              {t(lang, 'cover_loading')}
            </span>
          </div>
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-ink-3">
            <span className="font-serif text-[96px] leading-none text-line-2" aria-hidden="true">
              {initials(universityName) || '—'}
            </span>
            <span className="text-[14px]">{t(lang, 'cover_empty')}</span>
          </div>
        )}
        {photo && (
          <div className="absolute inset-x-0 top-0 p-3 md:p-4 flex items-start justify-between gap-2 pointer-events-none">
            <span className="badge badge-frost">{CATEGORY_LABELS[photo.category][lang]}</span>
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
        )}
      </div>
      {photo && (
        <figcaption className="px-4 py-3 flex items-center justify-between gap-3 text-[13px] text-ink-3">
          <span className="truncate">
            <span className="text-ink-2 font-medium">{t(lang, 'cover_caption')}: </span>
            {title}
          </span>
          <a
            href={photo.source_page_url}
            target="_blank"
            rel="noopener noreferrer"
            className="link text-ink-2 whitespace-nowrap inline-flex items-center gap-1 flex-none"
          >
            <Icon name="link" size={13} />
            {photo.source_label}, {dateSentence(photo, lang)}
          </a>
        </figcaption>
      )}
    </figure>
  )
}
