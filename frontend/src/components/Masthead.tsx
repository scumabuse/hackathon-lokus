import { Link } from 'react-router-dom'
import type { UniversityHeader } from '../types'
import { t, type Lang } from '../i18n'
import { formatAgo, formatKm } from '../lib/format'
import LangSwitch from './LangSwitch'

interface Props {
  header: UniversityHeader | null
  lang: Lang
  onToggleLang: () => void
  onRefresh: () => void
}

/** Serif name, local name, one line of place + distance + links, cached line (B5.2). */
export default function Masthead({ header, lang, onToggleLang, onRefresh }: Props) {
  return (
    <header className="pt-8 pb-6">
      <div className="flex items-baseline justify-between gap-6 text-[13px] text-ink-2">
        <Link to="/" className="text-ink-2">
          {t(lang, 'masthead_back')}
        </Link>
        <LangSwitch lang={lang} onToggle={onToggleLang} />
      </div>
      <h1 className="font-serif text-[clamp(48px,9vw,128px)] leading-[0.92] mt-8 break-words">
        {header ? header.name : ' '}
      </h1>
      {header?.local_name && (
        <p className="font-serif text-[clamp(22px,3vw,32px)] leading-[1.1] text-ink-2 mt-3">
          {header.local_name}
        </p>
      )}
      {header && (
        <p className="mt-5 max-w-[80ch] text-[15px] leading-[1.6]">
          {header.city?.name && (
            <span>
              {header.country
                ? t(lang, 'masthead_place', { city: header.city.name, country: header.country })
                : `${header.city.name}.`}{' '}
            </span>
          )}
          {header.distance_to_city_center_km != null && (
            <span>
              {t(lang, 'masthead_distance', {
                km: formatKm(header.distance_to_city_center_km, lang),
              })}{' '}
            </span>
          )}
          {header.official_website && (
            <span>
              <a href={header.official_website} target="_blank" rel="noopener noreferrer">
                {t(lang, 'masthead_site')}
              </a>
              {header.wikipedia_url ? ', ' : '.'}
            </span>
          )}
          {header.wikipedia_url && (
            <span>
              <a href={header.wikipedia_url} target="_blank" rel="noopener noreferrer">
                {t(lang, 'masthead_wikipedia')}
              </a>
              .
            </span>
          )}
        </p>
      )}
      {header?.cached && header.cached_at && (
        <p className="mt-2 text-[15px] text-ink-2">
          {t(lang, 'masthead_cached', { ago: formatAgo(header.cached_at, lang) })}{' '}
          <button type="button" className="textlink" onClick={onRefresh}>
            {t(lang, 'masthead_refresh')}
          </button>
        </p>
      )}
    </header>
  )
}
