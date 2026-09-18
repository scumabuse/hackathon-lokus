/** PhotoGrid — displays PhotoCards and manages Lightbox */
import { useState } from 'react'
import type { Photo } from '../types'
import type { Lang } from '../i18n'
import PhotoCard from './PhotoCard'
import Lightbox from './Lightbox'

interface Props {
  photos: Photo[]
  lang: Lang
}

export default function PhotoGrid({ photos, lang }: Props) {
  const [activePhoto, setActivePhoto] = useState<Photo | null>(null)

  return (
    <>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
        {photos.map(p => (
          <PhotoCard 
            key={p.id} 
            photo={p} 
            lang={lang} 
            onClick={() => setActivePhoto(p)}
          />
        ))}
      </div>
      
      {activePhoto && (
        <Lightbox 
          photo={activePhoto} 
          lang={lang} 
          onClose={() => setActivePhoto(null)} 
        />
      )}
    </>
  )
}
