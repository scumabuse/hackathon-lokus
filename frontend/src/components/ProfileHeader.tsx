/** ProfileHeader — name, local name, links, distance, cached badge */
import { useNavigate } from 'react-router-dom'
import type { UniversityHeader } from '../types'
import type { Lang } from '../i18n'
import { UI } from '../i18n'

interface Props {
  header: UniversityHeader
  lang: Lang
}

export default function ProfileHeader({ header, lang }: Props) {
  const navigate = useNavigate()
  const t = (k: string) => UI[k]?.[lang] ?? k

  const cachedMinutes = header.cached_at
    ? Math.round((Date.now() - new Date(header.cached_at).getTime()) / 60000)
    : 0

  return (
    <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-6 mb-4">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">{header.name}</h1>
          {header.local_name && header.local_name !== header.name && (
            <p className="text-lg text-slate-500 mt-0.5">{header.local_name}</p>
          )}
          {(header.city || header.country) && (
            <p className="text-slate-500 mt-1">
              {[header.city?.name, header.country].filter(Boolean).join(', ')}
            </p>
          )}
          {header.distance_to_city_center_km != null && (
            <p className="text-sm text-slate-400 mt-0.5">
              {header.distance_to_city_center_km} {t('distanceToCity')}
            </p>
          )}
        </div>
        <div className="flex flex-col gap-2 items-end">
          {header.cached && (
            <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-lg px-3 py-1.5 text-sm text-amber-700">
              <span>🕐 {t('cachedBadge')}, {cachedMinutes} мин. назад</span>
              <button
                onClick={() => navigate(`?refresh=1`)}
                className="underline hover:no-underline font-medium"
              >
                {t('refresh')}
              </button>
            </div>
          )}
          <div className="flex gap-2">
            {header.official_website && (
              <a
                href={header.official_website}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-blue-600 hover:underline flex items-center gap-1"
              >
                🌐 Сайт
              </a>
            )}
            {header.wikipedia_url && (
              <a
                href={header.wikipedia_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-blue-600 hover:underline flex items-center gap-1"
              >
                📖 Wikipedia
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
