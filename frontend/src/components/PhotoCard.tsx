import { useCallback, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import type { Photo } from '../types'
import { CATEGORY_LABELS, dateSentence, t, type Lang } from '../i18n'
import { formatDistance } from '../lib/format'
import Icon from './Icon'
import VerificationBadge from './VerificationBadge'
import ReasonsPopover from './ReasonsPopover'

interface Props {
  photo: Photo
  lang: Lang
  indexInBatch: number
  arrivedAt: number
  popoverOpen: boolean
  onTogglePopover: (id: string | null) => void
  onOpen: () => void
}

const DEVELOP_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1]
const FRESH_WINDOW_MS = 1500

/** One photo card: the picture is the hero (4:3, zooms slightly on hover), a frosted category
 *  badge and the verification pill sit on the image, a two-line title and an icon metadata
 *  row (source · date · distance) sit below. Cards "develop" from grayscale on arrival. */
export default function PhotoCard({
  photo,
  lang,
  indexInBatch,
  arrivedAt,
  popoverOpen,
  onTogglePopover,
  onOpen,
}: Props) {
  const reduced = useReducedMotion() ?? false
  const [fresh] = useState(() => Date.now() - arrivedAt < FRESH_WINDOW_MS)
  const badgeRef = useRef<HTMLButtonElement>(null)
  const categoryLabel = CATEGORY_LABELS[photo.category][lang]
  const title = photo.title?.trim() || categoryLabel
  const popoverId = `reasons-${photo.id}`
  const unverified = photo.verification === 'unverified'

  const closePopover = useCallback(() => {
    onTogglePopover(null)
    badgeRef.current?.focus()
  }, [onTogglePopover])

  const transition = reduced
    ? { duration: 0 }
    : fresh
      ? { duration: 0.75, ease: DEVELOP_EASE, delay: indexInBatch * 0.04 }
      : { duration: 0.3, ease: DEVELOP_EASE }

  return (
    <motion.figure
      className={`photo-card card overflow-hidden m-0 relative ${unverified ? 'is-unverified' : ''}`}
      initial={{ opacity: 0, y: 10, filter: 'grayscale(1) brightness(1.12)' }}
      animate={{ opacity: 1, y: 0, filter: 'grayscale(0) brightness(1)' }}
      whileHover={reduced ? undefined : { y: -3 }}
      transition={transition}
    >
      <div className="media relative aspect-[4/3] overflow-hidden bg-paper-2">
        <button
          type="button"
          onClick={onOpen}
          className="block w-full h-full cursor-zoom-in"
          aria-label={`${t(lang, 'frame_open')}: ${title}`}
        >
          <motion.img
            layoutId={`photo-${photo.id}`}
            src={photo.thumb_url}
            alt={title}
            loading="lazy"
            decoding="async"
            className="block w-full h-full object-cover"
          />
        </button>
        <div className="absolute inset-x-0 top-0 p-3 flex items-start justify-between gap-2 pointer-events-none">
          <span className="badge badge-frost pointer-events-auto">{categoryLabel}</span>
          <VerificationBadge
            ref={badgeRef}
            verification={photo.verification}
            lang={lang}
            expanded={popoverOpen}
            controls={popoverId}
            onClick={() => onTogglePopover(popoverOpen ? null : photo.id)}
            className="pointer-events-auto"
          />
        </div>
        <a
          href={photo.source_page_url}
          target="_blank"
          rel="noopener noreferrer"
          className="hover-action absolute bottom-3 right-3 badge badge-frost h-8 px-3 text-[12px] hover:bg-ink hover:text-paper"
        >
          <Icon name="external" size={13} />
          {t(lang, 'card_source')}
        </a>
      </div>
      <figcaption className="p-4 pt-3">
        <p className="clamp-2 text-[15px] font-medium leading-[1.4] m-0" title={title}>
          {title}
        </p>
        <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] leading-[1.4] text-ink-3 m-0">
          <a
            href={photo.source_page_url}
            target="_blank"
            rel="noopener noreferrer"
            className="link inline-flex items-center gap-1 text-ink-2 max-w-full"
          >
            <Icon name="link" size={13} />
            <span className="truncate">{photo.source_label}</span>
          </a>
          <span aria-hidden="true">·</span>
          <span className="inline-flex items-center gap-1 whitespace-nowrap">
            <Icon name="calendar" size={13} />
            {dateSentence(photo, lang)}
          </span>
          {photo.distance_m != null && (
            <>
              <span aria-hidden="true">·</span>
              <span className="inline-flex items-center gap-1 whitespace-nowrap">
                <Icon name="pin" size={13} />
                {t(lang, 'frame_distance', { distance: formatDistance(photo.distance_m, lang) })}
              </span>
            </>
          )}
        </p>
        {popoverOpen && (
          <ReasonsPopover
            id={popoverId}
            photo={photo}
            lang={lang}
            anchor={badgeRef.current}
            onClose={closePopover}
          />
        )}
      </figcaption>
    </motion.figure>
  )
}
