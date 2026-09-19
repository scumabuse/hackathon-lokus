import type { Stats, UniversityHeader } from '../types'
import { sourceName, t, type Lang } from '../i18n'
import { formatAgo, formatKm, formatSeconds } from '../lib/format'

interface Props {
  header: UniversityHeader
  stats: Stats | null
  totalMs: number | null
  cachedAt: string | null
  done: boolean
  lang: Lang
}

/** The facts panel next to the description: place, distance, the pipeline's counts, build time
 *  and when the profile was built, then the three sources that contributed most. */
export default function InfoBox({ header, stats, totalMs, cachedAt, done, lang }: Props) {
  const pending = <span className="skeleton inline-block h-[14px] w-12 align-middle" aria-label={t(lang, 'infobox_pending')} />
  const rows: Array<[string, React.ReactNode]> = []
  if (header.city?.name) rows.push([t(lang, 'infobox_city'), header.city.name])
  if (header.country) rows.push([t(lang, 'infobox_country'), header.country])
  if (header.distance_to_city_center_km != null) {
    rows.push([t(lang, 'infobox_distance'), formatKm(header.distance_to_city_center_km, lang)])
  }
  rows.push([t(lang, 'infobox_found'), stats ? stats.found : pending])
  rows.push([t(lang, 'infobox_dupes'), stats ? stats.duplicates_removed : pending])
  rows.push([t(lang, 'infobox_irrelevant'), stats ? stats.irrelevant_removed : pending])
  rows.push([t(lang, 'infobox_shown'), stats ? stats.shown : pending])
  rows.push([t(lang, 'infobox_hidden'), stats ? stats.hidden_unverified : pending])
  rows.push([
    t(lang, 'infobox_time'),
    done && (totalMs ?? stats?.total_ms) != null ? formatSeconds((totalMs ?? stats?.total_ms) as number, lang) : pending,
  ])
  rows.push([
    t(lang, 'infobox_collected'),
    cachedAt ? formatAgo(cachedAt, lang) : done ? t(lang, 'infobox_just_now') : pending,
  ])

  const sources = stats
    ? Object.entries(stats.per_source)
        .filter(([, n]) => n > 0)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
    : []

  return (
    <aside className="card rounded-xl p-5 md:p-6" aria-label={t(lang, 'infobox_title')}>
      <h2 className="font-serif text-[22px] leading-none m-0">{t(lang, 'infobox_title')}</h2>
      <dl className="infobox mt-3 m-0">
        {rows.map(([label, value]) => (
          <div key={label} className="row">
            <dt>{label}</dt>
            <dd className="num">{value}</dd>
          </div>
        ))}
      </dl>
      {sources.length > 0 && (
        <div className="mt-4 pt-4 border-t border-line">
          <p className="eyebrow m-0">{t(lang, 'infobox_sources')}</p>
          <ul className="m-0 mt-2 p-0 list-none grid gap-1.5 text-[13px] text-ink-2">
            {sources.map(([key, n]) => (
              <li key={key} className="flex items-baseline justify-between gap-3">
                <span className="capitalize-first">{sourceName(key, lang)}</span>
                <span className="num text-ink font-medium">{n}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  )
}
