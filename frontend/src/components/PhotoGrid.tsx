import type { Photo } from '../types'
import { t, type Lang } from '../i18n'
import PhotoCard from './PhotoCard'

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

/** Strict responsive grid of photo cards: 1 / 2 / 3 / 4 columns at 0 / 520 / 1024 / 1440 px
 *  with an even 20–24 px gutter. Skeleton cards appear only while the stream is open. */
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
      className="grid gap-5 md:gap-6 grid-cols-1 min-[520px]:grid-cols-2 lg:grid-cols-3 hd:grid-cols-4"
      aria-busy={streaming}
    >
      {photos.map((photo, index) => {
        const arrival = arrivals.get(photo.id)
        return (
          <PhotoCard
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
        <div
          key={`skeleton-${i}`}
          className="card overflow-hidden"
          aria-hidden={i > 0}
          aria-label={i === 0 ? t(lang, 'skeleton_aria') : undefined}
        >
          <div className="skeleton aspect-[4/3] rounded-none" />
          <div className="p-4 pt-3">
            <div className="skeleton h-[15px] w-3/4" />
            <div className="skeleton h-[13px] w-1/2 mt-3" />
          </div>
        </div>
      ))}
    </div>
  )
}
