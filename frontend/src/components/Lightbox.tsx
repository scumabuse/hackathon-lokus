/** Lightbox — modal overlay for photo */
import { useEffect } from 'react'
import type { Photo } from '../types'
import type { Lang } from '../i18n'
import { UI, CATEGORY_LABELS, DATE_KIND_LABELS } from '../i18n'
import ConfidenceBadge from './ConfidenceBadge'

interface Props {
  photo: Photo
  lang: Lang
  onClose: () => void
}

export default function Lightbox({ photo, lang, onClose }: Props) {
  const t = (k: string) => UI[k]?.[lang] ?? k
  
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', handleEsc)
    return () => {
      document.body.style.overflow = ''
      window.removeEventListener('keydown', handleEsc)
    }
  }, [onClose])

  const catLabel = CATEGORY_LABELS[photo.category]?.[lang] ?? photo.category
  
  let dateText = DATE_KIND_LABELS.unknown[lang]
  if (photo.date && photo.date_kind !== 'unknown') {
    dateText = `${DATE_KIND_LABELS[photo.date_kind]?.[lang] ?? photo.date_kind} ${photo.date}`
  }

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div 
        className="bg-white rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex justify-between items-center p-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <span className="px-2 py-1 rounded bg-slate-100 text-slate-700 text-sm font-medium">
              {catLabel}
            </span>
            <ConfidenceBadge verification={photo.verification} reasons={photo.reasons} lang={lang} />
          </div>
          <button 
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-full bg-slate-100 text-slate-500 hover:bg-slate-200 transition"
          >
            ✕
          </button>
        </div>
        
        <div className="flex-1 overflow-auto p-4 bg-slate-50 flex flex-col md:flex-row gap-6">
          <div className="flex-1 flex items-center justify-center min-h-[300px]">
            <img
              src={photo.thumb_url}
              alt={photo.title || catLabel}
              className="max-w-full max-h-[60vh] object-contain rounded-lg shadow-sm"
            />
          </div>
          
          <div className="w-full md:w-80 flex flex-col gap-4">
            {photo.title && (
              <div>
                <h3 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-1">Название</h3>
                <p className="text-slate-900">{photo.title}</p>
              </div>
            )}
            
            <div>
              <h3 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-1">Источник</h3>
              <a
                href={photo.source_page_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:underline flex items-center gap-1 font-medium"
              >
                {photo.source_label} ↗
              </a>
            </div>

            <div>
              <h3 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-1">Дата</h3>
              <p className="text-slate-700">{dateText}</p>
            </div>
            
            {(photo.author || photo.license) && (
              <div>
                <h3 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-1">Автор / Лицензия</h3>
                <p className="text-slate-700">
                  {[photo.author, photo.license].filter(Boolean).join(' • ')}
                </p>
              </div>
            )}

            <a
              href={photo.image_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-auto px-4 py-3 bg-slate-100 hover:bg-slate-200 text-slate-800 text-center rounded-xl font-medium transition"
            >
              {t('openOriginal')}
            </a>
          </div>
        </div>
      </div>
    </div>
  )
}
