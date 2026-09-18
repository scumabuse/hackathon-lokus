import type { Photo } from '../types'
import { t, type Lang } from '../i18n'
import Frame from './Frame'

export interface Arrival {
  batch: number
  index: number
  at: number
}

interface Props {
  photos: Photo[]
  arrivals: Map<string, Arrival>
  lang: Lang
  streaming: boolean
  popoverId: string | null
  onTogglePopover: (id: string | null) => void
  onOpen: (index: number) => void
}

const SKELETONS = 8

/** Full-bleed strict grid of 4:3 frames, gap 12 px, 2/3/4/5 columns at 0/640/1024/1440 (B5.8).
 *  Skeleton frames appear only while the stream is still open. */
export default function PhotoGrid({
  photos,
  arrivals,
  lang,
  streaming,
  popoverId,
  onTogglePopover,
  onOpen,
}: Props) {
  const skeletons = streaming ? (photos.length === 0 ? SKELETONS : 4) : 0
  return (
    <div
      className="-mx-gutter px-3 mt-4 grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 hd:grid-cols-5"
      aria-busy={streaming}
    >
      {photos.map((photo, index) => {
        const arrival = arrivals.get(photo.id)
        return (
          <Frame
            key={photo.id}
            photo={photo}
            lang={lang}
            indexInBatch={arrival?.index ?? 0}
            arrivedAt={arrival?.at ?? 0}
            popoverOpen={popoverId === photo.id}
            onTogglePopover={onTogglePopover}
            onOpen={() => onOpen(index)}
          />
        )
      })}
      {Array.from({ length: skeletons }, (_, i) => (
        <div key={`skeleton-${i}`} className="frame" aria-hidden={i > 0} aria-label={i === 0 ? t(lang, 'skeleton_aria') : undefined}>
          <div className="skeleton aspect-[4/3]" />
          <div className="mt-2 h-[13px] w-2/3 bg-surface" />
          <div className="mt-1 h-[13px] w-1/2 bg-surface" />
        </div>
      ))}
    </div>
  )
}
