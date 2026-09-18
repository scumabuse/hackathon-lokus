import { useCallback, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import type { Photo } from '../types'
import { CATEGORY_LABELS, dateSentence, distanceSentence, t, type Lang } from '../i18n'
import Mark from './Mark'
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

/** One contact-sheet frame (B5.8): 4:3 image, two caption lines, the mark, the popover.
 *  Frames "develop" from grayscale into colour: on stream arrival 0.9 s with a 45 ms stagger
 *  within the batch, on a tab switch 0.35 s; reduced motion means no animation at all. */
export default function Frame({
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
  const markRef = useRef<HTMLButtonElement>(null)
  const categoryLabel = CATEGORY_LABELS[photo.category][lang]
  const title = photo.title?.trim() || categoryLabel
  const popoverId = `reasons-${photo.id}`

  const closePopover = useCallback(() => {
    onTogglePopover(null)
    markRef.current?.focus()
  }, [onTogglePopover])

  const transition = reduced
    ? { duration: 0 }
    : fresh
      ? { duration: 0.9, ease: DEVELOP_EASE, delay: indexInBatch * 0.045 }
      : { duration: 0.35, ease: DEVELOP_EASE }

  const distance = distanceSentence(photo, lang)
  const sourceLine = `${photo.source_label}, ${dateSentence(photo, lang)}${distance ? `, ${distance}` : ''}`

  return (
    <motion.figure
      className={`frame relative m-0 ${photo.verification === 'unverified' ? 'frame-unverified' : ''}`}
      initial={{ opacity: 0, filter: 'grayscale(1) brightness(1.18)' }}
      animate={{ opacity: 1, filter: 'grayscale(0) brightness(1)' }}
      transition={transition}
    >
      <button
        type="button"
        onClick={onOpen}
        className="block w-full aspect-[4/3] bg-surface cursor-zoom-in overflow-hidden"
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
      <figcaption className="relative mt-2 text-[13px] leading-[1.4]">
        <div className="flex items-center gap-2 min-w-0">
          <Mark
            ref={markRef}
            verification={photo.verification}
            lang={lang}
            expanded={popoverOpen}
            controls={popoverId}
            onClick={() => onTogglePopover(popoverOpen ? null : photo.id)}
          />
          <span className="truncate">{title}</span>
        </div>
        <a
          href={photo.source_page_url}
          target="_blank"
          rel="noopener noreferrer"
          className="block truncate text-ink-2"
        >
          {sourceLine}
        </a>
        {popoverOpen && (
          <ReasonsPopover
            id={popoverId}
            photo={photo}
            lang={lang}
            anchor={markRef.current}
            onClose={closePopover}
          />
        )}
      </figcaption>
    </motion.figure>
  )
}
