/** DescriptionCard — text, sources, basis */
import type { Description } from '../types'
import type { Lang } from '../i18n'
import { UI, BASIS_LABELS } from '../i18n'

interface Props {
  description: Description
  lang: Lang
}

export default function DescriptionCard({ description, lang }: Props) {
  const t = (k: string) => UI[k]?.[lang] ?? k
  const basisText = BASIS_LABELS[description.basis]?.[lang] ?? description.basis

  return (
    <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-6 mb-4">
      <p className="text-slate-800 leading-relaxed mb-4">
        {lang === 'ru' ? description.text_ru : description.text_en}
      </p>
      
      {description.sources.length > 0 && (
        <div className="mb-2">
          <span className="text-sm font-medium text-slate-700 mr-2">{t('sources')}</span>
          <span className="text-sm flex gap-3 inline-flex flex-wrap">
            {description.sources.map((s, i) => (
              <a
                key={i}
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:underline"
              >
                {s.title}
              </a>
            ))}
          </span>
        </div>
      )}
      
      <p className="text-xs text-slate-400 italic">
        {basisText}
      </p>
    </div>
  )
}
