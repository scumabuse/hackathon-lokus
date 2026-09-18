/** PhotoCard — single photo in the grid */
import type { Photo } from '../types'
import type { Lang } from '../i18n'
import { CATEGORY_LABELS, DATE_KIND_LABELS } from '../i18n'
import ConfidenceBadge from './ConfidenceBadge'

interface Props {
  photo: Photo
  lang: Lang
  onClick: () => void
}

export default function PhotoCard({ photo, lang, onClick }: Props) {
  const catLabel = CATEGORY_LABELS[photo.category]?.[lang] ?? photo.category
  
  let dateText = DATE_KIND_LABELS.unknown[lang]
  if (photo.date && photo.date_kind !== 'unknown') {
    dateText = `${DATE_KIND_LABELS[photo.date_kind]?.[lang] ?? photo.date_kind} ${photo.date}`
  }

  return (
    <div 
      className="group flex flex-col bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden hover:shadow-md transition cursor-pointer"
      onClick={onClick}
    >
      <div className="relative aspect-video bg-slate-100 overflow-hidden">
        <img
          src={photo.thumb_url}
          alt={photo.title || catLabel}
          loading="lazy"
          className="w-full h-full object-cover group-hover:scale-105 transition duration-500"
        />
        <div className="absolute top-2 left-2 flex gap-1.5">
          <span className="px-2 py-0.5 rounded bg-black/60 text-white text-xs font-medium backdrop-blur-sm">
            {catLabel}
          </span>
          <ConfidenceBadge verification={photo.verification} reasons={photo.reasons} lang={lang} />
        </div>
      </div>
      
      <div className="p-3 flex flex-col gap-1 flex-1">
        <div className="flex items-center justify-between text-sm">
          <a
            href={photo.source_page_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-blue-600 hover:underline flex items-center gap-1 font-medium truncate pr-2"
          >
            {photo.source_label}
            <span className="text-[10px]">↗</span>
          </a>
        </div>
        
        <p className="text-xs text-slate-500 truncate" title={dateText}>
          {dateText}
        </p>
        
        {(photo.author || photo.license) && (
          <p className="text-xs text-slate-400 truncate mt-auto pt-1">
            {[photo.author, photo.license].filter(Boolean).join(' • ')}
          </p>
        )}
      </div>
    </div>
  )
}
